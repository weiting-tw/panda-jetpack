"""BIQU Panda Jetpack V2 -- RGB lighting on a Bambu Lab hotend shroud."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

from .coordinator import JetpackCoordinator

PLATFORMS = [
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
]

JetpackConfigEntry = ConfigEntry[JetpackCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: JetpackConfigEntry) -> bool:
    coordinator = JetpackCoordinator(hass, entry.data[CONF_HOST])
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: JetpackConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
