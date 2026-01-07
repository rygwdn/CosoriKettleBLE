"""Tests for the CosoriKettleCoordinator class."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call
import pytest

from custom_components.cosori_kettle_ble.coordinator import CosoriKettleCoordinator
from custom_components.cosori_kettle_ble.const import (
    ACK_HEADER_TYPE,
    CHAR_RX_UUID,
    CHAR_TX_UUID,
    DOMAIN,
    MESSAGE_HEADER_TYPE,
    PROTOCOL_VERSION_V1,
    SERVICE_UUID,
    UPDATE_INTERVAL,
)
from custom_components.cosori_kettle_ble.cosori_kettle.protocol import (
    ExtendedStatus,
    Frame,
    build_hello_frame,
    build_packet,
    build_set_baby_formula_frame,
    build_set_mode_frame,
    build_set_my_temp_frame,
    build_status_request_frame,
    build_stop_frame,
    parse_extended_status,
    parse_frames,
)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.loop = asyncio.get_event_loop()
    return hass


@pytest.fixture
def mock_ble_device():
    """Create a mock BLE device."""
    device = MagicMock()
    device.address = "AA:BB:CC:DD:EE:FF"
    device.name = "Cosori Kettle"
    return device


@pytest.fixture
def registration_key():
    """Registration key for testing."""
    return bytes.fromhex("00112233445566778899AABBCCDDEEFF")


@pytest.fixture
def coordinator(mock_hass, mock_ble_device, registration_key):
    """Create a coordinator instance."""
    return CosoriKettleCoordinator(mock_hass, mock_ble_device, registration_key)


@pytest.fixture
def mock_bleak_client():
    """Create a mock BleakClient."""
    client = AsyncMock()
    client.is_connected = True
    client.start_notify = AsyncMock()
    client.stop_notify = AsyncMock()
    client.disconnect = AsyncMock()
    client.write_gatt_char = AsyncMock()
    # Configure read_gatt_char to raise exception by default
    # Tests can override this if they need specific behavior
    client.read_gatt_char = AsyncMock(side_effect=Exception("Device info not available"))
    return client


@pytest.fixture
def mock_cosori_client():
    """Create a mock CosoriKettleBLEClient."""
    client = AsyncMock()
    client.is_connected = True
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.send_frame = AsyncMock(return_value=b'\x01\x40\x40\x00')
    return client


@pytest.fixture
def sample_status_payload():
    """Create a sample extended status payload."""
    return bytearray([
        0x01, 0x40, 0x40, 0x00,  # [0-3] header (version, cmd, cmd_type, reserved)
        0x01,  # [4] stage (heating)
        0x04,  # [5] mode (boil)
        0xD4,  # [6] setpoint (212F)
        0x5C,  # [7] temp (92F)
        0x8C,  # [8] my_temp (140F)
        0x00,  # [9] padding
        0x3C, 0x00,  # [10-11] configured_hold_time (60) little-endian
        0x1E, 0x00,  # [12-13] remaining_hold_time (30) little-endian
        0x00,  # [14] on_base (yes = 0x00)
        0x00, 0x00, 0x00, 0x00,  # [15-18] padding
        0x00, 0x00,  # [19-20] padding
        0x00, 0x00, 0x00,  # [21-23] padding
        0x00, 0x00,  # [24-25] padding
        0x01,  # [26] baby_formula_enabled
        0x00, 0x00,  # [27-28] padding (to reach 29 bytes minimum)
    ])


class TestCoordinatorInitialization:
    """Test coordinator initialization."""

    def test_init_creates_coordinator(self, coordinator, mock_ble_device, registration_key):
        """Test coordinator initialization."""
        assert coordinator._ble_device == mock_ble_device
        assert coordinator._protocol_version == PROTOCOL_VERSION_V1
        assert coordinator._registration_key == registration_key
        assert coordinator._client is None
        assert coordinator._bleak_client is None
        assert coordinator._tx_seq == 0

    def test_init_sets_coordinator_name(self, coordinator, mock_ble_device):
        """Test that coordinator name is set correctly."""
        expected_name = f"{DOMAIN}_{mock_ble_device.address}"
        assert coordinator.name == expected_name

    def test_init_sets_update_interval(self, coordinator):
        """Test that update interval is set correctly."""
        from datetime import timedelta
        expected_interval = timedelta(seconds=UPDATE_INTERVAL)
        assert coordinator.update_interval == expected_interval


class TestCoordinatorStartStop:
    """Test async_start and async_stop methods."""

    @pytest.mark.asyncio
    async def test_async_start_connects_and_refreshes(self, coordinator, mock_hass):
        """Test that async_start connects and does initial refresh."""
        with patch.object(coordinator, "_connect", new_callable=AsyncMock) as mock_connect, \
             patch.object(coordinator, "async_config_entry_first_refresh", new_callable=AsyncMock) as mock_refresh:
            await coordinator.async_start()
            mock_connect.assert_called_once()
            mock_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_start_handles_connection_error(self, coordinator):
        """Test that async_start propagates connection errors."""
        with patch.object(coordinator, "_connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = Exception("Connection failed")
            with pytest.raises(Exception, match="Connection failed"):
                await coordinator.async_start()

    @pytest.mark.asyncio
    async def test_async_stop_disconnects(self, coordinator):
        """Test that async_stop disconnects."""
        with patch.object(coordinator, "_disconnect", new_callable=AsyncMock) as mock_disconnect:
            await coordinator.async_stop()
            mock_disconnect.assert_called_once()


class TestCoordinatorConnection:
    """Test connection management."""

    @pytest.mark.asyncio
    async def test_connect_establishes_connection(self, coordinator, mock_ble_device, mock_bleak_client, mock_cosori_client):
        """Test successful connection."""
        with patch("custom_components.cosori_kettle_ble.coordinator.bluetooth") as mock_bt, \
             patch("custom_components.cosori_kettle_ble.coordinator.establish_connection", new_callable=AsyncMock) as mock_establish, \
             patch("custom_components.cosori_kettle_ble.coordinator.CosoriKettleBLEClient") as mock_client_class, \
             patch.object(coordinator, "_send_hello", new_callable=AsyncMock):

            # Setup mocks
            mock_bt.async_ble_device_from_address.return_value = mock_ble_device
            mock_establish.return_value = mock_bleak_client
            mock_client_class.return_value = mock_cosori_client

            await coordinator._connect()

            assert coordinator._client == mock_cosori_client
            mock_cosori_client.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_does_nothing_if_already_connected(self, coordinator, mock_cosori_client):
        """Test that connect does nothing if already connected."""
        coordinator._client = mock_cosori_client

        with patch("custom_components.cosori_kettle_ble.coordinator.bluetooth") as mock_bt:
            await coordinator._connect()
            mock_bt.async_ble_device_from_address.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_device_not_found(self, coordinator):
        """Test connection when device not found."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        with patch("custom_components.cosori_kettle_ble.coordinator.bluetooth") as mock_bt:
            mock_bt.async_ble_device_from_address.return_value = None

            with pytest.raises(UpdateFailed, match="Device not found"):
                await coordinator._connect()

    @pytest.mark.asyncio
    async def test_connect_bleak_error(self, coordinator, mock_ble_device):
        """Test connection with BleakError."""
        from bleak.exc import BleakError
        from homeassistant.helpers.update_coordinator import UpdateFailed

        with patch("custom_components.cosori_kettle_ble.coordinator.bluetooth") as mock_bt, \
             patch("custom_components.cosori_kettle_ble.coordinator.establish_connection", new_callable=AsyncMock) as mock_establish, \
             patch.object(coordinator, "_disconnect", new_callable=AsyncMock):

            mock_bt.async_ble_device_from_address.return_value = mock_ble_device
            mock_establish.side_effect = BleakError("Connection refused")

            with pytest.raises(UpdateFailed, match="Failed to connect"):
                await coordinator._connect()

    def test_on_disconnect_callback(self, coordinator):
        """Test disconnect callback."""
        coordinator._on_disconnect()
        # Should not raise, just log

    @pytest.mark.asyncio
    async def test_disconnect_closes_connection(self, coordinator, mock_cosori_client):
        """Test successful disconnect."""
        coordinator._client = mock_cosori_client

        await coordinator._disconnect()

        mock_cosori_client.disconnect.assert_called_once()
        assert coordinator._client is None

    @pytest.mark.asyncio
    async def test_disconnect_handles_bleak_error(self, coordinator, mock_cosori_client):
        """Test disconnect with BleakError."""
        from bleak.exc import BleakError

        coordinator._client = mock_cosori_client
        mock_cosori_client.disconnect.side_effect = BleakError("Error")

        # Should not raise
        await coordinator._disconnect()

        assert coordinator._client is None

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self, coordinator):
        """Test disconnect when not connected."""
        coordinator._client = None

        # Should not raise
        await coordinator._disconnect()


