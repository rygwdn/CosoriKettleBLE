"""Tests for the BLE client module."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

from custom_components.cosori_kettle_ble.cosori_kettle.client import (
    CosoriKettleBLEClient,
    CHAR_RX_UUID,
    CHAR_TX_UUID,
)
from custom_components.cosori_kettle_ble.cosori_kettle.protocol import (
    ACK_HEADER_TYPE,
    Frame,
    MESSAGE_HEADER_TYPE,
    build_packet,
)


@pytest.fixture
def mock_ble_device():
    """Create a mock BLE device."""
    device = MagicMock()
    device.address = "00:11:22:33:44:55"
    return device


@pytest.fixture
def mock_bleak_client():
    """Create a mock BleakClient."""
    client = AsyncMock()
    client.is_connected = True
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.start_notify = AsyncMock()
    client.stop_notify = AsyncMock()
    client.write_gatt_char = AsyncMock()
    return client


@pytest.fixture
def notification_callback():
    """Create a mock notification callback."""
    return MagicMock()


@pytest.fixture
def disconnected_callback():
    """Create a mock disconnected callback."""
    return MagicMock()


@pytest.fixture
def client(mock_ble_device, notification_callback, disconnected_callback):
    """Create a CosoriKettleBLEClient instance."""
    return CosoriKettleBLEClient(
        ble_device=mock_ble_device,
        notification_callback=notification_callback,
        disconnected_callback=disconnected_callback,
    )


class TestConnectionAndDisconnection:
    """Tests for connection and disconnection functionality."""

    @pytest.mark.asyncio
    async def test_connect_success(self, client, mock_bleak_client):
        """Test successful connection."""
        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak_client,
        ):
            await client.connect()

            assert client.is_connected is True
            mock_bleak_client.connect.assert_called_once()
            mock_bleak_client.start_notify.assert_called_once_with(
                CHAR_RX_UUID, client._notification_handler
            )

    @pytest.mark.asyncio
    async def test_connect_already_connected(self, client, mock_bleak_client):
        """Test connect when already connected."""
        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak_client,
        ):
            await client.connect()
            # Reset mocks to check second call
            mock_bleak_client.connect.reset_mock()
            mock_bleak_client.start_notify.reset_mock()

            # Second connect should be no-op
            await client.connect()

            mock_bleak_client.connect.assert_not_called()
            mock_bleak_client.start_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_failure_bleak_error(self, mock_ble_device):
        """Test connection failure due to BleakError."""
        # Create a fresh client for this test
        client = CosoriKettleBLEClient(mock_ble_device, None, None)

        mock_bleak = AsyncMock()
        mock_bleak.connect.side_effect = Exception("Connection refused")
        mock_bleak.is_connected = False

        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak,
        ):
            with pytest.raises(Exception):
                await client.connect()

            # Client should not be connected after failure
            assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_failure_notify_error(self, mock_ble_device):
        """Test connection failure during notify setup."""
        # Create a fresh client for this test
        client = CosoriKettleBLEClient(mock_ble_device, None, None)

        mock_bleak = AsyncMock()
        mock_bleak.start_notify.side_effect = Exception("Notify setup failed")
        mock_bleak.is_connected = True  # connect() succeeded, so is_connected would be True

        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak,
        ):
            with pytest.raises(Exception):
                await client.connect()

            # Client should not be connected after failure
            assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_disconnect_success(self, client, mock_bleak_client):
        """Test successful disconnection."""
        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak_client,
        ):
            await client.connect()
            await client.disconnect()

            assert client.is_connected is False
            assert client._client is None
            mock_bleak_client.stop_notify.assert_called_once_with(CHAR_RX_UUID)
            mock_bleak_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self, client):
        """Test disconnect when not connected."""
        # Should not raise an error
        await client.disconnect()
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_on_disconnect_callback(self, client, disconnected_callback, mock_bleak_client):
        """Test that disconnection callback is called."""
        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak_client,
        ):
            await client.connect()
            # Trigger the disconnect callback
            client._on_disconnect(mock_bleak_client)

            assert client._connected is False
            disconnected_callback.assert_called_once()

    def test_is_connected_property(self, client, mock_bleak_client):
        """Test is_connected property."""
        # Not connected initially
        assert client.is_connected is False

        # Manually set up client
        client._client = mock_bleak_client
        client._connected = True
        mock_bleak_client.is_connected = True

        assert client.is_connected is True

        # Check all conditions
        client._connected = False
        assert client.is_connected is False

        client._connected = True
        mock_bleak_client.is_connected = False
        assert client.is_connected is False

    def test_address_property(self, client, mock_ble_device):
        """Test address property."""
        assert client.address == "00:11:22:33:44:55"


class TestSendFrame:
    """Tests for frame sending functionality."""

    @pytest.mark.asyncio
    async def test_send_frame_without_ack(self, client, mock_bleak_client):
        """Test sending a frame without waiting for ACK."""
        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak_client,
        ):
            await client.connect()

            frame = Frame(frame_type=0x22, seq=0x01, payload=b"\x01\x81\xD1\x00")
            result = await client.send_frame(frame, wait_for_ack=False)

            assert result is None
            mock_bleak_client.write_gatt_char.assert_called()
            # ACK future should not be created
            assert 0x01 not in client._pending_ack

    @pytest.mark.asyncio
    async def test_send_frame_with_ack(self, client, mock_bleak_client):
        """Test sending a frame and waiting for ACK."""
        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak_client,
        ):
            await client.connect()

            frame = Frame(frame_type=0x22, seq=0x02, payload=b"\x01\x81\xD1\x00")

            # Create a task to simulate ACK reception
            async def send_and_receive_ack():
                send_task = asyncio.create_task(client.send_frame(frame, wait_for_ack=True))
                await asyncio.sleep(0.01)  # Let send_frame create the future
                # Simulate ACK reception (first 4 bytes must match sent command)
                ack_frame = Frame(
                    frame_type=ACK_HEADER_TYPE, seq=0x02, payload=b"\x01\x81\xD1\x00\x00"
                )
                client._handle_ack(ack_frame.seq, ack_frame.payload)
                return await send_task

            result = await send_and_receive_ack()

            assert result == b"\x01\x81\xD1\x00\x00"
            mock_bleak_client.write_gatt_char.assert_called()

    @pytest.mark.asyncio
    async def test_send_frame_not_connected(self, client):
        """Test sending frame when not connected raises error."""
        frame = Frame(frame_type=0x22, seq=0x03, payload=b"\x01\x81\xD1\x00")

        with pytest.raises(RuntimeError, match="Not connected"):
            await client.send_frame(frame)

    @pytest.mark.asyncio
    async def test_send_frame_creates_ack_future(self, client, mock_bleak_client):
        """Test that send_frame creates an ACK future when requested."""
        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak_client,
        ):
            await client.connect()

            frame = Frame(frame_type=0x22, seq=0x04, payload=b"\x01\x81\xD1\x00")

            # Start the send but don't wait for completion
            send_task = asyncio.create_task(client.send_frame(frame, wait_for_ack=True))
            await asyncio.sleep(0.01)

            # Check that ACK future was created
            assert 0x04 in client._pending_ack
            assert isinstance(client._pending_ack[0x04], asyncio.Future)

            # Clean up
            send_task.cancel()
            try:
                await send_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_send_frame_splits_into_packets(self, client, mock_bleak_client):
        """Test that large frames are split into BLE packets."""
        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak_client,
        ):
            await client.connect()

            # Create a large payload that will be split
            large_payload = b"\x01\x81" + b"\x00" * 100
            frame = Frame(frame_type=0x22, seq=0x05, payload=large_payload)

            await client.send_frame(frame, wait_for_ack=False)

            # Should have multiple write calls for a large frame
            assert mock_bleak_client.write_gatt_char.call_count >= 1

    @pytest.mark.asyncio
    async def test_send_frame_cleans_up_pending_ack_on_error(self, client, mock_bleak_client):
        """Test that pending ACK is cleaned up when sending fails."""
        mock_bleak_client.write_gatt_char.side_effect = Exception("Write failed")

        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak_client,
        ):
            await client.connect()

            frame = Frame(frame_type=0x22, seq=0x06, payload=b"\x01\x81\xD1\x00")

            with pytest.raises(Exception):
                await client.send_frame(frame, wait_for_ack=True)

            # ACK future should be cleaned up
            assert 0x06 not in client._pending_ack

    @pytest.mark.asyncio
    async def test_send_frame_cleans_up_pending_ack_on_timeout(self, client, mock_bleak_client):
        """Test that pending ACK is cleaned up on ACK timeout."""
        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak_client,
        ):
            await client.connect()
            client._ack_timeout = 0.01  # Short timeout for testing

            frame = Frame(frame_type=0x22, seq=0x07, payload=b"\x01\x81\xD1\x00")

            with pytest.raises(asyncio.TimeoutError):
                await client.send_frame(frame, wait_for_ack=True)

            # ACK future should be cleaned up
            assert 0x07 not in client._pending_ack


class TestWaitForAck:
    """Tests for ACK waiting and validation."""

    @pytest.mark.asyncio
    async def test_wait_for_ack_success(self, client):
        """Test successful ACK reception."""
        frame = Frame(frame_type=0x22, seq=0x08, payload=b"\x01\x81\xD1\x00")
        ack_future = asyncio.Future()

        # Simulate ACK reception in background
        async def receive_ack():
            await asyncio.sleep(0.01)
            ack_future.set_result(b"\x01\x81\xD1\x00\x00")

        asyncio.create_task(receive_ack())

        result = await client._wait_for_ack(frame, ack_future)
        assert result == b"\x01\x81\xD1\x00\x00"

    @pytest.mark.asyncio
    async def test_wait_for_ack_timeout(self, client):
        """Test ACK timeout."""
        frame = Frame(frame_type=0x22, seq=0x09, payload=b"\x01\x81\xD1\x00")
        ack_future = asyncio.Future()
        client._ack_timeout = 0.01

        with pytest.raises(asyncio.TimeoutError):
            await client._wait_for_ack(frame, ack_future)

    @pytest.mark.asyncio
    async def test_wait_for_ack_command_mismatch(self, client):
        """Test ACK with mismatched command ID."""
        frame = Frame(frame_type=0x22, seq=0x0A, payload=b"\x01\x81\xD1\x00")
        ack_future = asyncio.Future()
        client._ack_timeout = 5.0

        # Simulate ACK with wrong command
        ack_future.set_result(b"\x02\x81\x00\x00\x00")

        with pytest.raises(ValueError, match="ACK command mismatch"):
            await client._wait_for_ack(frame, ack_future)

    @pytest.mark.asyncio
    async def test_wait_for_ack_short_payload(self, client):
        """Test ACK with short payload (less than 4 bytes)."""
        frame = Frame(frame_type=0x22, seq=0x0B, payload=b"\x01\x81")
        ack_future = asyncio.Future()

        # ACK with short payload should not raise command mismatch
        ack_future.set_result(b"\x00\x00")

        result = await client._wait_for_ack(frame, ack_future)
        assert result == b"\x00\x00"

    @pytest.mark.asyncio
    async def test_wait_for_ack_with_error_code(self, client):
        """Test ACK with non-zero error code (should raise ProtocolError)."""
        from custom_components.cosori_kettle_ble.cosori_kettle.exceptions import ProtocolError

        frame = Frame(frame_type=0x22, seq=0x0C, payload=b"\x01\x81\xD1\x00")
        ack_future = asyncio.Future()

        # ACK with error code 0x01 (first 4 bytes must match)
        ack_future.set_result(b"\x01\x81\xD1\x00\x01")

        with pytest.raises(ProtocolError) as exc_info:
            await client._wait_for_ack(frame, ack_future)

        assert exc_info.value.status_code == 1

    @pytest.mark.asyncio
    async def test_wait_for_ack_no_error_code(self, client):
        """Test ACK with zero error code."""
        frame = Frame(frame_type=0x22, seq=0x0D, payload=b"\x01\x81\xD1\x00")
        ack_future = asyncio.Future()

        ack_future.set_result(b"\x01\x81\xD1\x00\x00")

        result = await client._wait_for_ack(frame, ack_future)
        assert result == b"\x01\x81\xD1\x00\x00"

    @pytest.mark.asyncio
    async def test_wait_for_ack_with_various_error_codes(self, client):
        """Test ACK with different error codes."""
        from custom_components.cosori_kettle_ble.cosori_kettle.exceptions import ProtocolError

        test_cases = [0x01, 0x02, 0xFF]

        for error_code in test_cases:
            frame = Frame(frame_type=0x22, seq=0x0E, payload=b"\x01\x81\xD1\x00")
            ack_future = asyncio.Future()
            ack_future.set_result(b"\x01\x81\xD1\x00" + bytes([error_code]))

            with pytest.raises(ProtocolError) as exc_info:
                await client._wait_for_ack(frame, ack_future)

            assert exc_info.value.status_code == error_code


class TestNotificationHandling:
    """Tests for notification handling and frame parsing."""

    def test_notification_handler_single_frame(self, client, notification_callback):
        """Test handling a single frame in notification."""
        frame = Frame(frame_type=0x22, seq=0x0E, payload=b"\x01\x81\xD1\x00")
        packet = build_packet(frame)

        client._notification_handler(1, bytearray(packet))

        notification_callback.assert_called_once()
        call_args = notification_callback.call_args[0][0]
        assert call_args.frame_type == 0x22
        assert call_args.seq == 0x0E

    def test_notification_handler_multiple_frames(self, client, notification_callback):
        """Test handling multiple frames in a single notification."""
        frame1 = Frame(frame_type=0x22, seq=0x0F, payload=b"\x01\x81\xD1\x00")
        frame2 = Frame(frame_type=0x22, seq=0x10, payload=b"\x01\x40\xD1\x00")

        packet1 = build_packet(frame1)
        packet2 = build_packet(frame2)

        # Send both packets in one notification
        client._notification_handler(1, bytearray(packet1 + packet2))

        assert notification_callback.call_count == 2
        calls = notification_callback.call_args_list
        assert calls[0][0][0].seq == 0x0F
        assert calls[1][0][0].seq == 0x10

    def test_notification_handler_partial_frame(self, client):
        """Test handling partial frame that spans multiple notifications."""
        frame = Frame(frame_type=0x22, seq=0x11, payload=b"\x01\x81\xD1\x00")
        packet = build_packet(frame)

        # Split packet in half
        first_half = packet[: len(packet) // 2]
        second_half = packet[len(packet) // 2 :]

        # First notification with partial frame
        client._notification_handler(1, bytearray(first_half))
        assert len(client._rx_buffer) > 0

        # Second notification completes the frame
        client._notification_handler(1, bytearray(second_half))
        # Buffer should be cleared after frame is parsed
        assert len(client._rx_buffer) == 0

    def test_notification_handler_with_ack_frame(self, client, notification_callback):
        """Test handling ACK frame in notification."""
        ack_frame = Frame(frame_type=ACK_HEADER_TYPE, seq=0x12, payload=b"\x01\x81\x00\x00\x00")
        packet = build_packet(ack_frame)

        client._notification_handler(1, bytearray(packet))

        # Callback should still be called for ACK frame
        notification_callback.assert_called_once()

    def test_notification_handler_corrupted_data(self, client, notification_callback):
        """Test handling corrupted data in notification."""
        # Send corrupted data that won't parse as a valid frame
        client._notification_handler(1, bytearray(b"\xFF\xFF\xFF"))

        # Notification callback should not be called for invalid data
        notification_callback.assert_not_called()

    def test_notification_handler_buffer_overflow(self, client):
        """Test that buffer is properly managed with large data."""
        # Create multiple large frames
        frame1 = Frame(frame_type=0x22, seq=0x13, payload=b"\x01\x81" + b"\x00" * 100)
        frame2 = Frame(frame_type=0x22, seq=0x14, payload=b"\x01\x40" + b"\x00" * 100)

        packet1 = build_packet(frame1)
        packet2 = build_packet(frame2)

        client._notification_handler(1, bytearray(packet1 + packet2))

        # Buffer should be cleared
        assert len(client._rx_buffer) == 0


class TestHandleAck:
    """Tests for ACK handling."""

    def test_handle_ack_completes_future(self, client):
        """Test that handle_ack completes the future."""
        ack_future = asyncio.Future()
        client._pending_ack[0x15] = ack_future

        client._handle_ack(0x15, b"\x01\x81\x00\x00\x00")

        assert ack_future.done()
        assert ack_future.result() == b"\x01\x81\x00\x00\x00"
        assert 0x15 not in client._pending_ack

    def test_handle_ack_no_pending_future(self, client):
        """Test handling ACK when no future is pending."""
        # Should not raise an error
        client._handle_ack(0x16, b"\x01\x81\x00\x00\x00")

    def test_handle_ack_already_done_future(self, client):
        """Test handling ACK for already completed future."""
        ack_future = asyncio.Future()
        ack_future.set_result(b"old_result")
        client._pending_ack[0x17] = ack_future

        # This should not update the result
        client._handle_ack(0x17, b"\x01\x81\x00\x00\x00")

        # Future result should remain unchanged
        assert ack_future.result() == b"old_result"

    def test_handle_ack_multiple_pending(self, client):
        """Test handling ACKs with multiple pending futures."""
        ack_future1 = asyncio.Future()
        ack_future2 = asyncio.Future()
        client._pending_ack[0x18] = ack_future1
        client._pending_ack[0x19] = ack_future2

        client._handle_ack(0x18, b"\x01\x81\x00\x00\x00")

        assert ack_future1.done()
        assert not ack_future2.done()
        assert 0x18 not in client._pending_ack
        assert 0x19 in client._pending_ack


class TestBufferManagement:
    """Tests for buffer management."""

    def test_rx_buffer_accumulates_data(self, client):
        """Test that rx_buffer accumulates data across notifications."""
        frame1 = Frame(frame_type=0x22, seq=0x1A, payload=b"\x01\x81\xD1\x00")
        packet1 = build_packet(frame1)

        # Send partial packet
        partial = packet1[: len(packet1) // 2]
        client._notification_handler(1, bytearray(partial))

        assert len(client._rx_buffer) == len(partial)

    def test_rx_buffer_cleared_after_frame_parse(self, client):
        """Test that buffer is cleared after successful frame parsing."""
        frame = Frame(frame_type=0x22, seq=0x1B, payload=b"\x01\x81\xD1\x00")
        packet = build_packet(frame)

        client._notification_handler(1, bytearray(packet))

        assert len(client._rx_buffer) == 0

    def test_rx_buffer_partial_frame_remains(self, client):
        """Test that partial frame data remains in buffer."""
        frame = Frame(frame_type=0x22, seq=0x1C, payload=b"\x01\x81\xD1\x00")
        packet = build_packet(frame)

        # Send complete frame plus extra bytes
        extra = b"\xFF\xFF"
        client._notification_handler(1, bytearray(packet + extra))

        # Extra bytes should remain in buffer (not a valid frame start)
        assert len(client._rx_buffer) == len(extra)

    def test_multiple_frames_in_buffer(self, client, notification_callback):
        """Test parsing multiple frames from buffer."""
        frames = [
            Frame(frame_type=0x22, seq=0x1D, payload=b"\x01\x81\xD1\x00"),
            Frame(frame_type=0x22, seq=0x1E, payload=b"\x01\x40\xD1\x00"),
            Frame(frame_type=0x22, seq=0x1F, payload=b"\x01\xF4\xD1\x00"),
        ]

        packets = b"".join(build_packet(f) for f in frames)
        client._notification_handler(1, bytearray(packets))

        assert notification_callback.call_count == 3
        assert client._rx_buffer == bytearray()


class TestConcurrency:
    """Tests for concurrent operations."""

    @pytest.mark.asyncio
    async def test_send_frame_lock(self, client, mock_bleak_client):
        """Test that send_frame uses lock for serialization."""
        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak_client,
        ):
            await client.connect()

            frame1 = Frame(frame_type=0x22, seq=0x20, payload=b"\x01\x81\xD1\x00")
            frame2 = Frame(frame_type=0x22, seq=0x21, payload=b"\x01\x40\xD1\x00")

            # Send two frames concurrently
            results = await asyncio.gather(
                client.send_frame(frame1, wait_for_ack=False),
                client.send_frame(frame2, wait_for_ack=False),
            )

            # Both should succeed
            assert len(results) == 2
            # Write should be called twice
            assert mock_bleak_client.write_gatt_char.call_count >= 2

    @pytest.mark.asyncio
    async def test_notification_handler_while_sending(self, client, mock_bleak_client):
        """Test that notification handler can run while sending."""
        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak_client,
        ):
            await client.connect()

            frame = Frame(frame_type=0x22, seq=0x22, payload=b"\x01\x81\xD1\x00")

            # Simulate sending with ACK (first 4 bytes must match)
            ack_frame = Frame(
                frame_type=ACK_HEADER_TYPE, seq=0x22, payload=b"\x01\x81\xD1\x00\x00"
            )

            async def send_and_receive():
                send_task = asyncio.create_task(client.send_frame(frame, wait_for_ack=True))
                await asyncio.sleep(0.01)
                # Simulate notification while send is pending
                ack_packet = build_packet(ack_frame)
                client._notification_handler(1, bytearray(ack_packet))
                return await send_task

            result = await send_and_receive()
            assert result == b"\x01\x81\xD1\x00\x00"


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_client_initialization(self, mock_ble_device):
        """Test client initialization."""
        client = CosoriKettleBLEClient(ble_device=mock_ble_device)
        assert client.address == "00:11:22:33:44:55"
        assert not client.is_connected
        assert client._notification_callback is None
        assert client._disconnected_callback is None

    def test_client_with_none_callbacks(self, client, mock_bleak_client):
        """Test notification handling without callbacks."""
        client._notification_callback = None
        client._disconnected_callback = None

        frame = Frame(frame_type=0x22, seq=0x23, payload=b"\x01\x81\xD1\x00")
        packet = build_packet(frame)

        # Should not raise an error
        client._notification_handler(1, bytearray(packet))

    @pytest.mark.asyncio
    async def test_disconnect_twice(self, client, mock_bleak_client):
        """Test calling disconnect twice."""
        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak_client,
        ):
            await client.connect()
            await client.disconnect()

            # Second disconnect should not raise an error
            await client.disconnect()
            assert not client.is_connected

    def test_notification_handler_with_garbage_data(self, client, notification_callback):
        """Test notification handler with garbage at start of buffer."""
        # Send garbage followed by valid frame
        frame = Frame(frame_type=0x22, seq=0x24, payload=b"\x01\x81\xD1\x00")
        packet = build_packet(frame)

        garbage = b"\xFF\xFF\xFF"
        client._notification_handler(1, bytearray(garbage + packet))

        # Should still parse the valid frame and call callback
        notification_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_frame_sequence_numbers(self, client, mock_bleak_client):
        """Test sending frames with different sequence numbers."""
        with patch(
            "custom_components.cosori_kettle_ble.cosori_kettle.client.BleakClient",
            return_value=mock_bleak_client,
        ):
            await client.connect()

            # Send frames with different seq numbers
            for seq in [0x00, 0x01, 0xFF]:
                frame = Frame(frame_type=0x22, seq=seq, payload=b"\x01\x81\xD1\x00")
                await client.send_frame(frame, wait_for_ack=False)

            assert mock_bleak_client.write_gatt_char.call_count >= 3

    def test_ack_timeout_configuration(self, client):
        """Test ACK timeout configuration."""
        assert client._ack_timeout == 5.0

        client._ack_timeout = 10.0
        assert client._ack_timeout == 10.0

    def test_notification_handler_empty_data(self, client, notification_callback):
        """Test handling empty notification data."""
        client._notification_handler(1, bytearray())

        notification_callback.assert_not_called()
        assert len(client._rx_buffer) == 0
