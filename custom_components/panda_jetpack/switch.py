"""Two global toggles: follow the printer, and warning override."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JetpackConfigEntry
from .entity import JetpackEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JetpackConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            JetpackSwitch(coordinator, entry.entry_id, "follow"),
            JetpackSwitch(coordinator, entry.entry_id, "warning_override"),
        ]
    )


class JetpackSwitch(JetpackEntity, SwitchEntity):
    def __init__(self, coordinator, entry_id: str, field: str) -> None:
        super().__init__(coordinator, entry_id, field)
        self._field = field
        self._attr_translation_key = field

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.settings.get(self._field))

    async def _set(self, value: int) -> None:
        await self.coordinator.async_toggle(
            self._field, value, self.coordinator.current_mode
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(0)
