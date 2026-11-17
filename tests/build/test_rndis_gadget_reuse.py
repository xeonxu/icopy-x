"""A role switch must not re-enumerate the USB device.

Swapping gateway for client keeps the same USB function, so tearing the gadget
down and building it again only makes the host restart the interface - and with
it the internet sharing whose DHCP server the client role is about to wait for.
These tests run the real script against a fake gadget tree and stubbed system
commands, and fail if the rebuild comes back.
"""

import os
import pathlib
import stat
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / 'tools/rndis/rndis.sh'

FAKE_IP = """#!/bin/sh
echo "$*" >> "$FAKE_STATE/ip.calls"
case "$*" in
  *"addr show"*)
    if [ -s "$FAKE_STATE/addr" ]; then
        echo "2: usb0: <BROADCAST,MULTICAST,UP> mtu 1500"
        echo "    inet $(cat "$FAKE_STATE/addr") brd 0.0.0.0 scope global usb0"
    fi ;;
  *"addr add "*)
    for arg in $*; do
        case "$arg" in *.*/*) echo "$arg" > "$FAKE_STATE/addr" ;; esac
    done ;;
  *flush*) : > "$FAKE_STATE/addr" ;;
esac
exit 0
"""

FAKE_SYSTEMCTL = """#!/bin/sh
echo "$*" >> "$FAKE_STATE/systemctl.calls"
exit 0
"""

FAKE_IPCALC = """#!/bin/sh
echo "Netmask=255.255.255.0"
"""


def _gadget(tmp_path, function, bound=True):
    """A gadget tree in the state a previous run left it."""
    gadget = tmp_path / 'gadget'
    (gadget / 'functions' / function).mkdir(parents=True)
    if function == 'rndis.usb0':
        (gadget / 'functions' / function / 'os_desc' / 'interface.rndis').mkdir(parents=True)
    (gadget / 'configs' / 'c.1').mkdir(parents=True)
    (gadget / 'configs' / 'c.1' / function).symlink_to(gadget / 'functions' / function)
    (gadget / 'UDC').write_text('musb-hdrc.4.auto\n' if bound else '')
    return gadget


def _run(tmp_path, gadget, driver, role):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name, body in (('ip', FAKE_IP), ('systemctl', FAKE_SYSTEMCTL), ('ipcalc', FAKE_IPCALC)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    state = tmp_path / 'state'
    state.mkdir()
    sysfs = tmp_path / 'sysfs'
    (sysfs / 'usb0').mkdir(parents=True)
    conf = tmp_path / 'rndis.conf'
    conf.write_text('role=%s\ndriver=%s\nsubnet=10.1.1.0/24\n'
                    'device_ip=10.1.1.1\npool_start=10.1.1.100\n'
                    'pool_end=10.1.1.150\nlease=12h\nfixed_octet=2\n' % (role, driver))
    status = tmp_path / 'status'
    env = dict(os.environ)
    env.update({
        'PATH': '%s:%s' % (bin_dir, env.get('PATH', '')),
        'FAKE_STATE': str(state),
        'ICOPY_GADGET_DIR': str(gadget),
        'ICOPY_NET_SYSFS': str(sysfs),
        'ICOPY_NET_CONF': str(conf),
        'ICOPY_NET_STATUS': str(status),
        'ICOPY_DNSMASQ_CONF': str(tmp_path / 'dnsmasq.conf'),
    })
    result = subprocess.run(['sh', str(SCRIPT)], env=env, cwd=str(tmp_path),
                            capture_output=True, timeout=60)
    calls = {}
    for name in ('ip', 'systemctl'):
        path = state / ('%s.calls' % name)
        calls[name] = path.read_text() if path.exists() else ''
    return result, calls, status


def test_switching_role_keeps_the_bound_gadget(tmp_path):
    """The MS OS descriptor directories survive: a teardown would have removed them."""
    gadget = _gadget(tmp_path, 'rndis.usb0')
    result, calls, status = _run(tmp_path, gadget, 'rndis', 'client')

    assert result.returncode == 0, result.stderr
    assert (gadget / 'functions' / 'rndis.usb0' / 'os_desc' / 'interface.rndis').is_dir(), \
        'the gadget was torn down for a role switch'
    assert not (gadget / 'idVendor').exists(), 'the gadget was rebuilt for a role switch'
    assert gadget.joinpath('UDC').read_text().strip() == 'musb-hdrc.4.auto'
    assert 'pending' in status.read_text()


def test_the_client_role_still_stops_the_dhcp_server(tmp_path):
    gadget = _gadget(tmp_path, 'rndis.usb0')
    _, calls, _ = _run(tmp_path, gadget, 'rndis', 'client')

    assert 'stop rndis-dhcp.service' in calls['systemctl']
    assert 'restart icopy-net.service' in calls['systemctl']


def test_the_gateway_role_takes_the_link_back_from_the_client(tmp_path):
    """A live udhcpc from the client role would fight the static address."""
    gadget = _gadget(tmp_path, 'rndis.usb0')
    _, calls, status = _run(tmp_path, gadget, 'rndis', 'gateway')

    assert 'stop icopy-net.service' in calls['systemctl']
    assert 'addr add 10.1.1.1/24 dev usb0' in calls['ip']
    assert 'restart rndis-dhcp.service' in calls['systemctl']
    assert 'address=10.1.1.1/24' in status.read_text()


def test_the_lease_does_not_make_the_device_the_hosts_gateway(tmp_path):
    """The device has no uplink: a router option sends the host's traffic nowhere.

    Measured on a Windows host: 0.0.0.0/0 via usb0 (metric 25) won over the
    Wi-Fi gateway (metric 35), so the PC lost internet whenever it held a lease.
    """
    gadget = _gadget(tmp_path, 'rndis.usb0')
    _run(tmp_path, gadget, 'rndis', 'gateway')

    conf = (tmp_path / 'dnsmasq.conf').read_text()
    assert 'dhcp-range=' in conf, 'the DHCP server was not configured at all'
    gateways = [line for line in conf.splitlines()
                if line.startswith('dhcp-option=3,') or line.startswith('dhcp-option=option:router,')]
    assert not gateways, 'the device still advertises a gateway: %s' % gateways
    assert 'dhcp-option=3' in conf, \
        'option 3 must be present and empty: dnsmasq defaults it to its own address'


def test_a_driver_change_rebuilds_the_gadget(tmp_path):
    """A different function is a different USB device: this one must be rebuilt."""
    gadget = _gadget(tmp_path, 'ecm.usb0')
    result, _, _ = _run(tmp_path, gadget, 'rndis', 'gateway')

    assert result.returncode == 0, result.stderr
    assert (gadget / 'functions' / 'rndis.usb0').is_dir(), 'the new function was never created'
    assert (gadget / 'configs' / 'c.1' / 'rndis.usb0').is_symlink()
    assert not (gadget / 'functions' / 'ecm.usb0').exists(), 'the old function was left behind'
