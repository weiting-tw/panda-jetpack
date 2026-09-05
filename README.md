# Panda Jetpack

Control the RGB lighting on a **BIQU Panda Jetpack V2** — the hotend shroud for
Bambu Lab P1/X1 printers. A zero-dependency CLI plus a Home Assistant
integration.

[繁體中文](README.zh-TW.md)

## ⚠️ Security

`ws://<ip>/ws` has **no authentication**, and the device pushes a full state
dump — including your **WiFi password**, its **AP password**, and the printer's
**access code**, all in plaintext — to anyone who connects. Any device on the
same network can read them in under a second.

This is a firmware issue and cannot be fixed from outside. Both the CLI and the
integration strip these three fields on arrival, so they never reach a terminal,
a log, an entity attribute, or a diagnostics download. **Keep it that way.**

Mitigation: put the Jetpack and the printer on an isolated VLAN or SSID, with a
one-way firewall rule allowing your main network in. The password it stores is
then only that isolated network's password. Home Assistant still reaches it.

## CLI

Zero dependencies. Runs on the stock system Python.

```
./jetpack.py status                # current state (secrets redacted)
./jetpack.py status --json
./jetpack.py mode breathing        # switch effect (name or number)
./jetpack.py color static red      # one effect's color
./jetpack.py brightness h2d 80     # 0-100
./jetpack.py speed breathing 30    # 0-100
./jetpack.py on static --off       # turn the light off
./jetpack.py follow                # follow the printer's state
./jetpack.py warning --off         # stop the hot-end warning overriding
./jetpack.py safe strobing         # style in the safe temperature band
./jetpack.py danger static
./jetpack.py h2d printing green    # h2d per-state color (the web UI cannot)
./jetpack.py rgb-reset
./jetpack.py restart
./jetpack.py palette blue --id 3   # web UI swatches, changes no light
```

Host defaults to `192.168.31.142`; override with `--host` or `$JETPACK_HOST`.

## Home Assistant

### Install via HACS

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=weiting-tw&repository=panda-jetpack&category=integration)

The button above opens this repository directly in your own Home Assistant.
Click **Download**, then restart Home Assistant.

Adding it by hand instead: HACS → ⋮ → **Custom repositories** → paste
`https://github.com/weiting-tw/panda-jetpack`, category **Integration** → Add →
Download → restart.

### Install manually

Copy `custom_components/panda_jetpack/` into your `config/custom_components/`
and restart Home Assistant.

### Set it up

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=panda_jetpack)

Or: Settings → Devices & Services → Add Integration → **Panda Jetpack**. Enter
the device's IP address.

| Entity | Covers |
|---|---|
| `light` | on/off, brightness, RGB, effect (10 modes) |
| `switch` × 2 | follow printer, warning override |
| `select` × 2 | safe / danger temperature style |
| `number` | effect speed |
| `button` × 2 | reset light settings, restart |
| service `set_h2d_color` | h2d per-state color |

The h2d colors are exposed read-only as light attributes (`h2d_idle_color`,
`h2d_printing_color`, `h2d_error_color`) and written via the service — they are
parameters of one effect, not three separate lights.

## Protocol

Port 80 only; every path except `/` redirects to a captive portal. All control
goes over WebSocket `ws://<ip>/ws` as `{"<root>": {<field>: <value>}}`. The only
POST is firmware OTA.

Two quirks: the device **pushes its full state on connect**, and it **never
replies to anything**. "No response" is not evidence of failure — the only way
to confirm a change is to disconnect, reconnect, and read the state.

| Root | Messages |
|---|---|
| `settings` | `rgb_info_mode`, `rgb_rgba` (+`rgb_state_index`), `rgb_info_brightness`, `rgb_info_speed`, `on`, `follow`, `warning_override`, `safe_effect`, `danger_effect`, `rgb_reset`, `reset`, `factory_reset`, `language` |
| `block` | `blockID` + `blockrgba` — swatches, **not LEDs** |
| `wifi` | `ssid`+`password`, `scan` |
| `ap` | `ssid`+`password`+`ip`, `on` |
| `sta` | `hostname` |
| `printer` | `name`+`sn`+`access_code`+`ip`, `scan`, `disconnect` |

### Effect modes

The value sent is the index into the web UI's `g_rgb_type_str`, **not** the N in
its `rgb_info_modeN` translation strings — they diverge after 7. Hot-end warning
is **7**, not 8.

`0` static · `1` breathing · `2` strobing · `3` wave · `4` marquee · `5` cycle ·
`6` rainbow · `7` warning · `8` fan · `9` h2d

Colors are `#RRGGBBAA`.

### h2d colors

`h2d` (mode 9) has three colors for the printer's idle / printing / error
states, selected by `rgb_state_index` 0/1/2 alongside `rgb_rgba`.

Sending an index writes **both** `list3[0].h2d_rgba[i]` and `list2[9].rgb_rgba`.
Omitting it writes only `list2[9]`. The firmware does not range-check the index
— sending 3 writes to slot 2.

## Firmware bugs found in V1.0.0

The web UI **cannot set the h2d colors at all**, due to three separate bugs:

1. It checks `colorButton_id==8` before attaching `rgb_state_index`, but h2d is
   `9` — so selecting h2d always takes the branch that omits the index.
2. `querySelector('.idle.color-item')` never matches; the buttons are created
   with classes `Idle` / `Printing` / `Printer-Error`.
3. The seven buttons in the h2d panel bind `show_note_h2d_printer` (show help),
   not a color picker — so `state_color_list[9]` is never set.

The protocol itself is fine. `./jetpack.py h2d` and the `set_h2d_color` service
work by sending the index the UI forgets.

## Known limits

- **Brightness and speed cannot be read back.** The `list2` the device reports
  holds stored defaults, not live values — the light really does dim, but the
  numbers never move. Both tools track what they sent; after a Home Assistant
  restart the displayed value falls back to `list2` and may not match reality.
- **Color, brightness and speed are per-effect**, not global. They apply to
  whichever effect is currently selected.
- The device pushes nothing; the integration re-reads every 30 s.
- `follow` is verified as a flag but its visual behaviour needs a live print.
- `restart` sends correctly, but the device answers again within ~2 s, so an
  actual reboot is unconfirmed.

## Disproven

- `blockID` 0–19 are **not** LEDs — they are the 20 swatches in the lower half
  of the web UI's color page. Changing them lights up nothing.
- `ws_theme` (recoloring the 15 print-stage GIFs) is **not implemented** in
  V1.0.0: no `theme` root anywhere in the UI, `theme_item_recolor_create` called
  zero times, `id_card_theme_gif` absent from the static HTML, and sending both
  shapes leaves the state's top-level keys unchanged.

## Not implemented

`factory_reset` (clears WiFi — too easy to brick), `wifi scan`,
`printer scan/bind`, and GIF upload via `POST /ota` (writes to flash).

## License

MIT
