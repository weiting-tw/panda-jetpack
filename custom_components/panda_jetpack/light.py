"""The ring of RGB LEDs on the shroud."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import voluptuous as vol

from . import JetpackConfigEntry
from .const import H2D_STATES, MODE_H2D, MODES
from .entity import JetpackEntity

SERVICE_SET_H2D_COLOR = "set_h2d_color"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: JetpackConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([JetpackLight(entry.runtime_data, entry.entry_id)])

    # The h2d colors are parameters of one effect, not three separate lights
    # -- the device has a single LED ring. So: a service to write them and
    # attributes to read them, rather than entities of their own.
    entity_platform.async_get_current_platform().async_register_entity_service(
        SERVICE_SET_H2D_COLOR,
        {
            vol.Required("state"): vol.In(H2D_STATES),
            vol.Required("color"): vol.All(
                vol.ExactSequence((cv.byte, cv.byte, cv.byte)), vol.Coerce(tuple)
            ),
        },
        "async_set_h2d_color",
    )


def _parse_rgba(value: Any) -> tuple[int, int, int] | None:
    """#RRGGBBAA -> (r, g, b). The alpha byte makes no observable difference."""
    if not isinstance(value, str):
        return None
    text = value.lstrip("#")
    if len(text) < 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


class JetpackLight(JetpackEntity, LightEntity):
    _attr_name = None
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_color_mode = ColorMode.RGB
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = list(MODES)

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "light")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.settings.get("on"))

    @property
    def effect(self) -> str | None:
        mode = self.coordinator.current_mode
        return MODES[mode] if 0 <= mode < len(MODES) else None

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        entry = self.coordinator.mode_entry(self.coordinator.current_mode)
        return _parse_rgba(entry.get("rgb_rgba"))

    @property
    def brightness(self) -> int | None:
        # The live brightness cannot be read back, so prefer what we last
        # sent; fall back to the stored default in list2 (which is the state
        # right after a restart, and may not match what you can see).
        percent = self.coordinator.optimistic.get("brightness")
        if percent is None:
            percent = self.coordinator.mode_entry(self.coordinator.current_mode).get(
                "brightness"
            )
        if not isinstance(percent, int):
            return None
        return round(percent * 255 / 100)

    async def async_turn_on(self, **kwargs: Any) -> None:
        mode = self.coordinator.current_mode
        if (effect := kwargs.get(ATTR_EFFECT)) in MODES:
            mode = MODES.index(effect)

        # Mode, color and on/off fit in one message. Brightness does not: it
        # carries no mode number and applies to whichever mode is selected, so
        # it has to wait until the mode has actually changed.
        members: dict[str, Any] = {"rgb_info_mode": mode, "on": 1}
        if (rgb := kwargs.get(ATTR_RGB_COLOR)) is not None:
            members["rgb_rgba"] = "#{:02X}{:02X}{:02X}FF".format(*rgb)
        await self.coordinator.async_send(members)

        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            # HA's minimum brightness is 1, which scales to 0 -- and 0 means
            # fully dark on the device.
            percent = max(1, round(brightness * 100 / 255))
            self.coordinator.optimistic["brightness"] = percent
            # Same reason as number: unreadable, so write it ourselves or the
            # UI snaps back to the old value.
            self.async_write_ha_state()
            await self.coordinator.async_send({"rgb_info_brightness": percent})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        colors = self.coordinator.h2d_colors
        if not colors:
            return None
        return {
            f"h2d_{name}_color": colors[i]
            for i, name in enumerate(H2D_STATES)
            if i < len(colors)
        }

    async def async_set_h2d_color(self, state: str, color: tuple[int, int, int]) -> None:
        """Set one of the h2d effect's per-printer-state colors.

        The device's own web UI cannot do this: in V1.0.0 it checks
        colorButton_id==8 before attaching rgb_state_index, but h2d is 9. The
        protocol itself is fine.
        """
        index = H2D_STATES.index(state)
        await self.coordinator.async_send(
            {
                "rgb_info_mode": MODE_H2D,
                "rgb_rgba": "#{:02X}{:02X}{:02X}FF".format(*color),
                # The firmware does not range-check this (sending 3 writes to
                # slot 2), so clamp it here.
                "rgb_state_index": max(0, min(index, len(H2D_STATES) - 1)),
            }
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_send(
            {"rgb_info_mode": self.coordinator.current_mode, "on": 0}
        )
