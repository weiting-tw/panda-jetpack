# Context

The project's vocabulary. The device's own field names contradict themselves in
a few places; what follows is the wording **we** use consistently. Fields sent
to the device keep its own spelling and are not covered here.

## Jetpack

A BIQU Panda Jetpack V2: the **hotend shroud** that mounts on a Bambu Lab
P1/X1 print head, carrying a ring of RGB LEDs. It is not a printer and not a
Klipper host. "The device" always means this; "the printer" always means the
Bambu printer it is bound to.

## Mode (light effect)

How the ring behaves. Ten of them, numbered 0-9: static, breathing, strobing,
wave, marquee, cycle, rainbow, warning, fan, h2d. Exactly one is active.

In Home Assistant this concept is called **effect**, HA's existing word for it,
and `effect_list` holds these ten. The device's fields are `rgb_info_mode` and
`current_mode`.

## Style (temperature style)

How the light behaves once the nozzle temperature enters the safe or the danger
band. Only two: static and strobing. Safe and danger each have their own,
independent of each other.

**Deliberately not called an effect.** The device writes them as `safe_effect` /
`danger_effect`, but "effect" already means the ten modes above, and one word
for two things will eventually confuse someone. Externally it is always a
style; only the wire field keeps the device's spelling.

The device is inconsistent with itself here too: it is written as `safe_effect`
and read back as `safe_current_mode`.

## H2D colors

Three colors belonging to the h2d effect, mapped to the printer's **idle /
printing / error** states. They are parameters of that one mode, **not three
separate lights** — the device has a single LED ring. In Home Assistant they
are therefore light attributes plus a service, with no entities of their own.

(H2D is a Bambu Lab printer model; this effect imitates that machine's
lighting.)

## Palette (swatches)

The 20 colors in the device's `block` root, `blockID` 0-19. They are the custom
swatches in the lower half of the web UI's color page (titled "color
definitions"), **not LEDs**. Changing them lights up nothing.

## Follow (follow printer)

A global toggle. While on, the current print stage picks the effect and any
manually selected mode is overridden.

## Warning override

A global toggle. While on, the warning effect takes over from the selected mode
when the nozzle overheats.
