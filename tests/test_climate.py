"""Tests for the climate platform module."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from custom_components.cosori_kettle_ble.const import (
    DOMAIN,
    MAX_TEMP_F,
    MIN_TEMP_F,
    MODE_BOIL,
    MODE_COFFEE,
    MODE_GREEN_TEA,
    MODE_HEAT,
    MODE_MY_TEMP,
    MODE_OOLONG,
)
from custom_components.cosori_kettle_ble.climate import (
    CosoriKettleClimate,
    PRESET_BOIL,
    PRESET_COFFEE,
    PRESET_GREEN_TEA,
    PRESET_OOLONG,
    PRESET_TO_MODE,
    MODE_TO_PRESET,
)


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = AsyncMock()
    coordinator.data = {
        "temperature": 75.0,
        "setpoint": 212,
        "heating": False,
        "stage": 0,
        "mode": MODE_MY_TEMP,
        "my_temp": 180,
    }
    coordinator.manufacturer = "Cosori"
    coordinator.model_number = "Smart Kettle"
    coordinator.hardware_version = None
    coordinator.software_version = None
    coordinator.async_set_mode = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_stop_heating = AsyncMock()
    return coordinator


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    return entry


@pytest.fixture
def climate_entity(mock_coordinator, mock_config_entry):
    """Create a climate entity instance."""
    return CosoriKettleClimate(mock_coordinator, mock_config_entry)


class TestCosoriKettleClimateInitialization:
    """Test climate entity initialization."""

    def test_entity_initialization(self, climate_entity, mock_config_entry):
        """Test that entity is properly initialized."""
        assert isinstance(climate_entity, ClimateEntity)
        assert climate_entity._attr_has_entity_name is True
        assert climate_entity._attr_name is None
        assert climate_entity._attr_temperature_unit == UnitOfTemperature.FAHRENHEIT

    def test_unique_id(self, climate_entity, mock_config_entry):
        """Test unique ID is set correctly."""
        assert climate_entity._attr_unique_id == "test_entry_id_climate"

    def test_device_info(self, climate_entity):
        """Test device info is properly configured."""
        device_info = climate_entity._attr_device_info
        assert device_info["identifiers"] == {(DOMAIN, "test_entry_id")}
        assert device_info["name"] == "Cosori Kettle"
        assert device_info["manufacturer"] == "Cosori"
        assert device_info["model"] == "Smart Kettle"

    def test_hvac_modes(self, climate_entity):
        """Test supported HVAC modes."""
        assert climate_entity._attr_hvac_modes == [HVACMode.OFF, HVACMode.HEAT]

    def test_preset_modes(self, climate_entity):
        """Test supported preset modes."""
        expected_presets = [PRESET_BOIL, PRESET_GREEN_TEA, PRESET_OOLONG, PRESET_COFFEE]
        assert climate_entity._attr_preset_modes == expected_presets

    def test_supported_features(self, climate_entity):
        """Test supported climate features."""
        expected_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        assert climate_entity._attr_supported_features == expected_features

    def test_temperature_limits(self, climate_entity):
        """Test temperature limits are set correctly."""
        assert climate_entity._attr_min_temp == MIN_TEMP_F
        assert climate_entity._attr_max_temp == MAX_TEMP_F
        assert climate_entity._attr_target_temperature_step == 1


class TestCosoriKettleClimateProperties:
    """Test climate entity properties."""

    def test_current_temperature(self, climate_entity, mock_coordinator):
        """Test current temperature property."""
        mock_coordinator.data = {"temperature": 75.5}
        assert climate_entity.current_temperature == 75.5

    def test_current_temperature_none_when_no_data(self, climate_entity, mock_coordinator):
        """Test current temperature returns None when no coordinator data."""
        mock_coordinator.data = None
        assert climate_entity.current_temperature is None

    def test_current_temperature_none_when_key_missing(self, climate_entity, mock_coordinator):
        """Test current temperature returns None when key missing from data."""
        mock_coordinator.data = {"other": "value"}
        assert climate_entity.current_temperature is None

    def test_target_temperature(self, climate_entity, mock_coordinator):
        """Test target temperature property."""
        mock_coordinator.data = {"setpoint": 212}
        assert climate_entity.target_temperature == 212

    def test_target_temperature_none_when_no_data(self, climate_entity, mock_coordinator):
        """Test target temperature returns None when no coordinator data."""
        mock_coordinator.data = None
        assert climate_entity.target_temperature is None

    def test_hvac_mode_heat(self, climate_entity, mock_coordinator):
        """Test HVAC mode is HEAT when heating."""
        mock_coordinator.data = {"heating": True}
        assert climate_entity.hvac_mode == HVACMode.HEAT

    def test_hvac_mode_off(self, climate_entity, mock_coordinator):
        """Test HVAC mode is OFF when not heating."""
        mock_coordinator.data = {"heating": False}
        assert climate_entity.hvac_mode == HVACMode.OFF

    def test_hvac_mode_off_when_no_data(self, climate_entity, mock_coordinator):
        """Test HVAC mode is OFF when no coordinator data."""
        mock_coordinator.data = None
        assert climate_entity.hvac_mode == HVACMode.OFF

    def test_hvac_action_heating(self, climate_entity, mock_coordinator):
        """Test HVAC action is HEATING when actively heating."""
        mock_coordinator.data = {"heating": True, "stage": 1}
        assert climate_entity.hvac_action == HVACAction.HEATING

    def test_hvac_action_idle(self, climate_entity, mock_coordinator):
        """Test HVAC action is IDLE when at stage 0."""
        mock_coordinator.data = {"heating": False, "stage": 0}
        assert climate_entity.hvac_action == HVACAction.IDLE

    def test_hvac_action_off_when_no_data(self, climate_entity, mock_coordinator):
        """Test HVAC action is OFF when no coordinator data."""
        mock_coordinator.data = None
        assert climate_entity.hvac_action == HVACAction.OFF

    def test_hvac_action_off_when_not_heating(self, climate_entity, mock_coordinator):
        """Test HVAC action is OFF when not heating and stage not 0."""
        mock_coordinator.data = {"heating": False, "stage": 2}
        assert climate_entity.hvac_action == HVACAction.OFF

    def test_preset_mode_boil(self, climate_entity, mock_coordinator):
        """Test preset mode is boil."""
        mock_coordinator.data = {"mode": MODE_BOIL}
        assert climate_entity.preset_mode == PRESET_BOIL

    def test_preset_mode_green_tea(self, climate_entity, mock_coordinator):
        """Test preset mode is green_tea."""
        mock_coordinator.data = {"mode": MODE_GREEN_TEA}
        assert climate_entity.preset_mode == PRESET_GREEN_TEA

    def test_preset_mode_oolong(self, climate_entity, mock_coordinator):
        """Test preset mode is oolong."""
        mock_coordinator.data = {"mode": MODE_OOLONG}
        assert climate_entity.preset_mode == PRESET_OOLONG

    def test_preset_mode_coffee(self, climate_entity, mock_coordinator):
        """Test preset mode is coffee."""
        mock_coordinator.data = {"mode": MODE_COFFEE}
        assert climate_entity.preset_mode == PRESET_COFFEE

    def test_preset_mode_none_for_unknown_mode(self, climate_entity, mock_coordinator):
        """Test preset mode is None for unknown mode."""
        mock_coordinator.data = {"mode": 0xFF}
        assert climate_entity.preset_mode is None

    def test_preset_mode_none_when_no_data(self, climate_entity, mock_coordinator):
        """Test preset mode is None when no coordinator data."""
        mock_coordinator.data = None
        assert climate_entity.preset_mode is None


class TestCosoriKettleClimateSetTemperature:
    """Test async_set_temperature method."""

    @pytest.mark.asyncio
    async def test_set_temperature_calls_coordinator(self, climate_entity, mock_coordinator):
        """Test setting temperature calls coordinator method."""
        await climate_entity.async_set_temperature(temperature=180)

        mock_coordinator.async_set_mode.assert_called_once_with(MODE_MY_TEMP, 180, 0)
        mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_temperature_converts_to_int(self, climate_entity, mock_coordinator):
        """Test temperature is converted to int."""
        await climate_entity.async_set_temperature(temperature=180.9)

        mock_coordinator.async_set_mode.assert_called_once_with(MODE_MY_TEMP, 180, 0)

    @pytest.mark.asyncio
    async def test_set_temperature_missing_temperature_kwarg(self, climate_entity, mock_coordinator):
        """Test that missing temperature kwarg doesn't call coordinator."""
        await climate_entity.async_set_temperature()

        mock_coordinator.async_set_mode.assert_not_called()
        mock_coordinator.async_request_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_temperature_min_value(self, climate_entity, mock_coordinator):
        """Test setting minimum temperature."""
        await climate_entity.async_set_temperature(temperature=MIN_TEMP_F)

        mock_coordinator.async_set_mode.assert_called_once_with(MODE_MY_TEMP, MIN_TEMP_F, 0)

    @pytest.mark.asyncio
    async def test_set_temperature_max_value(self, climate_entity, mock_coordinator):
        """Test setting maximum temperature."""
        await climate_entity.async_set_temperature(temperature=MAX_TEMP_F)

        mock_coordinator.async_set_mode.assert_called_once_with(MODE_MY_TEMP, MAX_TEMP_F, 0)


