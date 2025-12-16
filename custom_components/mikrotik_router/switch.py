"""Support for the Mikrotik Router switches."""

from __future__ import annotations

from logging import getLogger
from collections.abc import Mapping
from typing import Any, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import MikrotikEntity, async_add_entities
from .helper import format_attribute
from .switch_types import (
    SENSOR_TYPES,
    SENSOR_SERVICES,
    DEVICE_ATTRIBUTES_IFACE_ETHER,
    DEVICE_ATTRIBUTES_IFACE_SFP,
    DEVICE_ATTRIBUTES_IFACE_WIRELESS,
)

_LOGGER = getLogger(__name__)


# ---------------------------
#   async_setup_entry
# ---------------------------
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    _async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry for component"""
    dispatcher = {
        "MikrotikSwitch": MikrotikSwitch,
        "MikrotikPortSwitch": MikrotikPortSwitch,
        "MikrotikNATSwitch": MikrotikNATSwitch,
        "MikrotikMangleSwitch": MikrotikMangleSwitch,
        "MikrotikFilterSwitch": MikrotikFilterSwitch,
        "MikrotikQueueSwitch": MikrotikQueueSwitch,
        "MikrotikKidcontrolPauseSwitch": MikrotikKidcontrolPauseSwitch,
    }
    await async_add_entities(hass, config_entry, dispatcher)


# ---------------------------
#   MikrotikSwitch
# ---------------------------
class MikrotikSwitch(MikrotikEntity, SwitchEntity, RestoreEntity):
    """Representation of a switch."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._optimistic_is_on: bool | None = None
        self._write_in_progress = False

    @property
    def is_on(self) -> bool:
        """Return true if device is on."""
        if self._optimistic_is_on is not None:
            return self._optimistic_is_on

        return self._data[self.entity_description.data_attribute]

    @property
    def icon(self) -> str:
        """Return the icon."""
        if self.is_on:
            return self.entity_description.icon_enabled
        else:
            return self.entity_description.icon_disabled

    def _set_optimistic_state(self, is_on: bool) -> None:
        self._optimistic_is_on = is_on
        self.async_write_ha_state()

    async def _async_write_and_refresh(
        self,
        *,
        path: str,
        param: str,
        value: Any,
        mod_param: str,
        mod_value: Any,
        optimistic_is_on: bool,
    ) -> None:
        if self._write_in_progress:
            return

        previous_state = self.is_on
        self._write_in_progress = True
        self._set_optimistic_state(optimistic_is_on)
        try:
            result = await self.coordinator.async_set_value(
                path, param, value, mod_param, mod_value
            )
            if result is False:
                self._set_optimistic_state(previous_state)
                return
        finally:
            self._write_in_progress = False

        await self.coordinator.async_request_refresh()
        self._optimistic_is_on = None
        self.async_write_ha_state()

    def turn_on(self, **kwargs: Any) -> None:
        """Required abstract method."""
        pass

    def turn_off(self, **kwargs: Any) -> None:
        """Required abstract method."""
        pass

    async def async_turn_on(self) -> None:
        """Turn on the switch."""
        if "write" not in self.coordinator.data["access"]:
            return

        path = self.entity_description.data_switch_path
        param = self.entity_description.data_reference
        value = self._data[self.entity_description.data_reference]
        mod_param = self.entity_description.data_switch_parameter
        await self._async_write_and_refresh(
            path=path,
            param=param,
            value=value,
            mod_param=mod_param,
            mod_value=False,
            optimistic_is_on=True,
        )

    async def async_turn_off(self) -> None:
        """Turn off the switch."""
        if "write" not in self.coordinator.data["access"]:
            return

        path = self.entity_description.data_switch_path
        param = self.entity_description.data_reference
        value = self._data[self.entity_description.data_reference]
        mod_param = self.entity_description.data_switch_parameter
        await self._async_write_and_refresh(
            path=path,
            param=param,
            value=value,
            mod_param=mod_param,
            mod_value=True,
            optimistic_is_on=False,
        )


