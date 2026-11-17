"""Tests for BacklightActivity.

The screen holds two settings now: the level (which the hardware shows back
immediately) and how long the panel stays lit before it goes dark.

Ground truth for the level half of the screen:
    - Title: "Backlight" (resources.get_str('backlight'))
    - Values: "Low", "Middle", "High" (blline1, blline2, blline3)
    - M1: "" (empty), M2: "" (empty)
    - OK: advance the level, save it, stay on screen
    - PWR: restore the level the screen was opened with, finish()
    - Config key: "backlight", values 0/1/2

Ground truth for the timeout half:
    - Label: "Screen off" (net_sleep), values Off / 1 / 2 / 5 / 10 minutes
    - Persisted as usb_net_link_timeout; the watcher re-reads it every poll, so
      choosing it never restarts the USB link.
"""

import sys
import types
import pytest

from tests.ui.conftest import MockCanvas
import actstack
import resources
from _constants import KEY_UP, KEY_DOWN, KEY_OK, KEY_M1, KEY_M2, KEY_PWR


# ---------------------------------------------------------------
# Mock config infrastructure
# ---------------------------------------------------------------

class MockConfig:
    """In-memory config store for testing."""

    def __init__(self):
        self._store = {}

    def getValue(self, key):
        if key in self._store:
            return str(self._store[key])
        raise KeyError(key)

    def setKeyValue(self, key, value):
        self._store[key] = value


class MockSettings:
    """Mock settings.so module."""

    # Hardware brightness values matching middleware/settings.py
    # Ground truth (strace 2026-04-10): Low=20, Middle=50, High=100
    _HW_VALUES = [20, 50, 100]  # Low, Middle, High

    def __init__(self, config):
        self._config = config

    def getBacklight(self):
        val = self._config.getValue('backlight')
        return int(val)

    def setBacklight(self, level):
        self._config.setKeyValue('backlight', level)
        # Chain to hmi_driver like the real settings.setBacklight()
        hw_val = self.fromLevelGetBacklight(level)
        try:
            import hmi_driver
            hmi_driver.setbaklight(hw_val)
        except Exception:
            pass

    def fromLevelGetBacklight(self, level):
        """Convert UI level index (0/1/2) to GD32 hardware value."""
        if 0 <= level < len(self._HW_VALUES):
            return self._HW_VALUES[level]
        return self._HW_VALUES[-1]

    def getUsbNetLinkTimeout(self):
        return int(self._config._store.get('usb_net_link_timeout', 0))

    def setUsbNetLinkTimeout(self, value):
        self._config.setKeyValue('usb_net_link_timeout', int(value))


class MockHmiDriver:
    """Mock hmi_driver.so -- records setbaklight calls."""

    def __init__(self):
        self.calls = []

    def setbaklight(self, level):
        self.calls.append(('setbaklight', level))


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------

@pytest.fixture(autouse=True)
def _setup_actstack():
    """Reset actstack and install MockCanvas factory for each test."""
    actstack._reset()
    actstack._canvas_factory = lambda: MockCanvas()
    yield
    actstack._reset()


@pytest.fixture
def mock_config():
    """Provide a fresh MockConfig."""
    return MockConfig()


@pytest.fixture
def mock_hmi():
    """Provide a fresh MockHmiDriver."""
    return MockHmiDriver()


@pytest.fixture
def install_mocks(mock_config, mock_hmi):
    """Install config, settings, and hmi_driver mocks into sys.modules."""
    config_mod = types.ModuleType('config')
    config_mod.getValue = mock_config.getValue
    config_mod.setKeyValue = mock_config.setKeyValue

    mock_settings = MockSettings(mock_config)
    settings_mod = types.ModuleType('settings')
    settings_mod.getBacklight = mock_settings.getBacklight
    settings_mod.setBacklight = mock_settings.setBacklight
    settings_mod.fromLevelGetBacklight = mock_settings.fromLevelGetBacklight
    settings_mod.getUsbNetLinkTimeout = mock_settings.getUsbNetLinkTimeout
    settings_mod.setUsbNetLinkTimeout = mock_settings.setUsbNetLinkTimeout

    hmi_mod = types.ModuleType('hmi_driver')
    hmi_mod.setbaklight = mock_hmi.setbaklight

    old_config = sys.modules.get('config')
    old_settings = sys.modules.get('settings')
    old_hmi = sys.modules.get('hmi_driver')

    sys.modules['config'] = config_mod
    sys.modules['settings'] = settings_mod
    sys.modules['hmi_driver'] = hmi_mod

    yield

    # Restore
    if old_config is not None:
        sys.modules['config'] = old_config
    else:
        sys.modules.pop('config', None)
    if old_settings is not None:
        sys.modules['settings'] = old_settings
    else:
        sys.modules.pop('settings', None)
    if old_hmi is not None:
        sys.modules['hmi_driver'] = old_hmi
    else:
        sys.modules.pop('hmi_driver', None)


def _create_backlight(mock_config, level=2, timeout=0):
    """Start a BacklightActivity with the config pre-set."""
    mock_config._store['backlight'] = level
    mock_config._store['usb_net_link_timeout'] = timeout
    from activity_main import BacklightActivity
    return actstack.start_activity(BacklightActivity)


