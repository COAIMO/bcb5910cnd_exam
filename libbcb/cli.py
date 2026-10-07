"""BCB/BCB 모터 운전 명령행 및 실행 오류 처리."""

from __future__ import annotations

import argparse
from functools import partial
import sys
from typing import Callable

import can

from cancommon.bus import open_bus
from cancommon.cli import add_can_arguments, node_id_arg
from cancommon.config import CAN_INTERFACE


def motion_parser(description: str, node_count: int) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("start_id", type=partial(node_id_arg, node_count=node_count),
                        help=f"시작 Node ID (연속 {node_count}개 노드)")
    add_can_arguments(parser)
    return parser


def execute_motion(args: argparse.Namespace, node_count: int,
                   run: Callable[[can.BusABC, tuple[int, ...]], int]) -> int:
    node_ids = tuple(args.start_id + offset for offset in range(node_count))
    print(f"CAN 연결: {CAN_INTERFACE}, {args.channel}, {args.bitrate:,} bps, Node {node_ids}")
    try:
        with open_bus(args.channel, args.bitrate) as bus:
            return run(bus, node_ids)
    except KeyboardInterrupt:
        print("사용자 중단")
        return 130
    except (can.CanError, OSError, RuntimeError, TimeoutError, ValueError, KeyError) as exc:
        print(f"모터 동작 실패: {exc}", file=sys.stderr)
        return 1
