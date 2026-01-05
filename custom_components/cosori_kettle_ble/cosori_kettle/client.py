"""BLE client for Cosori Kettle communication.

This module provides the low-level BLE communication layer using bleak.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from .exceptions import ProtocolError
from .protocol import (
    ACK_HEADER_TYPE,
    Frame,
    build_packet,
    parse_frames,
    split_into_packets,
)

_LOGGER = logging.getLogger(__name__)

# BLE Service and Characteristics
SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
CHAR_RX_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"  # Notify (device -> app)
CHAR_TX_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"  # Write (app -> device)


class CosoriKettleBLEClient:
    """BLE client for Cosori Kettle."""

    def __init__(
        self,
        ble_device: BLEDevice,
        notification_callback: Callable[[Frame], None] | None = None,
        disconnected_callback: Callable[[], None] | None = None,
    ):
        """Initialize the BLE client.

        Args:
            ble_device: BLE device to connect to
            notification_callback: Callback for received frames
            disconnected_callback: Callback for disconnection events
        """
        self._ble_device = ble_device
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
            if len(ack_payload) > 4:
                status_code = ack_payload[4]
                if status_code != 0:
                    _LOGGER.warning("Device returned error status: %02x", status_code)
                    raise ProtocolError(
                        f"Device returned error status {status_code:02x}",
                        status_code=status_code,
                    )

            return ack_payload

        except asyncio.TimeoutError:
            _LOGGER.error("Timeout waiting for ACK (seq=%02x)", frame.seq)
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