class TestCosoriKettleClimateSetHVACMode:
    """Test async_set_hvac_mode method."""

    @pytest.mark.asyncio
    async def test_set_hvac_mode_off(self, climate_entity, mock_coordinator):
        """Test setting HVAC mode to OFF."""
        await climate_entity.async_set_hvac_mode(HVACMode.OFF)

        mock_coordinator.async_stop_heating.assert_called_once()
        mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_hvac_mode_heat(self, climate_entity, mock_coordinator):
        """Test setting HVAC mode to HEAT."""
        mock_coordinator.data = {"my_temp": 180}
        await climate_entity.async_set_hvac_mode(HVACMode.HEAT)

        mock_coordinator.async_set_mode.assert_called_once_with(MODE_MY_TEMP, 180, 0)
        mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_hvac_mode_heat_uses_default_temp_when_no_data(
        self, climate_entity, mock_coordinator
    ):
        """Test that HEAT mode uses default 212F when no my_temp in data."""
        mock_coordinator.data = None
        await climate_entity.async_set_hvac_mode(HVACMode.HEAT)

        mock_coordinator.async_set_mode.assert_called_once_with(MODE_MY_TEMP, 212, 0)

    @pytest.mark.asyncio
    async def test_set_hvac_mode_heat_uses_default_temp_when_missing(
        self, climate_entity, mock_coordinator
    ):
        """Test that HEAT mode uses default 212F when my_temp missing from data."""
        mock_coordinator.data = {"temperature": 75}
        await climate_entity.async_set_hvac_mode(HVACMode.HEAT)

        mock_coordinator.async_set_mode.assert_called_once_with(MODE_MY_TEMP, 212, 0)

    @pytest.mark.asyncio
    async def test_set_hvac_mode_heat_with_my_temp_data(self, climate_entity, mock_coordinator):
        """Test that HEAT mode uses my_temp from coordinator data."""
        mock_coordinator.data = {"my_temp": 195}
        await climate_entity.async_set_hvac_mode(HVACMode.HEAT)

        mock_coordinator.async_set_mode.assert_called_once_with(MODE_MY_TEMP, 195, 0)


