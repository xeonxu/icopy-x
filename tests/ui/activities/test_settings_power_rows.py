"""The Settings menu offers Shutdown and Reboot, and never hides a row.

Spec: the Settings menu gains Shutdown and Reboot items.  Five rows fill the
200 px content area exactly, so a build that adds a row (the Ethernet mirror
does) must scroll the window instead of drawing over the title.
"""

import pytest

import actstack
import power
import resources
from tests.ui.conftest import MockCanvas
from _constants import KEY_UP, KEY_DOWN, KEY_OK, KEY_PWR


@pytest.fixture(autouse=True)
def _setup(monkeypatch, activity_workers):
    actstack._reset()
    actstack._canvas_factory = MockCanvas
    import settings
    monkeypatch.setattr(settings, 'getScreenMirror', lambda: 0)
    monkeypatch.setattr(settings, 'setScreenMirror', lambda v: None)
    yield
    actstack._reset()


@pytest.fixture
def power_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(power, 'shutdown', lambda *a, **k: calls.append('shutdown'))
    monkeypatch.setattr(power, 'reboot', lambda *a, **k: calls.append('reboot'))
    return calls


def _open():
    from activity_main import SettingsMenuActivity
    return actstack.start_activity(SettingsMenuActivity)


def _texts(activity):
    canvas = activity.getCanvas()
    return [canvas.itemcget(item, 'text') for item in canvas.find_withtag('settings_row')]


def _walk(activity, row):
    """Move the selection to *row* using the keys a user would press."""
    while activity._selected < row:
        activity.onKeyEvent(KEY_DOWN)
    while activity._selected > row:
        activity.onKeyEvent(KEY_UP)


def test_both_power_rows_are_rendered(power_calls):
    activity = _open()
    _walk(activity, activity._ROW_REBOOT)   # scroll if the list is longer
    texts = _texts(activity)
    assert resources.get_str('shutdown') in texts
    assert resources.get_str('reboot') in texts


def test_shutdown_row_powers_the_device_off(power_calls):
    activity = _open()
    _walk(activity, activity._ROW_SHUTDOWN)
    activity.onKeyEvent(KEY_OK)
    assert power_calls == ['shutdown']


def test_reboot_row_restarts_the_device(power_calls):
    activity = _open()
    _walk(activity, activity._ROW_REBOOT)
    activity.onKeyEvent(KEY_OK)
    assert power_calls == ['reboot']


def test_a_power_row_is_not_reached_by_accident(power_calls):
    """Moving through the menu must never fire a power action."""
    activity = _open()
    for _ in range(activity._ROW_COUNT - 1):
        activity.onKeyEvent(KEY_DOWN)
    for _ in range(activity._ROW_COUNT - 1):
        activity.onKeyEvent(KEY_UP)
    assert power_calls == []


def test_pwr_still_leaves_without_powering_off(power_calls):
    activity = _open()
    activity.onKeyEvent(KEY_PWR)
    assert power_calls == []
    assert actstack.get_current_activity() is not activity


def test_the_window_follows_the_selection(power_calls):
    from activity_main import SettingsMenuActivity
    assert SettingsMenuActivity._visible_start.__doc__

    class SixRows(SettingsMenuActivity):
        _ROW_COUNT = 6
        _VISIBLE_ROWS = 5
        _LABEL_KEYS = dict(SettingsMenuActivity._LABEL_KEYS)
        _LABEL_KEYS[4] = 'shutdown'
        _LABEL_KEYS[5] = 'reboot'

    activity = actstack.start_activity(SixRows)
    assert activity._visible_start() == 0
    for _ in range(5):
        activity.onKeyEvent(KEY_DOWN)
    assert activity._selected == 5
    assert activity._visible_start() == 1
    texts = _texts(activity)
    assert resources.get_str('shutdown') in texts     # row 3, still visible
    assert resources.get_str('screen_mirroring') not in texts
