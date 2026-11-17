"""A press the mirror client injects must not count as panel activity.

Kept apart from the mirror service tests: this behaviour belongs to the panel
sleep feature, which does not ship the socket transport.
"""

import keymap

from lib import mirror_service


def test_an_injected_key_is_marked_remote(monkeypatch):
    """Without the flag every mirror click wakes the device panel."""
    calls = []

    class FakeKey:
        def onKey(self, name, remote=False):
            calls.append((name, remote))

    monkeypatch.setattr(keymap, 'key', FakeKey())

    service = mirror_service.MirrorService()
    code = sorted(mirror_service.KEY_MAP)[0]
    service._key(code)

    assert calls == [(mirror_service.KEY_MAP[code], True)], calls
