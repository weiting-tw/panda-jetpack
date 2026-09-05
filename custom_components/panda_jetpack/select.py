"""Styles used in the safe and danger temperature bands."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JetpackConfigEntry
from .const import STYLES
from .entity import JetpackEntity

# The write fields are safe_effect / danger_effect, but the device reports
# them back as safe_current_mode / danger_current_mode -- the names do not
# match, so reading and writing use different keys. Unlike follow and
# warning_override, these need no rgb_info_mode alongside them.
_FIELDS = {
    "safe_effect": "safe_current_mode",
    "danger_effect": "danger_current_mode",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JetpackConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        JetpackEffectSelect(coordinator, entry.entry_id, write, read)
        for write, read in _FIELDS.items()
    )


class JetpackEffectSelect(JetpackEntity, SelectEntity):
    _attr_options = list(STYLES)

    def __init__(self, coordinator, entry_id: str, write_field: str, read_field: str) -> None:
        super().__init__(coordinator, entry_id, write_field)
        self._write_field = write_field
        self._read_field = read_field
        self._attr_translation_key = write_field

    @property
    def current_option(self) -> str | None:
        value = self.coordinator.settings.get(self._read_field)
        if isinstance(value, int) and 0 <= value < len(STYLES):
            return STYLES[value]
        return None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_send({self._write_field: STYLES.index(option)})
