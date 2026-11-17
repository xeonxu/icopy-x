"""Where the client looks for the device over the network link.

The default matches the profile a device keeps when nobody changed it (Gateway
on 10.1.1.0/24). Change the Range or the Role and the address moves, so both
escapes the operator has - the command line and $ICOPY_MIRROR_TCP - must win
over the default.
"""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    'mirror_client_target',
    str(Path(__file__).resolve().parents[2] / 'tools' / 'screen_mirror' / 'mirror_client.py'))
mc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mc)


@pytest.fixture(autouse=True)
def _no_ambient_override(monkeypatch):
    monkeypatch.delenv('ICOPY_MIRROR_TCP', raising=False)


def test_the_default_is_the_gateway_address():
    assert mc.link_target() == '10.1.1.1:7767'


def test_the_environment_overrides_the_default(monkeypatch):
    monkeypatch.setenv('ICOPY_MIRROR_TCP', '192.168.137.2:7767')
    assert mc.link_target() == '192.168.137.2:7767'


def test_the_command_line_overrides_the_environment(monkeypatch):
    monkeypatch.setenv('ICOPY_MIRROR_TCP', '192.168.137.2:7767')
    assert mc.link_target('10.42.0.2:7767') == '10.42.0.2:7767'
