"""Binary sensor platform for Cosori Kettle BLE."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CosoriKettleCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CosoriKettleBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes Cosori Kettle binary sensor entity."""

    value_fn: Callable[[dict], bool] | None = None


BINARY_SENSORS: tuple[CosoriKettleBinarySensorEntityDescription, ...] = (
    CosoriKettleBinarySensorEntityDescription(
        key="on_base",
        name="On Base",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda data: data.get("on_base", False),
    ),
    CosoriKettleBinarySensorEntityDescription(
        key="heating",
        name="Heating",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda data: data.get("heating", False),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator: CosoriKettleCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        CosoriKettleBinarySensor(coordinator, entry, description)
        for description in BINARY_SENSORS
    )


class CosoriKettleBinarySensor(CoordinatorEntity[CosoriKettleCoordinator], BinarySensorEntity):
    """Binary sensor entity for Cosori Kettle."""

    entity_description: CosoriKettleBinarySensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CosoriKettleCoordinator,
        entry: ConfigEntry,
        description: CosoriKettleBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
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
        """Return the state of the binary sensor."""
        if self.coordinator.data and self.entity_description.value_fn:
            return self.entity_description.value_fn(self.coordinator.data)
        return False
