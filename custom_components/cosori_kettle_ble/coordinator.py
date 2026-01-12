"""DataUpdateCoordinator for Cosori Kettle BLE."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import (
    CONNECTION_BLUETOOTH,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ACK_HEADER_TYPE,
    ACK_TIMEOUT_RETRY_DELAY,
    DOMAIN,
    MAX_RECONNECT_ATTEMPTS,
    PROTOCOL_VERSION_V1,
    UPDATE_INTERVAL,
)
from .cosori_kettle.client import CosoriKettleBLEClient
from .cosori_kettle.exceptions import (
    InvalidRegistrationKeyError,
    ProtocolError,
)
from .cosori_kettle.protocol import (
    CMD_CTRL,
    CMD_POLL,
    CompactStatus,
    ExtendedStatus,
    Frame,
    parse_compact_status,
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
        self._lock = asyncio.Lock()

        # Device information
        self._hw_version: str | None = None
        self._sw_version: str | None = None
        self._model_number: str | None = None
        self._manufacturer: str | None = None

        # BLE client (will be initialized in async_start)
        self._client: CosoriKettleBLEClient | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Entity device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, format_mac(self._ble_device.address))},
            name="Cosori Kettle",
            manufacturer=self.manufacturer or "Cosori",
            model=self.model_number or "Smart Kettle",
            hw_version=self.hardware_version,
            sw_version=self.software_version,
            suggested_area="Kitchen",
            connections={(CONNECTION_BLUETOOTH, self._ble_device.address)},
        )

    @property
    def formatted_address(self) -> str | None:
        """Return the mac address of the kettle."""
        return format_mac(self._ble_device.address)

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

            # Create our BLE client wrapper
            self._client = CosoriKettleBLEClient(
                ble_device,
                registration_key=self._registration_key,
                protocol_version=self._protocol_version,
                notification_callback=self._frame_handler,
                disconnected_callback=self._on_disconnect,
            )

            # Read device info BEFORE connecting (uses temporary client internally)
            device_info = await self._client.read_device_info()
            self._hw_version = device_info.hardware_version
            self._sw_version = device_info.software_version
            self._model_number = device_info.model_number
            self._manufacturer = device_info.manufacturer
            self._protocol_version = device_info.protocol_version

            # Update protocol version on client if detected
            self._client.set_protocol_version(device_info.protocol_version)

            # Now connect for actual communication
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

    def _on_disconnect(self) -> None:
        """Handle disconnection.

        This callback is called when the BLE connection is lost.
        Updates will attempt to reconnect automatically.
        """
        _LOGGER.warning("Disconnected from %s", self._ble_device.address)
        # The next update cycle will attempt to reconnect

    async def _disconnect(self) -> None:
        """Disconnect from the device."""
        if self._client:
            try:
                await self._client.disconnect()
            except BleakError as err:
                _LOGGER.debug("Error during disconnect: %s", err)
            self._client = None

    @callback
    def _frame_handler(self, frame: Frame) -> None:
        """Handle received frames from BLE client.

        Extended status: ACK response to poll requests (CMD_POLL)
        Compact status: Unsolicited periodic updates from kettle (CMD_CTRL)

        Args:
            frame: Received frame from device
        """
        _LOGGER.debug(
            "Received frame: type=%02x seq=%02x payload=%s",
            frame.frame_type,
            frame.seq,
            frame.payload.hex(),
        )

        if len(frame.payload) < 2:
            return

        cmd_id = frame.payload[1]

        if cmd_id == CMD_POLL:
            # Extended status - ACK to our poll request
            status = parse_extended_status(frame.payload)
            if status.valid:
                self._update_data_from_status(status)
        elif cmd_id == CMD_CTRL:
            # Compact status - unsolicited periodic update from kettle
            status = parse_compact_status(frame.payload)
            if status.valid:
                self._update_data_from_compact_status(status)

    def _update_data_from_status(self, status: ExtendedStatus) -> None:
        """Update coordinator data from extended status."""
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

    def _update_data_from_compact_status(self, status: CompactStatus) -> None:
        """Update coordinator data from compact status.

        Compact status is sent periodically by the kettle as unsolicited updates.
        It only contains: stage, mode, setpoint, temp
        Preserve extended-only fields from previous data.
        """
        # Start with existing data to preserve extended fields
        data = self.data.copy() if self.data else {}

        # Update common fields from compact status
        data.update({
            "stage": status.stage,
            "mode": status.mode,
            "setpoint": status.setpoint,
            "temperature": status.temp,
            "heating": status.stage > 0,
        })

        # Initialize extended fields with defaults if not present
        data.setdefault("my_temp", 0)
        data.setdefault("configured_hold_time", 0)
        data.setdefault("remaining_hold_time", 0)
        data.setdefault("on_base", False)
        data.setdefault("baby_formula_enabled", False)

        self.async_set_updated_data(data)

    async def _send_hello(self) -> None:
        """Send hello packet.

        Raises:
            ConfigEntryAuthFailed: If registration key is invalid
        """
        try:
            await self._client.send_hello()
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
                await self._client.send_status_request(wait_for_ack=True)

                # Return current data (updated via notification handler)
                return self.data or {}

            except asyncio.TimeoutError as err:
                # ACK timeout - retry once after delay
                _LOGGER.warning(
                    "ACK timeout during status request, retrying in %ds: %s",
                    ACK_TIMEOUT_RETRY_DELAY,
                    err
                )

                # Wait before retry
                await asyncio.sleep(ACK_TIMEOUT_RETRY_DELAY)

                try:
                    # Retry the status request
                    await self._client.send_status_request(wait_for_ack=True)
                    _LOGGER.info("Retry successful after ACK timeout")
                    return self.data or {}
                except asyncio.TimeoutError:
                    # Second timeout - log but still keep device available
                    _LOGGER.warning("ACK timeout on retry, will try again on next update")
                    return self.data or {}
                except BleakError as retry_err:
                    # Connection lost during retry
                    _LOGGER.error("Bluetooth error during retry: %s", retry_err)
                    raise UpdateFailed(f"Bluetooth error: {retry_err}") from retry_err

            except BleakError as err:
                # Bluetooth error - attempt reconnection
                _LOGGER.error("Bluetooth error during update: %s", err)

                # Try to reconnect
                for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
                    _LOGGER.info("Reconnection attempt %d/%d", attempt, MAX_RECONNECT_ATTEMPTS)
                    try:
                        await self._disconnect()
                        await asyncio.sleep(1)  # Brief delay before reconnect
                        await self._connect()
                        _LOGGER.info("Successfully reconnected on attempt %d", attempt)
                        # Try to get status after reconnecting
                        await self._client.send_status_request(wait_for_ack=True)
                        return self.data or {}
                    except (BleakError, asyncio.TimeoutError) as reconnect_err:
                        _LOGGER.warning(
                            "Reconnection attempt %d failed: %s",
                            attempt,
                            reconnect_err
                        )
                        if attempt == MAX_RECONNECT_ATTEMPTS:
                            # All attempts failed
                            raise UpdateFailed(
                                f"Failed to reconnect after {MAX_RECONNECT_ATTEMPTS} attempts"
                            ) from err

    async def async_set_mode(self, mode: int, temp_f: int, hold_time: int) -> None:
        """Set heating mode."""
        async with self._lock:
            await self._client.send_set_mode(mode, temp_f, hold_time)

    async def async_set_my_temp(self, temp_f: int) -> None:
        """Set my temp."""
        async with self._lock:
            await self._client.send_set_my_temp(temp_f)

    async def async_set_baby_formula(self, enabled: bool) -> None:
        """Set baby formula mode."""
        async with self._lock:
            await self._client.send_set_baby_formula(enabled)

    async def async_stop_heating(self) -> None:
        """Stop heating."""
        async with self._lock:
            await self._client.send_stop()