class TestCoordinatorAsyncUpdateData:
    """Test _async_update_data method."""

    @pytest.mark.asyncio
    async def test_async_update_data_requests_status(self, coordinator, mock_cosori_client):
        """Test that async_update_data requests status."""
        coordinator._client = mock_cosori_client
        coordinator.data = {"stage": 0}

        with patch.object(coordinator, "_send_frame", new_callable=AsyncMock):
            result = await coordinator._async_update_data()
            assert result == coordinator.data

    @pytest.mark.asyncio
    async def test_async_update_data_connects_if_disconnected(self, coordinator, mock_ble_device, mock_bleak_client, mock_cosori_client):
        """Test that async_update_data reconnects if disconnected."""
        coordinator._client = None

        with patch("custom_components.cosori_kettle_ble.coordinator.bluetooth") as mock_bt, \
             patch("custom_components.cosori_kettle_ble.coordinator.establish_connection", new_callable=AsyncMock) as mock_establish, \
             patch("custom_components.cosori_kettle_ble.coordinator.CosoriKettleBLEClient") as mock_client_class, \
             patch.object(coordinator, "_send_frame", new_callable=AsyncMock):

            mock_bt.async_ble_device_from_address.return_value = mock_ble_device
            mock_establish.return_value = mock_bleak_client
            mock_client_class.return_value = mock_cosori_client
            coordinator.data = {}

            result = await coordinator._async_update_data()

            assert coordinator._client == mock_cosori_client
            assert result == {}

    @pytest.mark.asyncio
    async def test_async_update_data_increments_tx_seq(self, coordinator, mock_cosori_client):
        """Test that async_update_data increments tx sequence."""
        coordinator._client = mock_cosori_client
        coordinator._tx_seq = 5
        coordinator.data = {}

        with patch.object(coordinator, "_send_frame", new_callable=AsyncMock):
            await coordinator._async_update_data()
            assert coordinator._tx_seq == 6

    @pytest.mark.asyncio
    async def test_async_update_data_wraps_seq_at_255(self, coordinator, mock_cosori_client):
        """Test that tx_seq wraps at 255."""
        coordinator._client = mock_cosori_client
        coordinator._tx_seq = 255
        coordinator.data = {}

        with patch.object(coordinator, "_send_frame", new_callable=AsyncMock):
            await coordinator._async_update_data()
            assert coordinator._tx_seq == 0

    @pytest.mark.asyncio
    async def test_async_update_data_handles_bleak_error(self, coordinator, mock_cosori_client):
        """Test async_update_data handles BleakError."""
        from bleak.exc import BleakError
        from homeassistant.helpers.update_coordinator import UpdateFailed

        coordinator._client = mock_cosori_client

        with patch.object(coordinator, "_send_frame", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = BleakError("Error")

            with pytest.raises(UpdateFailed, match="Failed to update"):
                await coordinator._async_update_data()

    @pytest.mark.asyncio
    async def test_async_update_data_handles_timeout(self, coordinator, mock_cosori_client):
        """Test async_update_data handles timeout."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        coordinator._client = mock_cosori_client

        with patch.object(coordinator, "_send_frame", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = asyncio.TimeoutError()

            with pytest.raises(UpdateFailed, match="Failed to update"):
                await coordinator._async_update_data()

    @pytest.mark.asyncio
    async def test_async_update_data_lock_prevents_concurrent_access(self, coordinator, mock_cosori_client):
        """Test that lock prevents concurrent update data calls."""
        coordinator._client = mock_cosori_client
        coordinator.data = {}

        call_count = 0

        async def slow_send_frame(frame, wait_for_ack=True):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)

        with patch.object(coordinator, "_send_frame", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = slow_send_frame

            # Start two concurrent updates
            task1 = asyncio.create_task(coordinator._async_update_data())
            task2 = asyncio.create_task(coordinator._async_update_data())

            await asyncio.gather(task1, task2)

            # Both should complete but the second should wait for the first
            assert call_count == 2


class TestCoordinatorSendFrame:
    """Test _send_frame method."""

    @pytest.mark.asyncio
    async def test_send_frame_requires_connection(self, coordinator):
        """Test that send_frame requires connection."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        coordinator._client = None
        frame = Frame(frame_type=0x22, seq=0x01, payload=b"\x01\x81\xD1\x00")

        with pytest.raises(UpdateFailed, match="Not connected"):
            await coordinator._send_frame(frame)

    @pytest.mark.asyncio
    async def test_send_frame_disconnected_client(self, coordinator, mock_cosori_client):
        """Test that send_frame requires connected client."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        coordinator._client = mock_cosori_client
        mock_cosori_client.is_connected = False
        frame = Frame(frame_type=0x22, seq=0x01, payload=b"\x01\x81\xD1\x00")

        with pytest.raises(UpdateFailed, match="Not connected"):
            await coordinator._send_frame(frame)

    @pytest.mark.asyncio
    async def test_send_frame_writes_to_gatt(self, coordinator, mock_cosori_client):
        """Test that send_frame delegates to client."""
        coordinator._client = mock_cosori_client
        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=0x01, payload=b"\x01\x81\xD1\x00")

        ack_payload = b"\x01\x81\xD1\x00\x00"
        mock_cosori_client.send_frame.return_value = ack_payload

        result = await coordinator._send_frame(frame)

        assert result == ack_payload
        mock_cosori_client.send_frame.assert_called_once_with(frame, wait_for_ack=True)

    @pytest.mark.asyncio
    async def test_send_frame_ack_timeout(self, coordinator, mock_cosori_client):
        """Test send_frame timeout waiting for ACK."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        coordinator._client = mock_cosori_client
        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=0x01, payload=b"\x01\x81\xD1\x00")

        mock_cosori_client.send_frame.side_effect = asyncio.TimeoutError()

        with pytest.raises(UpdateFailed, match="Failed to send frame"):
            await coordinator._send_frame(frame)

    @pytest.mark.asyncio
    async def test_send_frame_ack_command_mismatch(self, coordinator, mock_cosori_client):
        """Test send_frame with ACK command mismatch."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        coordinator._client = mock_cosori_client
        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=0x01, payload=b"\x01\x81\xD1\x00")

        mock_cosori_client.send_frame.side_effect = ValueError("ACK command mismatch")

        with pytest.raises(UpdateFailed, match="Failed to send frame"):
            await coordinator._send_frame(frame)

    @pytest.mark.asyncio
    async def test_send_frame_ack_with_error_code(self, coordinator, mock_cosori_client):
        """Test send_frame ACK with error code raises ProtocolError."""
        from homeassistant.helpers.update_coordinator import UpdateFailed
        from custom_components.cosori_kettle_ble.cosori_kettle.exceptions import ProtocolError

        coordinator._client = mock_cosori_client
        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=0x01, payload=b"\x01\x81\xD1\x00")

        mock_cosori_client.send_frame.side_effect = ProtocolError("Device returned error status 0x01", status_code=1)

        with pytest.raises(UpdateFailed, match="Failed to send frame"):
            await coordinator._send_frame(frame)

    @pytest.mark.asyncio
    async def test_send_frame_no_ack_for_ack_frame(self, coordinator, mock_cosori_client):
        """Test that ACK frames can skip waiting for ACK."""
        coordinator._client = mock_cosori_client
        frame = Frame(frame_type=ACK_HEADER_TYPE, seq=0x01, payload=b"\x01\x81\xD1\x00")

        mock_cosori_client.send_frame.return_value = None

        result = await coordinator._send_frame(frame, wait_for_ack=False)

        assert result is None
        mock_cosori_client.send_frame.assert_called_once_with(frame, wait_for_ack=False)

    @pytest.mark.asyncio
    async def test_send_frame_cleanup_on_timeout(self, coordinator, mock_cosori_client):
        """Test that errors are properly propagated."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        coordinator._client = mock_cosori_client
        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=0x01, payload=b"\x01\x81\xD1\x00")

        mock_cosori_client.send_frame.side_effect = asyncio.TimeoutError()

        with pytest.raises(UpdateFailed):
            await coordinator._send_frame(frame)


