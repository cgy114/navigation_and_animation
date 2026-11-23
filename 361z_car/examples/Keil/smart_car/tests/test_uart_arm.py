"""Exercise merged UART drivers in the final ARM image with modeled registers."""

from collections import deque
import struct
import unittest

from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
)

from test_command_arm import Firmware


UART_DEBUG = 0x40108000
UART_PI = 0x40500000
UART_STAT = 0x1108
UART_TXDATA = 0x1120
UART_RXDATA = 0x1124
UART_RX_EMPTY = 4
UART_BUSY = 1


class UartFirmware(Firmware):
    def __init__(self):
        super().__init__()
        # Run the real drivers while retaining hooks for motor/servo actions.
        driver_hooks = ('debug_uart_send_string', 'debug_uart_send_char',
                        'debug_uart_get_char', 'uart_pi_get_char')
        self.hooks = {address: name for address, name in self.hooks.items()
                      if name not in driver_hooks}
        for address, size in ((UART_DEBUG, 0x2000), (UART_PI, 0x2000),
                              (0x40428000, 0x1000), (0xE000E000, 0x2000)):
            self.mu.mem_map(address, size)
        self.tx = {UART_DEBUG: bytearray(), UART_PI: bytearray()}
        self.pending_rx = {UART_DEBUG: deque(), UART_PI: deque()}
        self.mu.hook_add(UC_HOOK_MEM_WRITE, self._write_uart)
        self.mu.hook_add(UC_HOOK_MEM_READ, self._read_uart)
        self.call('SYSCFG_DL_UART_DEBUG_init')
        self.call('debug_uart_init')
        self.call('debug_uart_set_baud_9600')
        self.call('uart_pi_init')
        for base in self.tx:
            self.write32(base + UART_STAT, UART_RX_EMPTY)

    def read32(self, address):
        return struct.unpack('<I', self.mu.mem_read(address, 4))[0]

    def write32(self, address, value):
        self.mu.mem_write(address, struct.pack('<I', value))

    def call(self, name, *args):
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2), args):
            self.mu.reg_write(reg, value)
        self.mu.reg_write(UC_ARM_REG_SP, 0x20207F00)
        self.mu.reg_write(UC_ARM_REG_LR, 0x100001)
        self.mu.emu_start(self.symbols[name] | 1, 0x100000, count=100000)
        if self.mu.reg_read(UC_ARM_REG_PC) != 0x100000:
            raise AssertionError(f'{name} did not return within instruction budget')

    def _write_uart(self, mu, access, address, size, value, user):
        for base in self.tx:
            if address == base + UART_TXDATA:
                self.tx[base].append(value & 255)

    def _read_uart(self, mu, access, address, size, value, user):
        for base, pending in self.pending_rx.items():
            if address == base + UART_RXDATA and pending:
                self.write32(address, pending.popleft())
                if not pending:
                    self.write32(base + UART_STAT, UART_RX_EMPTY)

    def send_text(self, text):
        address = 0x20207000
        self.mu.mem_write(address, text.encode('ascii') + b'\0')
        self.call('debug_uart_send_string', address)

    def drain(self, cycles=2048):
        for _ in range(cycles):
            self.call('debug_uart_poll')
            self.call('uart_pi_poll')

    def receive(self, base, text):
        self.pending_rx[base].extend(text.encode('ascii'))
        self.write32(base + UART_STAT, 0)
        self.write32(base + 0x1020, 0x0B)  # CPU_INT.IIDX: RX interrupt.
        self.call('UART0_IRQHandler' if base == UART_DEBUG else 'UART3_IRQHandler')
        self.call('command_poll')


class TestUartArm(unittest.TestCase):
    def test_baud_divisors_and_single_byte_rx_threshold(self):
        firmware = UartFirmware()
        for base, clock, baud in ((UART_DEBUG, 40000000, 9600),
                                  (UART_PI, 80000000, 115200)):
            integer = firmware.read32(base + 0x1110)
            fraction = firmware.read32(base + 0x1114)
            actual = clock / (16 * (integer + fraction / 64))
            self.assertLess(abs(actual - baud) / baud, 0.001)
            self.assertEqual(firmware.read32(base + 0x110C) & 0x70, 0x70)

    def test_complete_startup_help_and_ready_are_mirrored(self):
        firmware = UartFirmware()
        firmware.call('command_init')
        firmware.send_text('READY\r\n')
        firmware.drain()
        for output in firmware.tx.values():
            self.assertTrue(output.startswith(b'Commands:\r\n'))
            self.assertIn(b'D <pulse_us>', output)
            self.assertIn(b'P <pwm>', output)
            self.assertTrue(output.endswith(b'READY\r\n'))
        self.assertEqual(firmware.tx[UART_DEBUG], firmware.tx[UART_PI])

    def test_busy_uart_does_not_block_or_lose_queued_bytes(self):
        firmware = UartFirmware()
        for base in firmware.tx:
            firmware.write32(base + UART_STAT, UART_RX_EMPTY | UART_BUSY)
        firmware.send_text('queued\r\n')
        firmware.drain(2)
        self.assertTrue(all(not output for output in firmware.tx.values()))
        for base in firmware.tx:
            firmware.write32(base + UART_STAT, UART_RX_EMPTY)
        firmware.drain(16)
        self.assertEqual(firmware.tx[UART_DEBUG], b'queued\r\n')
        self.assertEqual(firmware.tx[UART_PI], b'queued\r\n')

    def test_single_byte_stop_reaches_parser_on_both_links(self):
        for base in (UART_DEBUG, UART_PI):
            firmware = UartFirmware()
            firmware.receive(base, '0')
            firmware.drain(16)
            self.assertEqual(firmware.stops, 1)
            self.assertEqual(firmware.tx[UART_DEBUG], b'OK 0\r\n')
            self.assertEqual(firmware.tx[UART_PI], b'OK 0\r\n')

    def test_rx_interrupt_drains_all_available_bytes(self):
        for base in (UART_DEBUG, UART_PI):
            firmware = UartFirmware()
            firmware.receive(base, 'd 1500\r\nP -3000\n')
            firmware.drain(32)
            self.assertEqual(firmware.servo_pulses, [1500])
            self.assertEqual(firmware.wheels, [(-3000, -3000)])
            self.assertEqual(firmware.tx[UART_DEBUG], b'OK D\r\nOK P PWM\r\n')
            self.assertEqual(firmware.tx[UART_DEBUG], firmware.tx[UART_PI])


if __name__ == '__main__':
    unittest.main()
