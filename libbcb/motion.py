"""모터 테스트의 공통 입력, 감시, 정지 및 순차 운전 루프."""

from __future__ import annotations

import queue
import sys
import threading
import time
from typing import Callable

import can

from .drive import (
    ACTUAL_RPM, CONTROLWORD, EMERGENCY_STOP, TARGET_RPM,
    configure_node, emergency_stop_all, error_text, read_status, reset_errors_all,
)
from cancommon.sdo import read_value

from .sdo import write_value

FEEDBACK_INTERVAL = 0.1
STATUS_INTERVAL = 1.0


def input_worker(commands: queue.Queue[str], monitoring: threading.Event,
                 quit_requested: threading.Event, prompt_text: str,
                 immediate_quit: bool) -> None:
    while True:
        try:
            prompt = ("모니터 중 (Enter로 종료) > " if monitoring.is_set() else
                      prompt_text)
            command = input(prompt).strip()
            if immediate_quit and command.lower() in ("q", "quit", "exit"):
                quit_requested.set()
            commands.put(command)
        except EOFError:
            if immediate_quit:
                quit_requested.set()
            commands.put("quit")
            return


def run_motion(bus: can.BusABC, node_ids: tuple[int, ...], *,
               ramp_dec: int, max_rpm: int, prompt: str,
               parse_targets: Callable[[str], tuple[int, ...]] | None = None,
               sequence: list[tuple[int, tuple[int, int, int, int]]] | None = None,
               sequence_interval: float = 2.0) -> int:
    stopped = True
    last_status: dict[int, tuple[int, int] | None] = {}
    sequence_active = sequence is not None
    row_index = 0
    next_row_at = 0.0
    try:
        for node_id in node_ids:
            configure_node(bus, node_id, ramp_dec)
        for node_id in node_ids:
            write_value(bus, node_id, EMERGENCY_STOP, 0, 1)
            write_value(bus, node_id, CONTROLWORD, 0x0F, 2)
        stopped = False
        print(f"Node {', '.join(map(str, node_ids))} 활성화. 각 노드의 속도 범위: ±{max_rpm} rpm")

        commands: queue.Queue[str] = queue.Queue()
        monitoring = threading.Event()
        quit_requested = threading.Event()
        threading.Thread(
            target=input_worker,
            args=(commands, monitoring, quit_requested, prompt, sequence is not None),
            daemon=True,
        ).start()
        started_at = time.monotonic()
        next_feedback = started_at
        next_status = started_at
        next_row_at = started_at
        if sequence is not None:
            print(f"순차처리 파일: {len(sequence)}행, 각 행 {sequence_interval:g}초 적용. q로 즉시 중단")
        while True:
            try:
                deadlines = [next_status]
                if monitoring.is_set():
                    deadlines.append(next_feedback)
                if sequence_active:
                    deadlines.append(next_row_at)
                next_event = min(deadlines)
                wait = max(0.0, next_event - time.monotonic())
                command = commands.get(timeout=wait)
            except queue.Empty:
                command = None

            command_key = command.lower() if command is not None else None
            if command_key in ("quit", "q", "exit"):
                sequence_active = False
                print("종료: 모든 노드에 비상정지를 요청합니다")
                return 0 if emergency_stop_all(bus, node_ids) else 1
            if command_key == "monitor":
                monitoring.set()
                next_feedback = time.monotonic()
                print("실제 RPM 모니터 시작 (100ms 간격). Enter를 누르면 종료합니다")
            elif command == "" and monitoring.is_set():
                monitoring.clear()
                print("RPM 모니터 종료. 모터 운전은 계속됩니다")
            elif command_key in ("stop", "s", "estop"):
                sequence_active = False
                if not emergency_stop_all(bus, node_ids):
                    print("비상정지 응답을 확인하지 못했습니다. 실제 모터 정지를 확인하세요", file=sys.stderr)
                stopped = True
            elif command_key in ("resume", "r"):
                sequence_active = False
                states = {node: read_status(bus, node) for node in node_ids}
                if any(status & 0x0008 or error for status, error in states.values()):
                    print("오류가 남아 있어 정지를 해제하지 않습니다")
                else:
                    for node in node_ids:
                        write_value(bus, node, TARGET_RPM, 0, 2, signed=True)
                        write_value(bus, node, EMERGENCY_STOP, 0, 1)
                        write_value(bus, node, CONTROLWORD, 0x0F, 2)
                    stopped = False
                    print("비상정지 해제. 목표 속도 0 rpm")
            elif command_key == "reset":
                sequence_active = False
                stopped = True
                if reset_errors_all(bus, node_ids):
                    print("오류 해제 확인 완료. resume으로 운전을 재개하세요")
                else:
                    print("오류 해제를 확인하지 못했습니다. 모든 노드는 정지 상태로 유지합니다")
                last_status.clear()
            elif command_key == "status":
                last_status.clear()
                next_status = 0.0
            elif command_key == "clear":
                print("\033[2J\033[H", end="", flush=True)
                last_status.clear()
                next_status = 0.0
            elif command and parse_targets is not None:
                try:
                    targets = parse_targets(command)
                except ValueError as exc:
                    print(exc)
                else:
                    if stopped:
                        print("비상정지 중입니다. resume 후 속도를 입력하세요")
                    else:
                        try:
                            for node, target in zip(node_ids, targets):
                                write_value(bus, node, TARGET_RPM, target, 2, signed=True)
                            values = ", ".join(f"Node {node}={target}" for node, target in zip(node_ids, targets))
                            print(f"목표 속도: {values} rpm")
                        except (can.CanError, OSError, RuntimeError, TimeoutError):
                            emergency_stop_all(bus, node_ids)
                            stopped = True
                            raise
            elif command:
                print("속도는 '순차처리' 파일에서 읽습니다. q로 종료하거나 monitor/status를 입력하세요")

            if quit_requested.is_set():
                sequence_active = False
                print("q 입력: 모든 노드에 비상정지를 요청합니다")
                return 0 if emergency_stop_all(bus, node_ids) else 1

            if sequence_active and time.monotonic() >= next_row_at:
                if row_index == len(sequence):
                    print("마지막 행 적용 완료: 모든 노드에 비상정지를 요청합니다")
                    return 0 if emergency_stop_all(bus, node_ids) else 1
                line_number, targets = sequence[row_index]
                try:
                    for node, target in zip(node_ids, targets):
                        if quit_requested.is_set():
                            print("q 입력: 남은 노드 명령을 취소합니다")
                            return 0 if emergency_stop_all(bus, node_ids) else 1
                        write_value(bus, node, TARGET_RPM, target, 2, signed=True)
                except (can.CanError, OSError, RuntimeError, TimeoutError):
                    sequence_active = False
                    emergency_stop_all(bus, node_ids)
                    stopped = True
                    raise
                values = ", ".join(f"Node {node}={target}" for node, target in zip(node_ids, targets))
                print(f"파일 {line_number}행 ({row_index + 1}/{len(sequence)}): {values} rpm")
                row_index += 1
                next_row_at = time.monotonic() + sequence_interval

            if monitoring.is_set() and time.monotonic() >= next_feedback:
                try:
                    speeds = []
                    for node in node_ids:
                        if quit_requested.is_set():
                            print("q 입력: 모든 노드에 비상정지를 요청합니다")
                            return 0 if emergency_stop_all(bus, node_ids) else 1
                        speeds.append(read_value(bus, node, ACTUAL_RPM, 4, signed=True) / 1000)
                    elapsed = time.monotonic() - started_at
                    values = ", ".join(f"Node {node}={speed:8.3f}"
                                       for node, speed in zip(node_ids, speeds))
                    print(f"[{elapsed:7.1f}s] 실제 RPM: {values}")
                except (can.CanError, OSError, RuntimeError, TimeoutError) as exc:
                    if not stopped:
                        sequence_active = False
                        emergency_stop_all(bus, node_ids)
                        stopped = True
                    print(f"RPM 피드백 실패: {exc}", file=sys.stderr)
                next_feedback += FEEDBACK_INTERVAL
                if next_feedback < time.monotonic():
                    next_feedback = time.monotonic() + FEEDBACK_INTERVAL

            if time.monotonic() >= next_status:
                try:
                    for node in node_ids:
                        if quit_requested.is_set():
                            print("q 입력: 모든 노드에 비상정지를 요청합니다")
                            return 0 if emergency_stop_all(bus, node_ids) else 1
                        state = read_status(bus, node)
                        if last_status.get(node) != state:
                            status, error = state
                            print(f"Node {node}: 상태=0x{status:04X}, 오류=0x{error:04X} ({error_text(error)})")
                            last_status[node] = state
                        if state[0] & 0x0008 or state[1]:
                            if not stopped:
                                sequence_active = False
                                print(f"Node {node} 오류 감지: 모든 노드 비상정지")
                                emergency_stop_all(bus, node_ids)
                                stopped = True
                except (can.CanError, OSError, RuntimeError, TimeoutError) as exc:
                    if not stopped:
                        sequence_active = False
                        emergency_stop_all(bus, node_ids)
                        stopped = True
                    print(f"상태 모니터링 실패: {exc}", file=sys.stderr)
                next_status = time.monotonic() + STATUS_INTERVAL
    finally:
        emergency_stop_all(bus, node_ids)
