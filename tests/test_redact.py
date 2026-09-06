"""Credentials must never leak. One contract, checked against both copies.

/ws has no authentication and dumps three plaintext secrets on connect: the
user's WiFi password, the device's AP password, and the bound printer's access
code. Keeping them out of terminals, logs, entity attributes and diagnostics is
the one absolute rule in this project.

There are two implementations, because the CLI must run on the stock
interpreter and cannot import from the Home Assistant tree. They deliberately
differ in what they substitute -- a visible "<redacted>" marker for a human
reading a terminal, None for machine-read data. That cosmetic difference is
allowed. What follows is the part that is not: the safety contract, asserted
against both copies so neither can drift out of it.
"""

import json

import pytest

from conftest import cli, util


def _fake(label: str) -> str:
    """A stand-in secret, built rather than written as a literal.

    Secret scanners flag credential-shaped literals, and a fixture has no
    reason to look real -- a realistic-looking value here once tripped an alert
    on a commit that contained nothing real. Keep these obviously fake.
    """
    return f"NOT-A-REAL-SECRET-{label}"


# The two adapters at this seam. Every contract test below runs against both.
IMPLEMENTATIONS = [
    pytest.param(cli.redact, cli._SECRET_KEYS, id="cli"),
    pytest.param(util.redact, util.SECRET_KEYS, id="integration"),
]

# Shaped like a real state dump, with secrets at several depths: top-level
# roots, and nested inside a list of dicts (which the device does not send
# today, but a firmware update could).
STATE = {
    "wifi": {"ssid": "home-network", "password": _fake("wifi"), "scan": 0},
    "ap": {"ssid": "Panda_Jetpack_8CBFEA611A34", "password": _fake("ap"), "on": 1},
    "sta": {"hostname": "PandaJetpack", "ip": "192.168.31.142"},
    "printer": {"name": "number 2", "sn": "01P199552400005",
                "access_code": _fake("access"), "ip": "192.168.31.73"},
    "settings": {
        "on": 1, "current_mode": 9, "follow": 0,
        "list2": [{"rgb_info_mode": 0, "rgb_rgba": "#0000FFFF", "brightness": 50}],
        "list3": [{"h2d_rgba": ["#FFFFFFFF", "#FFFFFFFF", "#FF0000FF"]}],
    },
    # A shape the device does not send today; a firmware update might.
    "future_root": [{"label": "x", "password": _fake("nested")}],
}

SECRETS = tuple(_fake(n) for n in ("wifi", "ap", "access", "nested"))


def _walk(obj, path=()):
    """Every (path, key, value) pair in a nested structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path, k, v
            yield from _walk(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, path + (i,))


# -- the contract ------------------------------------------------------------

@pytest.mark.parametrize("redact,keys", IMPLEMENTATIONS)
def test_no_secret_value_survives_anywhere(redact, keys):
    """The whole point. Serialise the result and grep it."""
    dumped = json.dumps(redact(STATE), ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in dumped


@pytest.mark.parametrize("redact,keys", IMPLEMENTATIONS)
def test_every_secret_key_is_still_present_but_changed(redact, keys):
    """Redaction replaces the value; it must not drop the key.

    Dropping it would hide that the device even has a password, and would make
    the output structurally different from the device's own.
    """
    out = redact(STATE)
    for _, key, value in _walk(STATE):
        if key in keys and value:
            found = [v for _, k, v in _walk(out) if k == key]
            assert found, f"{key} disappeared from the output"
            assert value not in found, f"{key} kept its original value"


@pytest.mark.parametrize("redact,keys", IMPLEMENTATIONS)
def test_everything_that_is_not_a_secret_is_untouched(redact, keys):
    """Redaction must not damage the data the caller actually wants."""
    out = redact(STATE)
    assert out["settings"] == STATE["settings"]
    assert out["sta"] == STATE["sta"]
    assert out["wifi"]["ssid"] == STATE["wifi"]["ssid"]
    assert out["wifi"]["scan"] == STATE["wifi"]["scan"]
    assert out["ap"]["ssid"] == STATE["ap"]["ssid"]
    assert out["ap"]["on"] == STATE["ap"]["on"]
    assert out["printer"]["sn"] == STATE["printer"]["sn"]
    assert out["printer"]["ip"] == STATE["printer"]["ip"]
    assert out["future_root"][0]["label"] == "x"


@pytest.mark.parametrize("redact,keys", IMPLEMENTATIONS)
def test_secrets_nested_in_lists_are_redacted(redact, keys):
    """A firmware update could put a secret somewhere new. Recursion must reach it."""
    buried = _fake("buried")
    out = redact({"anything": [{"deep": [{"password": buried}]}]})
    assert buried not in json.dumps(out)


@pytest.mark.parametrize("redact,keys", IMPLEMENTATIONS)
def test_input_is_not_mutated(redact, keys):
    """Callers keep using the original; redaction returns a new structure."""
    original = json.dumps(STATE, sort_keys=True)
    redact(STATE)
    assert json.dumps(STATE, sort_keys=True) == original


@pytest.mark.parametrize("redact,keys", IMPLEMENTATIONS)
def test_survives_unexpected_shapes(redact, keys):
    """A firmware change adding or dropping fields must not break redaction."""
    assert redact({}) == {}
    assert redact([]) == []
    assert redact({"wifi": {}}) == {"wifi": {}}
    assert redact("a bare string") == "a bare string"
    assert redact(None) is None
    # An empty secret holds nothing to leak; both copies must still not raise.
    redact({"wifi": {"password": ""}})


@pytest.mark.parametrize("redact,keys", IMPLEMENTATIONS)
def test_covers_all_three_credentials_the_device_leaks(redact, keys):
    """Pin the actual field names, not just whatever the key list happens to hold."""
    values = {name: _fake(name) for name in ("w", "a", "p")}
    out = redact({
        "wifi": {"password": values["w"]},
        "ap": {"password": values["a"]},
        "printer": {"access_code": values["p"]},
    })
    dumped = json.dumps(out)
    for secret in values.values():
        assert secret not in dumped


def test_both_copies_cover_the_same_keys():
    """The two lists are maintained separately across the packaging seam."""
    assert set(cli._SECRET_KEYS) == set(util.SECRET_KEYS)
