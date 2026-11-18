"""The Settings list wraps at both ends, like the main menu.

Spec: UP on the first row lands on the last, DOWN on the last returns to the
first, so the operator never has to remember how many moves remain - the same
behaviour the main menu has.
"""

import pytest

import actstack
from tests.ui.conftest import MockCanvas
from _constants import KEY_UP, KEY_DOWN


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    actstack._reset()
    actstack._canvas_factory = MockCanvas
    import settings
    monkeypatch.setattr(settings, 'getScreenMirror', lambda: 0)
    monkeypatch.setattr(settings, 'setScreenMirror', lambda v: None)
    yield
    actstack._reset()


def _open():
    from activity_main import SettingsMenuActivity
    return actstack.start_activity(SettingsMenuActivity)


def test_the_selection_wraps_at_both_ends():
    activity = _open()
    last = activity._ROW_COUNT - 1

    activity.onKeyEvent(KEY_UP)
    assert activity._selected == last, 'UP on the first row must land on the last'

    activity.onKeyEvent(KEY_DOWN)
    assert activity._selected == 0, 'DOWN on the last row must return to the first'
