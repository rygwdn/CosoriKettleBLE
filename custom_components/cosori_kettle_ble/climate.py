"""Climate platform for Cosori Kettle BLE."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MAX_TEMP_F,
    MIN_TEMP_F,
    MODE_BOIL,
    MODE_COFFEE,
    MODE_GREEN_TEA,
    MODE_HEAT,
    MODE_MY_TEMP,
    MODE_NAMES,
    MODE_OOLONG,
)
from .coordinator import CosoriKettleCoordinator

_LOGGER = logging.getLogger(__name__)

# Custom HVAC modes for different heating modes
# We'll use custom modes since Home Assistant doesn't have built-in modes for these
HVAC_MODE_BOIL = "boil"
HVAC_MODE_GREEN_TEA = "green_tea"
HVAC_MODE_OOLONG = "oolong"
HVAC_MODE_COFFEE = "coffee"
HVAC_MODE_MY_TEMP = "my_temp"

HVAC_MODE_TO_KETTLE_MODE = {
    HVAC_MODE_BOIL: MODE_BOIL,
    HVAC_MODE_GREEN_TEA: MODE_GREEN_TEA,
    HVAC_MODE_OOLONG: MODE_OOLONG,
    HVAC_MODE_COFFEE: MODE_COFFEE,
    HVAC_MODE_MY_TEMP: MODE_MY_TEMP,
}

KETTLE_MODE_TO_HVAC_MODE = {v: k for k, v in HVAC_MODE_TO_KETTLE_MODE.items()}

# Temperature for each mode (in Fahrenheit)
MODE_TEMPS = {
    MODE_BOIL: 212,
    MODE_GREEN_TEA: 180,
    MODE_OOLONG: 195,
    MODE_COFFEE: 205,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate platform."""
    coordinator: CosoriKettleCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CosoriKettleClimate(coordinator)])


class CosoriKettleClimate(CoordinatorEntity[CosoriKettleCoordinator], ClimateEntity):
    """Climate entity for Cosori Kettle."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_hvac_modes = [
        HVACMode.OFF,
        HVAC_MODE_BOIL,
        HVAC_MODE_GREEN_TEA,
        HVAC_MODE_OOLONG,
        HVAC_MODE_COFFEE,
        HVAC_MODE_MY_TEMP,
    ]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_min_temp = MIN_TEMP_F
    _attr_max_temp = MAX_TEMP_F
    _attr_target_temperature_step = 1
    _attr_precision = 1.0
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: CosoriKettleCoordinator,
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator)

        self._attr_unique_id = f"{coordinator.formatted_address}_climate"
        self._attr_device_info = coordinator.device_info

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if self.coordinator.data:
            return self.coordinator.data.get("temperature")
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        if self.coordinator.data:
            return self.coordinator.data.get("setpoint")
        return None

    @property
    def hvac_mode(self) -> str:
        """Return current HVAC mode."""
        if not self.coordinator.data:
            return HVACMode.OFF

        # If not heating, return OFF
        if not self.coordinator.data.get("heating"):
            return HVACMode.OFF

        # Map the kettle mode to HVAC mode
        kettle_mode = self.coordinator.data.get("mode")
        return KETTLE_MODE_TO_HVAC_MODE.get(kettle_mode, HVAC_MODE_MY_TEMP)

    @property
    def hvac_action(self) -> HVACAction:
        """Return current HVAC action."""
        if self.coordinator.data:
            if self.coordinator.data.get("heating"):
                return HVACAction.HEATING
            if self.coordinator.data.get("stage") == 0:
                return HVACAction.IDLE
        return HVACAction.OFF

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature.

        If the temperature is within 1 degree C (~2 deg F) of a preset mode,
        use that mode. Otherwise use MY_TEMP mode.
        """
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        temp_f = int(temperature)

        # Find the closest mode temperature within 2 degrees F (approximately 1 degree C)
        mode = MODE_MY_TEMP
        for kettle_mode, preset_temp in MODE_TEMPS.items():
            if abs(temp_f - preset_temp) <= 2:
                mode = kettle_mode
                temp_f = preset_temp  # Use the exact preset temperature
                break

        await self.coordinator.async_set_mode(mode, temp_f, 0)
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Set HVAC mode."""
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_stop_heating()
        elif hvac_mode in HVAC_MODE_TO_KETTLE_MODE:
            # Get the kettle mode
            kettle_mode = HVAC_MODE_TO_KETTLE_MODE[hvac_mode]

            # Get the temperature for this mode
            if kettle_mode in MODE_TEMPS:
                temp_f = MODE_TEMPS[kettle_mode]
            else:
                # MY_TEMP mode - use current my_temp or default
                temp_f = self.coordinator.data.get("my_temp", 212) if self.coordinator.data else 212

            await self.coordinator.async_set_mode(kettle_mode, temp_f, 0)

        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        """Turn on."""
        await self.async_set_hvac_mode(HVAC_MODE_MY_TEMP)

    async def async_turn_off(self) -> None:
        """Turn off."""
        await self.async_set_hvac_mode(HVACMode.OFF)
