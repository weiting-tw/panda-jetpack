"""Credentials must never leak.

/ws has no authentication and dumps three plaintext secrets on connect. This is
the one absolute rule in the project: they must not reach a terminal, a log, an
entity attribute, or any file. The CLI and the integration each have their own
implementation, so both are tested.
"""

import json

from conftest import cli, util

STATE = {
    "wifi": {"ssid": "home", "password": "hunter2"},
    "ap": {"ssid": "Panda_Jetpack_8CBFEA611A34", "password": "apsecret", "on": 1},
    "printer": {"name": "p1", "sn": "01P199", "access_code": "12345678"},
    "settings": {"on": 1, "list2": [{"rgb_info_mode": 0, "rgb_rgba": "#0000FFFF"}]},
}
SECRETS = ("hunter2", "apsecret", "12345678")


def test_cli_redact_removes_every_secret():
    dumped = json.dumps(cli.redact(STATE), ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in dumped


def test_integration_redact_removes_every_secret():
    dumped = json.dumps(util.redact(STATE), ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in dumped


def test_redact_keeps_everything_else():
    """Redaction must not damage anything else -- settings stay untouched."""
    for redact in (cli.redact, util.redact):
        out = redact(STATE)
        assert out["settings"] == STATE["settings"]
        assert out["ap"]["ssid"] == STATE["ap"]["ssid"]
        assert out["printer"]["sn"] == STATE["printer"]["sn"]


def test_redact_survives_unexpected_shapes():
    """A firmware update adding or dropping fields must not break redaction."""
    for redact in (cli.redact, util.redact):
        assert redact({}) == {}
        assert redact({"wifi": {"password": None}})["wifi"]["password"] is None
        assert redact([{"password": "x"}])[0]["password"] != "x"


def test_both_implementations_cover_the_same_keys():
    """The two implementations are maintained separately; keep them in sync."""
    assert set(cli._SECRET_KEYS) == set(util.SECRET_KEYS)
