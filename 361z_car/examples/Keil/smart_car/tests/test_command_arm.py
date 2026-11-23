"""Exercise the compiled ARM UART parser, including compiler optimizations.

Requires: pip install unicorn pyelftools
Run after a Keil build: python tests/test_command_arm.py
Set COMMAND_TEST_ELF to test another build of smart_car.axf.
Hardware access is replaced with local hooks; no serial port is opened.
"""

import os
from pathlib import Path
import struct
import unittest
from collections import deque

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_MCLASS, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
)

ELF_PATH = Path(os.environ.get('COMMAND_TEST_ELF',
    Path(__file__).resolve().parents[1] / 'keil/Objects/smart_car.axf'))


class Firmware:
    def __init__(self):
        self.mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        self.mu.mem_map(0, 0x20000)
        self.mu.mem_map(0x20200000, 0x8000)
        self.mu.mem_map(0x100000, 0x1000)
        with ELF_PATH.open('rb') as stream:
            elf = ELFFile(stream)
            self.symbols = {s.name: s['st_value'] for s in
                            elf.get_section_by_name('.symtab').iter_symbols()}
            for section in elf.iter_sections():
                address = section['sh_addr']
                if (section['sh_flags'] & 2 and
                        section['sh_type'] != 'SHT_NOBITS' and
                        (address < 0x20000 or 0x20200000 <= address < 0x20208000)):
                    self.mu.mem_write(address, section.data())
        self.gains = (4000.0, 1500.0, 0.0)
        self.rx = deque()
        self.pi_rx = deque()
        self.output = ''
        self.wheels = []
        self.targets = []
        self.servo_pulses = []
        self.stops = 0
        names = ('debug_uart_send_string', 'debug_uart_send_char',
                 'debug_uart_get_char', 'uart_pi_get_char',
                 'motion_get_pid', 'motion_set_pid',
                 'pid_store_load', 'servo_set_pulse_us', 'servo_start_sweep',
                 'motion_stop', 'motion_set_direct_pwm', 'motion_set_target',
                 'odom_reset', 'encoder_reset_totals', 'encoder_left_total',
                 'encoder_right_total')
        self.hooks = {self.symbols[name] & ~1: name for name in names}
        self.mu.hook_add(UC_HOOK_CODE, self._hook)

    def _hook(self, mu, address, size, user):
        if address == 0x100000:
            mu.emu_stop()
            return
        name = self.hooks.get(address)
        if name is None:
            return
        r0, r1, r2 = [mu.reg_read(reg) for reg in
                      (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)]
        if name == 'debug_uart_send_string':
            text = bytearray()
            while True:
                char = mu.mem_read(r0, 1)[0]
                if not char:
                    break
                text.append(char)
                r0 += 1
            self.output += text.decode('ascii')
        elif name == 'debug_uart_send_char':
            self.output += chr(r0 & 255)
        elif name in ('debug_uart_get_char', 'uart_pi_get_char'):
            rx = self.rx if name == 'debug_uart_get_char' else self.pi_rx
            if rx:
                mu.mem_write(r0, bytes([rx.popleft()]))
                mu.reg_write(UC_ARM_REG_R0, 1)
            else:
                mu.reg_write(UC_ARM_REG_R0, 0)
        elif name == 'motion_get_pid':
            for pointer, value in zip((r0, r1, r2), self.gains):
                mu.mem_write(pointer, struct.pack('<f', value))
        elif name == 'motion_set_pid':
            self.gains = tuple(struct.unpack('<f', struct.pack('<I', value))[0]
                               for value in (r0, r1, r2))
        elif name in ('pid_store_load', 'encoder_left_total', 'encoder_right_total'):
            mu.reg_write(UC_ARM_REG_R0, 0)
        elif name == 'motion_set_direct_pwm':
            self.wheels.append(tuple(struct.unpack('<i', struct.pack('<I', value))[0]
                                     for value in (r0, r1)))
        elif name == 'servo_set_pulse_us':
            self.servo_pulses.append(r0)
        elif name == 'motion_stop':
            self.stops += 1
        elif name == 'motion_set_target':
            self.targets.append(tuple(struct.unpack('<f', struct.pack('<I', value))[0]
                                      for value in (r0, r1)))
        mu.reg_write(UC_ARM_REG_PC, mu.reg_read(UC_ARM_REG_LR))

    def feed(self, *chunks, source='debug'):
        start = len(self.output)
        rx = {'debug': self.rx, 'pi': self.pi_rx}[source]
        for chunk in chunks:
            rx.extend(chunk.encode('ascii'))
            self.mu.reg_write(UC_ARM_REG_SP, 0x20207F00)
            self.mu.reg_write(UC_ARM_REG_LR, 0x100001)
            self.mu.emu_start(self.symbols['command_poll'] | 1,
                              0x100000, count=1000000)
            if self.mu.reg_read(UC_ARM_REG_PC) != 0x100000:
                raise AssertionError('command_poll did not return')
        return self.output[start:]


