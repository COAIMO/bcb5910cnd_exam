"""BCB 객체 주소와 노드 초기화/상태/비상정지/오류 리셋."""

from __future__ import annotations

import sys
import can

from cancommon.sdo import read_value

from .sdo import write_value

CURRENT_LIMIT_PEAK_AP = 33
CURRENT_LIMIT_DEC = 2048

MODE = (0x6060, 0x00)
CONTROLWORD = (0x6040, 0x00)
STATUSWORD = (0x6041, 0x00)
ERROR_CODE = (0x2601, 0x00)
EMERGENCY_STOP = (0x605A, 0x11)
EMERGENCY_DECEL = (0x605A, 0x01)
ACCEL = (0x6083, 0x00)
DECEL = (0x6084, 0x00)
TARGET_RPM = (0x2FF0, 0x09)  # 16S, rpm
ACTUAL_RPM = (0x60F9, 0x19)  # 32S, 0.001 rpm
CURRENT_LIMIT = (0x6073, 0x00)  # 16U, 출력 전류 제한

ERROR_BITS = (
    "내부 오류", "엔코더 ABZ 오류", "엔코더 UVW 오류", "엔코더 계수 오류",
    "드라이버 과열", "버스 과전압", "버스 저전압", "출력 단락",
    "제동 저항 과열", "위치 추종 오류", "예약", "과부하 I²T",
    "속도 추종 오류", "모터 과열", "모터 탐색 실패", "통신 오류",
)


def error_text(code: int) -> str:
    return ", ".join(name for bit, name in enumerate(ERROR_BITS) if code & (1 << bit)) or "없음"


def read_status(bus: can.BusABC, node_id: int) -> tuple[int, int]:
    status = read_value(bus, node_id, STATUSWORD, 2)
    error = read_value(bus, node_id, ERROR_CODE, 2)
    return status, error


def emergency_stop_all(bus: can.BusABC, node_ids: tuple[int, ...]) -> bool:
    """한 노드가 실패해도 나머지 노드의 비상정지를 시도한다."""
    success = True
    for node_id in node_ids:
        try:
            write_value(bus, node_id, EMERGENCY_STOP, 1, 1)
            print(f"Node {node_id}: 비상정지 요청")
        except (can.CanError, OSError, RuntimeError, TimeoutError) as exc:
            success = False
            print(f"Node {node_id}: 비상정지 확인 실패 - {exc}", file=sys.stderr)
    return success


def reset_errors_all(bus: can.BusABC, node_ids: tuple[int, ...]) -> bool:
    """모든 노드를 정지한 상태에서 0x86 오류 해제를 요청하고 결과를 확인한다."""
    success = emergency_stop_all(bus, node_ids)
    for node_id in node_ids:
        try:
            write_value(bus, node_id, TARGET_RPM, 0, 2, signed=True)
            write_value(bus, node_id, CONTROLWORD, 0x86, 2)
            status, error = read_status(bus, node_id)
            print(f"Node {node_id}: 오류 리셋 후 상태=0x{status:04X}, 오류=0x{error:04X} ({error_text(error)})")
            if status & 0x0008 or error:
                success = False
        except (can.CanError, OSError, RuntimeError, TimeoutError) as exc:
            success = False
            print(f"Node {node_id}: 오류 리셋 실패 - {exc}", file=sys.stderr)
    return success


def configure_node(bus: can.BusABC, node_id: int, ramp_dec: int) -> None:
    status, error = read_status(bus, node_id)
    if status & 0x0008 or error:
        raise RuntimeError(f"Node {node_id}: 오류 상태 0x{status:04X}, 오류 코드 0x{error:04X} ({error_text(error)})")
    for address in (ACCEL, DECEL, EMERGENCY_DECEL):
        write_value(bus, node_id, address, ramp_dec, 4)
        actual = read_value(bus, node_id, address, 4)
        if actual != ramp_dec:
            raise RuntimeError(f"Node {node_id} 0x{address[0]:04X}:{address[1]:02X}: 설정 확인 실패 {actual}")
    write_value(bus, node_id, CURRENT_LIMIT, CURRENT_LIMIT_DEC, 2)
    if read_value(bus, node_id, CURRENT_LIMIT, 2) != CURRENT_LIMIT_DEC:
        raise RuntimeError(f"Node {node_id}: 출력 전류 제한 {CURRENT_LIMIT_PEAK_AP}Ap 설정 확인 실패")
    write_value(bus, node_id, MODE, 3, 1, signed=True)
    if read_value(bus, node_id, MODE, 1, signed=True) != 3:
        raise RuntimeError(f"Node {node_id}: 속도 모드 설정 실패")
    write_value(bus, node_id, TARGET_RPM, 0, 2, signed=True)
    print(f"Node {node_id}: 속도 모드, 가속/감속/비상감속 DEC={ramp_dec}, "
          f"출력 전류 제한 {CURRENT_LIMIT_PEAK_AP}Ap, 목표 속도 0 rpm")
