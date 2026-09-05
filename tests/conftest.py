"""Load the modules under test by file path.

Deliberately not a package import: custom_components/panda_jetpack/__init__.py
imports Home Assistant, and the whole point of these tests is that they run
without it.
"""

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "panda_jetpack"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cli = _load("jetpack_cli", ROOT / "jetpack.py")
util = _load("jetpack_util", COMPONENT / "util.py")
ws = _load("jetpack_ws", COMPONENT / "ws.py")
const = _load("jetpack_const", COMPONENT / "const.py")
