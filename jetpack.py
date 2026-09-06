#!/usr/bin/python3
"""Control the RGB lighting on a BIQU Panda Jetpack V2.

The shebang pins the system Python on purpose. macOS grants "local network"
access per executable, and Homebrew replaces its python binary on every
upgrade, which resets that grant -- connections to devices on your own subnet
then fail with EHOSTUNREACH while ping and curl still work fine. This script
has no dependencies and runs on the stock interpreter, so that whole problem
never comes up. Don't change it back to `env python3`.

The device has no REST API. Its web UI opens a WebSocket to ws://<ip>/ws and
sends every setting as {"<root>": {<field>: <value>}}. The only POST endpoint
is firmware OTA upload.

Two things about this device differ from a normal WebSocket service:

1. It pushes a full state dump the moment you connect -- you never ask for it.
2. It never replies to anything you send, not even to messages known to work.
   So "no response" is not evidence of failure. The only trustworthy way to
   observe a change is to close the connection, reconnect, and read the state.
"""

import argparse
import base64
import json
import os
import re
import socket
import struct
import sys

DEFAULT_HOST = "192.168.31.142"

# The value sent is the *index* into the web UI's g_rgb_type_str array, not the
# N in its rgb_info_modeN translation strings. The two diverge after 7, because
# the UI's 7 and 10 ("printer status" and "print progress") are not in this
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

# How the light behaves in the safe and danger temperature bands. Independent
# of each other and unrelated to the mode table above -- only two options.
# Deliberately not called "effect": that word already means the ten modes
# above, and one word for two things is a bug waiting to happen.
STYLES = ["static", "strobing"]

# The three colors belonging to the h2d effect, one per printer state. The
# index is exactly the rgb_state_index sent on the wire.
H2D_STATES = ["idle", "printing", "error"]


# --------------------------------------------------------------------------
# Minimal WebSocket client
#
# No websockets/websocket-client dependency: that would add an install step for
# what is really just "connect, read text frames, write text frames".
#
# Node's built-in WebSocket also cannot talk to this device -- it offers
# Sec-WebSocket-Extensions: permessage-deflate, which the ESP32 implementation
# rejects. Doing the handshake by hand guarantees we offer no extensions.
# --------------------------------------------------------------------------
class Ws:
    def __init__(self, host, timeout=6):
        self.sock = socket.create_connection((host, 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            f"GET /ws HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n"
            f"Sec-WebSocket-Key: {key}\r\nOrigin: http://{host}\r\n\r\n".encode()
        )
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1)
            if not chunk:
                raise ConnectionError("connection closed during handshake")
            head += chunk
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise ConnectionError(f"handshake failed: {head.splitlines()[0]!r}")
        self.buf = head.split(b"\r\n\r\n", 1)[1]

    def recv_text(self, seconds=5):
        """Collect every text frame that arrives before the timeout."""
        self.sock.settimeout(seconds)
        out = []
        try:
            while True:
                while True:
                    if len(self.buf) < 2:
                        break
                    opcode = self.buf[0] & 0x0F
                    n = self.buf[1] & 0x7F
                    off = 2
                    if n == 126:
                        if len(self.buf) < 4:
                            break
                        n = struct.unpack(">H", self.buf[2:4])[0]
                        off = 4
                    elif n == 127:
                        if len(self.buf) < 10:
                            break
                        n = struct.unpack(">Q", self.buf[2:10])[0]
                        off = 10
                    if len(self.buf) < off + n:
                        break
                    payload = self.buf[off:off + n]
                    self.buf = self.buf[off + n:]
                    if opcode == 1:
                        out.append(payload.decode("utf-8", "replace"))
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                self.buf += chunk
        except socket.timeout:
            pass
        return out

    def send_text(self, text):
        data = text.encode()
        n = len(data)
        hdr = bytearray([0x81])
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126)
            hdr += struct.pack(">H", n)
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack(">Q", n)
        mask = os.urandom(4)
        hdr += mask
        self.sock.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def send(host, root, members, wait=0.0):
    """Send one setting. The device applies it on disconnect; there is no ack."""
    ws = Ws(host)
    ws.recv_text(seconds=2)          # swallow the state dump it opens with
    ws.send_text(json.dumps({root: members}))
    if wait:
        ws.recv_text(seconds=wait)
    ws.close()


