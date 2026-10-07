"""실제 CAN 포트에 연결하지 않는 통신/운전 회귀 검사."""

from collections import deque
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import argparse
import importlib.util
import io
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import can

OUTPUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OUTPUT))

from cancommon import cli, sdo
from libbcb import drive, sdo as bcb_sdo
from libbcb.speeds import alternating_speeds, parse_speeds


def load_script(name, directory=OUTPUT):
    spec = importlib.util.spec_from_file_location(name, directory / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReplyBus:
    def __init__(self, replies):
        self.replies = deque(replies)
        self.sent = []

    def send(self, message):
        self.sent.append(message)

    def recv(self, timeout):
        return self.replies.popleft() if self.replies else None


def reply(command=0x43, index=0x6063, subindex=0, value=0, node=1, **flags):
    data = bytes((command, index & 255, index >> 8, subindex))
    data += (value & 0xFFFFFFFF).to_bytes(4, 'little')
    return can.Message(arbitration_id=0x580 + node, data=data,
                       is_extended_id=False, **flags)


class DeviceBus:
    """SDO 객체 저장소를 가진 가상 장치. 쓰기/읽기 프레임을 기록한다."""

    def __init__(self, nodes=(1, 2, 3, 4), immediate_id=True, drop_ack=()):
        self.nodes = set(nodes)
        self.immediate_id = immediate_id
        self.drop_ack = set(drop_ack)
        self.values = {}
        self.sent = []
        self.pending = None
        self.sizes = {
            drive.MODE: 1, drive.CONTROLWORD: 2, drive.STATUSWORD: 2,
            drive.ERROR_CODE: 2, drive.TARGET_RPM: 2, drive.ACTUAL_RPM: 4,
            (0x6063, 0): 4, (0x6510, 0x0F): 1,
        }

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def send(self, message):
        self.sent.append((message.arbitration_id, bytes(message.data)))
        node = message.arbitration_id - 0x600
        command, lo, hi, subindex = message.data[:4]
        address = (lo | hi << 8, subindex)
        self.pending = None
        if node not in self.nodes:
            return
        if command == 0x40:
            default = node if address == (0x6510, 0x0F) else 0
            size, value = self.values.get((node, address), (self.sizes[address], default))
            self.pending = reply({1: 0x4F, 2: 0x4B, 4: 0x43}[size], *address, value, node)
            return
        size = {0x2F: 1, 0x2B: 2, 0x23: 4}[command]
        value = int.from_bytes(message.data[4:4 + size], 'little')
        self.values[node, address] = (size, value)
        self.sizes[address] = size
        if address == (0x6510, 0x0F) and self.immediate_id:
            self.nodes.remove(node)
            self.nodes.add(value)
            self.values[value, address] = (size, value)
            node = value
        if address not in self.drop_ack:
            self.pending = reply(0x60, *address, node=node)

    def recv(self, timeout):
        result, self.pending = self.pending, None
        return result


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


class CommandQueue:
    def __init__(self, clock, commands):
        self.clock = clock
        self.commands = deque(commands)
        self.calls = 0

    def get(self, timeout):
        self.calls += 1
        if self.calls > 200:
            raise AssertionError('운전 루프가 종료되지 않았습니다')
        if self.commands:
            return self.commands.popleft()
        self.clock.now += timeout
        raise queue.Empty


def run_offline(module, nodes, commands, sequence=None, bus=None):
    """입력 스레드와 시계만 대체하여 실제 운전/SDO 코드를 실행한다."""
    bus = bus or DeviceBus(nodes)
    clock = Clock()
    commands = CommandQueue(clock, commands)
    with ExitStack() as stack:
        stack.enter_context(patch('time.monotonic', clock.monotonic))
        stack.enter_context(patch('time.sleep', clock.sleep))
        stack.enter_context(patch('queue.Queue', return_value=commands))
        stack.enter_context(patch('threading.Thread'))
        args = (bus, nodes) if sequence is None else (bus, nodes, sequence)
        result = module.run(*args)
    return result, bus.sent, clock.now


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.stack.enter_context(patch('can.Bus', side_effect=AssertionError('실제 CAN 접근 금지')))
        self.stack.enter_context(patch('time.sleep'))


class SdoTests(OfflineTests):
    def test_ignores_unrelated_and_invalid_frames(self):
        extended = reply()
        extended.is_extended_id = True
        short = reply()
        short.data = short.data[:7]
        bus = ReplyBus([reply(node=2), reply(index=0x6041), reply(subindex=1),
                        extended, reply(is_remote_frame=True), reply(is_error_frame=True),
                        short, reply(value=-123)])
        self.assertEqual(sdo.read_value(bus, 1, (0x6063, 0), 4, signed=True), -123)
        self.assertEqual(bytes(bus.sent[0].data), bytes.fromhex('40 63 60 00 00 00 00 00'))
        self.assertEqual(len(bus.sent), 1)

    def test_upload_sizes_and_commands(self):
        for command, size in ((0x4F, 1), (0x4B, 2), (0x43, 4)):
            with self.subTest(size=size):
                self.assertEqual(sdo.read_sdo(ReplyBus([reply(command, value=23)]),
                                             1, 0x6063), (23).to_bytes(size, 'little'))
        for command in (0x60, 0x47, 0x4F):
            with self.subTest(command=command), self.assertRaises(RuntimeError):
                sdo.read_value(ReplyBus([reply(command)]), 1, (0x6063, 0), 4)

    def test_abort_is_not_retried(self):
        bus = ReplyBus([reply(0x80, value=0x06020000)])
        with self.assertRaisesRegex(RuntimeError, '06020000'):
            sdo.read_value(bus, 1, (0x6063, 0), 4)
        self.assertEqual(len(bus.sent), 1)

    def test_timeout_retry_count(self):
        for attempts in (2, 3):
            bus = ReplyBus([])
            with self.assertRaises(TimeoutError):
                sdo.read_value(bus, 1, (0x6063, 0), 4, retries=attempts)
            self.assertEqual(len(bus.sent), attempts)

    def test_signed_write_and_missing_ack_readback(self):
        bus = DeviceBus(drop_ack=(drive.TARGET_RPM,))
        bcb_sdo.write_value(bus, 1, drive.TARGET_RPM, -123, 2, signed=True)
        self.assertEqual(bus.sent[0][1], bytes.fromhex('2B F0 2F 09 85 FF 00 00'))
        self.assertEqual([data[0] for _, data in bus.sent], [0x2B, 0x40])

    def test_motion_write_does_not_blindly_repeat(self):
        bus = ReplyBus([None, reply(0x4B, *drive.TARGET_RPM, value=0)])
        with self.assertRaises(TimeoutError):
            bcb_sdo.write_value(bus, 1, drive.TARGET_RPM, 123, 2)
        self.assertEqual([m.data[0] for m in bus.sent], [0x2B, 0x40])

    def test_parameter_retry_and_save_no_retry(self):
        bus = ReplyBus([None, reply(0x4B, 0x6410, 9), reply(0x60, 0x6410, 9)])
        bcb_sdo.write_parameter(bus, 1, 0x6410, 9, 100, 2)
        self.assertEqual([m.data[0] for m in bus.sent], [0x2B, 0x40, 0x2B])
        bus = ReplyBus([])
        with self.assertRaises(TimeoutError):
            bcb_sdo.write_parameter(bus, 1, bcb_sdo.SAVE_INDEX, 4, 1, 1)
        self.assertEqual(len(bus.sent), 1)

    def test_id_change_accepts_new_node_ack(self):
        bus = DeviceBus(nodes=(1,))
        sdo.write_byte(bus, 1, 0x6510, 15, 3, response_nodes=(1, 3))
        self.assertEqual(bus.nodes, {3})
        self.assertEqual(len(bus.sent), 1)


class ScriptTests(OfflineTests):
    def test_cancommon_imports_without_device_library(self):
        code = '''
import importlib.abc
import sys

class RejectDeviceLibrary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('libbcb', 'BCB'):
            raise ImportError('cancommon must be independent: ' + fullname)

sys.meta_path.insert(0, RejectDeviceLibrary())
import cancommon.bus
import cancommon.cli
import cancommon.config
import cancommon.sdo
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=OUTPUT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_scripts_help_without_can(self):
        for path in OUTPUT.glob('*.py'):
            with self.subTest(script=path.name), self.assertRaises(SystemExit) as result:
                load_script(path.stem).main(['--help'])
            self.assertEqual(result.exception.code, 0)

    def test_node_id_boundaries(self):
        for count, maximum in ((1, 127), (2, 126), (4, 124)):
            self.assertEqual(cli.node_id_arg(hex(maximum), node_count=count), maximum)
            for invalid in ('0', str(maximum + 1), 'abc'):
                with self.assertRaises(argparse.ArgumentTypeError):
                    cli.node_id_arg(invalid, node_count=count)

    def test_read_only_scripts_send_only_uploads(self):
        for name in ('노드ID체크', '노드ID위치'):
            module = load_script(name)
            bus = DeviceBus()
            with patch.object(cli, 'open_bus', return_value=bus):
                self.assertEqual(module.main(['1', '2']), 0)
            self.assertTrue(all(data[0] == 0x40 for _, data in bus.sent))

    def test_node_id_change_immediate_delayed_and_ack_loss(self):
        module = load_script('노드ID변경')
        for immediate in (False, True):
            for lost in (False, True):
                with self.subTest(immediate=immediate, lost=lost):
                    bus = DeviceBus(nodes=(1,), immediate_id=immediate,
                                    drop_ack=((0x6510, 15),) if lost else ())
                    with patch.object(module, 'open_bus', return_value=bus):
                        self.assertEqual(module.main(['1', '3']), 0)
                    writes = [data for _, data in bus.sent if data[0] != 0x40]
                    self.assertEqual(len(writes), 2)  # ID 쓰기와 S1 저장을 각각 한 번

    def test_node_id_collision_prevents_writes(self):
        module = load_script('노드ID변경')
        bus = DeviceBus(nodes=(1, 3))
        with patch.object(module, 'open_bus', return_value=bus):
            self.assertEqual(module.main(['1', '3']), 1)
        self.assertTrue(all(data[0] == 0x40 for _, data in bus.sent))

    def test_motor_parameters_and_save_groups(self):
        module = load_script('모터설정')
        bus = DeviceBus(nodes=(1,))
        bus.sizes.update({(index, sub): size for index, sub, _, size, _ in module.PARAMETERS})
        with patch.object(module, 'open_bus', return_value=bus):
            self.assertEqual(module.main(['1']), 0)
        for index, sub, value, size, _ in module.PARAMETERS:
            self.assertEqual(bus.values.get((1, (index, sub)), (size, 0)), (size, value))
        saves = [data for _, data in bus.sent if data[0] == 0x2F and data[1:3] == b'\xe5\x2f']
        self.assertEqual([data[3] for data in saves], [4, 5])

    def test_speed_parsing_and_sequence_file_errors(self):
        self.assertEqual(alternating_speeds('-100', node_count=4, max_rpm=500), (-100, 100, -100, 100))
        self.assertEqual(parse_speeds('1 -2 3 -4'), (1, -2, 3, -4))
        for invalid in ('1 2 3', 'a 2 3 4', '501 0 0 0'):
            with self.assertRaises(ValueError):
                parse_speeds(invalid)
        module = load_script('모터동작테스트seq')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'sequence'
            path.write_text('\ufeff1 2 3 4\n\n-1 -2 -3 -4\n', encoding='utf-8')
            self.assertEqual(module.load_sequence(path), [(1, (1, 2, 3, 4)), (3, (-1, -2, -3, -4))])
            path.write_text('\n1 2\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '2행'):
                module.load_sequence(path)


class MotionTests(OfflineTests):
    def test_manual_variants_keep_direction_and_ramp(self):
        for name, nodes, command, targets in (
            ('모터동작테스트', (1, 2), '100', (100, -100)),
            ('모터동작테스트multi', (1, 2, 3, 4), '100', (100, -100, 100, -100)),
            ('모터동작테스트mulicase', (1, 2, 3, 4), '10 -20 30 -40', (10, -20, 30, -40)),
        ):
            with self.subTest(script=name):
                bus = DeviceBus(nodes)
                result, _, _ = run_offline(load_script(name), nodes, [command, 'quit'], bus=bus)
                self.assertEqual(result, 0)
                for node, target in zip(nodes, targets):
                    self.assertEqual(bus.values[node, drive.TARGET_RPM], (2, target & 0xFFFF))
                    self.assertEqual(bus.values[node, drive.ACCEL], (4, 512))
                    self.assertEqual(bus.values[node, drive.EMERGENCY_STOP], (1, 1))

    def test_sequence_completes_after_last_row_interval(self):
        bus = DeviceBus()
        result, _, elapsed = run_offline(load_script('모터동작테스트seq'), (1, 2, 3, 4), [],
                                         [(1, (10, 20, 30, 40)), (2, (-10, -20, -30, -40))], bus)
        self.assertEqual(result, 0)
        self.assertEqual(elapsed, 4.0)
        for node in range(1, 5):
            self.assertEqual(bus.values[node, drive.ACCEL], (4, 1024))
            self.assertEqual(bus.values[node, drive.TARGET_RPM], (2, (-10 * node) & 0xFFFF))
            self.assertEqual(bus.values[node, drive.EMERGENCY_STOP], (1, 1))

    def test_stop_blocks_speed_until_resume(self):
        bus = DeviceBus(nodes=(1, 2))
        result, sent, _ = run_offline(load_script('모터동작테스트'), (1, 2),
                                      ['stop', '100', 'resume', '200', 'quit'], bus=bus)
        self.assertEqual(result, 0)
        targets = [int.from_bytes(data[4:6], 'little', signed=True) for _, data in sent
                   if data[:4] == bytes.fromhex('2B F0 2F 09')]
        self.assertNotIn(100, targets)
        self.assertEqual(targets[-2:], [200, -200])

    def test_failure_stops_every_node(self):
        bus = DeviceBus(nodes=(1, 2, 3, 4))
        bus.values[1, drive.ERROR_CODE] = (2, 1)
        with self.assertRaises(RuntimeError):
            run_offline(load_script('모터동작테스트multi'), (1, 2, 3, 4), [], bus=bus)
        for node in range(1, 5):
            self.assertEqual(bus.values[node, drive.EMERGENCY_STOP], (1, 1))

    def test_stop_attempts_remaining_nodes_after_failure(self):
        with patch.object(drive, 'write_value', side_effect=[TimeoutError(), None, None]) as write:
            self.assertFalse(drive.emergency_stop_all(object(), (1, 2, 3)))
        self.assertEqual([call.args[1] for call in write.call_args_list], [1, 2, 3])

    def test_sequence_quit_between_nodes_cancels_remaining_targets(self):
        module = load_script('모터동작테스트seq')
        bus = DeviceBus()
        quit_event = None
        original_send = bus.send

        def start_thread(*, target, args, daemon):
            nonlocal quit_event
            quit_event = args[2]
            return unittest.mock.Mock()

        def send(message):
            original_send(message)
            if message.data[:4] == bytes.fromhex('2B F0 2F 09') and message.data[4] == 10:
                quit_event.set()

        bus.send = send
        clock = Clock()
        with patch('threading.Thread', side_effect=start_thread), \
             patch('queue.Queue', return_value=CommandQueue(clock, [])), \
             patch('time.monotonic', clock.monotonic):
            self.assertEqual(module.run(bus, (1, 2, 3, 4), [(1, (10, 20, 30, 40))]), 0)
        self.assertEqual(bus.values[1, drive.TARGET_RPM], (2, 10))
        for node in (2, 3, 4):
            self.assertEqual(bus.values[node, drive.TARGET_RPM], (2, 0))


if __name__ == '__main__':
    unittest.main()
