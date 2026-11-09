import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".vendor"))
sys.path.insert(0, str(ROOT))

from mcp_backend import Bsl, SerialService, crc32, packet, parse_hex, parse_response


def response(command, data=b""):
    core = bytes((command,)) + data
    return b"\x08" + len(core).to_bytes(2, "little") + core + crc32(core).to_bytes(4, "little")


class FakePort:
    instances = []

    def __init__(self, name, baudrate, timeout, write_timeout):
        self.name = name
        self.baudrate = baudrate
        self.is_open = True
        self.incoming = bytearray()
        self.commands = []
        FakePort.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.is_open = False

    def flush(self):
        pass

    def write(self, data):
        command = data[3]
        self.commands.append(command)
        self.incoming.extend(b"\x00")
        if command == 0x19:
            info = bytearray(24)
            info[10:12] = (0x06C0).to_bytes(2, "little")
            self.incoming.extend(response(0x31, info))
        elif command in (0x21, 0x15, 0x20):
            self.incoming.extend(response(0x3B, b"\x00"))
        return len(data)

    def read(self, length):
        result = bytes(self.incoming[:length])
        del self.incoming[:length]
        return result


class ProtocolTests(unittest.TestCase):
    def test_ti_reference_frames(self):
        self.assertEqual(packet(0x12), bytes.fromhex("80 01 00 12 3A 61 44 DE"))
        self.assertEqual(packet(0x15), bytes.fromhex("80 01 00 15 99 F4 20 40"))
        self.assertEqual(packet(0x52, b"\x03"), bytes.fromhex("80 02 00 52 03 6C 83 A2 AF"))
        self.assertEqual(parse_response(bytes.fromhex("08 02 00 3B 00 38 02 94 82")), (0x3B, b"\x00"))

    def test_sample_hex(self):
        image = parse_hex((ROOT.parent / "mspm0g3507_project1.hex").read_text())
        self.assertEqual(image["first_address"], 0)
        self.assertEqual(image["source_bytes"], 4752)
        self.assertEqual(image["programmed_bytes"], 4752)

    def test_fake_device_flash_sequence(self):
        FakePort.instances.clear()
        service = SerialService()
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            self.assertTrue(Path(folder).resolve().is_relative_to(ROOT.resolve()))
            image = Path(folder) / "firmware.hex"
            image.write_text(":080000000102030405060708D4\n:00000001FF\n")
            with patch("mcp_backend.serial.Serial", FakePort):
                result = service.flash(str(image), "COM10", 115200)
        self.assertEqual(result["blocks_written"], 1)
        self.assertEqual(result["programmed_bytes"], 8)
        self.assertEqual(FakePort.instances[0].commands, [0x12, 0x19, 0x52, 0x21, 0x15, 0x20, 0x40])
        self.assertEqual(FakePort.instances[0].baudrate, 115200)

    def test_monitor_returns_text_and_hex_and_sends_bytes(self):
        service = SerialService()
        port = FakePort("COM10", 115200, 0.1, 5)
        service._port = port
        service._port_name = "COM10"
        service._baud_rate = 115200
        service._buffer.extend(b"READY\r\n")
        result = service.read(wait_ms=0)
        self.assertEqual(result["text"], "READY\r\n")
        self.assertEqual(result["hex"], "52 45 41 44 59 0D 0A")
        sent = service.send("PING", line_ending="crlf")
        self.assertEqual(sent["hex"], "50 49 4E 47 0D 0A")
        service.disconnect()


if __name__ == "__main__":
    unittest.main()
