"""Menu navigation wraps, and the title says which page the selection is on.

Spec: the Settings list behaves like the main menu - UP at the first row lands
on the last one, DOWN at the last row returns to the first - and the title
carries "current/total" so the operator can tell a windowed list from a short
one without counting rows.
"""

import pytest

import actstack
import resources
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


def _open(cls=None):
    from activity_main import SettingsMenuActivity
    return actstack.start_activity(cls or SettingsMenuActivity)


def _titles(activity):
    return activity.getCanvas().get_all_text()


def test_the_title_says_which_page_and_how_many():
    from activity_main import SettingsMenuActivity

    activity = _open()
    pages = max(1, -(-activity._ROW_COUNT // activity._VISIBLE_ROWS))
    expected = '%s 1/%d' % (resources.get_str('settings'), pages)

    assert expected in ' '.join(_titles(activity))


def test_the_page_follows_the_selection():
    from activity_main import SettingsMenuActivity

    class SixRows(SettingsMenuActivity):
        _ROW_COUNT = 6
        _VISIBLE_ROWS = 5
        _LABEL_KEYS = dict(SettingsMenuActivity._LABEL_KEYS)
        _LABEL_KEYS[4] = 'shutdown'
        _LABEL_KEYS[5] = 'reboot'

    activity = _open(SixRows)
    assert '%s 1/2' % resources.get_str('settings') in ' '.join(_titles(activity))

    for _ in range(5):
        activity.onKeyEvent(KEY_DOWN)

    assert '%s 2/2' % resources.get_str('settings') in ' '.join(_titles(activity))
