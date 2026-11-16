"""An app restart must never strand the always-on USB network.

A mirror session detaches the configfs gadget from the UDC, and only the session
puts it back.  When the app restarts while that session is interrupted, nothing
re-binds the gadget and the device vanishes from the host: no serial port, no
network.  ``application._restore_usb_network()`` is the safety net.
"""

import pytest

import application
import gadget_linux
import settings


@pytest.fixture
def calls(monkeypatch):
    state = {'restored': 0, 'mirror': 0}

    monkeypatch.setattr(settings, 'getScreenMirror', lambda: state['mirror'])

    def restore():
        state['restored'] += 1

    monkeypatch.setattr(gadget_linux, 'restore_rndis', restore)
    return state


def test_restores_the_gadget_when_the_mirror_is_off(calls):
    assert application._restore_usb_network() is True
    assert calls['restored'] == 1


def test_leaves_the_udc_to_a_configured_mirror(calls):
    calls['mirror'] = 1
    assert application._restore_usb_network() is False
    assert calls['restored'] == 0, 'the mirror needs the UDC; re-binding fights it'


def test_a_failing_restore_never_breaks_the_startup(calls, monkeypatch):
    def boom():
        raise OSError('no gadget')

    monkeypatch.setattr(gadget_linux, 'restore_rndis', boom)
    assert application._restore_usb_network() is False


def test_an_unreadable_setting_never_breaks_the_startup(calls, monkeypatch):
    def boom():
        raise RuntimeError('config unreadable')

    monkeypatch.setattr(settings, 'getScreenMirror', boom)
    assert application._restore_usb_network() is False
    assert calls['restored'] == 0


def test_startup_calls_the_restore_when_the_mirror_is_off(calls, monkeypatch):
    import tkinter
    import actstack

    monkeypatch.setattr(tkinter, 'Tk', lambda: _FakeRoot())
    monkeypatch.setattr(actstack, 'init', lambda root: None)
    monkeypatch.setattr(actstack, 'start_activity', lambda cls, bundle=None: None)
    import actmain
    monkeypatch.setattr(actmain, 'init_plugins', lambda: None)
    import batteryui
    monkeypatch.setattr(batteryui, 'start', lambda: None)
    import audio
    monkeypatch.setattr(audio, 'init', lambda: None)
    monkeypatch.setattr(audio, 'playSystemStart', lambda: None)
    import keymap
    monkeypatch.setattr(keymap.key, 'bind', lambda activity: None)

    _FakeRoot.mainloop = lambda self: None
    application.startApp()
    assert calls['restored'] == 1, 'startup left the USB network detached'


class _FakeRoot:
    def geometry(self, *a, **k):
        pass

    def resizable(self, *a, **k):
        pass

    def option_add(self, *a, **k):
        pass

    def configure(self, *a, **k):
        pass

    def tk(self):
        class _Tk:
            @staticmethod
            def call(*a, **k):
                return None
        return _Tk()

    def after(self, *a, **k):
        return None

    def mainloop(self):
        pass