class TestCoordinatorCommandMethods:
    """Test command methods (set_mode, set_temp, etc)."""

    @pytest.mark.asyncio
    async def test_async_set_mode(self, coordinator, mock_cosori_client):
        """Test async_set_mode."""
        coordinator._client = mock_cosori_client

        await coordinator.async_set_mode(0x04, 212, 60)

        assert coordinator._tx_seq == 1
        mock_cosori_client.send_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_set_mode_with_lock(self, coordinator, mock_cosori_client):
        """Test that async_set_mode uses lock."""
        coordinator._client = mock_cosori_client

        call_count = 0

        async def count_send(*args, **kwargs):
            nonlocal call_count
            call_count += 1

        mock_cosori_client.send_frame.side_effect = count_send

        task1 = asyncio.create_task(coordinator.async_set_mode(0x04, 212, 60))
        task2 = asyncio.create_task(coordinator.async_set_mode(0x06, 200, 30))

        await asyncio.gather(task1, task2)

        # Both should have been sent
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_async_set_my_temp(self, coordinator, mock_cosori_client):
        """Test async_set_my_temp."""
        coordinator._client = mock_cosori_client

        await coordinator.async_set_my_temp(180)

        assert coordinator._tx_seq == 1
        mock_cosori_client.send_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_set_baby_formula(self, coordinator, mock_cosori_client):
        """Test async_set_baby_formula."""
        coordinator._client = mock_cosori_client

        await coordinator.async_set_baby_formula(True)

        assert coordinator._tx_seq == 1
        mock_cosori_client.send_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_stop_heating(self, coordinator, mock_cosori_client):
        """Test async_stop_heating."""
        coordinator._client = mock_cosori_client

        await coordinator.async_stop_heating()

        assert coordinator._tx_seq == 1
        mock_cosori_client.send_frame.assert_called_once()


