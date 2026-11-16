"""The client role must ask for the fixed last octet, and must never leave the
device unreachable when the host offers no lease.

Runs the real script with the `ip` and `udhcpc` binaries replaced by stubs, so
the two-step sequence and the fallback are exercised without a device.
"""

import os
import pathlib
import stat
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / 'tools/rndis/icopy-netclient.sh'

FAKE_IP = """#!/bin/sh
ADDR_FILE="$FAKE_STATE/addr"
echo "$*" >> "$FAKE_STATE/ip.calls"
case "$*" in
  *flush*) : > "$ADDR_FILE" ;;
  *"addr show"*)
    if [ -s "$ADDR_FILE" ]; then
        echo "2: usb0: <BROADCAST,MULTICAST,UP> mtu 1500"
        echo "    inet $(cat "$ADDR_FILE") brd 0.0.0.0 scope global usb0"
    fi ;;
esac
exit 0
"""

FAKE_UDHCPC = """#!/bin/sh
echo "$*" >> "$FAKE_STATE/udhcpc.calls"
req=""; prev=""
for a in "$@"; do
    [ "$prev" = "-r" ] && req=$a
    prev=$a
done
[ -n "${FAKE_RC:-}" ] && [ "$FAKE_RC" != "0" ] && exit "$FAKE_RC"
if [ -n "$req" ] && [ -z "${FAKE_IGNORE_REQUEST:-}" ]; then
    echo "$req/24" > "$FAKE_STATE/addr"
else
    echo "${FAKE_OFFER:-}/24" > "$FAKE_STATE/addr"
fi
exit 0
"""


def _env(tmp_path, **extra):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name, body in (('ip', FAKE_IP), ('udhcpc', FAKE_UDHCPC)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    state = tmp_path / 'state'
    state.mkdir()
    conf = tmp_path / 'rndis.conf'
    conf.write_text(extra.pop('conf'))
    status = tmp_path / 'status'
    sysfs = tmp_path / 'sysfs'
    (sysfs / 'usb0').mkdir(parents=True)
    env = dict(os.environ)
    env.update({
        'PATH': '%s:%s' % (bin_dir, env.get('PATH', '')),
        'FAKE_STATE': str(state),
        'ICOPY_NET_CONF': str(conf),
        'ICOPY_NET_STATUS': str(status),
        'ICOPY_UDHCPC_HOOK': str(tmp_path / 'hook.sh'),
        'ICOPY_RNDIS_SCRIPT': str(tmp_path / 'fallback.sh'),
        'ICOPY_NET_SYSFS': str(sysfs),
    })
    env.update({k: v for k, v in extra.items() if v is not None})
    return env, status


def _run(tmp_path, **extra):
    env, status = _env(tmp_path, **extra)
    subprocess.run(['sh', str(SCRIPT), 'usb0'], env=env, cwd=str(tmp_path),
                   capture_output=True, timeout=60)
    return dict(line.split('=', 1) for line in status.read_text().splitlines() if '=' in line)


def test_requests_the_fixed_last_octet(tmp_path):
    result = _run(tmp_path, conf='driver=rndis\nfixed_octet=2\n', FAKE_OFFER='192.168.137.23')
    assert result['address'] == '192.168.137.2/24'
    assert result['msg'] == 'lease 192.168.137.2'
    assert result['role'] == 'client'


def test_reports_an_ignored_request_and_keeps_the_lease(tmp_path):
    result = _run(tmp_path, conf='driver=rndis\nfixed_octet=2\n',
                  FAKE_OFFER='192.168.137.23', FAKE_IGNORE_REQUEST='1')
    assert result['address'] == '192.168.137.23/24'
    assert result['msg'] == 'requested 192.168.137.2 ignored'


def test_auto_keeps_whatever_is_offered(tmp_path):
    result = _run(tmp_path, conf='driver=rndis\nfixed_octet=0\n', FAKE_OFFER='10.42.0.57')
    assert result['address'] == '10.42.0.57/24'
    assert result['msg'] == 'lease from host'


def test_no_lease_falls_back_to_the_gateway_role(tmp_path):
    marker = tmp_path / 'fallback.sh'
    marker.write_text('#!/bin/sh\necho ran > "%s"\n' % (tmp_path / 'fallback-ran'))
    env, status = _env(tmp_path, conf='driver=rndis\nfixed_octet=2\n', FAKE_RC='1')
    env['ICOPY_RNDIS_SCRIPT'] = str(marker)
    subprocess.run(['sh', str(SCRIPT), 'usb0'], env=env, cwd=str(tmp_path),
                   capture_output=True, timeout=60)
    result = dict(line.split('=', 1) for line in status.read_text().splitlines() if '=' in line)
    assert result['address'] == 'none'
    assert result['msg'] == 'no lease - gateway fallback'
    assert (tmp_path / 'fallback-ran').exists(), 'the gateway configuration was not re-applied'


def test_a_previous_gateway_address_is_not_mistaken_for_a_lease(tmp_path):
    """The address must come from the DHCP client, never from the old config."""
    env, status = _env(tmp_path, conf='driver=rndis\nfixed_octet=2\n', FAKE_RC='1')
    (tmp_path / 'state' / 'addr').write_text('10.1.1.1/24')
    subprocess.run(['sh', str(SCRIPT), 'usb0'], env=env, cwd=str(tmp_path),
                   capture_output=True, timeout=60)
    result = dict(line.split('=', 1) for line in status.read_text().splitlines() if '=' in line)
    assert result['address'] == 'none', 'a leftover static address was treated as a lease'
    assert 'fallback' in result['msg']
    calls = (tmp_path / 'state' / 'ip.calls').read_text()
    assert 'flush' in calls, 'the interface must start without a stale address' 


def _calls(tmp_path):
    path = tmp_path / 'state' / 'udhcpc.calls'
    return path.read_text().splitlines() if path.exists() else []


def test_a_named_host_subnet_is_requested_on_the_first_try(tmp_path):
    """Naming the host OS saves a lease: the address is asked for directly."""
    result = _run(tmp_path, conf='driver=rndis\nclient_network=win\nfixed_octet=2\n',
                  FAKE_OFFER='10.0.0.9')
    assert result['address'] == '192.168.137.2/24'
    assert result['msg'] == 'lease 192.168.137.2'
    first = _calls(tmp_path)[0]
    assert '-r 192.168.137.2' in first, first
    assert '-b' not in first


def test_a_refused_request_falls_back_to_learning_the_subnet(tmp_path):
    result = _run(tmp_path, conf='driver=rndis\nclient_network=mac\nfixed_octet=10\n',
                  FAKE_OFFER='192.168.2.77', FAKE_IGNORE_REQUEST='1')
    assert result['address'] == '192.168.2.77/24'
    assert result['msg'] == 'requested 192.168.2.10 ignored'
    calls = _calls(tmp_path)
    assert '-r 192.168.2.10' in calls[0]
    assert len([c for c in calls if '-b' not in c]) >= 2, calls


def test_auto_keeps_learning_and_never_presumes_a_subnet(tmp_path):
    """Auto spends the first lease learning; the octet follows what it learned."""
    result = _run(tmp_path, conf='driver=rndis\nclient_network=auto\nfixed_octet=2\n',
                  FAKE_OFFER='10.42.0.57')
    assert '-r' not in _calls(tmp_path)[0], 'Auto guessed a subnet instead of learning it'
    assert result['address'] == '10.42.0.2/24'
    assert result['msg'] == 'lease 10.42.0.2'
