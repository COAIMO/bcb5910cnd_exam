"""'순차처리' 파일의 네 노드 RPM을 한 줄씩 SEQUENCE_INTERVAL초 간격으로 적용한다.

실행: python 모터동작테스트seq.py 1
입력: q(전체 비상정지 후 종료), monitor, stop, resume, reset, status, clear
가속/감속 RAMP_DEC는 시간이 아니라 매뉴얼의 원시 DEC 값이다."""

from __future__ import annotations

from functools import partial
from pathlib import Path
import sys

import can

from libbcb.cli import execute_motion, motion_parser
from libbcb.motion import run_motion
from libbcb.speeds import parse_speeds

MAX_TEST_RPM = 500
RAMP_DEC = 1024
SEQUENCE_INTERVAL = 2.0


def load_sequence(path: Path) -> list[tuple[int, tuple[int, int, int, int]]]:
    """빈 줄을 제외한 각 줄을 네 노드의 RPM 데이터로만 해석한다."""
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            targets = parse_speeds(line, max_rpm=MAX_TEST_RPM)
        except ValueError as exc:
            raise ValueError(f"{path} {line_number}행: {exc}") from exc
        rows.append((line_number, targets))
    if not rows:
        raise ValueError(f"{path}: 실행할 속도 행이 없습니다")
    return rows


def run(bus: can.BusABC, node_ids: tuple[int, ...],
        sequence: list[tuple[int, tuple[int, int, int, int]]]) -> int:
    return run_motion(bus, node_ids, ramp_dec=RAMP_DEC, max_rpm=MAX_TEST_RPM,
                      prompt="q / monitor / stop / resume / reset / status / clear > ",
                      sequence=sequence, sequence_interval=SEQUENCE_INTERVAL)


def main(argv: list[str] | None = None) -> int:
    parser = motion_parser(f"'순차처리' 파일의 네 노드 속도를 행마다 {SEQUENCE_INTERVAL:g}초씩 적용", 4)
    parser.add_argument("--sequence-file", type=Path, default=Path(__file__).with_name("순차처리"),
                        help="속도 순서 파일 (기본: 스크립트 옆의 순차처리)")
    args = parser.parse_args(argv)
    if args.bitrate <= 0:
        parser.error("CAN 속도는 양수여야 합니다")
    try:
        sequence = load_sequence(args.sequence_file)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"순차처리 파일 오류: {exc}", file=sys.stderr)
        return 1
    return execute_motion(args, 4, partial(run, sequence=sequence))


if __name__ == "__main__":
    raise SystemExit(main())
