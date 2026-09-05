"""A minimal asyncio WebSocket client for the Panda Jetpack.

Deliberately not aiohttp's ws_connect. Node's built-in WebSocket cannot talk to
this device because it offers Sec-WebSocket-Extensions: permessage-deflate,
which the ESP32 implementation rejects; doing the handshake by hand guarantees
we offer no extensions at all. All that is needed here is connect, read text
frames, write text frames -- under a hundred lines, versus betting on whether a
library will negotiate compression.

Two device behaviours differ from a normal WebSocket service, noted here so
nobody has to rediscover them:

1. It pushes a full state dump the moment you connect. You never ask for it.
2. It never replies to anything, not even to settings known to work. So "no
   response" is not evidence of failure -- the only trustworthy way to observe
   a change is to close the connection, reconnect, and read the state.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
from typing import Any

WS_PORT = 80
CONNECT_TIMEOUT = 8
READ_TIMEOUT = 6


class JetpackError(Exception):
    """A connection or protocol level failure."""


async def _handshake(host: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, WS_PORT), timeout=CONNECT_TIMEOUT
        )
    except (OSError, asyncio.TimeoutError) as err:
        raise JetpackError(f"cannot reach {host}: {err}") from err

    key = base64.b64encode(os.urandom(16)).decode()
    writer.write(
        f"GET /ws HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Origin: http://{host}\r\n\r\n".encode()
    )
    try:
        await writer.drain()
        head = await asyncio.wait_for(
            reader.readuntil(b"\r\n\r\n"), timeout=CONNECT_TIMEOUT
        )
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as err:
        writer.close()
        raise JetpackError(f"connection dropped during handshake: {err}") from err

    status = head.split(b"\r\n", 1)[0]
    if b" 101 " not in status:
        writer.close()
        raise JetpackError(f"handshake failed: {status!r}")
    return reader, writer


async def _read_text_frame(reader: asyncio.StreamReader) -> str | None:
    """Read one frame. Returns the payload for text frames, None otherwise."""
    hdr = await reader.readexactly(2)
    opcode = hdr[0] & 0x0F
    masked = bool(hdr[1] & 0x80)
    length = hdr[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", await reader.readexactly(8))[0]
    # Per the RFC the server should not mask, but unmasking anyway costs
    # nothing and beats losing the whole connection over it.
    mask = await reader.readexactly(4) if masked else b""
    payload = await reader.readexactly(length) if length else b""
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    if opcode == 0x8:
        raise JetpackError("device closed the connection")
    if opcode != 0x1:
        return None
    return payload.decode("utf-8", "replace")


def _text_frame(text: str) -> bytes:
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
    return bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data))


async def _close(writer: asyncio.StreamWriter) -> None:
    try:
        writer.close()
        await writer.wait_closed()
    except (OSError, asyncio.TimeoutError):
        pass


async def fetch_state(host: str) -> dict[str, Any]:
    """Connect, take the state dump it opens with, disconnect."""
    reader, writer = await _handshake(host)
    try:
        deadline = asyncio.get_running_loop().time() + READ_TIMEOUT
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise JetpackError("device sent no state")
            try:
                text = await asyncio.wait_for(_read_text_frame(reader), timeout=remaining)
            except asyncio.TimeoutError as err:
                raise JetpackError("device sent no state") from err
            except (asyncio.IncompleteReadError, OSError) as err:
                raise JetpackError(f"connection dropped while reading state: {err}") from err
            if text is None:
                continue
            try:
                data = json.loads(text)
            except ValueError as err:
                raise JetpackError(f"state is not valid JSON: {err}") from err
            if isinstance(data, dict):
                return data
    finally:
        await _close(writer)


async def send(host: str, root: str, members: dict[str, Any]) -> None:
    """Send one setting. The device applies it on disconnect; there is no ack."""
    reader, writer = await _handshake(host)
    try:
        # Swallow the opening state dump so it does not sit in the buffer.
        # Not receiving it is harmless.
        try:
            await asyncio.wait_for(_read_text_frame(reader), timeout=2)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, OSError, JetpackError):
            pass
        writer.write(_text_frame(json.dumps({root: members})))
        await writer.drain()
    except OSError as err:
        raise JetpackError(f"failed to send setting: {err}") from err
    finally:
        await _close(writer)
