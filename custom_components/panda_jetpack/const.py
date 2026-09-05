"""Shared constants."""

DOMAIN = "panda_jetpack"

CONF_HOST = "host"

# Re-read every 30 seconds. The device never pushes state and never replies to
# anything we send, so "read the state" means opening a fresh connection,
# taking the dump it opens with, and closing again.
UPDATE_INTERVAL = 30

# The value sent is the index into the web UI's g_rgb_type_str array, not the N
# in its rgb_info_modeN translation strings. The two diverge after 7, because
# the UI's 7 and 10 ("printer status", "print progress") are not in this
# dropdown. That is why the hot-end warning is 7 and not 8.
MODES = [
    "static",
    "breathing",
    "strobing",
    "wave",
    "marquee",
    "cycle",
    "rainbow",
    "warning",
    "fan",
    "h2d",
]

# How the light behaves in the safe and danger temperature bands. Deliberately
# not called "effect" -- in Home Assistant that word already means the ten
# modes above, and one word for two things is a bug waiting to happen.
STYLES = ["static", "strobing"]

# The three colors belonging to the h2d effect, one per printer state. The
# index is exactly the rgb_state_index sent on the wire. The firmware does not
# range-check it -- sending 3 writes to slot 2 -- so callers must clamp.
H2D_STATES = ["idle", "printing", "error"]

# Effect mode 9. The h2d colors only mean anything for this mode.
MODE_H2D = 9
