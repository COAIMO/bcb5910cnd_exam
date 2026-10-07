"""장치 객체 주소를 가정하지 않는 CANopen expedited SDO 통신."""

from __future__ import annotations

import time
import can

from .config import READ_RETRIES, RESPONSE_TIMEOUT, RETRY_DELAY


def exchange_sdo(bus: can.BusABC, node_id: int, command: int,
                 index: int, subindex: int, payload: bytes = b"\x00" * 4, *,
                 response_nodes: tuple[int, ...] = (), timeout: float = RESPONSE_TIMEOUT) -> bytes:
    request_data = bytes((command, index & 0xFF, index >> 8, subindex)) + payload
    request = can.Message(arbitration_id=0x600 + node_id,
                          data=request_data, is_extended_id=False)
    expected_ids = {0x580 + node for node in (response_nodes or (node_id,))}
    bus.send(request)
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        reply = bus.recv(timeout=remaining)
        if reply is None:
            break
        if (reply.is_extended_id or reply.is_remote_frame or reply.is_error_frame
                or reply.arbitration_id not in expected_ids or len(reply.data) != 8
                or reply.data[1:4] != request_data[1:4]):
            continue
        if reply.data[0] == 0x80:
            abort_code = int.from_bytes(reply.data[4:8], "little")
            raise RuntimeError(f"Node {node_id} 0x{index:04X}:{subindex:02X} SDO abort 0x{abort_code:08X}")
        return bytes(reply.data)
    raise TimeoutError(f"Node {node_id} 0x{index:04X}:{subindex:02X} 응답 없음")


def read_sdo(bus: can.BusABC, node_id: int, index: int, subindex: int = 0,
             *, size: int | None = None, retries: int = READ_RETRIES,
             retry_delay: float = RETRY_DELAY) -> bytes:
    """1/2/4바이트 expedited upload. 타임아웃만 재시도한다."""
    lengths = {0x4F: 1, 0x4B: 2, 0x43: 4}
    if retries < 1:
        raise ValueError("읽기 재시도 횟수는 1 이상이어야 합니다")
    if size is not None and size not in lengths.values():
        raise ValueError("SDO 데이터 크기는 1, 2, 4바이트여야 합니다")
    for attempt in range(1, retries + 1):
        try:
            reply = exchange_sdo(bus, node_id, 0x40, index, subindex)
        except TimeoutError:
            if attempt == retries:
                raise
            print(f"Node {node_id} 0x{index:04X}:{subindex:02X}: 읽기 재시도 {attempt}/{retries}")
            if retry_delay:
                time.sleep(retry_delay)
            continue
        length = lengths.get(reply[0])
        if length is None or (size is not None and length != size):
            raise RuntimeError(f"Node {node_id} 0x{index:04X}:{subindex:02X}: 읽기 응답 0x{reply[0]:02X}")
        return reply[4:4 + length]
    raise AssertionError("읽기 재시도 루프가 끝났습니다")


def read_value(bus: can.BusABC, node_id: int, address: tuple[int, int],
               size: int, *, signed: bool = False, retries: int = READ_RETRIES,
               retry_delay: float = RETRY_DELAY) -> int:
    data = read_sdo(bus, node_id, *address, size=size, retries=retries,
                    retry_delay=retry_delay)
    return int.from_bytes(data, "little", signed=signed)


def write_byte(bus: can.BusABC, node_id: int, index: int, subindex: int,
               value: int, response_nodes: tuple[int, ...] = ()) -> None:
    """1바이트 쓰기를 한 번 전송하고 지정한 노드들의 ACK를 허용한다."""
    payload = value.to_bytes(1, "little").ljust(4, b"\x00")
    reply = exchange_sdo(bus, node_id, 0x2F, index, subindex, payload,
                         response_nodes=response_nodes)
    if reply[0] != 0x60:
        raise RuntimeError(f"Node {node_id}: 쓰기 응답 명령 0x{reply[0]:02X} (0x60 예상)")