def _texts(activity):
    return activity.getCanvas().get_all_text()


# ---------------------------------------------------------------
# The level
# ---------------------------------------------------------------

class TestBacklightLevel:

    def test_title_is_backlight(self, install_mocks, mock_config):
        activity = _create_backlight(mock_config)
        assert 'Backlight' in _texts(activity)

    def test_buttons_stay_empty(self, install_mocks, mock_config):
        """M1 and M2 labels are empty (ground truth: buttons hidden)."""
        activity = _create_backlight(mock_config)
        texts = _texts(activity)
        assert 'OK' not in texts
        assert 'Back' not in texts

    def test_the_row_shows_every_level(self, install_mocks, mock_config):
        for level, label in enumerate(('Low', 'Middle', 'High')):
            activity = _create_backlight(mock_config, level=level)
            assert label in _texts(activity), (level, _texts(activity))

    def test_initial_selection_matches_the_config(self, install_mocks, mock_config):
        for level in (0, 1, 2):
            activity = _create_backlight(mock_config, level=level)
            assert activity._level == level

    def test_default_level_when_config_is_empty(self, install_mocks, mock_config):
        """No stored level: High, the factory default."""
        mock_config._store.clear()
        from activity_main import BacklightActivity
        activity = actstack.start_activity(BacklightActivity)
        assert activity._level == 2

    def test_up_and_down_move_between_the_rows(self, install_mocks, mock_config):
        activity = _create_backlight(mock_config, level=0)
        assert activity._selected == activity._ROW_BRIGHTNESS
        activity.onKeyEvent(KEY_DOWN)
        assert activity._selected == activity._ROW_SLEEP
        activity.onKeyEvent(KEY_DOWN)
        assert activity._selected == activity._ROW_BRIGHTNESS
        activity.onKeyEvent(KEY_UP)
        assert activity._selected == activity._ROW_SLEEP

    def test_ok_advances_the_level_and_applies_it(self, install_mocks, mock_config,
                                                  mock_hmi):
        activity = _create_backlight(mock_config, level=0)
        activity.onKeyEvent(KEY_OK)      # Low -> Middle
        assert activity._level == 1
        assert mock_config._store['backlight'] == 1
        assert ('setbaklight', 50) in mock_hmi.calls
        assert not activity.life.destroyed, 'OK must not leave the screen'

    def test_m2_advances_like_ok(self, install_mocks, mock_config, mock_hmi):
        activity = _create_backlight(mock_config, level=2)
        activity.onKeyEvent(KEY_M2)      # High wraps to Low
        assert activity._level == 0
        assert ('setbaklight', 20) in mock_hmi.calls

    def test_pwr_restores_the_opening_level_and_leaves(self, install_mocks,
                                                       mock_config, mock_hmi):
        activity = _create_backlight(mock_config, level=0)
        activity.onKeyEvent(KEY_OK)      # preview Middle
        activity.onKeyEvent(KEY_PWR)
        assert ('setbaklight', 20) in mock_hmi.calls, 'the original level was not restored'
        assert activity.life.destroyed


# ---------------------------------------------------------------
# The timeout
# ---------------------------------------------------------------

class TestScreenOff:

    def test_the_row_shows_the_stored_timeout(self, install_mocks, mock_config):
        activity = _create_backlight(mock_config, timeout=5)
        assert resources.get_str('net_sleep') in _texts(activity)
        assert '5 min' in _texts(activity)

    def test_off_is_the_default(self, install_mocks, mock_config):
        activity = _create_backlight(mock_config, timeout=0)
        assert 'Off' in _texts(activity)

    def test_ok_cycles_through_the_choices_and_persists(self, install_mocks,
                                                        mock_config):
        activity = _create_backlight(mock_config, timeout=0)
        activity.onKeyEvent(KEY_DOWN)                # onto the Screen off row
        assert activity._selected == activity._ROW_SLEEP
        for expected in (1, 2, 5, 10, 0):
            activity.onKeyEvent(KEY_OK)
            assert activity._timeout == expected
            assert mock_config._store['usb_net_link_timeout'] == expected

    def test_choosing_the_timeout_does_not_touch_the_hardware(self, install_mocks,
                                                              mock_config, mock_hmi):
        """The watcher reads the setting on every poll; nothing is restarted."""
        activity = _create_backlight(mock_config, level=1)
        calls_before = list(mock_hmi.calls)
        activity.onKeyEvent(KEY_DOWN)
        activity.onKeyEvent(KEY_OK)
        assert mock_hmi.calls == calls_before
        assert not activity.life.destroyed


def test_the_labels_fit_inside_a_row():
    """Same character budget as the other two-row screens.

    Measured on the device with the real fonts: 240 px per row, 30 px of
    margins, and a value of up to six characters.
    """
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    for code, limit in {'en': 10, 'fr': 10, 'zh': 6}.items():
        with open(os.path.join(root, 'data', 'lang', '%s.json' % code),
                  encoding='utf-8') as handle:
            pack = json.load(handle)
        for key in ('backlight_level', 'net_sleep'):
            label = pack['tipsmsg'][key]
            assert len(label) <= limit, (code, key, label, limit)