class TestCosoriKettleClimateSetPresetMode:
    """Test async_set_preset_mode method."""

    @pytest.mark.asyncio
    async def test_set_preset_mode_boil(self, climate_entity, mock_coordinator):
        """Test setting preset mode to boil."""
        await climate_entity.async_set_preset_mode(PRESET_BOIL)

        mock_coordinator.async_set_mode.assert_called_once_with(MODE_BOIL, 212, 0)
        mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_preset_mode_green_tea(self, climate_entity, mock_coordinator):
        """Test setting preset mode to green_tea."""
        await climate_entity.async_set_preset_mode(PRESET_GREEN_TEA)

        mock_coordinator.async_set_mode.assert_called_once_with(MODE_GREEN_TEA, 180, 0)
        mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_preset_mode_oolong(self, climate_entity, mock_coordinator):
        """Test setting preset mode to oolong."""
        await climate_entity.async_set_preset_mode(PRESET_OOLONG)

        mock_coordinator.async_set_mode.assert_called_once_with(MODE_OOLONG, 195, 0)
        mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_preset_mode_coffee(self, climate_entity, mock_coordinator):
        """Test setting preset mode to coffee."""
        await climate_entity.async_set_preset_mode(PRESET_COFFEE)

        mock_coordinator.async_set_mode.assert_called_once_with(MODE_COFFEE, 205, 0)
        mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_preset_mode_invalid(self, climate_entity, mock_coordinator):
        """Test that invalid preset mode doesn't call coordinator."""
        await climate_entity.async_set_preset_mode("invalid_preset")

        mock_coordinator.async_set_mode.assert_not_called()
        mock_coordinator.async_request_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_preset_mode_empty_string(self, climate_entity, mock_coordinator):
        """Test that empty preset mode string doesn't call coordinator."""
        await climate_entity.async_set_preset_mode("")

        mock_coordinator.async_set_mode.assert_not_called()
        mock_coordinator.async_request_refresh.assert_not_called()


