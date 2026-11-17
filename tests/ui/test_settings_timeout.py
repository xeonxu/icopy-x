"""The panel timeout must actually read and write the config.

Field risk: the accessor called a helper that lived on another branch, and the
caller swallows the NameError - the screen then never blanks, silently.
"""

import settings


def test_the_panel_timeout_round_trips(monkeypatch):
    import config

    store = {}
    monkeypatch.setattr(config, 'getValue', lambda key, default=None: store.get(key, default))
    monkeypatch.setattr(config, 'setKeyValue', lambda key, value: store.__setitem__(key, value))

    settings.setUsbNetLinkTimeout(5)
    assert settings.getUsbNetLinkTimeout() == 5


def test_the_panel_timeout_defaults_to_off(monkeypatch):
    import config

    monkeypatch.setattr(config, 'getValue', lambda key, default=None: default)
    assert settings.getUsbNetLinkTimeout() == 0
