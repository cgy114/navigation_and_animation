"""Local MSPM0G3507 ROM BSL and UART monitor backend."""

from __future__ import annotations

from collections import deque
from pathlib import Path
import re
import threading
import time
import zlib

import serial
from serial.tools import list_ports


FLASH_SIZE = 0x20000
BUFFER_LIMIT = 65536
BSL_BAUD = {4800: 1, 9600: 2, 19200: 3, 38400: 4, 57600: 5,
            115200: 6, 1000000: 7, 2000000: 8, 3000000: 9}
ACK_ERRORS = {0x51: "帧头错误", 0x52: "CRC 错误", 0x53: "长度为零",
              0x54: "数据包过大", 0x55: "未知通信错误", 0x56: "不支持该波特率"}
CORE_ERRORS = {1: "BSL 已锁定", 2: "密码错误", 3: "多次密码错误",
               4: "未知命令", 5: "无效内存范围", 6: "无效命令",
               7: "禁止出厂重置", 8: "出厂重置密码错误", 9: "禁止读出",
               10: "地址或长度未按 8 字节对齐", 11: "验证长度小于 1 KB"}


def crc32(data: bytes) -> int:
    # TI ROM BSL: reflected CRC-32, seed FFFFFFFF, no final XOR.
    return zlib.crc32(data) ^ 0xFFFFFFFF


def packet(command: int, data: bytes = b"") -> bytes:
    core = bytes((command,)) + data
    if len(core) > 0xFFFF:
        raise ValueError("BSL 数据包过大")
    return b"\x80" + len(core).to_bytes(2, "little") + core + crc32(core).to_bytes(4, "little")


def parse_response(frame: bytes) -> tuple[int, bytes]:
    if len(frame) < 8 or frame[0] != 0x08:
        raise RuntimeError("BSL 响应帧头错误")
    length = int.from_bytes(frame[1:3], "little")
    if length < 1 or len(frame) != length + 7:
        raise RuntimeError("BSL 响应长度错误")
    core = frame[3:3 + length]
    if int.from_bytes(frame[-4:], "little") != crc32(core):
        raise RuntimeError("BSL 响应 CRC 错误")
    return core[0], core[1:]


