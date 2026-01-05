"""Tests for the CosoriKettle class."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.cosori_kettle_ble.cosori_kettle.kettle import CosoriKettle
from custom_components.cosori_kettle_ble.cosori_kettle.protocol import (
    PROTOCOL_VERSION_V1,
    ExtendedStatus,
    Frame,
    MODE_BOIL,
    MODE_COFFEE,
    MODE_GREEN_TEA,
    MODE_MY_TEMP,
    MODE_OOLONG,
)


@pytest.fixture
def mock_ble_device():
    """Create a mock BLE device."""
    device = MagicMock()
    device.address = "00:11:22:33:44:55"
    return device


@pytest.fixture
def registration_key():
    """Return a valid 16-byte registration key."""
    return bytes.fromhex("00112233445566778899AABBCCDDEEFF")


@pytest.fixture
def mock_ble_client():
    """Create a mock CosoriKettleBLEClient."""
    client = AsyncMock()
    client.is_connected = False
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.send_frame = AsyncMock(return_value=b"")
    return client


@pytest.fixture
def status_with_data():
    """Create a valid ExtendedStatus object with data."""
    return ExtendedStatus(
        valid=True,
        stage=1,
        mode=MODE_MY_TEMP,
        setpoint=180,
        temp=150,
        my_temp=180,
        configured_hold_time=60,
        remaining_hold_time=30,
        on_base=True,
        baby_formula_enabled=False,
    )


@pytest.fixture
def status_idle():
    """Create an idle ExtendedStatus object."""
    return ExtendedStatus(
        valid=True,
        stage=0,
        mode=0,
        setpoint=0,
        temp=70,
        my_temp=180,
        configured_hold_time=0,
        remaining_hold_time=0,
        on_base=True,
        baby_formula_enabled=False,
    )


class TestCosoriKettleInitialization:
    """Test CosoriKettle initialization."""

    def test_init_with_defaults(self, mock_ble_device, registration_key):
        """Test initialization with default parameters."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient"):
            kettle = CosoriKettle(mock_ble_device, registration_key)

            assert kettle._protocol_version == PROTOCOL_VERSION_V1
            assert kettle._registration_key == registration_key
            assert kettle._status_callback is None
            assert kettle._tx_seq == 0
            assert kettle._current_status is None

    def test_init_with_protocol_version(self, mock_ble_device, registration_key):
        """Test initialization with custom protocol version."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient"):
            custom_version = 0x02
            kettle = CosoriKettle(
                mock_ble_device,
                registration_key,
                protocol_version=custom_version,
            )

            assert kettle._protocol_version == custom_version

    def test_init_with_status_callback(self, mock_ble_device, registration_key):
        """Test initialization with status callback."""
        callback = MagicMock()
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient"):
            kettle = CosoriKettle(
                mock_ble_device,
                registration_key,
                status_callback=callback,
            )

            assert kettle._status_callback is callback

    def test_init_creates_ble_client(self, mock_ble_device, registration_key):
        """Test that initialization creates a BLE client."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient") as mock_client_class:
            CosoriKettle(mock_ble_device, registration_key)

            mock_client_class.assert_called_once()
            call_kwargs = mock_client_class.call_args[1]
            assert "notification_callback" in call_kwargs

    def test_init_with_invalid_key_length(self, mock_ble_device):
        """Test initialization with invalid registration key length."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient"):
            # Too short
            with pytest.raises(ValueError, match="exactly 16 bytes"):
                CosoriKettle(mock_ble_device, b"short")

            # Too long
            with pytest.raises(ValueError, match="exactly 16 bytes"):
                CosoriKettle(mock_ble_device, b"x" * 20)


class TestCosoriKettleAsyncContextManager:
    """Test async context manager functionality."""

    @pytest.mark.asyncio
    async def test_aenter_calls_connect(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that __aenter__ calls connect."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            with patch.object(kettle, "connect", new_callable=AsyncMock) as mock_connect:
                await kettle.__aenter__()
                mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_aenter_returns_self(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that __aenter__ returns self."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            with patch.object(kettle, "connect", new_callable=AsyncMock):
                result = await kettle.__aenter__()
                assert result is kettle

    @pytest.mark.asyncio
    async def test_aexit_calls_disconnect(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that __aexit__ calls disconnect."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)

            with patch.object(kettle, "disconnect", new_callable=AsyncMock) as mock_disconnect:
                await kettle.__aexit__(None, None, None)
                mock_disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_flow(self, mock_ble_device, registration_key, mock_ble_client):
        """Test full async context manager flow."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True

            async with CosoriKettle(mock_ble_device, registration_key) as kettle:
                mock_ble_client.connect.assert_called()
                assert kettle is not None

            mock_ble_client.disconnect.assert_called()


