"""WebSocket frame encoding, and the mode number mapping."""

import asyncio

import pytest

from conftest import const, ws


def _decode(frame: bytes) -> str:
    """Feed the bytes from _text_frame back into the reader.

    StreamReader wants a running loop, and get_event_loop has been deprecated
    since 3.12, so the whole thing runs inside asyncio.run.
    """
    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        reader.feed_eof()
        return await ws._read_text_frame(reader)

    return asyncio.run(run())


@pytest.mark.parametrize("text", [
    "",
    '{"settings":{"rgb_info_mode":9}}',
    "非 ASCII 也要過",   # multi-byte payload, length is in bytes not characters
    "x" * 200,          # crosses the 126 length encoding
    "y" * 70000,        # crosses the 65536 length encoding
])
def test_text_frame_round_trip(text):
    assert _decode(ws._text_frame(text)) == text


def test_client_frames_are_masked():
    """RFC 6455 requires client frames to be masked; the ESP32 checks."""
    frame = ws._text_frame("hi")
    assert frame[0] == 0x81
    assert frame[1] & 0x80


def test_mode_indexes_match_the_web_ui():
    """The value sent is the g_rgb_type_str index, not the UI string number.

    The two diverge after 7, so the hot-end warning is 7 and not 8. Get this
    order wrong and picking "warning" gives you "fan speed".
    """
    assert const.MODES == [
        "static", "breathing", "strobing", "wave", "marquee",
        "cycle", "rainbow", "warning", "fan", "h2d",
    ]
    assert const.MODES.index("warning") == 7
    assert const.MODES.index("h2d") == const.MODE_H2D


def test_h2d_states_are_in_rgb_state_index_order():
    """This order is the rgb_state_index; reversing it writes the wrong slot."""
    assert const.H2D_STATES == ["idle", "printing", "error"]


def test_styles_are_not_modes():
    """Only two temperature styles; a different thing from the ten modes."""
    assert const.STYLES == ["static", "strobing"]
    assert len(const.STYLES) != len(const.MODES)