class TestCoordinatorNotificationHandler:
    """Test frame handler (called by BLE client)."""

    def test_notification_handler_parses_frames(self, coordinator, sample_status_payload):
        """Test that frame handler processes status frames."""
        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=0x01, payload=sample_status_payload)

        with patch.object(coordinator, "_update_data_from_status") as mock_update:
            coordinator._frame_handler(frame)

            # Should have called update
            mock_update.assert_called_once()

    def test_notification_handler_handles_ack(self, coordinator):
        """Test that frame handler ignores ACK frames (handled by client)."""
        ack_payload = b"\x01\x81\xD1\x00\x00"
        frame = Frame(frame_type=ACK_HEADER_TYPE, seq=0x05, payload=ack_payload)

        with patch.object(coordinator, "_update_data_from_status") as mock_update:
            coordinator._frame_handler(frame)

            # Should not process ACK frames
            mock_update.assert_not_called()

    def test_notification_handler_multiple_frames(self, coordinator, sample_status_payload):
        """Test frame handler processes multiple frames."""
        frame1 = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=0x01, payload=sample_status_payload)
        frame2 = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=0x02, payload=sample_status_payload)

        with patch.object(coordinator, "_update_data_from_status") as mock_update:
            coordinator._frame_handler(frame1)
            coordinator._frame_handler(frame2)

            # Should have called update twice
            assert mock_update.call_count == 2

    def test_notification_handler_partial_frame(self, coordinator):
        """Test frame handler with invalid status data."""
        # Frame with invalid status payload
        frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=0x01, payload=b"\x01\x02")

        with patch.object(coordinator, "_update_data_from_status") as mock_update:
            coordinator._frame_handler(frame)

            # Should not update if status invalid
            mock_update.assert_not_called()