class TestCosoriKettleClimateTurnOnOff:
    """Test async_turn_on and async_turn_off methods."""

    @pytest.mark.asyncio
    async def test_turn_on(self, climate_entity, mock_coordinator):
        """Test turn on calls set hvac mode to HEAT."""
        mock_coordinator.data = {"my_temp": 180}
        await climate_entity.async_turn_on()

        mock_coordinator.async_set_mode.assert_called_once_with(MODE_MY_TEMP, 180, 0)
        mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_turn_off(self, climate_entity, mock_coordinator):
        """Test turn off calls set hvac mode to OFF."""
        await climate_entity.async_turn_off()

        mock_coordinator.async_stop_heating.assert_called_once()
        mock_coordinator.async_request_refresh.assert_called_once()


class TestCosoriKettleClimateCoordinatorDataUpdates:
    """Test that coordinator data updates reflect in entity state."""

    def test_current_temperature_updates_from_coordinator(
        self, climate_entity, mock_coordinator
    ):
        """Test current temperature reflects coordinator data changes."""
        mock_coordinator.data = {"temperature": 100.0}
        assert climate_entity.current_temperature == 100.0

        mock_coordinator.data = {"temperature": 150.0}
        assert climate_entity.current_temperature == 150.0

    def test_target_temperature_updates_from_coordinator(
        self, climate_entity, mock_coordinator
    ):
        """Test target temperature reflects coordinator data changes."""
        mock_coordinator.data = {"setpoint": 180}
        assert climate_entity.target_temperature == 180

        mock_coordinator.data = {"setpoint": 205}
        assert climate_entity.target_temperature == 205

    def test_hvac_mode_updates_from_coordinator(self, climate_entity, mock_coordinator):
        """Test HVAC mode reflects coordinator data changes."""
        mock_coordinator.data = {"heating": True}
        assert climate_entity.hvac_mode == HVACMode.HEAT

        mock_coordinator.data = {"heating": False}
        assert climate_entity.hvac_mode == HVACMode.OFF

    def test_hvac_action_updates_from_coordinator(self, climate_entity, mock_coordinator):
        """Test HVAC action reflects coordinator data changes."""
        mock_coordinator.data = {"heating": True, "stage": 2}
        assert climate_entity.hvac_action == HVACAction.HEATING

        mock_coordinator.data = {"heating": False, "stage": 0}
        assert climate_entity.hvac_action == HVACAction.IDLE

        mock_coordinator.data = {"heating": False, "stage": 1}
        assert climate_entity.hvac_action == HVACAction.OFF

    def test_preset_mode_updates_from_coordinator(self, climate_entity, mock_coordinator):
        """Test preset mode reflects coordinator data changes."""
        mock_coordinator.data = {"mode": MODE_BOIL}
        assert climate_entity.preset_mode == PRESET_BOIL

        mock_coordinator.data = {"mode": MODE_GREEN_TEA}
        assert climate_entity.preset_mode == PRESET_GREEN_TEA

        mock_coordinator.data = {"mode": MODE_OOLONG}
        assert climate_entity.preset_mode == PRESET_OOLONG

        mock_coordinator.data = {"mode": MODE_COFFEE}
        assert climate_entity.preset_mode == PRESET_COFFEE


