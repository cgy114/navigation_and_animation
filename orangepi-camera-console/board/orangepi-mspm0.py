#!/usr/bin/env python3
"""MSPM0G3507 ROM-BSL flasher and serial bridge for the Orange Pi.

Subcommands
  ports    print JSON list of serial ports
  flash    erase main flash and program an Intel HEX file, printing progress
  monitor  open a port and exchange hex lines with the caller on stdin/stdout
"""
import argparse
import json
import select
import sys
import time

import serial
from serial.tools import list_ports

FLASH_SIZE = 0x20000  # MSPM0G3507 main flash: 128 KiB


# ---------------------------------------------------------------- Intel HEX
class HexError(Exception):
    pass


def parse_hex(text):
    """Return (segments, source_bytes, first, last); segments are 8-byte aligned."""
    data = {}
    base = 0
    ended = False
    for number, line in enumerate(text.replace('﻿', '').splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if ended:
            raise HexError('第 %d 行：结束记录后还有数据' % number)
        if not line.startswith(':') or len(line) % 2 != 1:
            raise HexError('第 %d 行：不是有效 Intel HEX 记录' % number)
        try:
            record = bytes.fromhex(line[1:])
        except ValueError:
            raise HexError('第 %d 行：包含非十六进制字符' % number)
        count = record[0]
        if len(record) != count + 5:
            raise HexError('第 %d 行：记录长度不符' % number)
        if sum(record) & 0xFF:
            raise HexError('第 %d 行：校验和错误' % number)
        offset = (record[1] << 8) | record[2]
        kind = record[3]
        payload = record[4:4 + count]
        if kind == 0:
            start = base + offset
            if start < 0 or start + count > FLASH_SIZE:
                raise HexError('第 %d 行：地址超出 MSPM0G3507 主 Flash (0x00000–0x1FFFF)' % number)
            for index, value in enumerate(payload):
                address = start + index
                if address in data and data[address] != value:
                    raise HexError('第 %d 行：地址 0x%x 有冲突数据' % (number, address))
                data[address] = value
        elif kind == 1:
            if count != 0:
                raise HexError('第 %d 行：结束记录格式错误' % number)
            ended = True
        elif kind == 2:
            if count != 2:
                raise HexError('第 %d 行：段地址格式错误' % number)
            base = ((payload[0] << 8) | payload[1]) * 16
        elif kind == 4:
            if count != 2:
                raise HexError('第 %d 行：线性地址格式错误' % number)
            base = ((payload[0] << 8) | payload[1]) * 0x10000
        elif kind not in (3, 5):
            raise HexError('第 %d 行：不支持的记录类型 %d' % (number, kind))
    if not ended:
        raise HexError('HEX 缺少结束记录')
    if not data:
        raise HexError('HEX 不含可烧录数据')

    words = sorted({address & ~7 for address in data})
    segments = []
    start = previous = words[0]
    for word in words[1:]:
        if word != previous + 8:
            segments.append(_segment(start, previous + 8, data))
            start = word
        previous = word
    segments.append(_segment(start, previous + 8, data))
    return segments, len(data), words[0], words[-1] + 7


def _segment(start, end, data):
    block = bytearray(b'\xff' * (end - start))
    for address in range(start, end):
        if address in data:
            block[address - start] = data[address]
    return start, block


def chunks(segments, max_data=256):
    size = (max_data // 8) * 8
    if size < 8:
        raise HexError('BSL 缓冲区不足以写入 8 字节')
    for address, block in segments:
        for offset in range(0, len(block), size):
            yield address + offset, block[offset:offset + size]


# ---------------------------------------------------------------------- BSL
BSL_BAUD = {4800: 1, 9600: 2, 19200: 3, 38400: 4, 57600: 5,
            115200: 6, 1000000: 7, 2000000: 8, 3000000: 9}
CORE_ERRORS = ['成功', 'BSL 已锁定', '密码错误', '多次密码错误', '未知命令', '无效内存范围',
               '无效命令', '禁止出厂重置', '出厂重置密码错误', '禁止读出',
               '地址或长度未按 8 字节对齐', '验证长度小于 1 KB']
ACK_ERRORS = {0x51: '帧头错误', 0x52: 'CRC 错误', 0x53: '数据长度为零',
              0x54: '数据包太大', 0x55: '未知通信错误', 0x56: '不支持此波特率'}


def crc32(data):
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
    return crc & 0xFFFFFFFF


def packet(command, data=b''):
    core = bytes([command]) + bytes(data)
    return bytes([0x80, len(core) & 0xFF, len(core) >> 8]) + core + crc32(core).to_bytes(4, 'little')


def parse_response(frame):
    if frame[0] != 0x08:
        raise RuntimeError('BSL 响应帧头错误')
    length = frame[1] | frame[2] << 8
    if length < 1 or len(frame) != length + 7:
        raise RuntimeError('BSL 响应长度错误')
    core = frame[3:3 + length]
    if crc32(core).to_bytes(4, 'little') != frame[3 + length:]:
        raise RuntimeError('BSL 响应 CRC 错误')
    return core[0], core[1:]


class Bsl:
    def __init__(self, port, address, baud):
        self.port = port
        self.address = address
        self.baud = baud

    def _reopen(self, baud):
        self.port.close()
        self.port = serial.Serial(self.address, baud, timeout=0.05)
        self.baud = baud

    def read_exact(self, count, timeout):
        deadline = time.monotonic() + timeout
        buffer = bytearray()
        while len(buffer) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('等待芯片响应超时，请检查 BSL 模式、接线和波特率')
            self.port.timeout = min(0.05, remaining)
            chunk = self.port.read(count - len(buffer))
            if chunk:
                buffer.extend(chunk)
        return bytes(buffer)

    def command(self, command_id, data=b'', response=None, timeout=2.5):
        self.port.write(packet(command_id, data))
        self.port.flush()
        ack = self.read_exact(1, timeout)[0]
        if ack != 0:
            raise RuntimeError('BSL 拒绝命令 0x%02x：%s' % (
                command_id, ACK_ERRORS.get(ack, 'ACK 0x%02x' % ack)))
        if response is None:
            return None
        header = self.read_exact(3, timeout)
        if header[0] != 0x08:
            raise RuntimeError('BSL 响应帧头错误：0x%02x' % header[0])
        length = header[1] | header[2] << 8
        if length < 1 or length > 8192:
            raise RuntimeError('BSL 响应长度异常：%d' % length)
        frame = header + self.read_exact(length + 4, timeout)
        kind, payload = parse_response(frame)
        if kind == 0x3B:
            status = payload[0]
            if status != 0:
                detail = CORE_ERRORS[status] if status < len(CORE_ERRORS) else '状态 0x%02x' % status
                raise RuntimeError('BSL 执行失败：' + detail)
            if response != 0x3B:
                raise RuntimeError('BSL 返回了状态消息，未返回预期数据')
        elif kind == 0x3A:
            raise RuntimeError('BSL Flash 详细错误：' + ' '.join('%02x' % b for b in payload))
        elif kind != response:
            raise RuntimeError('BSL 返回类型 0x%02x，预期 0x%02x' % (kind, response))
        return payload

    def connect(self):
        self.command(0x12)

    def info(self):
        payload = self.command(0x19, b'', 0x31)
        if len(payload) != 24:
            raise RuntimeError('BSL 设备信息长度不符')
        max_buffer = payload[10] | payload[11] << 8
        if max_buffer < 32:
            raise RuntimeError('BSL 报告的缓冲区过小')
        return payload[0] | payload[1] << 8, max_buffer

    def set_baud(self, rate):
        if rate not in BSL_BAUD:
            raise RuntimeError('BSL 不支持所选波特率')
        if rate != 9600:
            self.command(0x52, bytes([BSL_BAUD[rate]]))
            self._reopen(rate)

    def unlock(self, password):
        if len(password) != 32:
            raise RuntimeError('BSL 密码必须为 32 字节')
        self.command(0x21, password, 0x3B)

    def erase(self):
        self.command(0x15, b'', 0x3B, timeout=15)

    def program(self, address, data):
        if address % 8 or len(data) % 8:
            raise RuntimeError('写入地址和长度须为 8 字节倍数')
        self.command(0x20, address.to_bytes(4, 'little') + bytes(data), 0x3B, timeout=5)

    def start(self):
        self.command(0x40)


# ----------------------------------------------------------------- commands
def emit(text):
    print(text, flush=True)


def command_ports(_args):
    ports = []
    for item in list_ports.comports():
        ports.append({'device': item.device, 'description': item.description or '',
                      'hwid': item.hwid or ''})
    print(json.dumps({'ports': ports}, ensure_ascii=False), flush=True)


def command_flash(args):
    with open(args.hex_file, 'r', encoding='utf-8', errors='replace') as source:
        text = source.read()
    segments, source_bytes, first, last = parse_hex(text)
    emit('LOG HEX 校验通过：%d 字节数据，地址 0x%05x–0x%05x' % (source_bytes, first, last))
    password = bytes.fromhex(args.password)

    port = serial.Serial(args.port, 9600, timeout=0.05)
    bsl = Bsl(port, args.port, 9600)
    try:
        emit('LOG 正在以 9600 bps 连接 ROM BSL…')
        bsl.connect()
        version, max_buffer = bsl.info()
        emit('LOG 芯片 BSL 版本 0x%02x，缓冲区 %d 字节' % (version, max_buffer))
        baud = int(args.baud)
        if baud != 9600:
            bsl.set_baud(baud)
            emit('LOG BSL 已切换到 %d bps' % baud)
        bsl.unlock(password)
        emit('LOG BSL 解锁成功')
        emit('LOG 正在擦除主 Flash…')
        bsl.erase()
        emit('LOG 主 Flash 擦除成功')
        blocks = list(chunks(segments, min(256, max_buffer - 12)))
        for index, (address, data) in enumerate(blocks):
            bsl.program(address, data)
            percent = round((index + 1) * 100 / len(blocks))
            emit('PROGRESS %d' % percent)
            if index == 0 or index == len(blocks) - 1 or index % 16 == 15:
                emit('LOG 已写入 %d/%d 块' % (index + 1, len(blocks)))
        emit('LOG 烧录完成：所有写入块均收到 BSL 成功回执')
        if args.start:
            bsl.start()
            emit('LOG 已发送启动应用命令')
        emit('DONE')
    finally:
        bsl.port.close()


def command_monitor(args):
    port = serial.Serial(args.port, int(args.baud), timeout=0.02)
    emit('READY %s %d' % (args.port, int(args.baud)))
    try:
        while True:
            if select.select([sys.stdin], [], [], 0)[0]:
                line = sys.stdin.readline()
                if not line:
                    break
                line = line.strip()
                if line.startswith('SEND '):
                    try:
                        port.write(bytes.fromhex(line[5:]))
                    except ValueError:
                        emit('ERR 发送数据不是有效的十六进制')
                elif line == 'QUIT':
                    break
            waiting = port.in_waiting
            data = port.read(waiting if waiting else 1)
            if data:
                emit('DATA ' + data.hex())
    finally:
        port.close()
        emit('CLOSED')


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('ports')

    flash = sub.add_parser('flash')
    flash.add_argument('--port', required=True)
    flash.add_argument('--hex-file', required=True)
    flash.add_argument('--baud', default='115200')
    flash.add_argument('--password', default='ff' * 32)
    flash.add_argument('--start', action='store_true')

    monitor = sub.add_parser('monitor')
    monitor.add_argument('--port', required=True)
    monitor.add_argument('--baud', required=True)

    args = parser.parse_args()
    try:
        {'ports': command_ports, 'flash': command_flash, 'monitor': command_monitor}[args.command](args)
    except (HexError, RuntimeError, serial.SerialException, OSError) as error:
        emit('FAIL %s' % error)
        sys.exit(1)


if __name__ == '__main__':
    main()
