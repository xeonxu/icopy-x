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
import resources
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

    values = {'role': 0, 'driver': 1, 'subnet': 0, 'octet': 2, 'client_network': 0}
    calls = []

    monkeypatch.setattr(settings, 'getUsbNetRole', lambda: values['role'])
    monkeypatch.setattr(settings, 'setUsbNetRole', lambda v: values.update(role=v))
    monkeypatch.setattr(settings, 'getUsbNetDriver', lambda: values['driver'])
    monkeypatch.setattr(settings, 'setUsbNetDriver', lambda v: values.update(driver=v))
    monkeypatch.setattr(settings, 'getUsbNetSubnet', lambda: values['subnet'])
    monkeypatch.setattr(settings, 'setUsbNetSubnet', lambda v: values.update(subnet=v))
    monkeypatch.setattr(settings, 'getUsbNetClientNetwork', lambda: values['client_network'])
    monkeypatch.setattr(settings, 'setUsbNetClientNetwork',
                        lambda v: values.update(client_network=v))
    monkeypatch.setattr(settings, 'getUsbNetFixedOctet', lambda: values['octet'])
    monkeypatch.setattr(settings, 'setUsbNetFixedOctet', lambda v: values.update(octet=v))

    status = {'value': {'role': 'gateway', 'address': '10.1.1.1/24',
                        'msg': 'gateway on usb0'}}
    monkeypatch.setattr(usbnet, 'read_status', lambda *a, **k: dict(status['value']))

    def apply(role, driver, subnet, octet, client_network=0, **kwargs):
        calls.append((role, driver, subnet, octet, client_network))
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
    for key in ('net_role', 'net_host_os', 'net_client_ip', 'net_subnet',
                'net_status'):
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
    assert state['calls'] == [(1, 1, 0, 2, 0)]


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


def test_range_row_is_live_in_both_roles(state):
    """The row means different things per role, but it is never inert."""
    from activity_main import NetworkActivity
    gateway = _open()
    assert gateway._is_enabled(gateway._ROW_SUBNET) is True
    state['values']['role'] = 1
    client = _open()
    assert client._is_enabled(client._ROW_SUBNET) is True
    assert client._is_enabled(client._ROW_FIXED) is True
    assert gateway._is_enabled(gateway._ROW_FIXED) is False


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


_LABEL_KEYS = ('net_role', 'net_host_os', 'net_client_ip', 'net_device_ip',
               'net_subnet', 'net_status')
# Measured on the device with the real fonts: 240 px per row, 30 px of margins
# and a value up to 13 characters. These limits are the character budget that
# keeps every label+value pair inside the row.
_LABEL_LIMIT = {'en': 10, 'fr': 10, 'zh': 6}


def test_labels_stay_inside_the_row():
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    for code, limit in _LABEL_LIMIT.items():
        path = os.path.join(root, 'data', 'lang', '%s.json' % code)
        with open(path, encoding='utf-8') as handle:
            pack = json.load(handle)
        for key in _LABEL_KEYS:
            label = pack['tipsmsg'][key]
            assert len(label) <= limit, (
                '%s %s is %d characters, the row fits %d: %r'
                % (code, key, len(label), limit, label))


def test_range_row_names_the_hosts_range_for_each_operating_system(state):
    state['values']['role'] = 1
    state['status']['value'] = {'role': 'client', 'address': 'none',
                                'msg': 'no lease - gateway fallback'}
    activity = _open()
    assert activity._subnet_label() == resources.get_str('net_fixed_auto')
    _press(activity, KEY_DOWN, KEY_DOWN, KEY_DOWN)               # move to Range
    assert activity._selected == activity._ROW_SUBNET
    for label in ('Windows', 'macOS', 'Linux'):
        _press(activity, KEY_OK)
        assert activity._subnet_label() == label
        assert state['values']['client_network'] in (1, 2, 3)
    _press(activity, KEY_OK)
    assert activity._subnet_label() == resources.get_str('net_fixed_auto')
    assert state['values']['client_network'] == 0


