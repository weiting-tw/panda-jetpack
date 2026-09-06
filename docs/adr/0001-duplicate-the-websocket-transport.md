# 1. Duplicate the WebSocket transport across the CLI/integration seam

Date: 2026-09-06

## Status

Accepted

## Context

This repository ships two things that talk to the same device:

- `jetpack.py`, a command-line tool.
- `custom_components/panda_jetpack/`, a Home Assistant integration.

Both have to speak the device's WebSocket protocol, and each carries its own
client: a synchronous one in `jetpack.py` (the `Ws` class, plus `send` and
`fetch_state`), and an asynchronous one in `ws.py`. Roughly fifty lines are
duplicated — the handshake request, the frame encoder, the 126/127 length
forms, and the connect/send/close and connect/read/close flows.

An architecture review flagged this. It is worth recording why it stays.

Three constraints pin it in place.

**The CLI must run on the stock system interpreter.** macOS grants "local
network" access per executable. Homebrew replaces its `python3` binary on every
upgrade, which resets that grant, and connections to devices on the same subnet
then fail with `EHOSTUNREACH` while `ping` and `curl` still work. Pinning the
shebang to `/usr/bin/python3` sidesteps that entirely. The stock interpreter has
no third-party packages, so the CLI cannot depend on anything.

**The CLI must stay a single file.** Its value is that you can copy `jetpack.py`
onto any Mac and run it. A shared module — even a dependency-free one inside
this repository — breaks that: the file stops being self-contained.

**The integration must be asynchronous and self-contained.** It runs on Home
Assistant's event loop, so a blocking socket client is not an option. It is also
distributed by HACS, which ships only the contents of
`custom_components/panda_jetpack/`; it cannot reach up to `jetpack.py`.

So neither side can import the other, and a third shared module would break the
CLI's single-file property.

## Decision

Keep the two transport implementations separate. Do not extract a shared
protocol module.

Contain the drift risk with tests instead. `tests/test_protocol.py` pins both
copies:

- both encoders produce the same frame for the same text, across both extended
  length forms, differing only in the random mask;
- both decoders read a frame shaped the way the device actually sends one.

The protocol *semantics* that matter most are pinned against both copies too:
the mode index order in `tests/test_protocol.py`, and the redaction contract in
`tests/test_redact.py`.

One difference between the copies is deliberate and should not be "fixed" by
making them identical: the async copy unmasks incoming frames defensively and
handles the close opcode, while the sync copy assumes the server does not mask.
RFC 6455 forbids a server from masking and the device complies, so the sync
copy is correct; the async copy is merely more defensive because it runs
unattended inside Home Assistant.

## Consequences

**Accepted.** About fifty lines exist twice. A fix to the framing in one copy
does not reach the other on its own.

**Mitigated.** The shared tests fail if the copies diverge in what they put on
the wire or accept off it. That is the property that actually matters; identical
source is not.

**Retained.** The CLI stays copyable and dependency-free, which is the whole
reason it exists in the form it does. The integration stays HACS-installable
without reaching outside its own directory.

**Revisit if** the CLI ever gains a dependency for another reason, or stops
needing to be a single file. At that point the shared module becomes free and
this decision should be reversed.

## Alternatives considered

**A shared `_protocol.py` that both import.** Rejected: breaks the CLI's
single-file property, and HACS would not ship a file outside
`custom_components/panda_jetpack/`.

**Make the integration import `jetpack.py`.** Rejected: it would put a blocking
socket client on Home Assistant's event loop, and the file is not inside the
component directory HACS distributes.

**Make the CLI import the integration's `ws.py`.** Rejected: same single-file
problem, and it would drag the `custom_components` tree along with it.

**Generate one copy from the other at build time.** Rejected: adds a build step
to a project whose CLI is deliberately buildless, and the generated file would
still have to be committed for the single-file property to hold.
