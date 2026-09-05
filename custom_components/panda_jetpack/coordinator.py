"""State polling, and the single module that speaks the device's protocol.

Every outgoing setting goes through one of the domain methods below, never a
raw dict. Those methods own three facts that used to be smeared across the
entities: which fields a message must (or must not) carry, that a compound
change has to stay atomic, and that brightness and speed have to be faked
because the device will not report them back.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, H2D_STATES, MODE_H2D, UPDATE_INTERVAL
from .util import redact
from .ws import JetpackError, fetch_state, send

_LOGGER = logging.getLogger(__name__)


def _rgba(rgb: tuple[int, int, int]) -> str:
    """(r, g, b) -> the device's #RRGGBBAA wire format. Alpha is always FF."""
    return "#{:02X}{:02X}{:02X}FF".format(*rgb)


class JetpackCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls state and is the only thing that talks to the device."""

    def __init__(self, hass: HomeAssistant, host: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.host = host
        # The ESP32 accepts very few concurrent connections, and every read and
        # write opens its own. A compound change sends several messages in a
        # row, so the whole sequence has to hold the lock -- not one message at
        # a time -- or another entity's write can interleave and land on a mode
        # that one of these messages just switched away from.
        self._lock = asyncio.Lock()
        # Brightness and speed cannot be read back: the values in list2 are
        # stored defaults, not what is in effect. So remember what we sent,
        # keyed by mode -- switching effect must not show the previous effect's
        # numbers. Cleared on restart, which then falls back to list2.
        self._optimistic: dict[tuple[int, str], int] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        async with self._lock:
            try:
                return redact(await fetch_state(self.host))
            except JetpackError as err:
                raise UpdateFailed(str(err)) from err

    async def _commit(
        self,
        messages: list[dict[str, Any]],
        optimistic: dict[tuple[int, str], int] | None = None,
    ) -> None:
        """Send a sequence of settings atomically, then re-read once.

        Holds the lock across the whole sequence so nothing interleaves. Uses
        async_refresh, not async_request_refresh: the latter's 10-second
        debounce would leave entities showing stale values, and a local read is
        about 0.3 s.
        """
        async with self._lock:
            try:
                for members in messages:
                    await send(self.host, "settings", members)
            except JetpackError as err:
                raise UpdateFailed(str(err)) from err
            if optimistic:
                self._optimistic.update(optimistic)
        await self.async_refresh()

    # -- outgoing: the device's message vocabulary -------------------------

    async def async_apply_light(
        self,
        mode: int,
        *,
        rgb: tuple[int, int, int] | None = None,
        brightness: int | None = None,
    ) -> None:
        """Turn the light on in `mode`, optionally setting color and brightness.

        Color rides in the same message as the mode switch. Brightness cannot:
        it carries no mode and lands on whatever is selected, so it follows in a
        second message -- both under one lock.
        """
        first: dict[str, Any] = {"rgb_info_mode": mode, "on": 1}
        if rgb is not None:
            first["rgb_rgba"] = _rgba(rgb)
        messages = [first]
        optimistic = None
        if brightness is not None:
            messages.append({"rgb_info_brightness": brightness})
            optimistic = {(mode, "brightness"): brightness}
        await self._commit(messages, optimistic)

    async def async_turn_off(self, mode: int) -> None:
        await self._commit([{"rgb_info_mode": mode, "on": 0}])

    async def async_set_speed(self, mode: int, percent: int) -> None:
        """Speed carries no mode, so switch to `mode` first, in one lock."""
        await self._commit(
            [{"rgb_info_mode": mode}, {"rgb_info_speed": percent}],
            {(mode, "speed"): percent},
        )

    async def async_toggle(self, field: str, value: int, mode: int) -> None:
        """follow / warning_override are global, but the UI attaches the mode."""
        await self._commit([{"rgb_info_mode": mode, field: value}])

    async def async_set_style(self, field: str, index: int) -> None:
        """safe_effect / danger_effect carry no mode."""
        await self._commit([{field: index}])

    async def async_action(self, field: str) -> None:
        """A one-shot flag: rgb_reset / reset. Just {field: 1}."""
        await self._commit([{field: 1}])

    async def async_set_h2d_color(self, state_index: int, rgb: tuple[int, int, int]) -> None:
        """Set one of the h2d effect's per-state colors.

        The web UI cannot do this (V1.0.0 checks colorButton_id==8 before
        attaching rgb_state_index, but h2d is 9). The firmware does not
        range-check the index -- sending 3 writes to slot 2 -- so clamp it.
        """
        clamped = max(0, min(state_index, len(H2D_STATES) - 1))
        await self._commit(
            [{"rgb_info_mode": MODE_H2D, "rgb_rgba": _rgba(rgb), "rgb_state_index": clamped}]
        )

    # -- reading state -----------------------------------------------------

    @property
    def settings(self) -> dict[str, Any]:
        return (self.data or {}).get("settings") or {}

    @property
    def current_mode(self) -> int:
        value = self.settings.get("current_mode")
        return value if isinstance(value, int) else 0

    @property
    def h2d_colors(self) -> list[str]:
        """The h2d effect's three colors, in idle / printing / error order."""
        entries = self.settings.get("list3") or []
        if not entries:
            return []
        colors = entries[0].get("h2d_rgba")
        return list(colors) if isinstance(colors, list) else []

    def mode_entry(self, mode: int) -> dict[str, Any]:
        """One mode's row in list2. The color is trustworthy; brightness and speed are not."""
        for entry in self.settings.get("list2") or []:
            if entry.get("rgb_info_mode") == mode:
                return entry
        return {}

    def effective(self, mode: int, field: str) -> int | None:
        """The brightness or speed in effect for `mode`.

        The device cannot report these back, so prefer what we last sent for
        this mode, then fall back to the stored default in list2. Keying by
        mode is what stops a just-switched effect from showing the previous
        one's numbers.
        """
        if (mode, field) in self._optimistic:
            return self._optimistic[(mode, field)]
        value = self.mode_entry(mode).get(field)
        return value if isinstance(value, int) else None
