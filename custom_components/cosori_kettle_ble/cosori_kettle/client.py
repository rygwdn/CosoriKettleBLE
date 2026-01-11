"""BLE client for Cosori Kettle communication.

This module provides the low-level BLE communication layer using bleak.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from .exceptions import ProtocolError
from .protocol import (
    ACK_HEADER_TYPE,
    CMD_CTRL,
    CMD_HELLO,
    CMD_POLL,
    CMD_REGISTER,
    CMD_SET_BABY_FORMULA,
    CMD_SET_HOLD_TIME,
    CMD_SET_MODE,
    CMD_SET_MY_TEMP,
    CMD_STOP,
    CMD_TYPE_40,
    CMD_TYPE_A3,
    CMD_TYPE_D1,
    COMMANDS_WITH_STATUS,
    Frame,
    MAX_TEMP_F,
    MESSAGE_HEADER_TYPE,
    MIN_TEMP_F,
    build_packet,
    parse_frames,
    split_into_packets,
)

_LOGGER = logging.getLogger(__name__)

# Device Information Service UUIDs
CHAR_HARDWARE_REVISION_UUID = "00002a27-0000-1000-8000-00805f9b34fb"
CHAR_SOFTWARE_REVISION_UUID = "00002a28-0000-1000-8000-00805f9b34fb"
CHAR_MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
CHAR_MANUFACTURER_UUID = "00002a29-0000-1000-8000-00805f9b34fb"


@dataclass
class DeviceInfo:
    """Device information from BLE Device Information Service."""

    hardware_version: str | None
    software_version: str | None
    model_number: str | None
    manufacturer: str | None
    protocol_version: int

# BLE Service and Characteristics
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_RX_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"  # Notify (device -> app)
CHAR_TX_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"  # Write (app -> device)


class CosoriKettleBLEClient:
    """BLE client for Cosori Kettle."""

    def __init__(
        self,
        ble_device: BLEDevice,
        registration_key: bytes | None = None,
        protocol_version: int = 1,
        notification_callback: Callable[[Frame], None] | None = None,
        disconnected_callback: Callable[[], None] | None = None,
    ):
        """Initialize the BLE client.

        Args:
            ble_device: BLE device to connect to
            registration_key: 16-byte registration key for authentication
            protocol_version: Protocol version to use (default: 1)
            notification_callback: Callback for received frames
            disconnected_callback: Callback for disconnection events
        """
        self._ble_device = ble_device
        self._registration_key = registration_key
        self._protocol_version = protocol_version
        self._tx_seq = 0
        self._notification_callback = notification_callback
        self._disconnected_callback = disconnected_callback
        self._client: BleakClient | None = None
        self._rx_buffer = bytearray()
        self._connected = False
        self._lock = asyncio.Lock()

        # ACK handling
        self._pending_ack: dict[int, asyncio.Future[bytes]] = {}
        self._ack_timeout = 5.0  # seconds

    @property
    def is_connected(self) -> bool:
        """Return whether the client is connected."""
        return self._connected and self._client is not None and self._client.is_connected

    @property
    def address(self) -> str:
        """Return the device address."""
        return self._ble_device.address

    @property
    def protocol_version(self) -> int:
        """Return the protocol version."""
        return self._protocol_version

    def set_protocol_version(self, version: int) -> None:
        """Set the protocol version (e.g., after auto-detection)."""
        self._protocol_version = version

    async def connect(self) -> None:
        """Connect to the device."""
        if self._connected:
            return

        _LOGGER.debug("Connecting to %s", self._ble_device.address)

        try:
            self._client = BleakClient(
                self._ble_device,
                disconnected_callback=self._on_disconnect,
            )
            await self._client.connect()

            # Subscribe to notifications
            await self._client.start_notify(CHAR_RX_UUID, self._notification_handler)

            self._connected = True
            _LOGGER.info("Connected to %s", self._ble_device.address)

        except (BleakError, asyncio.TimeoutError) as err:
            _LOGGER.error("Failed to connect: %s", err)
            await self.disconnect()
            raise

    def _on_disconnect(self, client: BleakClient) -> None:
        """Handle disconnection."""
        _LOGGER.warning("Disconnected from %s", self._ble_device.address)
        self._connected = False
        if self._disconnected_callback:
            self._disconnected_callback()

    async def disconnect(self) -> None:
        """Disconnect from the device."""
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(CHAR_RX_UUID)
                await self._client.disconnect()
            except BleakError as err:
                _LOGGER.debug("Error during disconnect: %s", err)
        self._client = None
        self._connected = False

    async def read_device_info(self) -> DeviceInfo:
        """Read device information from BLE Device Information Service.

        Can be called before or after connecting. If not connected, creates
        a temporary BleakClient to read the info.

        Returns:
            DeviceInfo with hardware version, software version, model number,
            manufacturer, and detected protocol version.
        """
        if self.is_connected:
            # Use existing connection
            client = self._client
            should_disconnect = False
        else:
            # Create temporary BleakClient
            from bleak_retry_connector import establish_connection

            _LOGGER.debug("Creating temporary connection to read device info")
            client = await establish_connection(
                BleakClient,
                self._ble_device,
                self._ble_device.address,
            )
            should_disconnect = True

        try:
            # Read device info characteristics (ignore errors if not available)
            hw_version = None
            sw_version = None
            model_number = None
            manufacturer = None

            try:
                hw_data = await client.read_gatt_char(CHAR_HARDWARE_REVISION_UUID)
                hw_version = hw_data.decode("utf-8").strip()
                _LOGGER.debug("Hardware version: %s", hw_version)
            except Exception as err:
                _LOGGER.debug("Could not read hardware version: %s", err)

            try:
                sw_data = await client.read_gatt_char(CHAR_SOFTWARE_REVISION_UUID)
                sw_version = sw_data.decode("utf-8").strip()
                _LOGGER.debug("Software version: %s", sw_version)
            except Exception as err:
                _LOGGER.debug("Could not read software version: %s", err)

            try:
                model_data = await client.read_gatt_char(CHAR_MODEL_NUMBER_UUID)
                model_number = model_data.decode("utf-8").strip()
                _LOGGER.debug("Model number: %s", model_number)
            except Exception as err:
                _LOGGER.debug("Could not read model number: %s", err)

            try:
                mfr_data = await client.read_gatt_char(CHAR_MANUFACTURER_UUID)
                manufacturer = mfr_data.decode("utf-8").strip()
                _LOGGER.debug("Manufacturer: %s", manufacturer)
            except Exception as err:
                _LOGGER.debug("Could not read manufacturer: %s", err)

            # Detect protocol version based on HW/SW versions
            from .protocol import detect_protocol_version

            protocol_version = detect_protocol_version(hw_version, sw_version)
            _LOGGER.info(
                "Detected protocol version V%d (HW: %s, SW: %s)",
                protocol_version,
                hw_version or "unknown",
                sw_version or "unknown",
            )

            return DeviceInfo(
                hardware_version=hw_version,
                software_version=sw_version,
                model_number=model_number,
                manufacturer=manufacturer,
                protocol_version=protocol_version,
            )
        finally:
            if should_disconnect and client.is_connected:
                await client.disconnect()
                _LOGGER.debug("Disconnected temporary connection")

    def _notification_handler(self, sender: int, data: bytearray) -> None:
        """Handle BLE notifications."""
        _LOGGER.debug("Received notification: %s", data.hex())
        self._rx_buffer.extend(data)

        # Parse all available frames
        frames, bytes_consumed = parse_frames(self._rx_buffer)

        for frame in frames:
            _LOGGER.debug(
                "Processed frame: type=%02x seq=%02x payload=%s",
                frame.frame_type,
                frame.seq,
                frame.payload.hex(),
            )

            # Handle ACK frames
            if frame.frame_type == ACK_HEADER_TYPE:
                self._handle_ack(frame.seq, frame.payload)

            # Call user callback
            if self._notification_callback:
                self._notification_callback(frame)

        # Remove consumed bytes from buffer
        if bytes_consumed > 0:
            self._rx_buffer = self._rx_buffer[bytes_consumed:]

    def _handle_ack(self, seq: int, payload: bytes) -> None:
        """Handle ACK frame."""
        _LOGGER.debug("ACK received: seq=%02x payload=%s", seq, payload.hex())

        # Complete pending future if exists
        if seq in self._pending_ack:
            future = self._pending_ack.pop(seq)
            if not future.done():
                future.set_result(payload)
                _LOGGER.debug("ACK future completed for seq=%02x", seq)

    async def _wait_for_ack(
        self, frame: Frame, ack_future: asyncio.Future[bytes]
    ) -> bytes:
        """Wait for and validate ACK response.

        Args:
            frame: Original frame that was sent
            ack_future: Future to wait on for ACK payload

        Returns:
            ACK payload

        Raises:
            asyncio.TimeoutError: If ACK timeout
            ValueError: If ACK validation fails
        """
        try:
            ack_payload = await asyncio.wait_for(ack_future, timeout=self._ack_timeout)

            # Verify first 4 bytes match (command ID)
            if len(frame.payload) >= 4 and len(ack_payload) >= 4:
                sent_cmd = frame.payload[:4]
                ack_cmd = ack_payload[:4]
                if sent_cmd != ack_cmd:
                    raise ValueError(
                        f"ACK command mismatch: sent {sent_cmd.hex()}, got {ack_cmd.hex()}"
                    )

            # Extract error code/status from payload[4] if available
            if len(ack_payload) > 4 and frame.payload[1] in COMMANDS_WITH_STATUS:
                status_code = ack_payload[4]
                if status_code != 0:
                    _LOGGER.warning("Device returned error status: %02x", status_code)
                    raise ProtocolError(
                        f"Device returned error status {status_code:02x}",
                        status_code=status_code,
                    )

            return ack_payload

        except asyncio.TimeoutError:
            cmd_hex = "??"
            if len(frame.payload) >= 2:
                cmd_hex = f"{frame.payload[1]:02x}"

            _LOGGER.error(
                "Timeout waiting for ACK (seq=%02x, cmd=0x%s, payload=%s)",
                frame.seq,
                cmd_hex,
                frame.payload.hex() if len(frame.payload) > 0 else "empty",
            )
            raise

    async def send_frame(self, frame: Frame, wait_for_ack: bool = True) -> bytes | None:
        """Send a frame to the device.

        Args:
            frame: Frame to send
            wait_for_ack: Whether to wait for ACK response

        Returns:
            ACK payload if waiting for ACK, None otherwise

        Raises:
            RuntimeError: If not connected
            asyncio.TimeoutError: If ACK timeout
            ValueError: If ACK validation fails
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to device")

        async with self._lock:
            # Build packet
            packet = build_packet(frame)

            # Create future for ACK if needed
            ack_future: asyncio.Future[bytes] | None = None
            if wait_for_ack:
                ack_future = asyncio.Future()
                self._pending_ack[frame.seq] = ack_future

            try:
                # Send packet in chunks
                packets = split_into_packets(packet)
                for pkt in packets:
                    _LOGGER.debug("Sending packet: %s", pkt.hex())
                    await self._client.write_gatt_char(CHAR_TX_UUID, pkt, response=True)

                # Wait for and validate ACK if needed
                if wait_for_ack and ack_future:
                    return await self._wait_for_ack(frame, ack_future)

            finally:
                # Clean up pending ACK if not completed
                if wait_for_ack and frame.seq in self._pending_ack:
                    self._pending_ack.pop(frame.seq, None)

        return None

    async def send_register(self, wait_for_ack: bool = True) -> bytes | None:
        """Send register packet for initial pairing.

        Uses the stored registration_key.

        Args:
            wait_for_ack: Whether to wait for ACK response

        Returns:
            ACK payload if waiting for ACK, None otherwise

        Raises:
            ValueError: If registration key is not exactly 16 bytes
            RuntimeError: If not connected
        """
        if self._registration_key is None or len(self._registration_key) != 16:
            raise ValueError("Registration key must be exactly 16 bytes")

        # Build payload with hex ASCII encoded registration key
        payload = bytearray(36)
        payload[0] = self._protocol_version
        payload[1] = CMD_REGISTER
        payload[2] = CMD_TYPE_D1
        payload[3] = 0x00
        hex_key = self._registration_key.hex()
        payload[4:] = hex_key.encode("ascii")

        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=self._tx_seq, payload=bytes(payload))
        result = await self.send_frame(frame, wait_for_ack)
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        return result

    async def send_hello(self, wait_for_ack: bool = True) -> bytes | None:
        """Send hello packet for reconnection.

        Uses the stored registration_key.

        Args:
            wait_for_ack: Whether to wait for ACK response

        Returns:
            ACK payload if waiting for ACK, None otherwise

        Raises:
            ValueError: If registration key is not exactly 16 bytes
            RuntimeError: If not connected
        """
        if self._registration_key is None or len(self._registration_key) != 16:
            raise ValueError("Registration key must be exactly 16 bytes")

        # Build payload with hex ASCII encoded registration key
        payload = bytearray(36)
        payload[0] = self._protocol_version
        payload[1] = CMD_HELLO
        payload[2] = CMD_TYPE_D1
        payload[3] = 0x00
        hex_key = self._registration_key.hex()
        payload[4:] = hex_key.encode("ascii")

        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=self._tx_seq, payload=bytes(payload))
        result = await self.send_frame(frame, wait_for_ack)
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        return result

    async def send_status_request(self, wait_for_ack: bool = True) -> bytes | None:
        """Send status request (POLL) packet.

        Args:
            wait_for_ack: Whether to wait for ACK response

        Returns:
            ACK payload if waiting for ACK, None otherwise

        Raises:
            RuntimeError: If not connected
        """
        payload = bytes([self._protocol_version, CMD_POLL, CMD_TYPE_40, 0x00])
        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=self._tx_seq, payload=payload)
        result = await self.send_frame(frame, wait_for_ack)
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        return result

    async def send_compact_status_request(self, wait_for_ack: bool = True) -> bytes | None:
        """Send compact status request (CTRL) packet.

        Args:
            wait_for_ack: Whether to wait for ACK response

        Returns:
            ACK payload if waiting for ACK, None otherwise

        Raises:
            RuntimeError: If not connected
        """
        payload = bytes([self._protocol_version, CMD_CTRL, CMD_TYPE_40, 0x00])
        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=self._tx_seq, payload=payload)
        result = await self.send_frame(frame, wait_for_ack)
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        return result

    async def send_set_my_temp(self, temp_f: int, wait_for_ack: bool = True) -> bytes | None:
        """Send set my temp packet.

        Args:
            temp_f: Target temperature in Fahrenheit (will be clamped to 104-212°F)
            wait_for_ack: Whether to wait for ACK response

        Returns:
            ACK payload if waiting for ACK, None otherwise

        Raises:
            RuntimeError: If not connected
        """
        # Clamp to valid range
        temp_f = max(MIN_TEMP_F, min(MAX_TEMP_F, temp_f))
        payload = bytes([self._protocol_version, CMD_SET_MY_TEMP, CMD_TYPE_A3, 0x00, temp_f])
        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=self._tx_seq, payload=payload)
        result = await self.send_frame(frame, wait_for_ack)
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        return result

    async def send_set_baby_formula(self, enabled: bool, wait_for_ack: bool = True) -> bytes | None:
        """Send set baby formula packet.

        Args:
            enabled: Whether to enable baby formula mode
            wait_for_ack: Whether to wait for ACK response

        Returns:
            ACK payload if waiting for ACK, None otherwise

        Raises:
            RuntimeError: If not connected
        """
        payload = bytes([self._protocol_version, CMD_SET_BABY_FORMULA, CMD_TYPE_A3, 0x00, 0x01 if enabled else 0x00])
        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=self._tx_seq, payload=payload)
        result = await self.send_frame(frame, wait_for_ack)
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        return result

    async def send_set_hold_time(self, seconds: int, wait_for_ack: bool = True) -> bytes | None:
        """Send set hold time packet.

        Args:
            seconds: Hold time in seconds
            wait_for_ack: Whether to wait for ACK response

        Returns:
            ACK payload if waiting for ACK, None otherwise

        Raises:
            RuntimeError: If not connected
        """
        payload = bytes([
            self._protocol_version,
            CMD_SET_HOLD_TIME,
            CMD_TYPE_A3,
            0x00,
            0x00,
            0x01 if seconds > 0 else 0x00,
            seconds & 0xFF,
            (seconds >> 8) & 0xFF,
        ])
        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=self._tx_seq, payload=payload)
        result = await self.send_frame(frame, wait_for_ack)
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        return result

    async def send_set_mode(
        self, mode: int, temp_f: int, hold_time_seconds: int, wait_for_ack: bool = True
    ) -> bytes | None:
        """Send set mode packet.

        Args:
            mode: Heating mode (MODE_BOIL, MODE_HEAT, MODE_GREEN_TEA, etc.)
            temp_f: Target temperature in Fahrenheit
            hold_time_seconds: Duration to hold temperature (seconds)
            wait_for_ack: Whether to wait for ACK response

        Returns:
            ACK payload if waiting for ACK, None otherwise

        Raises:
            RuntimeError: If not connected
        """
        payload = bytes([
            self._protocol_version,
            CMD_SET_MODE,
            CMD_TYPE_A3,
            0x00,
            mode,
            temp_f,
            0x01 if hold_time_seconds > 0 else 0x00,
            (hold_time_seconds >> 8) & 0xFF,
            hold_time_seconds & 0xFF,
        ])
        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=self._tx_seq, payload=payload)
        result = await self.send_frame(frame, wait_for_ack)
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        return result

    async def send_stop(self, wait_for_ack: bool = True) -> bytes | None:
        """Send stop heating packet.

        Args:
            wait_for_ack: Whether to wait for ACK response

        Returns:
            ACK payload if waiting for ACK, None otherwise

        Raises:
            RuntimeError: If not connected
        """
        payload = bytes([self._protocol_version, CMD_STOP, CMD_TYPE_A3, 0x00])
        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=self._tx_seq, payload=payload)
        result = await self.send_frame(frame, wait_for_ack)
        self._tx_seq = (self._tx_seq + 1) & 0xFF
        return result
