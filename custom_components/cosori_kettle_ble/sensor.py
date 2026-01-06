"""Sensor platform for Cosori Kettle BLE."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODE_NAMES
from .coordinator import CosoriKettleCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CosoriKettleSensorEntityDescription(SensorEntityDescription):
    """Describes Cosori Kettle sensor entity."""

    value_fn: Callable[[dict], any] | None = None


SENSORS: tuple[CosoriKettleSensorEntityDescription, ...] = (
    CosoriKettleSensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data: data.get("temperature"),
    ),
    CosoriKettleSensorEntityDescription(
        key="setpoint",
        name="Target Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data: data.get("setpoint"),
    ),
    CosoriKettleSensorEntityDescription(
        key="my_temp",
        name="My Temp Setting",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data: data.get("my_temp"),
    ),
    CosoriKettleSensorEntityDescription(
        key="mode",
        name="Mode",
        value_fn=lambda data: MODE_NAMES.get(data.get("mode"), "Unknown"),
    ),
    CosoriKettleSensorEntityDescription(
        key="remaining_hold_time",
        name="Remaining Hold Time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda data: data.get("remaining_hold_time"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator: CosoriKettleCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        CosoriKettleSensor(coordinator, entry, description)
        for description in SENSORS
    )


class CosoriKettleSensor(CoordinatorEntity[CosoriKettleCoordinator], SensorEntity):
    """Sensor entity for Cosori Kettle."""

    entity_description: CosoriKettleSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CosoriKettleCoordinator,
        entry: ConfigEntry,
        description: CosoriKettleSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
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
    def native_value(self) -> any:
        """Return the state of the sensor."""
        if self.coordinator.data and self.entity_description.value_fn:
            return self.entity_description.value_fn(self.coordinator.data)
        return None