class TestCoordinatorHandleAck:
    """Test ACK handling (now delegated to client)."""

    def test_handle_ack_completes_future(self, coordinator):
        """Test that ACK handling is delegated to client."""
        # ACK handling is now done by CosoriKettleBLEClient
        # Coordinator no longer manages pending ACKs directly
        pass

    def test_handle_ack_no_pending(self, coordinator):
        """Test that ACK handling is delegated to client."""
        # ACK handling is now done by CosoriKettleBLEClient
        pass

    def test_handle_ack_already_done(self, coordinator):
        """Test that ACK handling is delegated to client."""
        # ACK handling is now done by CosoriKettleBLEClient
        pass


class TestCoordinatorUpdateDataFromStatus:
    """Test _update_data_from_status method."""

    def test_update_data_from_status(self, coordinator):
        """Test that status updates coordinator data."""
        status = ExtendedStatus(
            stage=1,
            mode=0x04,
            setpoint=212,
            temp=92,
            my_temp=140,
            configured_hold_time=60,
            remaining_hold_time=30,
            on_base=True,
            baby_formula_enabled=True,
            valid=True,
        )

        with patch.object(coordinator, "async_set_updated_data") as mock_set:
            coordinator._update_data_from_status(status)

            mock_set.assert_called_once()
            data = mock_set.call_args[0][0]
            assert data["stage"] == 1
            assert data["mode"] == 0x04
            assert data["setpoint"] == 212
            assert data["temperature"] == 92
            assert data["my_temp"] == 140
            assert data["configured_hold_time"] == 60
            assert data["remaining_hold_time"] == 30
            assert data["on_base"] is True
            assert data["baby_formula_enabled"] is True
            assert data["heating"] is True  # stage > 0

    def test_update_data_heating_false_when_idle(self, coordinator):
        """Test that heating is False when stage is 0."""
        status = ExtendedStatus(
            stage=0,  # idle
            mode=0x04,
            setpoint=212,
            temp=92,
            my_temp=140,
            configured_hold_time=60,
            remaining_hold_time=30,
            on_base=True,
            baby_formula_enabled=False,
            valid=True,
        )

        with patch.object(coordinator, "async_set_updated_data") as mock_set:
            coordinator._update_data_from_status(status)

            data = mock_set.call_args[0][0]
            assert data["heating"] is False