# ---------------------------
#   MikrotikPortSwitch
# ---------------------------
class MikrotikPortSwitch(MikrotikSwitch):
    """Representation of a network port switch."""

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return the state attributes."""
        attributes = super().extra_state_attributes

        if self._data["type"] == "ether":
            for variable in DEVICE_ATTRIBUTES_IFACE_ETHER:
                if variable in self._data:
                    attributes[format_attribute(variable)] = self._data[variable]

            if "sfp-shutdown-temperature" in self._data:
                for variable in DEVICE_ATTRIBUTES_IFACE_SFP:
                    if variable in self._data:
                        attributes[format_attribute(variable)] = self._data[variable]

        elif self._data["type"] == "wlan":
            for variable in DEVICE_ATTRIBUTES_IFACE_WIRELESS:
                if variable in self._data:
                    attributes[format_attribute(variable)] = self._data[variable]

        return attributes

    @property
    def icon(self) -> str:
        """Return the icon."""
        if self._data["running"]:
            icon = self.entity_description.icon_enabled
        else:
            icon = self.entity_description.icon_disabled

        if not self.is_on:
            icon = "mdi:lan-disconnect"

        return icon

    async def async_turn_on(self) -> Optional[str]:
        """Turn on the switch."""
        if "write" not in self.coordinator.data["access"]:
            return

        path = self.entity_description.data_switch_path
        param = self.entity_description.data_reference
        if self._data["about"] == "managed by CAPsMAN":
            _LOGGER.error("Unable to enable %s, managed by CAPsMAN", self._data[param])
            return "managed by CAPsMAN"
        if "-" in self._data["port-mac-address"]:
            param = "name"
        value = self._data[self.entity_description.data_reference]
        mod_param = self.entity_description.data_switch_parameter
        if self._write_in_progress:
            return
        self._write_in_progress = True
        self._set_optimistic_state(True)
        try:
            await self.coordinator.async_set_value(path, param, value, mod_param, False)
            if "poe-out" in self._data and self._data["poe-out"] == "off":
                path = "/interface/ethernet"
                await self.coordinator.async_set_value(
                    path, param, value, "poe-out", "auto-on"
                )
        finally:
            self._write_in_progress = False

        await self.coordinator.async_request_refresh()
        self._optimistic_is_on = None
        self.async_write_ha_state()

    async def async_turn_off(self) -> Optional[str]:
        """Turn off the switch."""
        if "write" not in self.coordinator.data["access"]:
            return

        path = self.entity_description.data_switch_path
        param = self.entity_description.data_reference
        if self._data["about"] == "managed by CAPsMAN":
            _LOGGER.error("Unable to disable %s, managed by CAPsMAN", self._data[param])
            return "managed by CAPsMAN"
        if "-" in self._data["port-mac-address"]:
            param = "name"
        value = self._data[self.entity_description.data_reference]
        mod_param = self.entity_description.data_switch_parameter
        if self._write_in_progress:
            return
        self._write_in_progress = True
        self._set_optimistic_state(False)
        try:
            await self.coordinator.async_set_value(path, param, value, mod_param, True)
            if "poe-out" in self._data and self._data["poe-out"] == "auto-on":
                path = "/interface/ethernet"
                await self.coordinator.async_set_value(
                    path, param, value, "poe-out", "off"
                )
        finally:
            self._write_in_progress = False

        await self.coordinator.async_request_refresh()
        self._optimistic_is_on = None
        self.async_write_ha_state()


# ---------------------------
#   MikrotikNATSwitch
# ---------------------------
class MikrotikNATSwitch(MikrotikSwitch):
    """Representation of a NAT switch."""

    async def async_turn_on(self) -> None:
        """Turn on the switch."""
        if "write" not in self.coordinator.data["access"]:
            return

        path = self.entity_description.data_switch_path
        param = ".id"
        value = None
        for uid in self.coordinator.data["nat"]:
            if self.coordinator.data["nat"][uid]["uniq-id"] == (
                f"{self._data['chain']},{self._data['action']},{self._data['protocol']},"
                f"{self._data['in-interface']}:{self._data['dst-port']}-"
                f"{self._data['out-interface']}:{self._data['to-addresses']}:{self._data['to-ports']}"
            ):
                value = self.coordinator.data["nat"][uid][".id"]

        mod_param = self.entity_description.data_switch_parameter
        await self._async_write_and_refresh(
            path=path,
            param=param,
            value=value,
            mod_param=mod_param,
            mod_value=False,
            optimistic_is_on=True,
        )

    async def async_turn_off(self) -> None:
        """Turn off the switch."""
        if "write" not in self.coordinator.data["access"]:
            return

        path = self.entity_description.data_switch_path
        param = ".id"
        value = None
        for uid in self.coordinator.data["nat"]:
            if self.coordinator.data["nat"][uid]["uniq-id"] == (
                f"{self._data['chain']},{self._data['action']},{self._data['protocol']},"
                f"{self._data['in-interface']}:{self._data['dst-port']}-"
                f"{self._data['out-interface']}:{self._data['to-addresses']}:{self._data['to-ports']}"
            ):
                value = self.coordinator.data["nat"][uid][".id"]

        mod_param = self.entity_description.data_switch_parameter
        await self._async_write_and_refresh(
            path=path,
            param=param,
            value=value,
            mod_param=mod_param,
            mod_value=True,
            optimistic_is_on=False,
        )


# ---------------------------
#   MikrotikMangleSwitch
# ---------------------------
class MikrotikMangleSwitch(MikrotikSwitch):
    """Representation of a Mangle switch."""

    async def async_turn_on(self) -> None:
        """Turn on the switch."""
        if "write" not in self.coordinator.data["access"]:
            return

        path = self.entity_description.data_switch_path
        param = ".id"
        value = None
        for uid in self.coordinator.data["mangle"]:
            if self.coordinator.data["mangle"][uid]["uniq-id"] == (
                f"{self._data['chain']},{self._data['action']},{self._data['protocol']},"
                f"{self._data['src-address']}:{self._data['src-port']}-"
                f"{self._data['dst-address']}:{self._data['dst-port']},"
                f"{self._data['src-address-list']}-{self._data['dst-address-list']}"
            ):
                value = self.coordinator.data["mangle"][uid][".id"]

        mod_param = self.entity_description.data_switch_parameter
        await self._async_write_and_refresh(
            path=path,
            param=param,
            value=value,
            mod_param=mod_param,
            mod_value=False,
            optimistic_is_on=True,
        )

    async def async_turn_off(self) -> None:
        """Turn off the switch."""
        if "write" not in self.coordinator.data["access"]:
            return

        path = self.entity_description.data_switch_path
        param = ".id"
        value = None
        for uid in self.coordinator.data["mangle"]:
            if self.coordinator.data["mangle"][uid]["uniq-id"] == (
                f"{self._data['chain']},{self._data['action']},{self._data['protocol']},"
                f"{self._data['src-address']}:{self._data['src-port']}-"
                f"{self._data['dst-address']}:{self._data['dst-port']},"
                f"{self._data['src-address-list']}-{self._data['dst-address-list']}"
            ):
                value = self.coordinator.data["mangle"][uid][".id"]

        mod_param = self.entity_description.data_switch_parameter
        await self._async_write_and_refresh(
            path=path,
            param=param,
            value=value,
            mod_param=mod_param,
            mod_value=True,
            optimistic_is_on=False,
        )


# ---------------------------
#   MikrotikFilterSwitch
# ---------------------------
class MikrotikFilterSwitch(MikrotikSwitch):
    """Representation of a Filter switch."""

    async def async_turn_on(self) -> None:
        """Turn on the switch."""
        if "write" not in self.coordinator.data["access"]:
            return

        path = self.entity_description.data_switch_path
        param = ".id"
        value = None
        for uid in self.coordinator.data["filter"]:
            if self.coordinator.data["filter"][uid]["uniq-id"] == (
                f"{self._data['chain']},{self._data['action']},{self._data['protocol']},{self._data['layer7-protocol']},"
                f"{self._data['in-interface']},{self._data['in-interface-list']}:{self._data['src-address']},{self._data['src-address-list']}:{self._data['src-port']}-"
                f"{self._data['out-interface']},{self._data['out-interface-list']}:{self._data['dst-address']},{self._data['dst-address-list']}:{self._data['dst-port']}"
            ):
                value = self.coordinator.data["filter"][uid][".id"]

        mod_param = self.entity_description.data_switch_parameter
        await self._async_write_and_refresh(
            path=path,
            param=param,
            value=value,
            mod_param=mod_param,
            mod_value=False,
            optimistic_is_on=True,
        )

    async def async_turn_off(self) -> None:
        """Turn off the switch."""
        if "write" not in self.coordinator.data["access"]:
            return

        path = self.entity_description.data_switch_path
        param = ".id"
        value = None
        for uid in self.coordinator.data["filter"]:
            if self.coordinator.data["filter"][uid]["uniq-id"] == (
                f"{self._data['chain']},{self._data['action']},{self._data['protocol']},{self._data['layer7-protocol']},"
                f"{self._data['in-interface']},{self._data['in-interface-list']}:{self._data['src-address']},{self._data['src-address-list']}:{self._data['src-port']}-"
                f"{self._data['out-interface']},{self._data['out-interface-list']}:{self._data['dst-address']},{self._data['dst-address-list']}:{self._data['dst-port']}"
            ):
                value = self.coordinator.data["filter"][uid][".id"]

        mod_param = self.entity_description.data_switch_parameter
        await self._async_write_and_refresh(
            path=path,
            param=param,
            value=value,
            mod_param=mod_param,
            mod_value=True,
            optimistic_is_on=False,
        )


# ---------------------------
#   MikrotikQueueSwitch
# ---------------------------
class MikrotikQueueSwitch(MikrotikSwitch):
    """Representation of a queue switch."""

    async def async_turn_on(self) -> None:
        """Turn on the switch."""
        if "write" not in self.coordinator.data["access"]:
            return

        path = self.entity_description.data_switch_path
        param = ".id"
        value = None
        for uid in self.coordinator.data["queue"]:
            if self.coordinator.data["queue"][uid]["name"] == f"{self._data['name']}":
                value = self.coordinator.data["queue"][uid][".id"]

        mod_param = self.entity_description.data_switch_parameter
        await self._async_write_and_refresh(
            path=path,
            param=param,
            value=value,
            mod_param=mod_param,
            mod_value=False,
            optimistic_is_on=True,
        )

    async def async_turn_off(self) -> None:
        """Turn off the switch."""
        if "write" not in self.coordinator.data["access"]:
            return

        path = self.entity_description.data_switch_path
        param = ".id"
        value = None
        for uid in self.coordinator.data["queue"]:
            if self.coordinator.data["queue"][uid]["name"] == f"{self._data['name']}":
                value = self.coordinator.data["queue"][uid][".id"]

        mod_param = self.entity_description.data_switch_parameter
        await self._async_write_and_refresh(
            path=path,
            param=param,
            value=value,
            mod_param=mod_param,
            mod_value=True,
            optimistic_is_on=False,
        )


# ---------------------------
#   MikrotikKidcontrolPauseSwitch
# ---------------------------
class MikrotikKidcontrolPauseSwitch(MikrotikSwitch):
    """Representation of a queue switch."""

    async def async_turn_on(self) -> None:
        """Turn on the switch."""
        if "write" not in self.coordinator.data["access"]:
            return

        path = self.entity_description.data_switch_path
        param = self.entity_description.data_reference
        value = self._data[self.entity_description.data_reference]
        command = "resume"
        if self._write_in_progress:
            return
        self._write_in_progress = True
        self._set_optimistic_state(True)
        try:
            await self.coordinator.async_execute(path, command, param, value)
        finally:
            self._write_in_progress = False

        await self.coordinator.async_request_refresh()
        self._optimistic_is_on = None
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Turn off the switch."""
        if "write" not in self.coordinator.data["access"]:
            return

        path = self.entity_description.data_switch_path
        param = self.entity_description.data_reference
        value = self._data[self.entity_description.data_reference]
        command = "pause"
        if self._write_in_progress:
            return
        self._write_in_progress = True
        self._set_optimistic_state(False)
        try:
            await self.coordinator.async_execute(path, command, param, value)
        finally:
            self._write_in_progress = False

        await self.coordinator.async_request_refresh()
        self._optimistic_is_on = None
        self.async_write_ha_state()
