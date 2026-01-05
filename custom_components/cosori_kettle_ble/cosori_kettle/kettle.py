"""High-level API for controlling Cosori Kettle."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from bleak.backends.device import BLEDevice

from .client import CosoriKettleBLEClient
from .exceptions import (
    DeviceNotInPairingModeError,
    InvalidRegistrationKeyError,
    ProtocolError,
)
from .protocol import (
    ACK_HEADER_TYPE,
    PROTOCOL_VERSION_V1,
    ExtendedStatus,
    Frame,
    build_hello_frame,
    build_register_frame,
    build_set_baby_formula_frame,
    build_set_mode_frame,
    build_set_my_temp_frame,
    build_status_request_frame,
    build_stop_frame,
    parse_extended_status,
    MODE_BOIL,
    MODE_COFFEE,
    MODE_GREEN_TEA,
    MODE_MY_TEMP,
    MODE_OOLONG,
)

_LOGGER = logging.getLogger(__name__)


class CosoriKettle:
    """High-level controller for Cosori Kettle.

    Example usage:
        >>> async with CosoriKettle(ble_device, mac_address) as kettle:
        >>>     await kettle.heat_to_temperature(180)
        >>>     status = kettle.status
        >>>     print(f"Temperature: {status.temp}F")
    """

    def __init__(
        self,
        ble_device: BLEDevice,
        registration_key: bytes,
        protocol_version: int = PROTOCOL_VERSION_V1,
        status_callback: Callable[[ExtendedStatus], None] | None = None,
    ):
        """Initialize the kettle controller.

        Args:
            ble_device: BLE device object
            registration_key: 16-byte registration key for authentication
            protocol_version: Protocol version to use
            status_callback: Optional callback for status updates

        Raises:
            ValueError: If registration key is not exactly 16 bytes
        """
        if len(registration_key) != 16:
            raise ValueError("Registration key must be exactly 16 bytes")

        self._protocol_version = protocol_version
        self._registration_key = registration_key
        self._status_callback = status_callback
        self._tx_seq = 0
        self._current_status: ExtendedStatus | None = None

        # Create BLE client
        self._client = CosoriKettleBLEClient(
            ble_device,
            notification_callback=self._on_notification,
        )

    async def __aenter__(self) -> CosoriKettle:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()

    @property
    def is_connected(self) -> bool:
        """Return whether the kettle is connected."""
        return self._client.is_connected

    @property
    def status(self) -> ExtendedStatus | None:
        """Return the current kettle status."""
        return self._current_status

    @property
    def temperature(self) -> int | None:
        """Return the current temperature in Fahrenheit."""
        return self._current_status.temp if self._current_status else None

    @property
    def is_heating(self) -> bool:
        """Return whether the kettle is currently heating."""
        return self._current_status.stage > 0 if self._current_status else False

    @property
    def is_on_base(self) -> bool:
        """Return whether the kettle is on the charging base."""
        return self._current_status.on_base if self._current_status else False

    @property
    def setpoint(self) -> int | None:
        """Return the target temperature in Fahrenheit."""
        return self._current_status.setpoint if self._current_status else None

    async def connect(self) -> None:
        """Connect to the kettle."""
        await self._client.connect()
        await self._send_hello()
        # Initial status request
        await self.update_status()

    async def pair(self) -> None:
        """Pair with the kettle using registration key.

        This should be called during initial setup when the device
        is in pairing mode.

        Raises:
            DeviceNotInPairingModeError: Device not in pairing mode
            RuntimeError: Not connected to device
        """
        if not self.is_connected:
            raise RuntimeError("Must connect to device before pairing")

        await self._send_register()
        # After successful registration, send hello
        await self._send_hello()
        # Initial status request
        await self.update_status()

    async def disconnect(self) -> None:
        """Disconnect from the kettle."""
        await self._client.disconnect()

    def _on_notification(self, frame: Frame) -> None:
        """Handle notification from BLE client."""
        # Skip ACK frames as they're handled by the client
        if frame.frame_type == ACK_HEADER_TYPE:
            return

        # Parse status
        status = parse_extended_status(frame.payload)
        if status.valid:
            self._current_status = status
            if self._status_callback:
                self._status_callback(status)

    async def _send_hello(self) -> None:
        """Send hello packet for reconnection.

        Raises:
            InvalidRegistrationKeyError: If key is rejected (status=1)
            ProtocolError: Other protocol errors
        """
        frame = build_hello_frame(self._protocol_version, self._registration_key, self._tx_seq)
        self._tx_seq = (self._tx_seq + 1) & 0xFF

        try:
            await self._client.send_frame(frame)
        except ProtocolError as err:
            if err.status_code == 1:
                raise InvalidRegistrationKeyError(
                    "Registration key was rejected. Please reconfigure the device with the correct key.",
                    status_code=1,
                ) from err
            raise

    async def _send_register(self) -> None:
        """Send register packet for initial pairing.

        Raises:
            DeviceNotInPairingModeError: If device not in pairing mode (status=1)
            ProtocolError: Other protocol errors
        """
        frame = build_register_frame(
            self._protocol_version,
            self._registration_key,
            self._tx_seq,
        )
        self._tx_seq = (self._tx_seq + 1) & 0xFF

        try:
            await self._client.send_frame(frame)
        except ProtocolError as err:
            if err.status_code == 1:
                raise DeviceNotInPairingModeError(
                    "Device is not in pairing mode. Please put the device into pairing mode and try again.",
                    status_code=1,
                ) from err
            raise

    async def update_status(self) -> ExtendedStatus | None:
        """Request status update from the kettle.

        Returns:
            Current status or None if update failed
        """
        frame = build_status_request_frame(self._protocol_version, self._tx_seq)
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        await self._client.send_frame(frame)

        # Wait a bit for response
        await asyncio.sleep(0.5)

        return self._current_status

    async def heat_to_temperature(self, temp_f: int, hold_time_seconds: int = 0) -> None:
        """Heat water to a specific temperature.

        Args:
            temp_f: Target temperature in Fahrenheit (104-212)
            hold_time_seconds: How long to keep warm after reaching temperature
        """
        # Set my_temp first
        await self.set_my_temp(temp_f)

        # Start heating in MY_TEMP mode
        frame = build_set_mode_frame(
            self._protocol_version,
            MODE_MY_TEMP,
            temp_f,
            hold_time_seconds,
            self._tx_seq,
        )
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        await self._client.send_frame(frame)

    async def boil(self, hold_time_seconds: int = 0) -> None:
        """Boil water (212°F).

        Args:
            hold_time_seconds: How long to keep warm after boiling
        """
        frame = build_set_mode_frame(
            self._protocol_version,
            MODE_BOIL,
            212,
            hold_time_seconds,
            self._tx_seq,
        )
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        await self._client.send_frame(frame)

    async def heat_for_green_tea(self, hold_time_seconds: int = 0) -> None:
        """Heat water for green tea (180°F).

        Args:
            hold_time_seconds: How long to keep warm after heating
        """
        frame = build_set_mode_frame(
            self._protocol_version,
            MODE_GREEN_TEA,
            180,
            hold_time_seconds,
            self._tx_seq,
        )
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        await self._client.send_frame(frame)

    async def heat_for_oolong_tea(self, hold_time_seconds: int = 0) -> None:
        """Heat water for oolong tea (195°F).

        Args:
            hold_time_seconds: How long to keep warm after heating
        """
        frame = build_set_mode_frame(
            self._protocol_version,
            MODE_OOLONG,
            195,
            hold_time_seconds,
            self._tx_seq,
        )
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        await self._client.send_frame(frame)

    async def heat_for_coffee(self, hold_time_seconds: int = 0) -> None:
        """Heat water for coffee (205°F).

        Args:
            hold_time_seconds: How long to keep warm after heating
        """
        frame = build_set_mode_frame(
            self._protocol_version,
            MODE_COFFEE,
            205,
            hold_time_seconds,
            self._tx_seq,
        )
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        await self._client.send_frame(frame)

    async def stop_heating(self) -> None:
        """Stop the current heating operation."""
        frame = build_stop_frame(self._protocol_version, self._tx_seq)
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        await self._client.send_frame(frame)

    async def set_my_temp(self, temp_f: int) -> None:
        """Set the custom temperature setting.

        Args:
            temp_f: Temperature in Fahrenheit (104-212)
        """
        frame = build_set_my_temp_frame(self._protocol_version, temp_f, self._tx_seq)
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        await self._client.send_frame(frame)

    async def set_baby_formula_mode(self, enabled: bool) -> None:
        """Enable or disable baby formula mode.

        Args:
            enabled: Whether to enable baby formula mode
        """
        frame = build_set_baby_formula_frame(self._protocol_version, enabled, self._tx_seq)
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        await self._client.send_frame(frame)