def parse_hex(text: str) -> dict:
    """Validate Intel HEX and group written bytes into aligned main-flash segments."""
    memory: dict[int, int] = {}
    base = 0
    ended = False
    for line_number, raw in enumerate(text.lstrip("\ufeff").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if ended:
            raise ValueError(f"第 {line_number} 行：结束记录后还有数据")
        if not line.startswith(":") or len(line[1:]) % 2 or not re.fullmatch(r"[0-9a-fA-F]+", line[1:]):
            raise ValueError(f"第 {line_number} 行：无效 Intel HEX 记录")
        record = bytes.fromhex(line[1:])
        if len(record) < 5 or len(record) != record[0] + 5:
            raise ValueError(f"第 {line_number} 行：记录长度不符")
        if sum(record) & 0xFF:
            raise ValueError(f"第 {line_number} 行：校验和错误")
        count, offset, kind = record[0], int.from_bytes(record[1:3], "big"), record[3]
        data = record[4:-1]
        if kind == 0:
            start = base + offset
            if start < 0 or start + count > FLASH_SIZE:
                raise ValueError(f"第 {line_number} 行：地址超出 MSPM0G3507 主 Flash")
            for index, value in enumerate(data):
                address = start + index
                if address in memory and memory[address] != value:
                    raise ValueError(f"第 {line_number} 行：地址 0x{address:05X} 有冲突数据")
                memory[address] = value
        elif kind == 1:
            if count != 0:
                raise ValueError(f"第 {line_number} 行：结束记录格式错误")
            ended = True
        elif kind == 2:
            if count != 2:
                raise ValueError(f"第 {line_number} 行：段地址格式错误")
            base = int.from_bytes(data, "big") * 16
        elif kind == 4:
            if count != 2:
                raise ValueError(f"第 {line_number} 行：线性地址格式错误")
            base = int.from_bytes(data, "big") * 0x10000
        elif kind not in (3, 5):
            raise ValueError(f"第 {line_number} 行：不支持的记录类型 {kind}")
    if not ended or not memory:
        raise ValueError("HEX 缺少结束记录或不含可烧录数据")

    words = sorted({address & ~7 for address in memory})
    groups: list[tuple[int, bytes]] = []
    start = previous = words[0]
    for word in words[1:]:
        if word != previous + 8:
            groups.append(_segment(start, previous + 8, memory))
            start = word
        previous = word
    groups.append(_segment(start, previous + 8, memory))
    return {"segments": groups, "source_bytes": len(memory),
            "programmed_bytes": sum(len(data) for _, data in groups),
            "first_address": words[0], "last_address": words[-1] + 7}


def _segment(start: int, end: int, memory: dict[int, int]) -> tuple[int, bytes]:
    data = bytearray(b"\xFF" * (end - start))
    for address in range(start, end):
        if address in memory:
            data[address - start] = memory[address]
    return start, bytes(data)


def image_chunks(image: dict, max_data: int):
    size = min(256, max_data) // 8 * 8
    if size < 8:
        raise RuntimeError("BSL 缓冲区不足以写入 8 字节")
    for address, data in image["segments"]:
        for offset in range(0, len(data), size):
            yield address + offset, data[offset:offset + size]


class Bsl:
    def __init__(self, port: serial.Serial):
        self.port = port

    def _read_exact(self, length: int, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        result = bytearray()
        while len(result) < length:
            if time.monotonic() >= deadline:
                raise TimeoutError("等待芯片响应超时；请检查 BSL 模式、接线和波特率")
            part = self.port.read(length - len(result))
            if part:
                result.extend(part)
        return bytes(result)

    def command(self, command: int, data: bytes = b"", response: int | None = None,
                timeout: float = 3.0) -> bytes:
        self.port.write(packet(command, data))
        self.port.flush()
        ack = self._read_exact(1, timeout)[0]
        if ack != 0:
            raise RuntimeError(f"BSL 拒绝命令 0x{command:02X}：{ACK_ERRORS.get(ack, f'ACK 0x{ack:02X}')}")
        if response is None:
            return b""
        header = self._read_exact(3, timeout)
        if header[0] != 0x08:
            raise RuntimeError("BSL 响应帧头错误")
        length = int.from_bytes(header[1:3], "little")
        if length < 1 or length > 8192:
            raise RuntimeError(f"BSL 响应长度异常：{length}")
        kind, payload = parse_response(header + self._read_exact(length + 4, timeout))
        if kind == 0x3B:
            status = payload[0] if payload else -1
            if status != 0:
                raise RuntimeError(f"BSL 执行失败：{CORE_ERRORS.get(status, f'状态 0x{status:02X}')}")
            if response != kind:
                raise RuntimeError("BSL 未返回预期数据")
        elif kind == 0x3A:
            raise RuntimeError(f"BSL Flash 详细错误：{payload.hex(' ')}")
        elif kind != response:
            raise RuntimeError(f"BSL 返回类型 0x{kind:02X}，预期 0x{response:02X}")
        return payload

    def connect(self) -> None:
        self.command(0x12)

    def info(self) -> dict:
        data = self.command(0x19, response=0x31)
        if len(data) != 24:
            raise RuntimeError("BSL 设备信息长度不符")
        size = int.from_bytes(data[10:12], "little")
        if size < 32:
            raise RuntimeError("BSL 缓冲区过小")
        return {"interpreter": int.from_bytes(data[0:2], "little"), "max_buffer": size}

    def set_baud(self, rate: int) -> None:
        if rate not in BSL_BAUD:
            raise ValueError("不支持的 BSL 波特率")
        if rate != 9600:
            self.command(0x52, bytes((BSL_BAUD[rate],)))
            self.port.baudrate = rate

    def unlock(self, password: bytes) -> None:
        if len(password) != 32:
            raise ValueError("BSL 密码须为 32 字节")
        self.command(0x21, password, response=0x3B)

    def erase(self) -> None:
        self.command(0x15, response=0x3B, timeout=20)

    def program(self, address: int, data: bytes) -> None:
        if address % 8 or len(data) % 8:
            raise ValueError("写入地址和长度必须按 8 字节对齐")
        self.command(0x20, address.to_bytes(4, "little") + data, response=0x3B, timeout=8)

    def start_application(self) -> None:
        self.command(0x40)


class SerialService:
    def __init__(self):
        self._activity = threading.RLock()
        self._buffer_lock = threading.Lock()
        self._buffer: deque[int] = deque()
        self._dropped = 0
        self._last_error = ""
        self._port: serial.Serial | None = None
        self._port_name = ""
        self._baud_rate = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @staticmethod
    def list_ports() -> list[dict]:
        return [{"port": item.device, "description": item.description,
                 "vid": f"0x{item.vid:04X}" if item.vid is not None else None,
                 "pid": f"0x{item.pid:04X}" if item.pid is not None else None}
                for item in list_ports.comports()]

    def _watch(self, port: serial.Serial) -> None:
        while not self._stop.is_set() and port.is_open:
            try:
                data = port.read(4096)
            except (serial.SerialException, OSError) as error:
                self._last_error = str(error)
                break
            if data:
                with self._buffer_lock:
                    for value in data:
                        if len(self._buffer) >= BUFFER_LIMIT:
                            self._buffer.popleft()
                            self._dropped += 1
                        self._buffer.append(value)

    def _disconnect(self) -> None:
        self._stop.set()
        port, self._port = self._port, None
        if port is not None:
            try:
                port.close()
            except (serial.SerialException, OSError):
                pass
        if self._thread is not None:
            self._thread.join(timeout=1)
        self._thread = None
        self._port_name = ""
        self._baud_rate = 0

    def disconnect(self) -> dict:
        with self._activity:
            old = self._port_name
            self._disconnect()
            return {"disconnected": old or None}

    def connect(self, port_name: str, baud_rate: int = 115200) -> dict:
        if not port_name or baud_rate < 300 or baud_rate > 3000000:
            raise ValueError("请指定有效的 COM 口和波特率")
        with self._activity:
            self._disconnect()
            try:
                port = serial.Serial(port_name, baudrate=baud_rate, timeout=0.1, write_timeout=5)
            except (serial.SerialException, OSError) as error:
                raise RuntimeError(f"无法打开 {port_name}：{error}。请先断开浏览器串口监视器或其他占用此 COM 口的程序") from error
            self._port = port
            self._port_name = port_name
            self._baud_rate = baud_rate
            self._last_error = ""
            with self._buffer_lock:
                self._buffer.clear()
                self._dropped = 0
            self._stop.clear()
            self._thread = threading.Thread(target=self._watch, args=(port,), daemon=True)
            self._thread.start()
            return {"connected": port_name, "baud_rate": baud_rate, "format": "8N1"}

    def read(self, max_bytes: int = 4096, wait_ms: int = 1000, encoding: str = "utf-8") -> dict:
        if not 1 <= max_bytes <= BUFFER_LIMIT or not 0 <= wait_ms <= 10000:
            raise ValueError("max_bytes 须为 1–65536，wait_ms 须为 0–10000")
        deadline = time.monotonic() + wait_ms / 1000
        while True:
            with self._buffer_lock:
                if self._buffer:
                    data = bytes(self._buffer.popleft() for _ in range(min(max_bytes, len(self._buffer))))
                    dropped = self._dropped
                    self._dropped = 0
                    break
                dropped = self._dropped
            if time.monotonic() >= deadline or self._port is None:
                data = b""
                break
            time.sleep(0.02)
        try:
            text = data.decode(encoding, errors="replace")
        except LookupError as error:
            raise ValueError(f"未知文本编码：{encoding}") from error
        return {"port": self._port_name or None, "baud_rate": self._baud_rate or None,
                "byte_count": len(data), "text": text, "hex": data.hex(" ").upper(),
                "dropped_bytes": dropped, "connection_error": self._last_error or None}

    def capture(self, port_name: str, baud_rate: int = 115200, duration_ms: int = 3000,
                max_bytes: int = 4096, encoding: str = "utf-8") -> dict:
        if not 0 <= duration_ms <= 10000:
            raise ValueError("duration_ms 须为 0–10000")
        with self._activity:
            self.connect(port_name, baud_rate)
            try:
                time.sleep(duration_ms / 1000)
                return self.read(max_bytes, 0, encoding)
            finally:
                self._disconnect()

    def send(self, data: str, format: str = "text", line_ending: str = "none") -> dict:
        with self._activity:
            if self._port is None or not self._port.is_open:
                raise RuntimeError("串口监视器未连接；先调用 connect_serial")
            if format == "hex":
                clean = re.sub(r"[\s,]+", "", data)
                if not clean or len(clean) % 2 or not re.fullmatch(r"[0-9a-fA-F]+", clean):
                    raise ValueError("HEX 发送须为成对的十六进制字节")
                payload = bytes.fromhex(clean)
            elif format == "text":
                endings = {"none": "", "lf": "\n", "cr": "\r", "crlf": "\r\n"}
                if line_ending not in endings:
                    raise ValueError("line_ending 须为 none/lf/cr/crlf")
                payload = (data + endings[line_ending]).encode("utf-8")
            else:
                raise ValueError("format 须为 text 或 hex")
            count = self._port.write(payload)
            self._port.flush()
            return {"port": self._port_name, "bytes_sent": count, "hex": payload.hex(" ").upper()}

    def flash(self, hex_path: str, port_name: str = "", bsl_baud_rate: int = 115200,
              password_hex: str = "FF" * 32, start_application: bool = True,
              monitor_after: bool = False, monitor_baud_rate: int = 115200) -> dict:
        path = Path(hex_path).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in (".hex", ".ihex"):
            raise ValueError("请指定存在的 .hex/.ihex 固件绝对路径")
        if path.stat().st_size > 2_000_000:
            raise ValueError("HEX 文件超过 2 MB 上限")
        image = parse_hex(path.read_text(encoding="utf-8-sig"))
        if bsl_baud_rate not in BSL_BAUD:
            raise ValueError("BSL 波特率不受支持")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", password_hex):
            raise ValueError("BSL 密码须为 64 位十六进制字符")
        password = bytes.fromhex(password_hex)
        with self._activity:
            selected_port = port_name or self._port_name
            if not selected_port:
                raise ValueError("请指定 port_name，或先调用 connect_serial 选择串口")
            self._disconnect()
            try:
                with serial.Serial(selected_port, baudrate=9600, timeout=0.1, write_timeout=5) as port:
                    bsl = Bsl(port)
                    bsl.connect()
                    info = bsl.info()
                    bsl.set_baud(bsl_baud_rate)
                    bsl.unlock(password)
                    blocks = list(image_chunks(image, info["max_buffer"] - 12))
                    bsl.erase()
                    for address, data in blocks:
                        bsl.program(address, data)
                    if start_application:
                        bsl.start_application()
            except (serial.SerialException, OSError) as error:
                raise RuntimeError(f"烧录串口 {selected_port} 无法使用：{error}。请关闭占用此 COM 口的浏览器或终端") from error
            result = {"port": selected_port, "file": str(path), "bsl_baud_rate": bsl_baud_rate,
                      "source_bytes": image["source_bytes"], "programmed_bytes": image["programmed_bytes"],
                      "blocks_written": len(blocks), "first_address": f"0x{image['first_address']:05X}",
                      "last_address": f"0x{image['last_address']:05X}",
                      "started_application": start_application,
                      "verification": "每块收到 BSL ACK 与成功状态；未执行 Flash 读回比较"}
            if monitor_after and start_application:
                result["monitor"] = self.connect(selected_port, monitor_baud_rate)
            return result
