"""Two one-shot actions: reset the light settings, and reboot."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import JetpackConfigEntry
from .entity import JetpackEntity

# The device also accepts {"settings":{"factory_reset":1}}, deliberately not
# exposed as a button: mis-tapping it clears the WiFi settings, and recovering
# the device then means going through its own AP hotspot.
_BUTTONS = [
    ("rgb_reset", None),
    ("reset", ButtonDeviceClass.RESTART),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JetpackConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        JetpackButton(entry.runtime_data, entry.entry_id, field, device_class)
        for field, device_class in _BUTTONS
    )


class JetpackButton(JetpackEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry_id: str, field: str, device_class) -> None:
        super().__init__(coordinator, entry_id, field)
        self._field = field
        self._attr_translation_key = field
        self._attr_device_class = device_class

    async def async_press(self) -> None:
        await self.coordinator.async_send({self._field: 1})
