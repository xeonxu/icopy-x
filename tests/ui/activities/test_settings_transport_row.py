"""The mirror link is chosen from Settings and applied without a restart.

Field risk: the transport is only read when ``MirrorService`` starts. Flipping
the row used to persist the choice and change nothing until the app was
restarted, so the PC kept seeing the old link (a COM port that never appeared,
or a TCP port that never listened).
"""

import sys
import types

import pytest

from tests.ui.conftest import MockCanvas
import actstack
from _constants import KEY_DOWN, KEY_OK


class MirrorRecorder:
    """Stands in for MirrorService and records start/stop order."""

    def __init__(self):
        self._events = []

    def start(self):
        self._events.append('start')

    def stop(self):
        self._events.append('stop')

    def snapshot(self):
        return list(self._events)


@pytest.fixture(autouse=True)
def _setup_actstack():
    actstack._reset()
    actstack._canvas_factory = lambda: MockCanvas()
    yield
    actstack._reset()


@pytest.fixture
def mirror(monkeypatch):
    """Stub the persisted settings and the mirror service."""
    recorder = MirrorRecorder()
    store = {'mirror': 0, 'transport': 0}

    settings_mod = types.ModuleType('settings')
    settings_mod.getScreenMirror = lambda: store['mirror']
    settings_mod.setScreenMirror = lambda value: store.__setitem__('mirror', value)
    settings_mod.getMirrorTransport = lambda: store['transport']
    settings_mod.setMirrorTransport = lambda value: store.__setitem__('transport', value)
    monkeypatch.setitem(sys.modules, 'settings', settings_mod)

    import lib.mirror_service as service_mod
    monkeypatch.setattr(service_mod, 'get_service', lambda: recorder)

    return recorder, store


def _open_settings():
    from activity_main import SettingsMenuActivity
    return actstack.start_activity(SettingsMenuActivity)


def _walk_to_transport(activity):
    """The mirror row is selected when the screen opens."""
    activity.onKeyEvent(KEY_DOWN)
    assert activity._selected == activity._ROW_TRANSPORT


def test_the_transport_row_shows_the_configured_link(mirror):
    import resources

    _, store = mirror
    store['transport'] = 0
    activity = _open_settings()

    assert resources.get_str('mirror_transport') in activity.getCanvas().get_all_text()
    assert resources.get_str('link_serial') in activity.getCanvas().get_all_text()


def test_flipping_the_row_persists_the_other_link(mirror):
    import resources

    _, store = mirror
    activity = _open_settings()
    _walk_to_transport(activity)

    activity.onKeyEvent(KEY_OK)

    assert store['transport'] == 1, 'the choice must be persisted'
    texts = activity.getCanvas().get_all_text()
    assert resources.get_str('link_ethernet') in texts
    assert resources.get_str('link_serial') not in texts


def test_a_link_change_restarts_a_running_mirror(mirror, activity_workers):
    recorder, store = mirror
    store['mirror'] = 1
    activity = _open_settings()
    _walk_to_transport(activity)

    activity.onKeyEvent(KEY_OK)

    assert len(activity_workers) == 1, 'the change must be applied now'
    activity_workers[0].run()
    assert recorder.snapshot() == ['stop', 'start'], \
        'the old listener has to be closed before the new link opens'