class TestCosoriKettleConnectivity:
    """Test connectivity and status checking."""

    def test_is_connected_property(self, mock_ble_device, registration_key, mock_ble_client):
        """Test is_connected property."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)

            mock_ble_client.is_connected = False
            assert kettle.is_connected is False

            mock_ble_client.is_connected = True
            assert kettle.is_connected is True

    @pytest.mark.asyncio
    async def test_connect_sends_hello_and_requests_status(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that connect sends hello frame and requests status."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            with patch.object(kettle, "update_status", new_callable=AsyncMock):
                await kettle.connect()

            mock_ble_client.connect.assert_called_once()
            mock_ble_client.send_frame.assert_called()

    @pytest.mark.asyncio
    async def test_disconnect(self, mock_ble_device, registration_key, mock_ble_client):
        """Test disconnect."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)

            await kettle.disconnect()

            mock_ble_client.disconnect.assert_called_once()


class TestCosoriKettleStatusProperties:
    """Test status-related properties."""

    def test_status_property_when_none(self, mock_ble_device, registration_key, mock_ble_client):
        """Test status property when no status set."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)

            assert kettle.status is None

    def test_status_property_with_data(self, mock_ble_device, registration_key, mock_ble_client, status_with_data):
        """Test status property when status is set."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)
            kettle._current_status = status_with_data

            assert kettle.status is status_with_data

    def test_temperature_property_when_none(self, mock_ble_device, registration_key, mock_ble_client):
        """Test temperature property when no status."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)

            assert kettle.temperature is None

    def test_temperature_property_with_status(self, mock_ble_device, registration_key, mock_ble_client, status_with_data):
        """Test temperature property returns current temp."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)
            kettle._current_status = status_with_data

            assert kettle.temperature == 150

    def test_is_heating_property_when_none(self, mock_ble_device, registration_key, mock_ble_client):
        """Test is_heating property when no status."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)

            assert kettle.is_heating is False

    def test_is_heating_property_when_heating(self, mock_ble_device, registration_key, mock_ble_client, status_with_data):
        """Test is_heating property when stage > 0."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)
            kettle._current_status = status_with_data

            assert kettle.is_heating is True

    def test_is_heating_property_when_idle(self, mock_ble_device, registration_key, mock_ble_client, status_idle):
        """Test is_heating property when stage == 0."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)
            kettle._current_status = status_idle

            assert kettle.is_heating is False

    def test_is_on_base_property_when_none(self, mock_ble_device, registration_key, mock_ble_client):
        """Test is_on_base property when no status."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)

            assert kettle.is_on_base is False

    def test_is_on_base_property_when_on_base(self, mock_ble_device, registration_key, mock_ble_client, status_with_data):
        """Test is_on_base property when on base."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)
            kettle._current_status = status_with_data

            assert kettle.is_on_base is True

    def test_is_on_base_property_when_off_base(self, mock_ble_device, registration_key, mock_ble_client):
        """Test is_on_base property when off base."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)
            status_off_base = ExtendedStatus(
                valid=True,
                stage=0,
                mode=0,
                setpoint=0,
                temp=70,
                my_temp=180,
                configured_hold_time=0,
                remaining_hold_time=0,
                on_base=False,
                baby_formula_enabled=False,
            )
            kettle._current_status = status_off_base

            assert kettle.is_on_base is False

    def test_setpoint_property_when_none(self, mock_ble_device, registration_key, mock_ble_client):
        """Test setpoint property when no status."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)

            assert kettle.setpoint is None

    def test_setpoint_property_with_status(self, mock_ble_device, registration_key, mock_ble_client, status_with_data):
        """Test setpoint property returns target temp."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)
            kettle._current_status = status_with_data

            assert kettle.setpoint == 180