def fetch_state(host):
    ws = Ws(host)
    frames = ws.recv_text(seconds=4)
    ws.close()
    if not frames:
        raise ConnectionError("device sent no state")
    return json.loads(frames[0])


# This device puts your WiFi password, its own AP password and the printer's
# access code in the state dump, in the clear, and /ws has no authentication at
# all. Printing them would only spread them into shell history and scrollback.
_SECRET_KEYS = ("password", "access_code")

# The integration has its own copy of this (the packaging seam: this script has
# to run on the stock interpreter, so it cannot import from the Home Assistant
# tree). The two deliberately differ in what they substitute, because their
# audiences differ: this one prints to a terminal, where a visible marker says
# "a secret is here and it is hidden", which null would confuse with "no
# password set". The integration's copy is machine-read and uses None.
#
# What must NOT differ is the safety contract -- no secret value survives, the
# structure is otherwise untouched -- and tests/test_redact.py checks that one
# contract against both copies.
_REDACTED = "<redacted>"


def redact(obj):
    if isinstance(obj, dict):
        # `and v` on purpose: an empty password is not a secret, and marking it
        # redacted would imply one exists.
        return {k: (_REDACTED if k in _SECRET_KEYS and v else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def parse_color(text):
    """Accept #RGB / #RRGGBB / #RRGGBBAA / a color name; return #RRGGBBAA."""
    named = {"red": "FF0000", "green": "00FF00", "blue": "0000FF",
             "white": "FFFFFF", "black": "000000", "yellow": "FFFF00",
             "cyan": "00FFFF", "magenta": "FF00FF", "orange": "FF8000",
             "purple": "8000FF"}
    t = named.get(text.lower(), text).lstrip("#").upper()
    if not re.fullmatch(r"[0-9A-F]+", t or "x"):
        raise argparse.ArgumentTypeError(f"not a color: {text}")
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(t) == 6:
        t += "FF"
    if len(t) != 8:
        raise argparse.ArgumentTypeError(f"not a color: {text}")
    return "#" + t


def mode_index(name):
    key = name.lower()
    if key.isdigit():
        i = int(key)
        if 0 <= i < len(MODES):
            return i
        raise argparse.ArgumentTypeError(f"mode number must be 0-{len(MODES) - 1}")
    if key in MODES:
        return MODES.index(key)
    raise argparse.ArgumentTypeError(f"unknown mode: {name} ({', '.join(MODES)})")


def style_index(name):
    key = name.lower()
    if key.isdigit():
        i = int(key)
        if 0 <= i < len(STYLES):
            return i
        raise argparse.ArgumentTypeError(f"style number must be 0-{len(STYLES) - 1}")
    if key in STYLES:
        return STYLES.index(key)
    raise argparse.ArgumentTypeError(f"unknown style: {name} ({', '.join(STYLES)})")


def h2d_state_index(name):
    key = name.lower()
    if key.isdigit():
        i = int(key)
        if 0 <= i < len(H2D_STATES):
            return i
        raise argparse.ArgumentTypeError(f"state number must be 0-{len(H2D_STATES) - 1}")
    if key in H2D_STATES:
        return H2D_STATES.index(key)
    raise argparse.ArgumentTypeError(
        f"unknown printer state: {name} ({', '.join(H2D_STATES)})")


def cmd_status(a):
    st = redact(fetch_state(a.host))
    if a.json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return
    s = st.get("settings", {})
    cur = s.get("current_mode", -1)
    name = MODES[cur] if 0 <= cur < len(MODES) else str(cur)
    print(f"firmware   {s.get('fw_version')}")
    print(f"host       {st.get('sta', {}).get('hostname')} @ {st.get('sta', {}).get('ip')}")
    p = st.get("printer", {})
    print(f"printer    {p.get('name')} ({p.get('sn')}) @ {p.get('ip')}  state={p.get('state')}")
    print(f"light      {'on' if s.get('on') else 'off'}   current mode {cur} = {name}")
    print(f"follow printer      {'on' if s.get('follow') else 'off'}")
    print(f"warning override    {'on' if s.get('warning_override') else 'off'}")

    def style(v):
        ok = isinstance(v, int) and 0 <= v < len(STYLES)
        return STYLES[v] if ok else str(v)
    print(f"safe temp style     {style(s.get('safe_current_mode'))}")
    print(f"danger temp style   {style(s.get('danger_current_mode'))}")

    h2d = (s.get("list3") or [{}])[0].get("h2d_rgba") or []
    if h2d:
        parts = [f"{H2D_STATES[i]} {c}" for i, c in enumerate(h2d) if i < len(H2D_STATES)]
        print("h2d colors          " + "   ".join(parts))
    print()
    print("  #  mode          bright  speed  color")
    for e in s.get("list2", []):
        i = e["rgb_info_mode"]
        mark = "*" if i == cur else " "
        print(f" {mark}{i}  {MODES[i]:<12}  {e['brightness']:>5}%  {e['speed']:>4}%  {e['rgb_rgba']}")


def cmd_mode(a):
    i = mode_index(a.mode)
    send(a.host, "settings", {"rgb_info_mode": i})
    print(f"mode -> {i} {MODES[i]}")


def cmd_color(a):
    i = mode_index(a.mode)
    rgba = parse_color(a.color)
    send(a.host, "settings", {"rgb_info_mode": i, "rgb_rgba": rgba})
    print(f"{MODES[i]} color -> {rgba}")


# Brightness and speed messages carry no mode number -- they apply to whichever
# mode is currently selected. So select the mode first, or you will adjust a
# different one.
#
# Do not verify these two against the list2 the device reports back: the light
# really does dim and the breathing really does slow down, but the brightness
# and speed in list2 never move. That list holds stored defaults, not the
# values in effect.
def cmd_brightness(a):
    i = mode_index(a.mode)
    send(a.host, "settings", {"rgb_info_mode": i})
    send(a.host, "settings", {"rgb_info_brightness": a.value})
    print(f"{MODES[i]} brightness -> {a.value}%")


def cmd_speed(a):
    i = mode_index(a.mode)
    send(a.host, "settings", {"rgb_info_mode": i})
    send(a.host, "settings", {"rgb_info_speed": a.value})
    print(f"{MODES[i]} speed -> {a.value}%")


def cmd_on(a):
    i = mode_index(a.mode)
    send(a.host, "settings", {"rgb_info_mode": i, "on": 0 if a.off else 1})
    print(f"light -> {'off' if a.off else 'on'}")


def _toggle(a, field, label):
    """follow and warning_override are global, but the web UI always attaches
    the current mode number. Do the same, reading the mode from the device so
    we never write it onto a different one."""
    cur = fetch_state(a.host)["settings"].get("current_mode", 0)
    value = 0 if a.off else 1
    send(a.host, "settings", {"rgb_info_mode": cur, field: value})
    now = fetch_state(a.host)["settings"].get(field)
    ok = "applied" if now == value else f"NOT applied (device still reports {now})"
    print(f"{label} -> {'off' if a.off else 'on'}   {ok}")


def cmd_follow(a):
    # Light follows the printer's state. While on, the print stage picks the
    # effect and whatever mode you selected by hand is overridden.
    _toggle(a, "follow", "follow printer")


def cmd_warning(a):
    # Hot-end warning overrides the current effect. Turn it off and an
    # overheating nozzle will no longer flash the warning color.
    _toggle(a, "warning_override", "warning override")


# The write field is safe_effect / danger_effect, but the device reports them
# back as safe_current_mode / danger_current_mode. The names don't match, so
# reading and writing use different keys. Unlike follow and warning_override,
# these need no rgb_info_mode alongside them.
def _style(a, field, report_field, label):
    i = style_index(a.style)
    send(a.host, "settings", {field: i})
    now = fetch_state(a.host)["settings"].get(report_field)
    ok = "applied" if now == i else f"NOT applied (device still reports {now})"
    print(f"{label} -> {i} {STYLES[i]}   {ok}")


def cmd_safe(a):
    _style(a, "safe_effect", "safe_current_mode", "safe temp style")


def cmd_danger(a):
    _style(a, "danger_effect", "danger_current_mode", "danger temp style")


def read_h2d(host):
    entries = fetch_state(host)["settings"].get("list3") or []
    colors = entries[0].get("h2d_rgba") if entries else None
    return list(colors) if isinstance(colors, list) else []


def cmd_h2d(a):
    """Set one of the h2d effect's per-printer-state colors.

    The device's own web UI cannot do this. In V1.0.0 it checks
    colorButton_id==8 before attaching rgb_state_index, but h2d is 9, so
    selecting h2d always takes the branch that omits the index and none of the
    three colors is ever written. The protocol itself is fine: send the index
    and it works.
    """
    i = h2d_state_index(a.state)
    rgba = parse_color(a.color)
    # The firmware does not range-check this -- sending 3 writes to slot 2 --
    # so clamp it here.
    i = max(0, min(i, len(H2D_STATES) - 1))
    send(a.host, "settings",
         {"rgb_info_mode": MODES.index("h2d"), "rgb_rgba": rgba, "rgb_state_index": i})
    now = read_h2d(a.host)
    ok = "applied" if i < len(now) and now[i] == rgba else f"NOT applied (device reports {now})"
    print(f"h2d {H2D_STATES[i]} color -> {rgba}   {ok}")


def cmd_rgb_reset(a):
    send(a.host, "settings", {"rgb_reset": 1})
    print("light settings reset sent")


def cmd_restart(a):
    send(a.host, "settings", {"reset": 1})
    print("restart sent; the device takes a few seconds to come back")


def cmd_palette(a):
    # blockID 0-19 are *swatches*, not LEDs. The lower half of the web UI's
    # color page has a row of 20 (titled rgb_status_title, "color definitions")
    # holding colors you can pick from later. Changing them lights up nothing
    # -- use the `color` command for that.
    rgba = parse_color(a.color)
    ids = range(20) if a.id is None else [a.id]
    for i in ids:
        send(a.host, "block", {"blockID": i, "blockrgba": rgba})
    print(f"swatch {'all' if a.id is None else a.id} -> {rgba}")


def percent(v):
    n = int(v)
    if not 0 <= n <= 100:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return n


def main():
    p = argparse.ArgumentParser(description="Control a Panda Jetpack V2's RGB lighting")
    p.add_argument("--host", default=os.environ.get("JETPACK_HOST", DEFAULT_HOST))
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="show the current state")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("mode", help="switch the light effect")
    s.add_argument("mode", help=" / ".join(MODES))
    s.set_defaults(func=cmd_mode)

    s = sub.add_parser("color", help="set one effect's color")
    s.add_argument("mode")
    s.add_argument("color", help="#RRGGBB or red/blue/...")
    s.set_defaults(func=cmd_color)

    s = sub.add_parser("brightness", help="set one effect's brightness")
    s.add_argument("mode")
    s.add_argument("value", type=percent)
    s.set_defaults(func=cmd_brightness)

    s = sub.add_parser("speed", help="set one effect's speed")
    s.add_argument("mode")
    s.add_argument("value", type=percent)
    s.set_defaults(func=cmd_speed)

    s = sub.add_parser("on", help="turn the light on or off")
    s.add_argument("mode")
    s.add_argument("--off", action="store_true")
    s.set_defaults(func=cmd_on)

    s = sub.add_parser("follow", help="make the light follow the printer's state")
    s.add_argument("--off", action="store_true")
    s.set_defaults(func=cmd_follow)

    s = sub.add_parser("warning", help="let the hot-end warning override the current effect")
    s.add_argument("--off", action="store_true")
    s.set_defaults(func=cmd_warning)

    s = sub.add_parser("safe", help="style used in the safe temperature band")
    s.add_argument("style", help=" / ".join(STYLES))
    s.set_defaults(func=cmd_safe)

    s = sub.add_parser("danger", help="style used in the danger temperature band")
    s.add_argument("style", help=" / ".join(STYLES))
    s.set_defaults(func=cmd_danger)

    s = sub.add_parser("h2d", help="set one of the h2d effect's per-state colors")
    s.add_argument("state", help=" / ".join(H2D_STATES))
    s.add_argument("color", help="#RRGGBB or red/blue/...")
    s.set_defaults(func=cmd_h2d)

    s = sub.add_parser("rgb-reset", help="reset light settings to defaults")
    s.set_defaults(func=cmd_rgb_reset)

    s = sub.add_parser("restart", help="reboot the device")
    s.set_defaults(func=cmd_restart)

    s = sub.add_parser("palette", help="set the web UI's color swatches (changes no light)")
    s.add_argument("color")
    s.add_argument("--id", type=int, choices=range(20), metavar="0-19",
                   help="omit to set all 20")
    s.set_defaults(func=cmd_palette)

    a = p.parse_args()
    try:
        a.func(a)
    except (OSError, ConnectionError) as e:
        print(f"cannot reach {a.host}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
