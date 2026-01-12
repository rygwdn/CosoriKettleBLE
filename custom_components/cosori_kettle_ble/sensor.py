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
from homeassistant.helpers.device_registry import (
    CONNECTION_BLUETOOTH,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODE_NAMES
from .coordinator import CosoriKettleCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CosoriKettleSensorEntityDescription(SensorEntityDescription):
    """Describes Cosori Kettle sensor entity."""

    value_fn: Callable[[dict], any] | None = None
    display_precision: int | None = None


def _get_heating_status(data: dict) -> str:
    """Get heating status based on stage.

    Stage values:
    - 0x00: Off
    - 0x01: Heating (actively heating to target temperature)
    - 0x02: Warming (maintaining temperature after reaching target)
    - 0x03: Holding (maintaining temperature with hold timer active)
    """
    stage = data.get("stage", 0)

    if stage == 0x00:
        return "Off"
    elif stage == 0x01:
        return "Heating"
    elif stage == 0x02:
        return "Warming"
    elif stage == 0x03:
        return "Holding"
    else:
        # Fallback for unknown stages
        return "Off"


SENSORS: tuple[CosoriKettleSensorEntityDescription, ...] = (
    CosoriKettleSensorEntityDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data: data.get("temperature"),
        suggested_display_precision=0,
    ),
    CosoriKettleSensorEntityDescription(
        key="setpoint",
        name="Target Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data: data.get("setpoint"),
        suggested_display_precision=0,
    ),
    CosoriKettleSensorEntityDescription(
        key="my_temp",
        name="My Temp Setting",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        value_fn=lambda data: data.get("my_temp"),
        suggested_display_precision=0,
    ),
    CosoriKettleSensorEntityDescription(
        key="heating_status",
        name="Heating Status",
        value_fn=_get_heating_status,
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
        _: ConfigEntry,
        description: CosoriKettleSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description

        formatted_mac = format_mac(coordinator.address)
        self._attr_unique_id = f"{formatted_mac}_{description.key}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, formatted_mac)},
            name="Cosori Kettle",
            manufacturer=coordinator.manufacturer or "Cosori",
            model=coordinator.model_number or "Smart Kettle",
            hw_version=coordinator.hardware_version,
            sw_version=coordinator.software_version,
            suggested_area="Kitchen",
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
        )

    @property
    def native_value(self) -> any:
        """Return the state of the sensor."""
        if self.coordinator.data and self.entity_description.value_fn:
            return self.entity_description.value_fn(self.coordinator.data)
        return None
