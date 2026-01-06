"""Tests for the config_flow module."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homeassistant import data_entry_flow
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResultType

from custom_components.cosori_kettle_ble.const import SERVICE_UUID
from custom_components.cosori_kettle_ble.config_flow import CosoriKettleConfigFlow


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.data = {}
    return hass


@pytest.fixture
def mock_bluetooth_service_info():
    """Create a mock BluetoothServiceInfoBleak object."""
    info = MagicMock()
    info.address = "AA:BB:CC:DD:EE:FF"
    info.name = "Cosori Kettle"
    info.service_uuids = [SERVICE_UUID]
    return info


@pytest.fixture
def mock_config_flow(mock_hass):
    """Create a config flow instance."""
    flow = CosoriKettleConfigFlow()
    flow.hass = mock_hass
    return flow


class TestAsyncStepUser:
    """Test the async_step_user method."""

    @pytest.mark.asyncio
    async def test_no_devices_found(self, mock_config_flow):
        """Test when no Cosori kettles are discovered."""
        with patch(
            "custom_components.cosori_kettle_ble.config_flow.bluetooth.async_discovered_service_info"
        ) as mock_discover:
            mock_discover.return_value = []

            result = await mock_config_flow.async_step_user(user_input=None)

            assert result["type"] == FlowResultType.ABORT
            assert result["reason"] == "no_devices_found"

    @pytest.mark.asyncio
    async def test_devices_discovered(self, mock_config_flow, mock_bluetooth_service_info):
        """Test when valid Cosori kettles are found."""
        with patch(
            "custom_components.cosori_kettle_ble.config_flow.bluetooth.async_discovered_service_info"
        ) as mock_discover:
            mock_discover.return_value = [mock_bluetooth_service_info]

            result = await mock_config_flow.async_step_user(user_input=None)

            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "user"
            assert CONF_ADDRESS in result["data_schema"].schema

    @pytest.mark.asyncio
    async def test_filter_already_configured(self, mock_config_flow, mock_bluetooth_service_info):
        """Test that already configured devices are filtered out."""
        with patch(
            "custom_components.cosori_kettle_ble.config_flow.bluetooth.async_discovered_service_info"
        ) as mock_discover, \
        patch.object(
            mock_config_flow, "_async_current_ids", return_value={mock_bluetooth_service_info.address}
        ):
            mock_discover.return_value = [mock_bluetooth_service_info]

            result = await mock_config_flow.async_step_user(user_input=None)

            # Device should be filtered out, so no devices found
            assert result["type"] == FlowResultType.ABORT
            assert result["reason"] == "no_devices_found"

    @pytest.mark.asyncio
    async def test_service_uuid_filtering(self, mock_config_flow):
        """Test that only devices with matching SERVICE_UUID are included."""
        # Create one device with correct UUID and one without
        correct_device = MagicMock()
        correct_device.address = "AA:BB:CC:DD:EE:FF"
        correct_device.name = "Cosori Kettle"
        correct_device.service_uuids = [SERVICE_UUID]

        wrong_device = MagicMock()
        wrong_device.address = "11:22:33:44:55:66"
        wrong_device.name = "Other Device"
        wrong_device.service_uuids = ["00001234-0000-1000-8000-00805f9b34fb"]

        with patch(
            "custom_components.cosori_kettle_ble.config_flow.bluetooth.async_discovered_service_info"
        ) as mock_discover:
            mock_discover.return_value = [correct_device, wrong_device]

            result = await mock_config_flow.async_step_user(user_input=None)

            assert result["type"] == FlowResultType.FORM
            # Only the correct device should be in the discovered devices
            assert len(mock_config_flow._discovered_devices) == 1
            assert correct_device.address in mock_config_flow._discovered_devices

    @pytest.mark.asyncio
    async def test_service_uuid_case_insensitive(self, mock_config_flow):
        """Test that SERVICE_UUID matching is case insensitive."""
        device = MagicMock()
        device.address = "AA:BB:CC:DD:EE:FF"
        device.name = "Cosori Kettle"
        device.service_uuids = [SERVICE_UUID.upper()]  # Use uppercase version

        with patch(
            "custom_components.cosori_kettle_ble.config_flow.bluetooth.async_discovered_service_info"
        ) as mock_discover:
            mock_discover.return_value = [device]

            result = await mock_config_flow.async_step_user(user_input=None)

            assert result["type"] == FlowResultType.FORM
            assert len(mock_config_flow._discovered_devices) == 1

    @pytest.mark.asyncio
    async def test_user_selection(self, mock_config_flow, mock_bluetooth_service_info):
        """Test when user selects a device from the form."""
        # First, populate the discovered devices
        mock_config_flow._discovered_devices = {
            mock_bluetooth_service_info.address: mock_bluetooth_service_info
        }

        user_input = {CONF_ADDRESS: mock_bluetooth_service_info.address}

        with patch.object(
            mock_config_flow, "async_set_unique_id", new_callable=AsyncMock
        ) as mock_set_unique_id, \
        patch.object(
            mock_config_flow, "_abort_if_unique_id_configured"
        ) as mock_abort, \
        patch.object(
            mock_config_flow, "async_step_pairing_mode", new_callable=AsyncMock
        ) as mock_pairing_mode:
            mock_pairing_mode.return_value = {"type": FlowResultType.FORM}

            result = await mock_config_flow.async_step_user(user_input=user_input)

            # Verify unique ID was set
            mock_set_unique_id.assert_called_once_with(
                mock_bluetooth_service_info.address, raise_on_progress=False
            )

            # Verify abort check was called
            mock_abort.assert_called_once()

            # Verify discovery info and address were stored
            assert mock_config_flow._discovery_info == mock_bluetooth_service_info
            assert mock_config_flow._selected_address == mock_bluetooth_service_info.address

            # Verify flow proceeded to pairing mode
            mock_pairing_mode.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_devices_discovered(self, mock_config_flow):
        """Test when multiple Cosori kettles are found."""
        device1 = MagicMock()
        device1.address = "AA:BB:CC:DD:EE:FF"
        device1.name = "Cosori Kettle 1"
        device1.service_uuids = [SERVICE_UUID]

        device2 = MagicMock()
        device2.address = "11:22:33:44:55:66"
        device2.name = "Cosori Kettle 2"
        device2.service_uuids = [SERVICE_UUID]

        with patch(
            "custom_components.cosori_kettle_ble.config_flow.bluetooth.async_discovered_service_info"
        ) as mock_discover:
            mock_discover.return_value = [device1, device2]

            result = await mock_config_flow.async_step_user(user_input=None)

            assert result["type"] == FlowResultType.FORM
            assert len(mock_config_flow._discovered_devices) == 2
            assert device1.address in mock_config_flow._discovered_devices
            assert device2.address in mock_config_flow._discovered_devices

    @pytest.mark.asyncio
    async def test_device_without_name(self, mock_config_flow):
        """Test handling of device without a name."""
        device = MagicMock()
        device.address = "AA:BB:CC:DD:EE:FF"
        device.name = None  # No name
        device.service_uuids = [SERVICE_UUID]

        with patch(
            "custom_components.cosori_kettle_ble.config_flow.bluetooth.async_discovered_service_info"
        ) as mock_discover:
            mock_discover.return_value = [device]

            result = await mock_config_flow.async_step_user(user_input=None)

            assert result["type"] == FlowResultType.FORM
            # The form should show "Cosori Kettle" as fallback name
            assert len(mock_config_flow._discovered_devices) == 1
