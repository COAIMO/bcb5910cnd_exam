"""BCB 드라이버의 CANopen SDO 응답으로 지정한 Node ID의 위치를 읽는다.

실행: python 노드ID위치.py 1 2 (인자 생략 시 NODE_IDS 사용)
읽기 전용: 모터 구동 명령이나 파라미터 쓰기는 보내지 않는다.
"""

from __future__ import annotations

import can

from cancommon.cli import read_nodes_main
from cancommon.sdo import read_value


NODE_IDS = (1, 2)

SDO_INDEX = 0x6063  # Actual position (매뉴얼 4.3절, 32-bit signed)
SDO_SUBINDEX = 0x00
RETRIES = 2


def read_actual_position(bus: can.BusABC, node_id: int) -> int:
    return read_value(bus, node_id, (SDO_INDEX, SDO_SUBINDEX), 4,
                      signed=True, retries=RETRIES, retry_delay=0)


def main(argv: list[str] | None = None) -> int:
    return read_nodes_main(
        argv, description="지정한 CAN Node ID의 실제 위치 읽기", default_nodes=NODE_IDS,
        read_node=lambda bus, node_id: f"확인됨, 실제 위치={read_actual_position(bus, node_id)}",
    )


if __name__ == "__main__":
    raise SystemExit(main())
