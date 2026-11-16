"""Panel sleep follows the USB link, never the user's patience.

Spec: after `usb_net_link_timeout` minutes without a USB host (gadget netdev
present, carrier down) the backlight goes off; the next key press turns it back
on. Nothing about the network is retried or reverted because of the timeout.
"""

import pytest

import linkwatch


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _watch(clock, present=False, timeout=lambda: 1, blank=None, unblank=None):
    actions = {'blank': [], 'unblank': []}
    watcher = linkwatch.PanelSleep(
        present=lambda: present,
        blank=lambda: actions['blank'].append(clock.now),
        unblank=lambda: actions['unblank'].append(clock.now),
        timeout_minutes=timeout,
        clock=clock,
        schedule=lambda action: action(),
    )
    return watcher, actions


class TestLinkPresence:

    def test_carrier_one_means_a_host_is_attached(self, tmp_path):
        carrier = tmp_path / 'carrier'
        carrier.write_text('1\n')
        assert linkwatch.carrier_up(str(carrier)) is True

    def test_carrier_zero_means_no_host(self, tmp_path):
        carrier = tmp_path / 'carrier'
        carrier.write_text('0\n')
        assert linkwatch.carrier_up(str(carrier)) is False

    def test_a_missing_interface_is_no_host(self, tmp_path):
        assert linkwatch.carrier_up(str(tmp_path / 'absent' / 'carrier')) is False

    def test_any_interface_with_carrier_counts(self, tmp_path):
        (tmp_path / 'usb0').mkdir()
        (tmp_path / 'usb0' / 'carrier').write_text('0')
        (tmp_path / 'usb1').mkdir()
        (tmp_path / 'usb1' / 'carrier').write_text('1')
        assert linkwatch.link_present(names=('usb0', 'usb1'), root=str(tmp_path)) is True


class TestDecision:

    def test_zero_timeout_never_blanks(self):
        assert linkwatch.should_blank(10 ** 6, 0) is False

    def test_blanks_exactly_at_the_timeout(self):
        assert linkwatch.should_blank(59, 1) is False
        assert linkwatch.should_blank(60, 1) is True

    def test_unknown_absence_never_blanks(self):
        assert linkwatch.should_blank(None, 1) is False


class TestPanelSleep:

    def test_blanks_once_after_the_timeout(self):
        clock = Clock()
        watcher, actions = _watch(clock)
        watcher.poll()
        clock.advance(30)
        watcher.poll()
        assert actions['blank'] == []
        clock.advance(31)
        watcher.poll()
        assert len(actions['blank']) == 1
        clock.advance(60)
        watcher.poll()
        assert len(actions['blank']) == 1, 'the backlight was commanded off twice'

    def test_a_returning_link_lights_the_panel(self):
        clock = Clock()
        state = {'present': False}
        actions = {'blank': 0, 'unblank': 0}
        watcher = linkwatch.PanelSleep(
            present=lambda: state['present'],
            blank=lambda: actions.__setitem__('blank', actions['blank'] + 1),
            unblank=lambda: actions.__setitem__('unblank', actions['unblank'] + 1),
            timeout_minutes=lambda: 1, clock=clock, schedule=lambda a: a())
        watcher.poll()
        clock.advance(60)
        watcher.poll()
        assert actions == {'blank': 1, 'unblank': 0}
        state['present'] = True
        watcher.poll()
        assert actions == {'blank': 1, 'unblank': 1}
        assert watcher.blanked is False

    def test_a_key_press_wakes_the_panel_immediately(self):
        clock = Clock()
        watcher, actions = _watch(clock)
        watcher.poll()
        clock.advance(60)
        watcher.poll()
        assert watcher.blanked is True
        assert watcher.note_key() is True
        assert watcher.blanked is False
        assert len(actions['unblank']) == 1

    def test_a_key_press_restarts_the_dwell_time(self):
        clock = Clock()
        watcher, actions = _watch(clock)
        watcher.poll()
        clock.advance(60)
        watcher.poll()
        watcher.note_key()
        clock.advance(30)
        watcher.poll()
        assert watcher.blanked is False, 'the panel blanked again right after a key press'
        clock.advance(31)
        watcher.poll()
        assert watcher.blanked is True

    def test_a_key_press_while_awake_changes_nothing(self):
        clock = Clock()
        watcher, actions = _watch(clock, present=True)
        watcher.poll()
        assert watcher.note_key() is False
        assert actions == {'blank': [], 'unblank': []}

    def test_the_timeout_is_read_every_time(self):
        clock = Clock()
        settings = {'minutes': 0}
        actions = {'blank': 0}
        watcher = linkwatch.PanelSleep(
            present=lambda: False,
            blank=lambda: actions.__setitem__('blank', actions['blank'] + 1),
            unblank=lambda: None,
            timeout_minutes=lambda: settings['minutes'],
            clock=clock, schedule=lambda a: a())
        watcher.poll()
        clock.advance(600)
        watcher.poll()
        assert actions['blank'] == 0, 'the timeout is off; the panel must stay lit'
        settings['minutes'] = 1
        watcher.poll()
        assert actions['blank'] == 1


class TestKeyHook:

    def test_any_key_wakes_the_panel_before_the_activity_sees_it(self, monkeypatch):
        import keymap

        calls = []
        monkeypatch.setattr(linkwatch, 'get_watch', lambda: _Recorder(calls))
        keymap.KeyEvent().onKey('KEYOK_PRES!')
        assert calls == ['note_key'], 'the key never reached the panel watcher'


class _Recorder:
    def __init__(self, calls):
        self.calls = calls

    def note_key(self):
        self.calls.append('note_key')