def test_range_row_shows_the_acquired_address_on_auto(state):
    state['values']['role'] = 1
    state['status']['value'] = {'role': 'client', 'address': '192.168.137.2/24',
                                'msg': 'lease 192.168.137.2'}
    activity = _open()
    assert activity._subnet_label() == '192.168.137.2/24'


def test_gateway_range_does_not_touch_the_client_network(state):
    activity = _open()
    _press(activity, KEY_DOWN, KEY_DOWN, KEY_DOWN, KEY_OK)       # Range row
    assert state['values']['subnet'] == 1
    assert state['values']['client_network'] == 0
    assert activity._subnet_label() == '192.168.7.x'


def test_the_address_row_says_whose_address_it_is(state):
    """Gateway serves the computer's address; Client sets our own."""
    activity = _open()
    label, value = activity._rows()[activity._ROW_FIXED]
    assert label == resources.get_str('net_client_ip')
    assert value == '100-150', value      # the pool the computer takes from

    state['values']['role'] = 1
    state['values']['octet'] = 10
    activity = _open()
    label, value = activity._rows()[activity._ROW_FIXED]
    assert label == resources.get_str('net_device_ip')
    assert value == '.10'


def test_the_status_row_follows_the_file_while_the_screen_is_open(state):
    """The address is produced after the screen is drawn; the row must catch up.

    A profile switch re-enumerates the device and the host answers seconds
    later, so a single read on entry leaves the operator looking at a stale row.
    """
    activity = _open()
    canvas = activity.getCanvas()
    assert canvas is not None
    assert activity._poll_timer is not None, 'the screen does not follow the status file'

    state['status']['value'] = {'role': 'client', 'address': '192.168.137.2/24',
                               'msg': 'lease 192.168.137.2'}
    canvas.advance(activity._STATUS_POLL_MS)
    assert '192.168.137.2/24' in _texts(canvas)

    # And once more: the poll must reschedule itself, not fire once.
    state['status']['value'] = {'role': 'client', 'address': 'none',
                               'msg': 'no lease - gateway fallback'}
    canvas.advance(activity._STATUS_POLL_MS)
    assert resources.get_str('net_no_lease') in _texts(canvas)
    assert '192.168.137.2/24' not in _texts(canvas)


def test_leaving_the_screen_stops_the_poll(state):
    """No timer may outlive the screen that owns it."""
    activity = _open()
    canvas = activity.getCanvas()
    activity.onPause()
    assert activity._poll_timer is None

    state['status']['value'] = {'role': 'client', 'address': '192.168.137.2/24',
                               'msg': 'lease 192.168.137.2'}
    canvas.advance(activity._STATUS_POLL_MS * 4)
    assert '192.168.137.2/24' not in _texts(canvas), 'a paused screen kept repainting'


def test_the_status_row_refreshes_from_the_device(state):
    """Field ask: OK on Status must ask the device again, not do nothing."""
    activity = _open()
    assert '10.1.1.1/24' in _texts(activity.getCanvas())

    # The link changed while the screen was open: the client got its lease.
    state['status']['value'] = {'role': 'client', 'address': '192.168.137.2/24',
                               'msg': 'lease 192.168.137.2'}
    state['values']['role'] = 1

    activity._selected = activity._ROW_STATUS
    activity.onKeyEvent(KEY_OK)

    texts = _texts(activity.getCanvas())
    assert '192.168.137.2/24' in texts, 'the Status row did not ask the device again'
    assert state['calls'] == [], 'refreshing the status wrote a profile'


def test_the_selection_wraps_at_both_ends(state):
    activity = _open()
    last = activity._ROW_COUNT - 1

    _press(activity, KEY_UP)
    assert activity._selected == last, 'UP on the first row must land on the last'

    _press(activity, KEY_DOWN)
    assert activity._selected == 0, 'DOWN on the last row must return to the first'


def test_the_title_carries_the_page_indicator(state):
    activity = _open()
    canvas = activity.getCanvas()
    indicator = [canvas.itemcget(item, 'text')
                 for item in canvas.find_withtag('page_indicator:top')]
    assert indicator == ['1/1'], 'five rows fit, and the title must say so'
