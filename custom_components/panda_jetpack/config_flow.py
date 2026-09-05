"""Set up a Panda Jetpack by IP address."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST

from .const import DOMAIN
from .util import device_mac
from .ws import JetpackError, fetch_state

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


class JetpackConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                state = await fetch_state(host)
            except JetpackError:
                errors["base"] = "cannot_connect"
            else:
                # Use the device's own MAC as the unique id, falling back to
                # the host: a changed AP SSID format is not worth failing setup
                # over.
                await self.async_set_unique_id(device_mac(state) or host)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                name = (state.get("sta") or {}).get("hostname") or "Panda Jetpack"
                return self.async_create_entry(title=name, data={CONF_HOST: host})

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
