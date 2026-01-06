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

# Preset modes
PRESET_BOIL = "boil"
PRESET_GREEN_TEA = "green_tea"
PRESET_OOLONG = "oolong"
PRESET_COFFEE = "coffee"

PRESET_TO_MODE = {
    PRESET_BOIL: MODE_BOIL,
    PRESET_GREEN_TEA: MODE_GREEN_TEA,
    PRESET_OOLONG: MODE_OOLONG,
    PRESET_COFFEE: MODE_COFFEE,
}

MODE_TO_PRESET = {v: k for k, v in PRESET_TO_MODE.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate platform."""
    coordinator: CosoriKettleCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CosoriKettleClimate(coordinator, entry)])


class CosoriKettleClimate(CoordinatorEntity[CosoriKettleCoordinator], ClimateEntity):
    """Climate entity for Cosori Kettle."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = [PRESET_BOIL, PRESET_GREEN_TEA, PRESET_OOLONG, PRESET_COFFEE]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_min_temp = MIN_TEMP_F
    _attr_max_temp = MAX_TEMP_F
    _attr_target_temperature_step = 1

    def __init__(
        self,
        coordinator: CosoriKettleCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_climate"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Cosori Kettle",
            "manufacturer": coordinator.manufacturer or "Cosori",
            "model": coordinator.model_number or "Smart Kettle",
            "hw_version": coordinator.hardware_version,
            "sw_version": coordinator.software_version,
        }
        self._preset_mode = None

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
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        if self.coordinator.data and self.coordinator.data.get("heating"):
            return HVACMode.HEAT
        return HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        """Return current HVAC action."""
        if self.coordinator.data:
            if self.coordinator.data.get("heating"):
                return HVACAction.HEATING
            if self.coordinator.data.get("stage") == 0:
                return HVACAction.IDLE
        return HVACAction.OFF

    @property
    def preset_mode(self) -> str | None:
        """Return current preset mode."""
        if self.coordinator.data:
            mode = self.coordinator.data.get("mode")
            return MODE_TO_PRESET.get(mode)
        return None

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        temp_f = int(temperature)
        await self.coordinator.async_set_mode(MODE_MY_TEMP, temp_f, 0)
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_stop_heating()
        elif hvac_mode == HVACMode.HEAT:
            # Start heating to current my_temp or default
            temp_f = self.coordinator.data.get("my_temp", 212) if self.coordinator.data else 212
            await self.coordinator.async_set_mode(MODE_MY_TEMP, temp_f, 0)

        await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode."""
        if preset_mode not in PRESET_TO_MODE:
            return

        mode = PRESET_TO_MODE[preset_mode]

        # Get default temperature for mode
        if mode == MODE_BOIL:
            temp_f = 212
        elif mode == MODE_GREEN_TEA:
            temp_f = 180
        elif mode == MODE_OOLONG:
            temp_f = 195
        elif mode == MODE_COFFEE:
            temp_f = 205
        else:
            temp_f = 212

        await self.coordinator.async_set_mode(mode, temp_f, 0)
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        """Turn on."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Turn off."""
        await self.async_set_hvac_mode(HVACMode.OFF)
