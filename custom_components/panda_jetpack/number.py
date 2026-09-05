"""Animation speed for the current effect."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JetpackConfigEntry
from .entity import JetpackEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JetpackConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([JetpackSpeed(entry.runtime_data, entry.entry_id)])


class JetpackSpeed(JetpackEntity, NumberEntity):
    _attr_translation_key = "speed"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "speed")

    @property
    def native_value(self) -> float | None:
        # Unreadable like brightness, so prefer what we last sent.
        value = self.coordinator.optimistic.get("speed")
        if value is None:
            value = self.coordinator.mode_entry(self.coordinator.current_mode).get("speed")
        return value if isinstance(value, int) else None

    async def async_set_native_value(self, value: float) -> None:
        # This message carries no mode number and applies to whichever mode
        # is selected -- same temperament as brightness.
        percent = int(value)
        self.coordinator.optimistic["speed"] = percent
        # The device never reports this back, so a coordinator refresh will
        # not carry it either. Without this line the slider snaps back to the
        # old value as soon as you let go.
        self.async_write_ha_state()
        await self.coordinator.async_send({"rgb_info_speed": percent})