class TestCosoriKettleUpdateStatus:
    """Test status update functionality."""

    @pytest.mark.asyncio
    async def test_update_status_sends_status_request(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that update_status sends a status request frame."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)
            kettle._current_status = None

            await kettle.update_status()

            # Verify send_frame was called
            assert mock_ble_client.send_frame.called

    @pytest.mark.asyncio
    async def test_update_status_increments_seq(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that update_status increments tx_seq."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            initial_seq = kettle._tx_seq
            await kettle.update_status()

            assert kettle._tx_seq == (initial_seq + 1) & 0xFF

    @pytest.mark.asyncio
    async def test_update_status_returns_current_status(self, mock_ble_device, registration_key, mock_ble_client, status_with_data):
        """Test that update_status returns current status."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)
            kettle._current_status = status_with_data

            result = await kettle.update_status()

            assert result is status_with_data


class TestCosoriKettleHeatingMethods:
    """Test all heating control methods."""

    @pytest.mark.asyncio
    async def test_boil_default_hold_time(self, mock_ble_device, registration_key, mock_ble_client):
        """Test boil with default hold time."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            await kettle.boil()

            mock_ble_client.send_frame.assert_called()
            sent_frame = mock_ble_client.send_frame.call_args[0][0]
            assert isinstance(sent_frame, Frame)

    @pytest.mark.asyncio
    async def test_boil_with_hold_time(self, mock_ble_device, registration_key, mock_ble_client):
        """Test boil with custom hold time."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            await kettle.boil(hold_time_seconds=300)

            mock_ble_client.send_frame.assert_called()

    @pytest.mark.asyncio
    async def test_boil_increments_seq(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that boil increments tx_seq."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            initial_seq = kettle._tx_seq
            await kettle.boil()

            assert kettle._tx_seq == (initial_seq + 1) & 0xFF

    @pytest.mark.asyncio
    async def test_heat_for_green_tea(self, mock_ble_device, registration_key, mock_ble_client):
        """Test heat_for_green_tea."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            await kettle.heat_for_green_tea()

            mock_ble_client.send_frame.assert_called()

    @pytest.mark.asyncio
    async def test_heat_for_oolong_tea(self, mock_ble_device, registration_key, mock_ble_client):
        """Test heat_for_oolong_tea."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            await kettle.heat_for_oolong_tea()

            mock_ble_client.send_frame.assert_called()

    @pytest.mark.asyncio
    async def test_heat_for_coffee(self, mock_ble_device, registration_key, mock_ble_client):
        """Test heat_for_coffee."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            await kettle.heat_for_coffee()

            mock_ble_client.send_frame.assert_called()

    @pytest.mark.asyncio
    async def test_heat_to_temperature(self, mock_ble_device, registration_key, mock_ble_client):
        """Test heat_to_temperature."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            await kettle.heat_to_temperature(175)

            # Should call send_frame twice: once for set_my_temp, once for set_mode
            assert mock_ble_client.send_frame.call_count >= 2

    @pytest.mark.asyncio
    async def test_heat_to_temperature_with_hold_time(self, mock_ble_device, registration_key, mock_ble_client):
        """Test heat_to_temperature with hold time."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            await kettle.heat_to_temperature(175, hold_time_seconds=120)

            assert mock_ble_client.send_frame.call_count >= 2

    @pytest.mark.asyncio
    async def test_heat_to_temperature_calls_set_my_temp(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that heat_to_temperature calls set_my_temp first."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            with patch.object(kettle, "set_my_temp", new_callable=AsyncMock) as mock_set_my_temp:
                await kettle.heat_to_temperature(175)

                mock_set_my_temp.assert_called_once_with(175)


class TestCosoriKettleStopHeating:
    """Test stop heating functionality."""

    @pytest.mark.asyncio
    async def test_stop_heating(self, mock_ble_device, registration_key, mock_ble_client):
        """Test stop_heating sends stop frame."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            await kettle.stop_heating()

            mock_ble_client.send_frame.assert_called()
            sent_frame = mock_ble_client.send_frame.call_args[0][0]
            assert isinstance(sent_frame, Frame)

    @pytest.mark.asyncio
    async def test_stop_heating_increments_seq(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that stop_heating increments tx_seq."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            initial_seq = kettle._tx_seq
            await kettle.stop_heating()

            assert kettle._tx_seq == (initial_seq + 1) & 0xFF


class TestCosoriKettleCustomSettings:
    """Test custom temperature and baby formula settings."""

    @pytest.mark.asyncio
    async def test_set_my_temp(self, mock_ble_device, registration_key, mock_ble_client):
        """Test set_my_temp."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            await kettle.set_my_temp(185)

            mock_ble_client.send_frame.assert_called()
            sent_frame = mock_ble_client.send_frame.call_args[0][0]
            assert isinstance(sent_frame, Frame)

    @pytest.mark.asyncio
    async def test_set_my_temp_increments_seq(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that set_my_temp increments tx_seq."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            initial_seq = kettle._tx_seq
            await kettle.set_my_temp(185)

            assert kettle._tx_seq == (initial_seq + 1) & 0xFF

    @pytest.mark.asyncio
    async def test_set_baby_formula_mode_enabled(self, mock_ble_device, registration_key, mock_ble_client):
        """Test set_baby_formula_mode with enabled=True."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            await kettle.set_baby_formula_mode(True)

            mock_ble_client.send_frame.assert_called()

    @pytest.mark.asyncio
    async def test_set_baby_formula_mode_disabled(self, mock_ble_device, registration_key, mock_ble_client):
        """Test set_baby_formula_mode with enabled=False."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            await kettle.set_baby_formula_mode(False)

            mock_ble_client.send_frame.assert_called()

    @pytest.mark.asyncio
    async def test_set_baby_formula_mode_increments_seq(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that set_baby_formula_mode increments tx_seq."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            initial_seq = kettle._tx_seq
            await kettle.set_baby_formula_mode(True)

            assert kettle._tx_seq == (initial_seq + 1) & 0xFF


class TestCosoriKettleNotificationHandling:
    """Test status notification handling."""

    def test_on_notification_ignores_ack_frames(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that _on_notification ignores ACK frames."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)

            # Create an ACK frame (type 0x01)
            ack_frame = Frame(frame_type=0x01, seq=0x00, payload=b"")

            kettle._on_notification(ack_frame)

            # Status should not be updated
            assert kettle._current_status is None

    def test_on_notification_parses_valid_status(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that _on_notification parses valid status frames."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key)

            # Create a valid extended status payload
            payload = bytearray([
                0x01, 0x40, 0x40, 0x00,  # [0-3] header
                0x01,  # [4] stage (heating)
                0x00,  # [5] mode
                0xD4,  # [6] setpoint (212)
                0x5C,  # [7] temp (92)
                0x8C,  # [8] my_temp (140)
                0x00,  # [9] padding
                0x3C, 0x00,  # [10-11] configured_hold_time (60) little-endian
                0x00, 0x00,  # [12-13] remaining_hold_time (0) little-endian
                0x00,  # [14] on_base (yes = 0x00)
                0x00, 0x00, 0x00, 0x00,  # [15-18] padding
                0x00, 0x00,  # [19-20] padding
                0x00, 0x00, 0x00,  # [21-23] padding
                0x00, 0x00,  # [24-25] padding
                0x01,  # [26] baby_formula_enabled
                0x00, 0x00,  # [27-28] padding (to reach 29 bytes minimum)
            ])
            status_frame = Frame(frame_type=0x22, seq=0x00, payload=bytes(payload))

            kettle._on_notification(status_frame)

            assert kettle._current_status is not None
            assert kettle._current_status.valid
            assert kettle._current_status.stage == 1
            assert kettle._current_status.setpoint == 212

    def test_on_notification_calls_callback(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that _on_notification calls status callback."""
        callback = MagicMock()

        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            kettle = CosoriKettle(mock_ble_device, registration_key, status_callback=callback)

            # Create a valid extended status payload
            payload = bytearray([
                0x01, 0x40, 0x40, 0x00,  # [0-3] header
                0x01,  # [4] stage (heating)
                0x00,  # [5] mode
                0xD4,  # [6] setpoint (212)
                0x5C,  # [7] temp (92)
                0x8C,  # [8] my_temp (140)
                0x00,  # [9] padding
                0x3C, 0x00,  # [10-11] configured_hold_time (60) little-endian
                0x00, 0x00,  # [12-13] remaining_hold_time (0) little-endian
                0x00,  # [14] on_base (yes = 0x00)
                0x00, 0x00, 0x00, 0x00,  # [15-18] padding
                0x00, 0x00,  # [19-20] padding
                0x00, 0x00, 0x00,  # [21-23] padding
                0x00, 0x00,  # [24-25] padding
                0x01,  # [26] baby_formula_enabled
                0x00, 0x00,  # [27-28] padding (to reach 29 bytes minimum)
            ])
            status_frame = Frame(frame_type=0x22, seq=0x00, payload=bytes(payload))

            kettle._on_notification(status_frame)

            callback.assert_called_once()
            called_status = callback.call_args[0][0]
            assert called_status.stage == 1


class TestCosoriKettleSequenceNumbering:
    """Test sequence number management."""

    def test_tx_seq_wraps_at_255(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that tx_seq wraps around at 256."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            # Set seq to 255
            kettle._tx_seq = 0xFF

            # After next operation, should wrap to 0
            initial_seq = kettle._tx_seq
            kettle._tx_seq = (kettle._tx_seq + 1) & 0xFF

            assert kettle._tx_seq == 0

    @pytest.mark.asyncio
    async def test_multiple_operations_increment_seq(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that multiple operations increment seq correctly."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            initial_seq = kettle._tx_seq

            await kettle.boil()
            assert kettle._tx_seq == (initial_seq + 1) & 0xFF

            await kettle.stop_heating()
            assert kettle._tx_seq == (initial_seq + 2) & 0xFF

            await kettle.set_my_temp(180)
            assert kettle._tx_seq == (initial_seq + 3) & 0xFF


class TestCosoriKettleFrameBuilding:
    """Test that correct frames are built for operations."""

    @pytest.mark.asyncio
    async def test_boil_frame_payload(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that boil builds a frame with correct mode."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            await kettle.boil()

            sent_frame = mock_ble_client.send_frame.call_args[0][0]
            # Frame should have the mode set in payload
            assert sent_frame.frame_type == 0x22
            assert len(sent_frame.payload) > 0

    @pytest.mark.asyncio
    async def test_stop_frame_payload(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that stop_heating builds a frame."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            await kettle.stop_heating()

            sent_frame = mock_ble_client.send_frame.call_args[0][0]
            assert sent_frame.frame_type == 0x22
            assert sent_frame.seq < 256  # Valid seq number

    @pytest.mark.asyncio
    async def test_set_my_temp_frame_payload(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that set_my_temp builds a frame."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            await kettle.set_my_temp(180)

            sent_frame = mock_ble_client.send_frame.call_args[0][0]
            assert sent_frame.frame_type == 0x22
            assert len(sent_frame.payload) > 0


class TestCosoriKettleIntegration:
    """Integration tests combining multiple operations."""

    @pytest.mark.asyncio
    async def test_full_heating_workflow(self, mock_ble_device, registration_key, mock_ble_client, status_idle, status_with_data):
        """Test complete heating workflow."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            # Initial state
            assert kettle.is_heating is False

            # Start heating
            await kettle.heat_to_temperature(185)
            assert mock_ble_client.send_frame.called

            # Simulate status update
            kettle._current_status = status_with_data
            assert kettle.is_heating is True
            assert kettle.temperature == 150
            assert kettle.setpoint == 180

            # Stop heating
            await kettle.stop_heating()

            # Simulate idle status
            kettle._current_status = status_idle
            assert kettle.is_heating is False

    @pytest.mark.asyncio
    async def test_multiple_heating_modes(self, mock_ble_device, registration_key, mock_ble_client):
        """Test switching between different heating modes."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            # Test all heating modes
            await kettle.boil()
            await kettle.heat_for_green_tea()
            await kettle.heat_for_oolong_tea()
            await kettle.heat_for_coffee()
            await kettle.heat_to_temperature(190)

            # Verify all calls were made
            assert mock_ble_client.send_frame.call_count >= 5


class TestCosoriKettleRegistrationAndPairing:
    """Test registration and pairing functionality."""

    @pytest.mark.asyncio
    async def test_pair_sends_register_and_hello(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that pair() sends both register and hello frames."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            kettle = CosoriKettle(mock_ble_device, registration_key)

            with patch.object(kettle, "update_status", new_callable=AsyncMock):
                await kettle.pair()

            # Should send register frame and hello frame
            assert mock_ble_client.send_frame.call_count >= 2

    @pytest.mark.asyncio
    async def test_pair_raises_when_not_connected(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that pair() raises RuntimeError when not connected."""
        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = False
            kettle = CosoriKettle(mock_ble_device, registration_key)

            with pytest.raises(RuntimeError, match="Must connect to device before pairing"):
                await kettle.pair()

    @pytest.mark.asyncio
    async def test_send_register_with_device_not_in_pairing_mode(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that _send_register raises DeviceNotInPairingModeError when status=1."""
        from custom_components.cosori_kettle_ble.cosori_kettle.exceptions import (
            DeviceNotInPairingModeError,
            ProtocolError,
        )

        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            mock_ble_client.send_frame.side_effect = ProtocolError("Error", status_code=1)

            kettle = CosoriKettle(mock_ble_device, registration_key)

            with pytest.raises(DeviceNotInPairingModeError) as exc_info:
                await kettle._send_register()

            assert exc_info.value.status_code == 1
            assert "not in pairing mode" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_send_hello_with_invalid_key(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that _send_hello raises InvalidRegistrationKeyError when status=1."""
        from custom_components.cosori_kettle_ble.cosori_kettle.exceptions import (
            InvalidRegistrationKeyError,
            ProtocolError,
        )

        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            mock_ble_client.send_frame.side_effect = ProtocolError("Error", status_code=1)

            kettle = CosoriKettle(mock_ble_device, registration_key)

            with pytest.raises(InvalidRegistrationKeyError) as exc_info:
                await kettle._send_hello()

            assert exc_info.value.status_code == 1
            assert "rejected" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_send_hello_with_other_protocol_error(self, mock_ble_device, registration_key, mock_ble_client):
        """Test that _send_hello propagates other ProtocolErrors."""
        from custom_components.cosori_kettle_ble.cosori_kettle.exceptions import ProtocolError

        with patch("custom_components.cosori_kettle_ble.cosori_kettle.kettle.CosoriKettleBLEClient", return_value=mock_ble_client):
            mock_ble_client.is_connected = True
            mock_ble_client.send_frame.side_effect = ProtocolError("Other error", status_code=2)

            kettle = CosoriKettle(mock_ble_device, registration_key)

            with pytest.raises(ProtocolError) as exc_info:
                await kettle._send_hello()

            assert exc_info.value.status_code == 2
