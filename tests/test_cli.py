"""CLI input parsing."""

import argparse

import pytest

from conftest import cli, util


@pytest.mark.parametrize("text,expected", [
    ("#FF0000", "#FF0000FF"),
    ("#f00", "#FF0000FF"),
    ("red", "#FF0000FF"),
    ("#0000FFFF", "#0000FFFF"),
    ("BLUE", "#0000FFFF"),
])
def test_parse_color(text, expected):
    assert cli.parse_color(text) == expected


@pytest.mark.parametrize("text", ["nosuchcolor", "#12345", "", "#GGGGGG"])
def test_parse_color_rejects_garbage(text):
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_color(text)


def test_mode_index_accepts_names_and_numbers():
    assert cli.mode_index("h2d") == 9
    assert cli.mode_index("9") == 9
    assert cli.mode_index("WARNING") == 7


@pytest.mark.parametrize("text", ["10", "-1", "nosuchmode"])
def test_mode_index_rejects_out_of_range(text):
    with pytest.raises(argparse.ArgumentTypeError):
        cli.mode_index(text)


def test_h2d_state_index():
    assert cli.h2d_state_index("idle") == 0
    assert cli.h2d_state_index("printing") == 1
    assert cli.h2d_state_index("error") == 2


def test_device_mac_from_ap_ssid():
    """unique_id depends on this; getting it wrong duplicates the device."""
    state = {"ap": {"ssid": "Panda_Jetpack_8CBFEA611A34"}}
    assert util.device_mac(state) == "8C:BF:EA:61:1A:34"


def test_device_mac_falls_back_when_ssid_has_no_mac():
    """Return None on an unexpected SSID format so the caller can use the IP."""
    assert util.device_mac({}) is None
    assert util.device_mac({"ap": {"ssid": "SomethingElse"}}) is None