class TestCosoriKettleClimatePresetMappings:
    """Test preset to mode mappings are correct."""

    def test_preset_to_mode_mapping(self):
        """Test all preset to mode mappings."""
        assert PRESET_TO_MODE[PRESET_BOIL] == MODE_BOIL
        assert PRESET_TO_MODE[PRESET_GREEN_TEA] == MODE_GREEN_TEA
        assert PRESET_TO_MODE[PRESET_OOLONG] == MODE_OOLONG
        assert PRESET_TO_MODE[PRESET_COFFEE] == MODE_COFFEE

    def test_mode_to_preset_mapping(self):
        """Test all mode to preset mappings are inverse of preset to mode."""
        assert MODE_TO_PRESET[MODE_BOIL] == PRESET_BOIL
        assert MODE_TO_PRESET[MODE_GREEN_TEA] == PRESET_GREEN_TEA
        assert MODE_TO_PRESET[MODE_OOLONG] == PRESET_OOLONG
        assert MODE_TO_PRESET[MODE_COFFEE] == PRESET_COFFEE

    def test_preset_mode_mappings_are_inverse(self):
        """Test that preset to mode and mode to preset are inverses."""
        for preset, mode in PRESET_TO_MODE.items():
            assert MODE_TO_PRESET[mode] == preset


class TestCosoriKettleClimateConstants:
    """Test climate entity constants are correct."""

    def test_preset_constants(self):
        """Test preset mode constants are correctly defined."""
        assert PRESET_BOIL == "boil"
        assert PRESET_GREEN_TEA == "green_tea"
        assert PRESET_OOLONG == "oolong"
        assert PRESET_COFFEE == "coffee"

    def test_all_presets_in_entity_preset_modes(self, climate_entity):
        """Test all preset constants are in entity's preset modes."""
        presets = [PRESET_BOIL, PRESET_GREEN_TEA, PRESET_OOLONG, PRESET_COFFEE]
        for preset in presets:
            assert preset in climate_entity._attr_preset_modes


class TestCosoriKettleClimateEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_set_temperature_with_none_value(self, climate_entity, mock_coordinator):
        """Test setting temperature to None doesn't call coordinator."""
        await climate_entity.async_set_temperature(temperature=None)

        mock_coordinator.async_set_mode.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_temperature_with_zero(self, climate_entity, mock_coordinator):
        """Test setting temperature to zero calls coordinator with 0."""
        await climate_entity.async_set_temperature(temperature=0)

        mock_coordinator.async_set_mode.assert_called_once_with(MODE_MY_TEMP, 0, 0)

    @pytest.mark.asyncio
    async def test_multiple_set_temperature_calls(self, climate_entity, mock_coordinator):
        """Test multiple temperature changes work correctly."""
        await climate_entity.async_set_temperature(temperature=180)
        await climate_entity.async_set_temperature(temperature=200)
        await climate_entity.async_set_temperature(temperature=212)

        assert mock_coordinator.async_set_mode.call_count == 3
        assert mock_coordinator.async_request_refresh.call_count == 3

    @pytest.mark.asyncio
    async def test_set_hvac_mode_multiple_times(self, climate_entity, mock_coordinator):
        """Test setting HVAC mode multiple times."""
        mock_coordinator.data = {"my_temp": 180}

        await climate_entity.async_set_hvac_mode(HVACMode.HEAT)
        await climate_entity.async_set_hvac_mode(HVACMode.OFF)
        await climate_entity.async_set_hvac_mode(HVACMode.HEAT)

        assert mock_coordinator.async_set_mode.call_count == 2
        assert mock_coordinator.async_stop_heating.call_count == 1
        assert mock_coordinator.async_request_refresh.call_count == 3

    @pytest.mark.asyncio
    async def test_set_preset_mode_sequence(self, climate_entity, mock_coordinator):
        """Test setting preset modes in sequence."""
        await climate_entity.async_set_preset_mode(PRESET_BOIL)
        await climate_entity.async_set_preset_mode(PRESET_GREEN_TEA)
        await climate_entity.async_set_preset_mode(PRESET_OOLONG)
        await climate_entity.async_set_preset_mode(PRESET_COFFEE)

        assert mock_coordinator.async_set_mode.call_count == 4
        assert mock_coordinator.async_request_refresh.call_count == 4

        # Verify correct modes were set
        calls = mock_coordinator.async_set_mode.call_args_list
        assert calls[0][0] == (MODE_BOIL, 212, 0)
        assert calls[1][0] == (MODE_GREEN_TEA, 180, 0)
        assert calls[2][0] == (MODE_OOLONG, 195, 0)
        assert calls[3][0] == (MODE_COFFEE, 205, 0)
