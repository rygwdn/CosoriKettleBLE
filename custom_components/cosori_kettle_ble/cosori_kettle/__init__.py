"""Cosori Kettle BLE Library.

A standalone Python library for controlling Cosori Smart Kettles via Bluetooth Low Energy.

Basic usage:
    >>> from cosori_kettle import CosoriKettle
    >>> from bleak import BleakScanner
    >>>
    >>> # Scan for device
    >>> device = await BleakScanner.find_device_by_address("AA:BB:CC:DD:EE:FF")
    >>>
    >>> # Connect and control
    >>> async with CosoriKettle(device, "AA:BB:CC:DD:EE:FF") as kettle:
    >>>     await kettle.boil()
    >>>     print(f"Temperature: {kettle.temperature}F")

Advanced usage:
    >>> from cosori_kettle import CosoriKettle, CosoriKettleBLEClient
    >>> from cosori_kettle.protocol import (
    >>>     parse_extended_status,
    >>>     PROTOCOL_VERSION_V1,
    >>> )
"""

__version__ = "1.0.0"

from .client import CosoriKettleBLEClient
from .kettle import CosoriKettle
from .protocol import (
    CompactStatus,
    ExtendedStatus,
    Frame,
    MODE_BOIL,
    MODE_COFFEE,
    MODE_GREEN_TEA,
    MODE_HEAT,
    MODE_MY_TEMP,
    MODE_NAMES,
    MODE_OOLONG,
    PROTOCOL_VERSION_V0,
    PROTOCOL_VERSION_V1,
    build_packet,
    parse_extended_status,
    parse_frames,
)

__all__ = [
    # Main classes
    "CosoriKettle",
    "CosoriKettleBLEClient",
    # Data classes
    "CompactStatus",
    "ExtendedStatus",
    "Frame",
    # Constants
    "MODE_BOIL",
    "MODE_COFFEE",
    "MODE_GREEN_TEA",
    "MODE_HEAT",
    "MODE_MY_TEMP",
    "MODE_NAMES",
    "MODE_OOLONG",
    "PROTOCOL_VERSION_V0",
    "PROTOCOL_VERSION_V1",
    # Protocol functions
    "build_packet",
    "parse_extended_status",
    "parse_frames",
]
