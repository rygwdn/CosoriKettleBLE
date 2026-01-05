"""Config flow for Cosori Kettle BLE integration."""
from __future__ import annotations

import logging
import secrets
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_DEVICE_ID, CONF_REGISTRATION_KEY, DOMAIN, SERVICE_UUID
from .cosori_kettle.exceptions import (
    DeviceNotInPairingModeError,
    InvalidRegistrationKeyError,
)
from .cosori_kettle.kettle import CosoriKettle

_LOGGER = logging.getLogger(__name__)


class CosoriKettleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Cosori Kettle BLE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}
        self._selected_address: str | None = None
        self._pairing_mode: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info

        # Check if device has our service
        if SERVICE_UUID.lower() not in [
            str(uuid).lower() for uuid in discovery_info.service_uuids
        ]:
            return self.async_abort(reason="not_supported")

        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle user confirmation of discovered device."""
        assert self._discovery_info is not None

        if user_input is not None:
            # Store address and move to pairing step
            self._selected_address = self._discovery_info.address
            return await self.async_step_pairing_mode()

        self._set_confirm_only()

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._discovery_info.name or "Cosori Kettle",
                "address": self._discovery_info.address,
            },
        )

    async def async_step_pairing_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask user if they have an existing key or want to pair."""
        if user_input is not None:
            self._pairing_mode = user_input["pairing_mode"]

            if self._pairing_mode == "new":
                return await self.async_step_pair_device()
            else:
                return await self.async_step_enter_key()

        return self.async_show_form(
            step_id="pairing_mode",
            data_schema=vol.Schema(
                {
                    vol.Required("pairing_mode"): vol.In(
                        {
                            "new": "Pair a new device (device must be in pairing mode)",
                            "existing": "I have an existing registration key",
                        }
                    ),
                }
            ),
            description_placeholders={
                "name": (
                    self._discovery_info.name or "Cosori Kettle"
                    if self._discovery_info
                    else "Cosori Kettle"
                ),
            },
        )

    async def async_step_pair_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pair with a new device by generating and registering a key."""
        errors = {}

        if user_input is not None:
            assert self._selected_address is not None

            # Generate random 16-byte registration key
            registration_key = secrets.token_bytes(16)

            # Get BLE device
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self._selected_address, connectable=True
            )

            if ble_device is None:
                return self.async_abort(reason="device_not_found")

            # Attempt pairing
            try:
                async with CosoriKettle(ble_device, registration_key) as kettle:
                    await kettle.pair()  # Sends register + hello

                # Success! Create config entry
                return self.async_create_entry(
                    title=self._discovery_info.name or "Cosori Kettle"
                    if self._discovery_info
                    else "Cosori Kettle",
                    data={
                        CONF_DEVICE_ID: self._selected_address,
                        CONF_ADDRESS: self._selected_address,
                        CONF_REGISTRATION_KEY: registration_key.hex(),
                    },
                )

            except DeviceNotInPairingModeError:
                errors["base"] = "device_not_in_pairing_mode"
            except Exception as err:
                _LOGGER.exception("Failed to pair device: %s", err)
                errors["base"] = "pairing_failed"

        return self.async_show_form(
            step_id="pair_device",
            errors=errors,
            description_placeholders={
                "name": (
                    self._discovery_info.name or "Cosori Kettle"
                    if self._discovery_info
                    else "Cosori Kettle"
                ),
            },
        )

    async def async_step_enter_key(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Allow user to enter existing registration key."""
        errors = {}

        if user_input is not None:
            assert self._selected_address is not None

            registration_key_hex = user_input["registration_key"].strip().replace(" ", "")

            # Validate format
            if len(registration_key_hex) != 32:
                errors["registration_key"] = "invalid_key_length"
            else:
                try:
                    registration_key = bytes.fromhex(registration_key_hex)
                except ValueError:
                    errors["registration_key"] = "invalid_key_format"
                else:
                    # Get BLE device
                    ble_device = bluetooth.async_ble_device_from_address(
                        self.hass, self._selected_address, connectable=True
                    )

                    if ble_device is None:
                        return self.async_abort(reason="device_not_found")

                    # Test key by connecting
                    try:
                        async with CosoriKettle(ble_device, registration_key) as kettle:
                            # connect() calls _send_hello() which validates key
                            pass  # If we get here, key is valid

                        # Success! Create config entry
                        return self.async_create_entry(
                            title=self._discovery_info.name or "Cosori Kettle"
                            if self._discovery_info
                            else "Cosori Kettle",
                            data={
                                CONF_DEVICE_ID: self._selected_address,
                                CONF_ADDRESS: self._selected_address,
                                CONF_REGISTRATION_KEY: registration_key_hex,
                            },
                        )

                    except InvalidRegistrationKeyError:
                        errors["registration_key"] = "invalid_key"
                    except Exception as err:
                        _LOGGER.exception("Failed to validate key: %s", err)
                        errors["base"] = "connection_failed"

        return self.async_show_form(
            step_id="enter_key",
            data_schema=vol.Schema(
                {
                    vol.Required("registration_key"): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "name": (
                    self._discovery_info.name or "Cosori Kettle"
                    if self._discovery_info
                    else "Cosori Kettle"
                ),
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the user step to pick discovered device."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()

            self._discovery_info = self._discovered_devices[address]
            self._selected_address = address

            # Go to pairing mode selection
            return await self.async_step_pairing_mode()

        # Scan for devices
        current_addresses = self._async_current_ids()
        discovered = await bluetooth.async_discovered_service_info(self.hass)

        self._discovered_devices = {}
        for info in discovered:
            if info.address in current_addresses:
                continue
            if SERVICE_UUID.lower() in [str(uuid).lower() for uuid in info.service_uuids]:
                self._discovered_devices[info.address] = info

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS): vol.In({
                    address: f"{info.name or 'Cosori Kettle'} ({address})"
                    for address, info in self._discovered_devices.items()
                }),
            }),
        )
