"""BCB 드라이버의 지정한 Node ID별 운전 모드와 Controlword를 읽는다.

실행: python 노드ID체크.py 1 2 (인자 생략 시 NODE_IDS 사용)
읽기 전용: 모터 구동 명령이나 파라미터 쓰기는 보내지 않는다.
"""

from __future__ import annotations

import can

from cancommon.cli import read_nodes_main
from cancommon.sdo import read_sdo


NODE_IDS = (1, 2)

RETRIES = 3


def read_node(bus: can.BusABC, node_id: int) -> str:
    mode_data = read_sdo(bus, node_id, 0x6060, retries=RETRIES, retry_delay=0)
    controlword_data = read_sdo(bus, node_id, 0x6040, retries=RETRIES, retry_delay=0)
    if len(mode_data) != 1 or len(controlword_data) != 2:
        raise RuntimeError("Operation Mode 또는 Controlword의 데이터 길이가 예상과 다릅니다")
    mode = int.from_bytes(mode_data, "little", signed=True)
    controlword = int.from_bytes(controlword_data, "little")
    return f"Operation Mode={mode}, Controlword=0x{controlword:04X}"


def main(argv: list[str] | None = None) -> int:
    return read_nodes_main(argv, description="지정한 CAN Node ID의 운전 모드와 Controlword 읽기",
                           default_nodes=NODE_IDS, read_node=read_node)


if __name__ == "__main__":
    raise SystemExit(main())
