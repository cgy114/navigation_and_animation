"""Test ADC result handling in the final Keil ARM image with modeled registers.

Requires the same unicorn/pyelftools packages as test_command_arm.py.
These tests do not validate physical wiring, VDDA accuracy or divider resistors.
"""

import re
import struct
import unittest

from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
)
from test_command_arm import Firmware


class BatteryFirmware(Firmware):
    def __init__(self):
        super().__init__()
        self.mu.mem_map(0x40000000, 0x2000)  # ADC0 ULLMEM
        self.mu.mem_map(0x40556000, 0x1000)  # ADC0 SVT result alias
        self.mu.mem_map(0x40428000, 0x1000)  # IOMUX
        self.mu.hook_add(UC_HOOK_MEM_WRITE, self._clear_irq)
        self.call('battery_init')

    def _clear_irq(self, mu, access, address, size, value, user):
        if address == 0x40001048:  # CPU_INT.ICLR, write-one-to-clear
            flags = struct.unpack('<I', mu.mem_read(0x40001030, 4))[0]
            mu.mem_write(0x40001030, struct.pack('<I', flags & ~value))

    def call(self, name, *args):
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2), args):
            self.mu.reg_write(reg, value)
        self.mu.reg_write(UC_ARM_REG_SP, 0x20207F00)
        self.mu.reg_write(UC_ARM_REG_LR, 0x100001)
        self.mu.emu_start(self.symbols[name] | 1, 0x100000, count=1000000)
        if self.mu.reg_read(UC_ARM_REG_PC) != 0x100000:
            raise AssertionError(f'{name} did not return')

    def sample(self, raw, now_ms):
        self.call('battery_poll', now_ms)  # Start a due conversion.
        self.mu.mem_write(0x40556280, struct.pack('<I', raw))
        self.mu.mem_write(0x40001030, struct.pack('<I', 0x100))
        self.call('battery_poll', now_ms)


class TestBatteryArm(unittest.TestCase):
    def test_channel_and_long_acquisition_configuration(self):
        firmware = BatteryFirmware()
        memctl = struct.unpack('<I', firmware.mu.mem_read(0x40001180, 4))[0]
        sample_time = struct.unpack('<I', firmware.mu.mem_read(0x40001114, 4))[0]
        self.assertEqual(memctl & 0x1F, 2)
        self.assertEqual(sample_time, 500)

    def test_nominal_twelve_volt_input_and_query(self):
        firmware = BatteryFirmware()
        self.assertIn('ERR B ADC', firmware.feed('B?'))
        firmware.sample(1354, 0)  # About 1.091 V at PA25, about 12 V at x11.
        response = firmware.feed('B?\r\n')
        self.assertIn('BAT raw=1354 adc_mv=1091', response)
        voltage = int(re.search(r'battery_mv=(\d+)', response)[1])
        self.assertAlmostEqual(voltage, 12000, delta=10)
        self.assertEqual(firmware.wheels, [])

    def test_filter_warmup_and_replacement(self):
        firmware = BatteryFirmware()
        for index in range(8):
            firmware.sample(1000, index * 20)
            self.assertIn('BAT raw=1000 ', firmware.feed('B?'))
        firmware.sample(1800, 160)
        self.assertIn('BAT raw=1100 ', firmware.feed('B?'))

    def test_timeout_returns_and_next_sample_recovers(self):
        firmware = BatteryFirmware()
        firmware.call('battery_poll', 20)
        self.assertIn('ERR B ADC', firmware.feed('B?'))
        firmware.sample(4095, 40)
        self.assertIn('adc_mv=3300 battery_mv=36300', firmware.feed('B?'))
        firmware.call('battery_poll', 60)
        firmware.call('battery_poll', 80)
        self.assertIn('ERR B ADC', firmware.feed('B?'))


if __name__ == '__main__':
    unittest.main()
