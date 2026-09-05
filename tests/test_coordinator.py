"""The coordinator's message vocabulary and mode-keyed optimistic cache.

This is the payoff of moving message assembly into the coordinator: the wire
shapes and the fallback logic can be tested through one interface with a fake
send, no Home Assistant and no network.
"""

import asyncio
import sys
import types

import pytest

# Stub the Home Assistant modules the coordinator imports, so it loads without
# HA installed. We only need the class to instantiate and its methods to run.
def _install_ha_stubs():
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object

    class _Coordinator:
        def __init__(self, *a, **k):
            pass

        async def async_refresh(self):
            self.refreshed = getattr(self, "refreshed", 0) + 1

    upd = types.ModuleType("homeassistant.helpers.update_coordinator")
    upd.DataUpdateCoordinator = _Coordinator
    upd.DataUpdateCoordinator.__class_getitem__ = classmethod(lambda cls, item: cls)

    class _UpdateFailed(Exception):
        pass

    upd.UpdateFailed = _UpdateFailed

    ha = types.ModuleType("homeassistant")
    helpers = types.ModuleType("homeassistant.helpers")
    sys.modules.setdefault("homeassistant", ha)
    sys.modules.setdefault("homeassistant.core", core)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules["homeassistant.helpers.update_coordinator"] = upd


_install_ha_stubs()

import importlib.util
import pathlib

COMPONENT = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "panda_jetpack"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, COMPONENT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ws and util are imported by coordinator; load them under their package names.
_load("jp_ws", "ws.py")
_load("jp_util", "util.py")
_load("jp_const", "const.py")
sys.modules["custom_components"] = types.ModuleType("custom_components")
pkg = types.ModuleType("custom_components.panda_jetpack")
pkg.__path__ = [str(COMPONENT)]
sys.modules["custom_components.panda_jetpack"] = pkg
sys.modules["custom_components.panda_jetpack.ws"] = sys.modules["jp_ws"]
sys.modules["custom_components.panda_jetpack.util"] = sys.modules["jp_util"]
sys.modules["custom_components.panda_jetpack.const"] = sys.modules["jp_const"]
coord_mod = _load("custom_components.panda_jetpack.coordinator", "coordinator.py")


@pytest.fixture
def coord(monkeypatch):
    """A coordinator whose send() records messages instead of hitting the wire.

    One event loop per test, with the lock built inside it -- asyncio.Lock
    binds to the running loop at construction, so it cannot be made in the
    fixture before the loop exists.
    """
    loop = asyncio.new_event_loop()
    c = coord_mod.JetpackCoordinator.__new__(coord_mod.JetpackCoordinator)
    c.host = "test"
    c._lock = loop.run_until_complete(_make_lock())
    c._optimistic = {}
    c.data = {"settings": {"current_mode": 9, "list2": [
        {"rgb_info_mode": 1, "brightness": 40, "speed": 60},
        {"rgb_info_mode": 9, "brightness": 100, "speed": 50},
    ]}}
    c.sent = []
    c._loop = loop

    async def fake_send(host, root, members):
        c.sent.append((root, members))

    async def fake_refresh():
        pass

    monkeypatch.setattr(coord_mod, "send", fake_send)
    c.async_refresh = fake_refresh
    yield c
    loop.close()


async def _make_lock():
    return asyncio.Lock()


def run(coord, coro):
    return coord._loop.run_until_complete(coro)


# -- message shapes ----------------------------------------------------------

def test_apply_light_folds_mode_color_on_into_one_message(coord):
    run(coord, coord.async_apply_light(3, rgb=(255, 0, 0)))
    assert coord.sent == [("settings", {"rgb_info_mode": 3, "on": 1, "rgb_rgba": "#FF0000FF"})]


def test_apply_light_sends_brightness_as_a_second_message(coord):
    run(coord, coord.async_apply_light(3, brightness=80))
    # mode/on first, brightness second -- brightness carries no mode.
    assert coord.sent == [
        ("settings", {"rgb_info_mode": 3, "on": 1}),
        ("settings", {"rgb_info_brightness": 80}),
    ]


def test_toggle_attaches_the_mode(coord):
    run(coord, coord.async_toggle("follow", 1, 9))
    assert coord.sent == [("settings", {"rgb_info_mode": 9, "follow": 1})]


def test_style_does_not_attach_a_mode(coord):
    run(coord, coord.async_set_style("safe_effect", 1))
    assert coord.sent == [("settings", {"safe_effect": 1})]


def test_speed_switches_mode_first(coord):
    run(coord, coord.async_set_speed(9, 30))
    assert coord.sent == [
        ("settings", {"rgb_info_mode": 9}),
        ("settings", {"rgb_info_speed": 30}),
    ]


def test_h2d_color_carries_state_index_and_clamps(coord):
    run(coord, coord.async_set_h2d_color(1, (0, 255, 0)))
    assert coord.sent == [("settings",
        {"rgb_info_mode": 9, "rgb_rgba": "#00FF00FF", "rgb_state_index": 1})]
    coord.sent.clear()
    # Index 3 is out of range; the firmware writes it to slot 2, so we clamp.
    run(coord, coord.async_set_h2d_color(3, (0, 0, 255)))
    assert coord.sent[0][1]["rgb_state_index"] == 2


# -- mode-keyed optimistic cache (the codex bug) -----------------------------

def test_effective_prefers_the_value_we_sent_for_that_mode(coord):
    run(coord, coord.async_set_speed(9, 30))
    assert coord.effective(9, "speed") == 30


def test_effective_is_keyed_by_mode_not_global(coord):
    # Sending speed for mode 9 must not change what mode 1 reports.
    run(coord, coord.async_set_speed(9, 30))
    assert coord.effective(1, "speed") == 60      # mode 1's list2 default, untouched
    assert coord.effective(9, "speed") == 30      # mode 9's sent value


def test_effective_falls_back_to_list2_when_nothing_sent(coord):
    assert coord.effective(9, "brightness") == 100
    assert coord.effective(1, "brightness") == 40


def test_effective_returns_none_for_unknown_mode(coord):
    assert coord.effective(7, "brightness") is None
