"""Switch platform for Cosori Kettle BLE."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CosoriKettleCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CosoriKettleSwitchEntityDescription(SwitchEntityDescription):
    """Describes Cosori Kettle switch entity."""

    value_fn: Callable[[dict], bool] | None = None
    turn_on_fn: Callable[[CosoriKettleCoordinator], Any] | None = None
    turn_off_fn: Callable[[CosoriKettleCoordinator], Any] | None = None


SWITCHES: tuple[CosoriKettleSwitchEntityDescription, ...] = (
    CosoriKettleSwitchEntityDescription(
        key="baby_formula",
        name="Baby Formula Mode",
        value_fn=lambda data: data.get("baby_formula_enabled", False),
        turn_on_fn=lambda coord: coord.async_set_baby_formula(True),
        turn_off_fn=lambda coord: coord.async_set_baby_formula(False),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    coordinator: CosoriKettleCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        CosoriKettleSwitch(coordinator, entry, description)
        for description in SWITCHES
    )


class CosoriKettleSwitch(CoordinatorEntity[CosoriKettleCoordinator], SwitchEntity):
    """Switch entity for Cosori Kettle."""

    entity_description: CosoriKettleSwitchEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CosoriKettleCoordinator,
        entry: ConfigEntry,
        description: CosoriKettleSwitchEntityDescription,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Cosori Kettle",
            "manufacturer": coordinator.manufacturer or "Cosori",
            "model": coordinator.model_number or "Smart Kettle",
            "hw_version": coordinator.hardware_version,
            "sw_version": coordinator.software_version,
        }

    @property
    def is_on(self) -> bool:
        """Return the state of the switch."""
        if self.coordinator.data and self.entity_description.value_fn:
            return self.entity_description.value_fn(self.coordinator.data)
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        if self.entity_description.turn_on_fn:
            await self.entity_description.turn_on_fn(self.coordinator)
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        if self.entity_description.turn_off_fn:
            await self.entity_description.turn_off_fn(self.coordinator)
            await self.coordinator.async_request_refresh()
