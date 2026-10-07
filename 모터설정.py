"""BCB 모터 파라미터와 속도 루프 PI 게인을 CAN SDO로 설정하고 저장한다.

실행: python 모터설정.py 1  (인자 생략 시 NODE_ID 사용)
매뉴얼 Table F1-1: 0x6410의 각 SubIndex는 S4 모터 파라미터이다.
매뉴얼 Table F1-2: 0x60F9:01/02는 S5 속도 루프 P/I 게인이다.
매뉴얼 Table F1-6: 0x2FE5:04/05에 1을 쓰면 S4/S5를 저장한다.
"""

from __future__ import annotations

import argparse
import sys

import can

from cancommon.bus import open_bus
from cancommon.cli import add_can_arguments, node_id_arg
from cancommon.config import CAN_INTERFACE
from libbcb.sdo import read_parameter, write_parameter


NODE_ID = 1

# (SubIndex, 설정값, 바이트 수, 항목명). 0x09/0x0B의 단위는 0.1 A이다.
MOTOR_PARAMETERS = (
    (0x03, 4096, 4, "Encoder resolution"),
    (0x05, 15,   1, "Motor pole pair"),
    (0x06, 0,    1, "Exciting mode"),
    (0x09, 100,   2, "Motor IIt current (0.1 A)"),
    (0x0B, 300,  2, "Motor max. current (0.1 A)"),
    (0x1A, 350,  2, "Motor rated speed (rpm)"),
    (0x08, 100,  2, "Exciting time (ms)"),
)
MOTOR_INDEX = 0x6410
# (Index, SubIndex, 설정값, 바이트 수, 항목명). 둘 다 16U, S5이다.
SPEED_GAINS = (
    (0x60F9, 0x01, 300, 2, "Speed loop P gain (Kvp0)"),
    (0x60F9, 0x02, 10,   2, "Speed loop I gain (Kvi0)"),
)
PARAMETERS = tuple(
    (MOTOR_INDEX, subindex, value, size, name)
    for subindex, value, size, name in MOTOR_PARAMETERS
) + SPEED_GAINS
SAVE_INDEX = 0x2FE5
SAVE_SUBINDICES = (0x04, 0x05)  # S4 모터 파라미터, S5 제어 루프 파라미터


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BCB 모터 파라미터 7개와 속도 PI 게인 설정 및 S4/S5 저장")
    parser.add_argument("node_id", nargs="?", type=node_id_arg, default=NODE_ID,
                        help=f"설정할 CAN Node ID (기본: {NODE_ID})")
    add_can_arguments(parser)
    args = parser.parse_args(argv)
    if not 1 <= args.node_id <= 127:
        parser.error("설정한 NODE_ID는 1~127이어야 합니다")
    if args.bitrate <= 0:
        parser.error("CAN 속도는 양수여야 합니다")

    print(f"CAN 연결: {CAN_INTERFACE}, {args.channel}, {args.bitrate:,} bps, Node {args.node_id}")
    try:
        with open_bus(args.channel, args.bitrate) as bus:
            # 모든 항목이 읽히는지 확인한 뒤 변경을 시작한다.
            current_values: dict[tuple[int, int], int] = {}
            for index, subindex, value, size, name in PARAMETERS:
                current = read_parameter(bus, args.node_id, index, subindex, size)
                current_values[index, subindex] = current
                if current == value:
                    print(f"0x{index:04X}:{subindex:02X} {name}: 현재 {current} (이미 설정됨)")
                else:
                    print(f"0x{index:04X}:{subindex:02X} {name}: 현재 {current} -> 목표 {value}")

            for index, subindex, value, size, name in PARAMETERS:
                if current_values[index, subindex] == value:
                    continue
                write_parameter(bus, args.node_id, index, subindex, value, size)
                actual = read_parameter(bus, args.node_id, index, subindex, size)
                if actual != value:
                    raise RuntimeError(f"0x{index:04X}:{subindex:02X} 확인 실패: {actual} (예상 {value})")
                print(f"0x{index:04X}:{subindex:02X} {name}: {actual} 확인")

            for save_subindex in SAVE_SUBINDICES:
                write_parameter(bus, args.node_id, SAVE_INDEX, save_subindex, 1, 1)
                print(f"S{save_subindex} 파라미터 저장 완료")
            for index, subindex, value, size, _ in PARAMETERS:
                actual = read_parameter(bus, args.node_id, index, subindex, size)
                if actual != value:
                    raise RuntimeError(f"저장 후 0x{index:04X}:{subindex:02X} 확인 실패: {actual} (예상 {value})")
            print(f"저장 후 {len(PARAMETERS)}개 설정값 읽기 확인 완료")
            return 0
    except (can.CanError, OSError, ValueError, KeyError, RuntimeError, TimeoutError) as exc:
        print(f"모터 설정 실패: {exc}", file=sys.stderr)
        print("일부 값이 이미 변경되었을 수 있습니다. 장치 상태를 확인하세요.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
