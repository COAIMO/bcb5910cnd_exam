"""BCB의 연속된 두 CAN 노드를 반대 방향 속도로 운전한다.

실행: python 모터동작테스트.py 1
입력: RPM 숫자, monitor(Enter로 종료), stop, resume, reset, status, clear, quit
가속/감속 4096은 시간이 아니라 매뉴얼의 원시 DEC 값이다."""

from __future__ import annotations

from functools import partial

import can

from libbcb.cli import execute_motion, motion_parser
from libbcb.motion import run_motion
from libbcb.speeds import alternating_speeds

MAX_TEST_RPM = 500
RAMP_DEC = 512


def run(bus: can.BusABC, node_ids: tuple[int, ...]) -> int:
    return run_motion(bus, node_ids, ramp_dec=RAMP_DEC, max_rpm=MAX_TEST_RPM,
                      prompt="속도(rpm) / monitor / stop / resume / reset / status / clear / quit > ",
                      parse_targets=partial(alternating_speeds, node_count=len(node_ids), max_rpm=MAX_TEST_RPM))


def main(argv: list[str] | None = None) -> int:
    parser = motion_parser("연속된 두 CAN 노드의 반대 방향 속도 운전", 2)
    args = parser.parse_args(argv)
    if args.bitrate <= 0:
        parser.error("CAN 속도는 양수여야 합니다")
    return execute_motion(args, 2, run)


if __name__ == "__main__":
    raise SystemExit(main())
