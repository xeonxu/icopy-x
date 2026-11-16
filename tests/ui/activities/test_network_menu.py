"""Behavioural tests for the USB network menu (NetworkActivity).

Spec (docs/superpowers/specs/2026-11-15-usb-network-profiles-design.md):

  * Settings gains a row that opens NetworkActivity;
  * rows: Role, Host OS, Fixed IP, Subnet, Status (read-only);
  * profiles are labelled by operating system, never by USB class name;
  * rows the current role makes irrelevant are dimmed and refuse input instead
    of disappearing;
  * an accepted change persists the keys, applies the profile live (restarting
    the unit, no reboot) and shows the new status;
  * PWR leaves without applying anything.
"""

import pytest

import actstack
from tests.ui.conftest import MockCanvas
from _constants import KEY_UP, KEY_DOWN, KEY_OK, KEY_PWR


@pytest.fixture(autouse=True)
def _setup(monkeypatch, activity_workers):
    actstack._reset()
    actstack._canvas_factory = MockCanvas
    yield
    actstack._reset()


@pytest.fixture
def state(monkeypatch):
    """In-memory replacement for the persisted settings, plus an apply spy."""
    import settings
    import usbnet

    values = {'role': 0, 'driver': 1, 'subnet': 0, 'octet': 2}
    calls = []

    monkeypatch.setattr(settings, 'getUsbNetRole', lambda: values['role'])
    monkeypatch.setattr(settings, 'setUsbNetRole', lambda v: values.update(role=v))
    monkeypatch.setattr(settings, 'getUsbNetDriver', lambda: values['driver'])
    monkeypatch.setattr(settings, 'setUsbNetDriver', lambda v: values.update(driver=v))
    monkeypatch.setattr(settings, 'getUsbNetSubnet', lambda: values['subnet'])
    monkeypatch.setattr(settings, 'setUsbNetSubnet', lambda v: values.update(subnet=v))
    monkeypatch.setattr(settings, 'getUsbNetFixedOctet', lambda: values['octet'])
    monkeypatch.setattr(settings, 'setUsbNetFixedOctet', lambda v: values.update(octet=v))

    status = {'value': {'role': 'gateway', 'address': '10.1.1.1/24',
                        'msg': 'gateway on usb0'}}
    monkeypatch.setattr(usbnet, 'read_status', lambda *a, **k: dict(status['value']))

    def apply(role, driver, subnet, octet, **kwargs):
        calls.append((role, driver, subnet, octet))
        return dict(status['value'])

    monkeypatch.setattr(usbnet, 'apply', apply)
    return {'values': values, 'calls': calls, 'status': status}


def _texts(canvas, tag='net_row'):
    return [canvas.itemcget(item, 'text') for item in canvas.find_withtag(tag)]


def _open():
    from activity_main import NetworkActivity
    return actstack.start_activity(NetworkActivity)


def _press(activity, *keys):
    for key in keys:
        activity.onKeyEvent(key)


def test_settings_menu_opens_the_network_screen(state):
    import resources
    from activity_main import NetworkActivity, SettingsMenuActivity
    menu = actstack.start_activity(SettingsMenuActivity)
    rendered = [menu.getCanvas().itemcget(item, 'text')
                for item in menu.getCanvas().find_withtag('settings_row')]
    assert resources.get_str('network') in rendered, 'the row is missing from Settings'
    for _ in range(menu._ROW_NETWORK):
        menu.onKeyEvent(KEY_DOWN)
    assert menu._selected == menu._ROW_NETWORK
    menu.onKeyEvent(KEY_OK)
    assert isinstance(actstack.get_current_activity(), NetworkActivity)


def test_rows_are_labelled_by_what_the_user_chooses(state):
    import resources
    activity = _open()
    texts = _texts(activity.getCanvas())
    for key in ('net_role', 'net_host_os', 'net_fixed', 'net_subnet', 'net_status'):
        assert resources.get_str(key) in texts
    # The host profile never names the USB class.
    for word in ('rndis', 'RNDIS', 'ecm', 'ECM', 'ncm', 'NCM'):
        assert word not in ' '.join(texts)


def test_host_os_offers_every_operating_system(state):
    activity = _open()
    _press(activity, KEY_DOWN, KEY_OK)          # cycle the Host OS row
    assert state['values']['driver'] == 2      # RNDIS (1) -> NCM (2)
    assert state['calls'], 'the profile was not applied'
    _press(activity, KEY_OK)
    assert state['values']['driver'] == 0      # wraps to ECM
    _press(activity, KEY_OK)
    assert state['values']['driver'] == 1


def test_role_change_persists_and_applies_once(state):
    activity = _open()
    _press(activity, KEY_OK)
    assert state['values']['role'] == 1
    assert state['calls'] == [(1, 1, 0, 2)]


def test_fixed_row_is_dimmed_and_inert_while_sharing(state):
    from activity_main import DIM_TEXT_COLOR
    activity = _open()
    _press(activity, KEY_DOWN, KEY_DOWN)
    assert activity._selected == activity._ROW_FIXED
    _press(activity, KEY_OK)
    assert state['calls'] == [], 'a row the role makes irrelevant accepted input'
    assert state['values']['octet'] == 2
    canvas = activity.getCanvas()
    label = [t for t in canvas.find_withtag('net_row')
             if canvas.itemcget(t, 'text') == activity._rows()[activity._ROW_FIXED][0]][0]
    assert canvas.itemcget(label, 'fill') == DIM_TEXT_COLOR


def test_subnet_row_is_dimmed_and_inert_while_borrowing(state):
    state['values']['role'] = 1
    activity = _open()
    _press(activity, KEY_DOWN, KEY_DOWN, KEY_DOWN)
    assert activity._selected == activity._ROW_SUBNET
    _press(activity, KEY_OK)
    assert state['calls'] == []
    assert state['values']['subnet'] == 0


def test_fixed_octet_cycles_through_the_offered_values(state):
    state['values']['role'] = 1
    activity = _open()
    _press(activity, KEY_DOWN, KEY_DOWN, KEY_OK)
    assert state['values']['octet'] == 10      # 2 -> 10
    assert activity._octet_label() == '.10'
    while state['values']['octet'] != 0:
        _press(activity, KEY_OK)
    assert activity._octet_label() != '0'


def test_status_row_never_applies(state):
    activity = _open()
    _press(activity, KEY_DOWN, KEY_DOWN, KEY_DOWN, KEY_DOWN)
    assert activity._selected == activity._ROW_STATUS
    _press(activity, KEY_OK)
    assert state['calls'] == []


def test_pwr_leaves_without_applying(state):
    activity = _open()
    _press(activity, KEY_PWR)
    assert state['calls'] == []
    assert actstack.get_current_activity() is not activity


def test_status_shows_the_live_address(state):
    activity = _open()
    assert '10.1.1.1/24' in _texts(activity.getCanvas())


def test_status_reports_a_missing_host(state):
    import resources
    state['status']['value'] = {'role': 'gateway', 'address': 'none',
                               'msg': 'no lease - gateway fallback'}
    activity = _open()
    assert resources.get_str('net_no_lease') in _texts(activity.getCanvas())
