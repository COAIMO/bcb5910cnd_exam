"""CANopen 노드 인자와 읽기 전용 조회의 공통 실행 처리."""

from __future__ import annotations

import argparse
import sys
from typing import Callable

import can

from .bus import open_bus
from .config import CAN_INTERFACE, CAN_CHANNEL, CAN_BITRATE


def node_id_arg(value: str, *, node_count: int = 1) -> int:
    maximum = 128 - node_count
    label = "Node ID" if node_count == 1 else "시작 Node ID"
    try:
        node_id = int(value, 16 if value.lower().startswith("0x") else 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label}는 숫자여야 합니다") from exc
    if not 1 <= node_id <= maximum:
        raise argparse.ArgumentTypeError(f"{label}는 1~{maximum}이어야 합니다")
    return node_id


def add_can_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--channel", default=CAN_CHANNEL, help=f"CAN 포트 (기본: {CAN_CHANNEL})")
    parser.add_argument("--bitrate", type=int, default=CAN_BITRATE, help=f"CAN 속도 (기본: {CAN_BITRATE})")


def read_nodes_main(argv: list[str] | None, *, description: str,
                    default_nodes: tuple[int, ...],
                    read_node: Callable[[can.BusABC, int], str]) -> int:
    """노드별 읽기 결과를 표시하며 한 노드의 실패가 다른 조회를 막지 않게 한다."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("node_ids", nargs="*", type=node_id_arg,
                        help=f"확인할 Node ID 목록 (기본: {', '.join(map(str, default_nodes))})")
    args = parser.parse_args(argv)
    node_ids = args.node_ids or default_nodes
    print(f"CAN 연결: {CAN_INTERFACE}, {CAN_CHANNEL}, {CAN_BITRATE:,} bps")
    results: dict[int, bool] = {}
    try:
        with open_bus() as bus:
            for node_id in node_ids:
                prefix = f"Node {node_id} [요청 0x{0x600 + node_id:03X} / 응답 0x{0x580 + node_id:03X}]"
                try:
                    detail = read_node(bus, node_id)
                except (can.CanError, RuntimeError, TimeoutError) as exc:
                    results[node_id] = False
                    print(f"{prefix}: 실패 - {exc}")
                else:
                    results[node_id] = True
                    print(f"{prefix}: {detail}")
    except (can.CanError, OSError, ValueError, KeyError) as exc:
        print(f"CAN 어댑터 연결 실패: {exc}", file=sys.stderr)
        return 2
    return 0 if all(results.values()) else 1
