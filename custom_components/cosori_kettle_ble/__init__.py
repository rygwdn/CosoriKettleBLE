"""The Cosori Kettle BLE integration."""
from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import CONF_DEVICE_ID, CONF_REGISTRATION_KEY, DOMAIN
from .coordinator import CosoriKettleCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Cosori Kettle BLE from a config entry."""
    device_id = entry.data[CONF_DEVICE_ID]
    address = device_id  # MAC address

    # Get registration key from config entry
    registration_key_hex = entry.data.get(CONF_REGISTRATION_KEY)
    if not registration_key_hex:
        # Migration case: old entries don't have key
        _LOGGER.error(
            "No registration key found in config entry. "
            "Please remove and re-add this device."
        )
        raise ConfigEntryNotReady(
            "Registration key missing. Please reconfigure the device."
        )

    try:
        registration_key = bytes.fromhex(registration_key_hex)
    except ValueError:
        _LOGGER.error("Invalid registration key format in config entry")
        raise ConfigEntryNotReady("Invalid registration key format")

    # Get BLE device
    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise ConfigEntryNotReady(f"Could not find Cosori Kettle with address {address}")

    # Create coordinator with registration key
    coordinator = CosoriKettleCoordinator(hass, ble_device, registration_key)

    # Start coordinator
    try:
        await coordinator.async_start()
    except ConfigEntryAuthFailed:
        # Key is invalid - requires reconfiguration
        raise
    except Exception as err:
        _LOGGER.error("Failed to start coordinator: %s", err)
        raise ConfigEntryNotReady(f"Failed to connect to device: {err}") from err

    # Store coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Forward to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Stop coordinator
        coordinator: CosoriKettleCoordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.async_stop()

        # Remove from hass.data
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
