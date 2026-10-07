"""BCB 드라이버의 CAN Node ID를 SDO로 변경하고 S1에 저장한다.

파일 상단의 OLD_NODE_ID, NEW_NODE_ID를 설정한 뒤 인자 없이 실행할 수 있다.
실행 시 다른 값을 쓰려면: python 노드ID변경.py 1 3
매뉴얼: SW3가 OFF일 때 0x6510:0F(RS485/CAN ID)가 적용된다.
변경 후 전원을 다시 켜고 새 ID에서 확인해야 한다.
"""

from __future__ import annotations

import argparse
import sys

import can

from cancommon.bus import open_bus
from cancommon.cli import add_can_arguments, node_id_arg
from cancommon.config import CAN_INTERFACE
from cancommon.sdo import read_value, write_byte


# 변경할 ID를 여기서 지정한다. 명령행 인자를 주면 이 값보다 우선한다.
OLD_NODE_ID = 1
NEW_NODE_ID = 3

ID_INDEX, ID_SUBINDEX = 0x6510, 0x0F
SAVE_INDEX, SAVE_SUBINDEX = 0x2FE5, 0x01  # S1 파라미터 저장


def read_id(bus: can.BusABC, node_id: int) -> int:
    return read_value(bus, node_id, (ID_INDEX, ID_SUBINDEX), 1)


def find_active_id(bus: can.BusABC, old_id: int, new_id: int) -> int:
    """변경이 즉시 적용되는지 알 수 없으므로 두 주소를 읽어 확인한다."""
    for node_id in (new_id, old_id):
        try:
            value = read_id(bus, node_id)
        except TimeoutError:
            continue
        if value != new_id:
            raise RuntimeError(f"Node {node_id}의 ID 설정값이 {value}입니다 (예상: {new_id})")
        return node_id
    raise TimeoutError("ID 쓰기 후 기존 ID와 새 ID 모두 응답하지 않습니다. 전원 및 SW3 상태를 확인하세요")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BCB CAN Node ID 변경 및 S1 저장 (SW3 OFF 필요)")
    parser.add_argument("old_id", nargs="?", type=node_id_arg, default=OLD_NODE_ID,
                        help=f"현재 CAN Node ID (기본: {OLD_NODE_ID})")
    parser.add_argument("new_id", nargs="?", type=node_id_arg, default=NEW_NODE_ID,
                        help=f"변경할 CAN Node ID (기본: {NEW_NODE_ID})")
    add_can_arguments(parser)
    args = parser.parse_args(argv)
    if not 1 <= args.old_id <= 127 or not 1 <= args.new_id <= 127:
        parser.error("설정한 ID는 1~127이어야 합니다")
    if args.old_id == args.new_id:
        parser.error("현재 ID와 새 ID가 같습니다")

    print(f"CAN 연결: {CAN_INTERFACE}, {args.channel}, {args.bitrate:,} bps")
    try:
        with open_bus(args.channel, args.bitrate) as bus:
            current_value = read_id(bus, args.old_id)
            print(f"Node {args.old_id}: 0x6510:0F = {current_value}")
            if current_value != args.old_id:
                raise RuntimeError("현재 CAN ID와 설정값이 다릅니다. SW3를 OFF로 설정하고 실제 ID를 확인하세요")

            try:
                destination_value = read_id(bus, args.new_id)
            except TimeoutError:
                pass
            else:
                raise RuntimeError(f"새 ID {args.new_id}에 이미 응답하는 장치가 있습니다 (설정값 {destination_value})")

            print(f"ID 변경: {args.old_id} -> {args.new_id}")
            # ID가 쓰기 즉시 바뀌는 펌웨어도 있으므로 양쪽 응답 ID를 수락한다.
            try:
                write_byte(bus, args.old_id, ID_INDEX, ID_SUBINDEX, args.new_id,
                           response_nodes=(args.old_id, args.new_id))
            except TimeoutError:
                # 전송 직후 주소가 바뀌어 ACK를 받지 못했을 수 있다. 재전송 전에 읽기로 확인한다.
                print("ID 쓰기 응답 없음: 현재/새 ID의 설정값을 읽어 확인합니다")
            active_id = find_active_id(bus, args.old_id, args.new_id)
            print(f"Node {active_id}: 새 ID 설정값 읽기 확인")

            write_byte(bus, active_id, SAVE_INDEX, SAVE_SUBINDEX, 1)
            print("S1 파라미터 저장 완료")
            active_id = find_active_id(bus, args.old_id, args.new_id)
            print(f"Node {active_id}: 저장 후 ID 설정값 = {args.new_id}")
            print(f"전원을 다시 켠 뒤 Node {args.new_id}로 응답하는지 확인하세요.")
            return 0
    except (can.CanError, OSError, ValueError, KeyError, RuntimeError, TimeoutError) as exc:
        print(f"ID 변경 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
