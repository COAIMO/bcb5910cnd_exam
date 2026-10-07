"""공통 CAN 어댑터 연결."""

import can

from .config import CAN_INTERFACE, CAN_CHANNEL, CAN_BITRATE


def open_bus(channel: str = CAN_CHANNEL, bitrate: int = CAN_BITRATE) -> can.BusABC:
    return can.Bus(interface=CAN_INTERFACE, channel=channel, bitrate=bitrate,
                   frame_type="STD", operation_mode="normal", ignore_config=True)
