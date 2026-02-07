"""Tests for the number platform module."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.cosori_kettle_ble.const import DOMAIN
from custom_components.cosori_kettle_ble.number import (
    CosoriKettleNumber,
    NUMBERS,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = AsyncMock()
    coordinator.data = {}
    coordinator.formatted_address = "test_entry_id"
    coordinator.device_info = {
        "identifiers": {(DOMAIN, "test_entry_id")},
        "name": "Cosori Kettle",
        "manufacturer": "Cosori",
        "model": "Smart Kettle",
    }
    coordinator.desired_hold_time_minutes = 0
    coordinator.async_set_desired_hold_time = AsyncMock()
    return coordinator


@pytest.fixture
def hold_time_description():
    """Return the hold time number entity description."""
    return NUMBERS[0]


@pytest.fixture
def number_entity(mock_coordinator, hold_time_description):
    """Create a number entity instance."""
    return CosoriKettleNumber(mock_coordinator, hold_time_description)


class TestCosoriKettleNumberInitialization:
    """Test number entity initialization."""

    def test_unique_id(self, number_entity):
        """Test unique ID is set correctly."""
        assert number_entity.unique_id == "test_entry_id_hold_time"

    def test_has_entity_name(self, number_entity):
        """Test has_entity_name is True."""
        assert number_entity._attr_has_entity_name is True

    def test_device_info(self, number_entity, mock_coordinator):
        """Test device info matches coordinator."""
        assert number_entity.device_info == mock_coordinator.device_info

    def test_entity_description(self, number_entity, hold_time_description):
        """Test entity description is set."""
        assert number_entity.entity_description == hold_time_description


class TestCosoriKettleNumberDescription:
    """Test the hold time number entity description."""

    def test_key(self, hold_time_description):
        """Test description key."""
        assert hold_time_description.key == "hold_time"

    def test_name(self, hold_time_description):
        """Test description name."""
        assert hold_time_description.name == "Hold Time"

    def test_min_value(self, hold_time_description):
        """Test minimum value is 0."""
        assert hold_time_description.native_min_value == 0

    def test_max_value(self, hold_time_description):
        """Test maximum value is 60 minutes."""
        assert hold_time_description.native_max_value == 60

    def test_step(self, hold_time_description):
        """Test step is 1 minute."""
        assert hold_time_description.native_step == 1

    def test_unit(self, hold_time_description):
        """Test unit is minutes."""
        from homeassistant.const import UnitOfTime
        assert hold_time_description.native_unit_of_measurement == UnitOfTime.MINUTES


class TestCosoriKettleNumberValue:
    """Test native_value property."""

    def test_native_value_zero(self, number_entity, mock_coordinator):
        """Test native value when hold time is 0."""
        mock_coordinator.desired_hold_time_minutes = 0
        assert number_entity.native_value == 0

    def test_native_value_set(self, number_entity, mock_coordinator):
        """Test native value when hold time is configured."""
        mock_coordinator.desired_hold_time_minutes = 30
        assert number_entity.native_value == 30

    def test_native_value_max(self, number_entity, mock_coordinator):
        """Test native value at maximum."""
        mock_coordinator.desired_hold_time_minutes = 60
        assert number_entity.native_value == 60


class TestCosoriKettleNumberSetValue:
    """Test async_set_native_value method."""

    @pytest.mark.asyncio
    async def test_set_value(self, number_entity, mock_coordinator):
        """Test setting hold time value."""
        await number_entity.async_set_native_value(30)
        mock_coordinator.async_set_desired_hold_time.assert_called_once_with(30)

    @pytest.mark.asyncio
    async def test_set_value_zero_disables(self, number_entity, mock_coordinator):
        """Test setting hold time to 0 disables hold."""
        await number_entity.async_set_native_value(0)
        mock_coordinator.async_set_desired_hold_time.assert_called_once_with(0)

    @pytest.mark.asyncio
    async def test_set_value_max(self, number_entity, mock_coordinator):
        """Test setting hold time to max value."""
        await number_entity.async_set_native_value(60)
        mock_coordinator.async_set_desired_hold_time.assert_called_once_with(60)
