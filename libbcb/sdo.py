"""BCB/BCB 쓰기 확인과 파라미터 저장 정책.

모터 명령은 ACK 누락 시 읽기로 확인한다. 일반 파라미터는 제한적으로
재시도하며, 0x2FE5 저장 명령은 중복 실행을 피하기 위해 한 번만 전송한다.
"""

from __future__ import annotations

import time
import can

from cancommon.config import RETRY_DELAY
from cancommon.sdo import exchange_sdo, read_value

SAVE_INDEX = 0x2FE5
WRITE_RETRIES = 2


def write_value(bus: can.BusABC, node_id: int, address: tuple[int, int],
                value: int, size: int, *, signed: bool = False) -> None:
    index, subindex = address
    data = value.to_bytes(size, "little", signed=signed)
    command = {1: 0x2F, 2: 0x2B, 4: 0x23}[size]
    try:
        reply = exchange_sdo(bus, node_id, command, index, subindex,
                             data.ljust(4, b"\x00"))
    except TimeoutError:
        # ACK만 누락됐을 수 있다. 같은 쓰기를 반복하기 전에 현재값을 확인한다.
        if read_value(bus, node_id, address, size, signed=signed) == value:
            print(f"Node {node_id} 0x{index:04X}:{subindex:02X}: ACK 누락, 읽기 확인 성공")
            return
        raise
    if reply[0] != 0x60:
        raise RuntimeError(f"Node {node_id} 0x{index:04X}:{subindex:02X}: 쓰기 응답 0x{reply[0]:02X}")


def read_parameter(bus: can.BusABC, node_id: int, index: int,
                   subindex: int, size: int) -> int:
    return read_value(bus, node_id, (index, subindex), size)


def write_parameter(bus: can.BusABC, node_id: int, index: int,
                    subindex: int, value: int, size: int) -> None:
    if not 0 <= value < 1 << (size * 8):
        raise ValueError(f"0x{index:04X}:{subindex:02X} 값 {value}가 {size}바이트 범위를 벗어났습니다")
    command = {1: 0x2F, 2: 0x2B, 4: 0x23}[size]
    # 저장 명령은 ACK가 없어도 실행됐을 수 있으므로 무조건 재전송하지 않는다.
    retries = WRITE_RETRIES if index != SAVE_INDEX else 1
    for attempt in range(1, retries + 1):
        try:
            reply = exchange_sdo(bus, node_id, command, index, subindex, value.to_bytes(4, "little"))
        except TimeoutError:
            print(f"0x{index:04X}:{subindex:02X} 쓰기 응답 없음 ({attempt}/{retries})")
            if index != SAVE_INDEX:
                try:
                    if read_parameter(bus, node_id, index, subindex, size) == value:
                        print(f"0x{index:04X}:{subindex:02X} 읽기 확인 성공: 쓰기 재전송 생략")
                        return
                except TimeoutError:
                    pass
            if attempt == retries:
                raise
            time.sleep(RETRY_DELAY)
            continue
        if reply[0] != 0x60:
            raise RuntimeError(f"0x{index:04X}:{subindex:02X} 쓰기 응답 0x{reply[0]:02X} (예상 0x60)")
        return