class TestCommandArm(unittest.TestCase):
    def test_pid_apply_and_query(self):
        firmware = Firmware()
        response = firmware.feed('P 3 2 0\n')
        self.assertIn('OK P\r\n', response)
        self.assertIn('PID RAM 3 2 0 FLASH NONE\r\n', response)
        self.assertEqual(firmware.gains, (3, 2, 0))
        self.assertIn('PID RAM 3 2 0', firmware.feed('P?'))
        self.assertEqual(firmware.wheels, [])

    def test_fragmented_tabs_and_crlf(self):
        firmware = Firmware()
        response = firmware.feed('p\t+4000', '\t+1500 ', '+0\r', '\n')
        self.assertEqual(response.count('OK P\r\n'), 1)
        self.assertEqual(firmware.gains, (4000, 1500, 0))
        self.assertEqual(firmware.wheels, [])

    def test_zero_and_upper_limits(self):
        firmware = Firmware()
        for command, expected in [('P 0 0 0\n', (0, 0, 0)),
                                  ('P 100000 100000 100000\n', (100000,) * 3)]:
            with self.subTest(command=command):
                self.assertIn('OK P\r\n', firmware.feed(command))
                self.assertEqual(firmware.gains, expected)
        self.assertEqual(firmware.wheels, [])

    def test_invalid_parameters_do_not_change_gains(self):
        firmware = Firmware()
        for command in ('P -1 2 0\n', 'P 100001 2 0\n', 'P 3 2\n',
                        'P x 2 0\n', 'P 3 2 0 garbage\n'):
            with self.subTest(command=command):
                self.assertIn('ERR P\r\n', firmware.feed(command))
                self.assertEqual(firmware.gains, (4000, 1500, 0))
        self.assertEqual(firmware.wheels, [])

    def test_movement_numeric_parser_and_immediate_stop(self):
        firmware = Firmware()
        self.assertIn('OK M\r\n', firmware.feed('M 0 0\n'))
        self.assertIn('OK G\r\n', firmware.feed('G -300 0\n'))
        self.assertAlmostEqual(firmware.targets[-1][0], -0.3, places=5)
        self.assertIn('OK 0\r\n', firmware.feed('0'))

    def test_direct_pwm_and_pid_commands_on_both_links(self):
        for source in ('debug', 'pi'):
            firmware = Firmware()
            for pwm in (0, 1, 10000, -10000):
                with self.subTest(source=source, pwm=pwm):
                    self.assertIn('OK P PWM\r\n',
                                  firmware.feed(f'P {pwm}\n', source=source))
                    self.assertEqual(firmware.wheels[-1], (pwm, pwm))
                    self.assertEqual(firmware.gains, (4000, 1500, 0))
            count = len(firmware.wheels)
            for command in ('P 10001\n', 'P -10001\n', 'P 3 2\n'):
                self.assertIn('ERR P', firmware.feed(command, source=source))
                self.assertEqual(len(firmware.wheels), count)
            self.assertIn('OK P\r\n',
                          firmware.feed('P 3000 1000 0\n', source=source))
            self.assertEqual(firmware.gains, (3000, 1000, 0))

    def test_servo_commands_on_both_links(self):
        for source in ('debug', 'pi'):
            firmware = Firmware()
            for pulse in (1000, 1500, 2000):
                self.assertIn('OK D\r\n',
                              firmware.feed(f'd {pulse}\r\n', source=source))
                self.assertEqual(firmware.servo_pulses[-1], pulse)
            count = len(firmware.servo_pulses)
            for command in ('D 999\n', 'D 2001\n', 'D -1\n',
                            'D 1500 extra\n', 'D\n'):
                self.assertIn('ERR D\r\n', firmware.feed(command, source=source))
                self.assertEqual(len(firmware.servo_pulses), count)

    def test_fragmented_commands_from_different_links_are_independent(self):
        firmware = Firmware()
        self.assertEqual(firmware.feed('P 35'), '')
        self.assertEqual(firmware.feed('d 15', source='pi'), '')
        self.assertIn('OK P PWM\r\n', firmware.feed('00\n'))
        self.assertEqual(firmware.wheels, [(3500, 3500)])
        self.assertEqual(firmware.servo_pulses, [])
        self.assertIn('OK D\r\n', firmware.feed('00\n', source='pi'))
        self.assertEqual(firmware.servo_pulses, [1500])
        self.assertIn('OK G\r\n', firmware.feed('G -300 0\n', source='pi'))
        self.assertAlmostEqual(firmware.targets[-1][0], -0.3, places=5)
        self.assertIn('OK 0\r\n', firmware.feed('0', source='pi'))
        self.assertEqual(firmware.stops, 1)

    def test_overlength_line_is_discarded_then_parser_recovers(self):
        for source in ('debug', 'pi'):
            firmware = Firmware()
            self.assertIn('ERR LINE\r\n',
                          firmware.feed('P 100' + ' ' * 70 + 'junk\n',
                                        source=source))
            self.assertEqual(firmware.wheels, [])
            self.assertIn('OK P PWM\r\n',
                          firmware.feed('P 200\n', source=source))
            self.assertEqual(firmware.wheels, [(200, 200)])


if __name__ == '__main__':
    unittest.main()