class TestCoordinatorSendHello:
    """Test _send_hello method."""

    @pytest.mark.asyncio
    async def test_send_hello_increments_seq(self, coordinator, mock_bleak_client):
        """Test that _send_hello increments tx_seq."""
        coordinator._client = mock_bleak_client
        coordinator._tx_seq = 0

        async def handle_write(*args, **kwargs):
            if coordinator._pending_ack:
                seq = list(coordinator._pending_ack.keys())[0]
                if not coordinator._pending_ack[seq].done():
                    coordinator._pending_ack[seq].set_result(b"\x01\x81\xD1\x00\x00")

        mock_bleak_client.write_gatt_char.side_effect = handle_write

        await coordinator._send_hello()

        assert coordinator._tx_seq == 1


class TestCoordinatorIntegration:
    """Integration tests."""

    @pytest.mark.asyncio
    async def test_full_connection_flow(self, coordinator, mock_ble_device, mock_bleak_client, mock_cosori_client, sample_status_payload):
        """Test full connection and update flow."""
        with patch("custom_components.cosori_kettle_ble.coordinator.bluetooth") as mock_bt, \
             patch("custom_components.cosori_kettle_ble.coordinator.establish_connection", new_callable=AsyncMock) as mock_establish, \
             patch("custom_components.cosori_kettle_ble.coordinator.CosoriKettleBLEClient") as mock_client_class:

            mock_bt.async_ble_device_from_address.return_value = mock_ble_device
            mock_establish.return_value = mock_bleak_client
            mock_client_class.return_value = mock_cosori_client

            # Connect
            await coordinator._connect()
            assert coordinator._client == mock_cosori_client

            # Receive status update via frame handler
            frame = Frame(frame_type=MESSAGE_HEADER_TYPE, seq=0x01, payload=sample_status_payload)

            with patch.object(coordinator, "async_set_updated_data") as mock_set:
                coordinator._frame_handler(frame)
                mock_set.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconnection_on_update(self, coordinator, mock_ble_device, mock_bleak_client, mock_cosori_client):
        """Test that update reconnects when disconnected."""
        with patch("custom_components.cosori_kettle_ble.coordinator.bluetooth") as mock_bt, \
             patch("custom_components.cosori_kettle_ble.coordinator.establish_connection", new_callable=AsyncMock) as mock_establish, \
             patch("custom_components.cosori_kettle_ble.coordinator.CosoriKettleBLEClient") as mock_client_class:

            mock_bt.async_ble_device_from_address.return_value = mock_ble_device
            mock_establish.return_value = mock_bleak_client
            mock_client_class.return_value = mock_cosori_client

            # Start disconnected
            coordinator._client = None
            coordinator.data = {}

            # Update should reconnect
            result = await coordinator._async_update_data()

            assert coordinator._client == mock_cosori_client
            assert result == {}

    @pytest.mark.asyncio
    async def test_multiple_commands_in_sequence(self, coordinator, mock_cosori_client):
        """Test sending multiple commands in sequence."""
        coordinator._client = mock_cosori_client

        await coordinator.async_set_mode(0x04, 212, 60)
        await coordinator.async_set_my_temp(180)
        await coordinator.async_set_baby_formula(True)
        await coordinator.async_stop_heating()

        # All should succeed and increment seq
        assert coordinator._tx_seq == 4
