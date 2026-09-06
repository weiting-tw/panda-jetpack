"""WebSocket frame encoding, and the mode number mapping."""

import asyncio
import socket
import struct

import pytest

from conftest import cli, const, ws


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


# -- the CLI's own framing ---------------------------------------------------
#
# The CLI carries a second, synchronous copy of the frame encoder (see
# docs/adr/0001-duplicate-the-websocket-transport.md for why it is not shared).
# Duplication is only safe while both copies are pinned, so the sync copy gets
# the same round-trip check as the async one.

class _FakeSocket:
    """Records what was written; raises timeout when read, like an idle peer."""

    def __init__(self, to_read=b""):
        self.written = b""
        self._to_read = to_read

    def sendall(self, data):
        self.written += data

    def recv(self, _n):
        if self._to_read:
            chunk, self._to_read = self._to_read, b""
            return chunk
        raise socket.timeout()

    def settimeout(self, _s):
        pass


def _cli_ws(buf=b"", to_read=b""):
    """A CLI Ws with the handshake skipped and a fake socket attached."""
    ws = cli.Ws.__new__(cli.Ws)
    ws.sock = _FakeSocket(to_read)
    ws.buf = buf
    return ws


@pytest.mark.parametrize("text", [
    "",
    '{"settings":{"rgb_info_mode":9}}',
    "非 ASCII 也要過",
    "x" * 200,
    "y" * 70000,
])
def test_cli_and_async_encoders_agree(text):
    """Both copies must produce the same frame, mask aside.

    The mask is random, so compare the header shape and the unmasked payload.
    """
    ws_frame = ws._text_frame(text)
    cli_sock = _cli_ws()
    cli_sock.send_text(text)
    cli_frame = cli_sock.sock.written

    assert cli_frame[0] == ws_frame[0] == 0x81
    assert cli_frame[1] == ws_frame[1]          # same length encoding + mask bit
    assert len(cli_frame) == len(ws_frame)

    def unmask(frame):
        n = frame[1] & 0x7F
        off = 2 if n < 126 else (4 if n == 126 else 10)
        mask = frame[off:off + 4]
        body = frame[off + 4:]
        return bytes(b ^ mask[i % 4] for i, b in enumerate(body))

    assert unmask(cli_frame) == unmask(ws_frame) == text.encode()


def _server_frame(text):
    """An unmasked text frame, the way the device actually sends one.

    RFC 6455 forbids the server from masking. The CLI's decoder relies on that
    and does not unmask; the async copy unmasks defensively anyway. That
    asymmetry is deliberate -- see the ADR -- so the decode tests below feed
    each copy what the device really puts on the wire.
    """
    data = text.encode()
    n = len(data)
    if n < 126:
        return bytes([0x81, n]) + data
    if n < 65536:
        return bytes([0x81, 126]) + struct.pack(">H", n) + data
    return bytes([0x81, 127]) + struct.pack(">Q", n) + data


@pytest.mark.parametrize("text", [
    '{"settings":{"on":1}}',
    "非 ASCII 也要過",
    "x" * 200,      # 126 length form
    "y" * 70000,    # 127 length form
])
def test_both_decoders_read_a_real_device_frame(text):
    """Both copies must read what the device actually sends."""
    assert _cli_ws(buf=_server_frame(text)).recv_text(seconds=0) == [text]
    assert _decode(_server_frame(text)) == text
