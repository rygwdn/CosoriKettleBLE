"""Number platform for Cosori Kettle BLE."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CosoriKettleCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CosoriKettleNumberEntityDescription(NumberEntityDescription):
    """Describes Cosori Kettle number entity."""

    value_fn: Callable[[CosoriKettleCoordinator], float | None] | None = None
    set_value_fn: Callable[[CosoriKettleCoordinator, float], Any] | None = None


NUMBERS: tuple[CosoriKettleNumberEntityDescription, ...] = (
    CosoriKettleNumberEntityDescription(
        key="hold_time",
        name="Hold Time",
        native_min_value=0,
        native_max_value=60,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode=NumberMode.SLIDER,
        value_fn=lambda coord: coord.desired_hold_time_minutes,
        set_value_fn=lambda coord, val: coord.async_set_desired_hold_time(val),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number platform."""
    coordinator: CosoriKettleCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        CosoriKettleNumber(coordinator, description)
        for description in NUMBERS
    )


class CosoriKettleNumber(CoordinatorEntity[CosoriKettleCoordinator], NumberEntity):
    """Number entity for Cosori Kettle."""

    entity_description: CosoriKettleNumberEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CosoriKettleCoordinator,
        description: CosoriKettleNumberEntityDescription,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.formatted_address}_{description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if self.entity_description.value_fn:
            return self.entity_description.value_fn(self.coordinator)
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        if self.entity_description.set_value_fn:
            await self.entity_description.set_value_fn(self.coordinator, value)
