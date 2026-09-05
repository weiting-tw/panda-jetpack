"""State polling and the single way out to the device."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, UPDATE_INTERVAL
from .util import redact
from .ws import JetpackError, fetch_state, send

_LOGGER = logging.getLogger(__name__)


class JetpackCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls state and serialises every outgoing write."""

    def __init__(self, hass: HomeAssistant, host: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.host = host
        # The ESP32 accepts very few concurrent connections, and every read
        # and write opens its own. A single service call can send several
        # messages in a row, so they have to queue.
        self._lock = asyncio.Lock()
        # Brightness and speed cannot be read back: the values in list2 are
        # stored defaults, not what is in effect (the light really does dim and
        # the breathing really does slow down, but those numbers never move).
        # So remember what we sent; only a restart falls back to list2.
        self.optimistic: dict[str, int] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        async with self._lock:
            try:
                return redact(await fetch_state(self.host))
            except JetpackError as err:
                raise UpdateFailed(str(err)) from err

    async def async_send(self, members: dict[str, Any], root: str = "settings") -> None:
        """Send one setting, then re-read the state immediately.

        async_refresh rather than async_request_refresh: the latter carries a
        10-second debounce cooldown that leaves entities showing stale values
        in the UI. The device is on the local network and a read takes about
        0.3 s, so reading straight away is the better trade.
        """
        async with self._lock:
            try:
                await send(self.host, root, members)
            except JetpackError as err:
                raise UpdateFailed(str(err)) from err
        await self.async_refresh()

    # -- state shortcuts --------------------------------------------------

    @property
    def settings(self) -> dict[str, Any]:
        return (self.data or {}).get("settings") or {}

    @property
    def current_mode(self) -> int:
        value = self.settings.get("current_mode")
        return value if isinstance(value, int) else 0

    @property
    def h2d_colors(self) -> list[str]:
        """The h2d effect's three colors: idle, printing, error.

        The web UI can read these but never writes them -- in V1.0.0 it checks
        colorButton_id==8 before attaching rgb_state_index, but h2d is 9, so it
        always takes the branch that omits the index. The protocol is fine;
        sending the index works.
        """
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
