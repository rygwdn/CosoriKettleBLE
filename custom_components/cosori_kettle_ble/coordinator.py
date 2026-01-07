"""DataUpdateCoordinator for Cosori Kettle BLE."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ACK_HEADER_TYPE,
    CHAR_HARDWARE_REVISION_UUID,
    CHAR_MANUFACTURER_UUID,
    CHAR_MODEL_NUMBER_UUID,
    CHAR_SOFTWARE_REVISION_UUID,
    DOMAIN,
    PROTOCOL_VERSION_V1,
    UPDATE_INTERVAL,
)
from .cosori_kettle.client import CosoriKettleBLEClient
from .cosori_kettle.exceptions import (
    InvalidRegistrationKeyError,
    ProtocolError,
)
from .cosori_kettle.protocol import (
    ExtendedStatus,
    Frame,
    build_hello_frame,
    build_set_baby_formula_frame,
    build_set_mode_frame,
    build_set_my_temp_frame,
    build_status_request_frame,
    build_stop_frame,
    detect_protocol_version,
    parse_extended_status,
)

_LOGGER = logging.getLogger(__name__)


class CosoriKettleCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for Cosori Kettle BLE communication."""

    def __init__(
        self,
        hass: HomeAssistant,
        ble_device: BLEDevice,
        registration_key: bytes,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance
            ble_device: BLE device object
            registration_key: 16-byte registration key for authentication
        """
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{ble_device.address}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self._ble_device = ble_device
        self._protocol_version = PROTOCOL_VERSION_V1
        self._registration_key = registration_key
        self._tx_seq = 0
        self._lock = asyncio.Lock()

        # Device information
        self._hw_version: str | None = None
        self._sw_version: str | None = None
        self._model_number: str | None = None
        self._manufacturer: str | None = None

        # BLE client (will be initialized in async_start)
        self._client: CosoriKettleBLEClient | None = None
        # TODO: remove..
        self._bleak_client: BleakClient | None = None

    @property
    def hardware_version(self) -> str | None:
        """Return the hardware version."""
        return self._hw_version

    @property
    def software_version(self) -> str | None:
        """Return the software version."""
        return self._sw_version

    @property
    def model_number(self) -> str | None:
        """Return the model number."""
        return self._model_number

    @property
    def manufacturer(self) -> str | None:
        """Return the manufacturer."""
        return self._manufacturer

    @property
    def protocol_version(self) -> int:
        """Return the detected protocol version."""
        return self._protocol_version

    async def async_start(self) -> None:
        """Start the coordinator."""
        try:
            await self._connect()
            # Do initial update
            await self.async_config_entry_first_refresh()
        except Exception as err:
            _LOGGER.error("Failed to start coordinator: %s", err)
            raise

    async def async_stop(self) -> None:
        """Stop the coordinator."""
        await self._disconnect()

    async def _connect(self) -> None:
        """Connect to the device."""
        if self._client and self._client.is_connected:
            return

        _LOGGER.debug("Connecting to %s", self._ble_device.address)

        try:
            # Get updated BLE device from HA's Bluetooth manager
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self._ble_device.address, connectable=True
            )

            if ble_device is None:
                raise UpdateFailed("Device not found")

            # Use retry connector for robust connection to establish initial connection
            self._bleak_client = await establish_connection(
                BleakClient,
                ble_device,
                self._ble_device.address,
            )

            # Read device information and detect protocol version
            # TODO: move the read device info logic into the cosori client
            await self._read_device_info()

            # Disconnect bleak client after reading device info
            if self._bleak_client and self._bleak_client.is_connected:
                await self._bleak_client.disconnect()
            self._bleak_client = None

            # Create our BLE client wrapper
            self._client = CosoriKettleBLEClient(
                ble_device,
                notification_callback=self._frame_handler,
                disconnected_callback=self._on_disconnect,
            )
            await self._client.connect()

            # Send hello
            await self._send_hello()

            _LOGGER.info(
                "Connected to %s (HW: %s, SW: %s, Protocol: V%d)",
                self._ble_device.address,
                self._hw_version or "unknown",
                self._sw_version or "unknown",
                self._protocol_version,
            )

        except ConfigEntryAuthFailed:
            # Re-raise auth failures to trigger reconfiguration flow
            await self._disconnect()
            raise
        except (BleakError, asyncio.TimeoutError) as err:
            _LOGGER.error("Failed to connect: %s", err)
            await self._disconnect()
            raise UpdateFailed(f"Failed to connect: {err}") from err

    async def _read_device_info(self) -> None:
        """Read device information from BLE Device Information Service.

        Reads hardware version, software version, model number, and manufacturer
        from standard BLE characteristics, then detects the appropriate protocol version.
        """
        if not self._bleak_client:
            return

        # Read device information characteristics (ignore errors if not available)
        try:
            hw_data = await self._bleak_client.read_gatt_char(CHAR_HARDWARE_REVISION_UUID)
            self._hw_version = hw_data.decode("utf-8").strip()
            _LOGGER.debug("Hardware version: %s", self._hw_version)
        except Exception as err:
            _LOGGER.debug("Could not read hardware version: %s", err)

        try:
            sw_data = await self._bleak_client.read_gatt_char(CHAR_SOFTWARE_REVISION_UUID)
            self._sw_version = sw_data.decode("utf-8").strip()
            _LOGGER.debug("Software version: %s", self._sw_version)
        except Exception as err:
            _LOGGER.debug("Could not read software version: %s", err)

        try:
            model_data = await self._bleak_client.read_gatt_char(CHAR_MODEL_NUMBER_UUID)
            self._model_number = model_data.decode("utf-8").strip()
            _LOGGER.debug("Model number: %s", self._model_number)
        except Exception as err:
            _LOGGER.debug("Could not read model number: %s", err)

        try:
            mfr_data = await self._bleak_client.read_gatt_char(CHAR_MANUFACTURER_UUID)
            self._manufacturer = mfr_data.decode("utf-8").strip()
            _LOGGER.debug("Manufacturer: %s", self._manufacturer)
        except Exception as err:
            _LOGGER.debug("Could not read manufacturer: %s", err)

        # Detect protocol version based on HW/SW versions
        detected_version = detect_protocol_version(self._hw_version, self._sw_version)
        self._protocol_version = detected_version
        _LOGGER.info(
            "Detected protocol version V%d (HW: %s, SW: %s)",
            detected_version,
            self._hw_version or "unknown",
            self._sw_version or "unknown",
        )

    def _on_disconnect(self) -> None:
        """Handle disconnection."""
        _LOGGER.warning("Disconnected from %s", self._ble_device.address)

    async def _disconnect(self) -> None:
        """Disconnect from the device."""
        if self._client:
            try:
                await self._client.disconnect()
            except BleakError as err:
                _LOGGER.debug("Error during disconnect: %s", err)
            self._client = None
        if self._bleak_client and self._bleak_client.is_connected:
            try:
                await self._bleak_client.disconnect()
            except BleakError as err:
                _LOGGER.debug("Error during disconnect: %s", err)
            self._bleak_client = None

    @callback
    def _frame_handler(self, frame: Frame) -> None:
        """Handle received frames from BLE client.

        Args:
            frame: Received frame from device
        """
        _LOGGER.debug(
            "Received frame: type=%02x seq=%02x payload=%s",
            frame.frame_type,
            frame.seq,
            frame.payload.hex(),
        )

        status = parse_extended_status(frame.payload)
        # TODO: check command ID and parse both extended and compact status!
        if status.valid:
            self._update_data_from_status(status)

    def _update_data_from_status(self, status: ExtendedStatus) -> None:
        """Update coordinator data from status."""
        # TODO: handle compact status too..
        self.async_set_updated_data({
            "stage": status.stage,
            "mode": status.mode,
            "setpoint": status.setpoint,
            "temperature": status.temp,
            "my_temp": status.my_temp,
            "configured_hold_time": status.configured_hold_time,
            "remaining_hold_time": status.remaining_hold_time,
            "on_base": status.on_base,
            "baby_formula_enabled": status.baby_formula_enabled,
            "heating": status.stage > 0,
        })

    async def _send_hello(self) -> None:
        """Send hello packet.

        Raises:
            ConfigEntryAuthFailed: If registration key is invalid
        """
        try:
            # TODO: convert the build_x_frame functions into build_x_payload and have the client handle tx sequences and protocol version
            frame = build_hello_frame(self._protocol_version, self._registration_key, self._tx_seq)
            self._tx_seq = (self._tx_seq + 1) & 0xFF
            await self._send_frame(frame)
        except InvalidRegistrationKeyError as err:
            _LOGGER.error("Invalid registration key: %s", err)
            raise ConfigEntryAuthFailed(
                "Registration key is invalid. Please reconfigure the integration."
            ) from err

    async def _send_frame(self, frame: Frame, wait_for_ack: bool = True) -> bytes | None:
        """Send a frame to the device.

        Args:
            frame: Frame to send
            wait_for_ack: Whether to wait for ACK response

        Returns:
            ACK payload if waiting for ACK, None otherwise

        Raises:
            UpdateFailed: If not connected, ACK timeout, or command validation fails
        """
        if not self._client or not self._client.is_connected:
            raise UpdateFailed("Not connected to device")

        try:
            return await self._client.send_frame(frame, wait_for_ack=wait_for_ack)
        except (asyncio.TimeoutError, ValueError, ProtocolError) as err:
            raise UpdateFailed(f"Failed to send frame: {err}") from err

    async def _async_update_data(self) -> dict[str, Any]:
        """Poll the device for status."""
        async with self._lock:
            try:
                # Ensure connection
                if not self._client or not self._client.is_connected:
                    await self._connect()

                # Request status and wait for ACK
                frame = build_status_request_frame(self._protocol_version, self._tx_seq)
                self._tx_seq = (self._tx_seq + 1) & 0xFF
                await self._send_frame(frame, wait_for_ack=True)

                # Return current data (updated via notification handler)
                return self.data or {}

            except (BleakError, asyncio.TimeoutError) as err:
                _LOGGER.error("Failed to update: %s", err)
                raise UpdateFailed(f"Failed to update: {err}") from err

    async def async_set_mode(self, mode: int, temp_f: int, hold_time: int) -> None:
        """Set heating mode."""
        async with self._lock:
            frame = build_set_mode_frame(self._protocol_version, mode, temp_f, hold_time, self._tx_seq)
            self._tx_seq = (self._tx_seq + 1) & 0xFF
            await self._send_frame(frame)

    async def async_set_my_temp(self, temp_f: int) -> None:
        """Set my temp."""
        async with self._lock:
            frame = build_set_my_temp_frame(self._protocol_version, temp_f, self._tx_seq)
            self._tx_seq = (self._tx_seq + 1) & 0xFF
            await self._send_frame(frame)

    async def async_set_baby_formula(self, enabled: bool) -> None:
        """Set baby formula mode."""
        async with self._lock:
            frame = build_set_baby_formula_frame(self._protocol_version, enabled, self._tx_seq)
            self._tx_seq = (self._tx_seq + 1) & 0xFF
            await self._send_frame(frame)

    async def async_stop_heating(self) -> None:
        """Stop heating."""
        async with self._lock:
            frame = build_stop_frame(self._protocol_version, self._tx_seq)
            self._tx_seq = (self._tx_seq + 1) & 0xFF
            await self._send_frame(frame)
