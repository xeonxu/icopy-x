"""The mirror client must open on X11 and macOS, not only on Windows.

Tk's colour-key transparency ('-transparentcolor') exists only on Windows; an
X11 root raises TclError, which used to abort window creation with a traceback
before the client could connect. The surround then has to be painted in a
neutral colour, because the magenta key would otherwise be a glaring frame.
"""

import importlib.util
import os

import pytest

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'tools', 'screen_mirror', 'mirror_client.py')


@pytest.fixture(scope='module')
def client():
    spec = importlib.util.spec_from_file_location('mirror_client_under_test', _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _WindowsRoot:
    def __init__(self):
        self.attributes_seen = []

    def attributes(self, name, value):
        self.attributes_seen.append((name, value))


class _X11Root:
    def attributes(self, name, value):
        raise AssertionError('TclError') if False else (_ for _ in ()).throw(
            RuntimeError('bad attribute "-transparentcolor"'))


def test_windows_gets_the_real_colour_key(client):
    root = _WindowsRoot()
    assert client.enable_color_key(root) == client.KEY_COLOR
    assert root.attributes_seen == [('-transparentcolor', client.KEY_COLOR)]


def test_x11_falls_back_to_a_neutral_surround(client):
    assert client.enable_color_key(_X11Root()) == client.SURROUND_FALLBACK


def test_the_fallback_is_not_the_magenta_key(client):
    assert client.SURROUND_FALLBACK != client.KEY_COLOR


def test_the_surround_colour_is_decoded_for_the_mask(client):
    assert client.rgb_of(client.KEY_COLOR) == (255, 0, 255)
    assert client.rgb_of(client.SURROUND_FALLBACK) == (16, 16, 16)


def test_the_window_uses_the_returned_colour_as_its_background(client):
    """The canvas must not hardcode the key, or X11 paints a magenta frame."""
    source = open(_PATH).read()
    assert 'bg=self._transparent_color' in source
    assert "bg=TRANSPARENT" not in source
