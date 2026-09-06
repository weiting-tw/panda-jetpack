"""Pure helpers with no Home Assistant imports.

Kept separate so the tests can run without pulling in all of Home Assistant --
especially redact(), which enforces the one rule in this project that must
never regress.
"""

from __future__ import annotations

import re
from typing import Any

# /ws has no authentication whatsoever, and the device dumps three plaintext
# secrets the moment anyone connects: the user's WiFi password, the device's
# own AP password, and the bound printer's access code. The integration needs
# none of them, so they are dropped at the door -- that keeps them out of
# entity attributes, logs, and downloaded diagnostics. The leak itself is a
# firmware issue and cannot be fixed from out here.
SECRET_KEYS = frozenset({"password", "access_code"})

# The CLI has its own copy (it must run on the stock interpreter, so it cannot
# import from here). It substitutes a visible "<redacted>" marker because it
# prints to a terminal; this copy is machine-read, so None is the natural
# absent value. The substituted value is allowed to differ. The safety
# contract -- no secret value survives, everything else is untouched -- is not,
# and tests/test_redact.py checks that one contract against both copies.


def redact(obj: Any) -> Any:
    """Replace secret fields with None, leaving everything else untouched."""
    if isinstance(obj, dict):
        return {
            k: (None if k in SECRET_KEYS else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def device_mac(state: dict[str, Any]) -> str | None:
    """Extract the device's own MAC from its AP SSID.

    The SSID looks like Panda_Jetpack_8CBFEA611A34. This beats printer.sn as a
    unique id -- that one belongs to the bound printer and changes if you swap
    printers. Returns None if the firmware ever changes the SSID format, so the
    caller can fall back to the IP instead of failing outright.
    """
    ssid = (state.get("ap") or {}).get("ssid") or ""
    m = re.search(r"([0-9A-Fa-f]{12})$", ssid)
    if not m:
        return None
    raw = m.group(1).upper()
    return ":".join(raw[i:i + 2] for i in range(0, 12, 2))
