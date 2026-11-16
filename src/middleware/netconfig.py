##########################################################################
# Required Notice: Copyright ETOILE401 SAS (http://www.lab401.com)
#
# Initial author: ETOILE401 SAS & https://github.com/quantum-x/ as of April 16, 2026
#
# Since this date, each contribution is under the copyright of its respective author.
#
# Copyright of each contribution is tracked by the Git history. See the output of git shortlog -nse for a full list or git log --pretty=short --follow <path/to/sourcefile> |git shortlog -ne to track a specific file.
#
# A mailmap is maintained to map author and committer names and email addresses to canonical names and email addresses.
# If by accident a copyright was removed from a file and is not directly deducible from the Git history, please submit a PR.
#
#
# This software is licensed under the PolyForm Noncommercial License 1.0.0.
# You may not use this software for commercial purposes.
#
# A copy of the license is available at:
# https://polyformproject.org/licenses/noncommercial/1.0.0
#
# This entire header "Required Notice" must remain in place.
##########################################################################

"""USB network profile decisions (pure, no I/O).

The Settings menu persists four keys; the boot scripts need two artefacts: the
generated ``/etc/icopy/rndis.conf`` and the ``dnsmasq`` argument list. Both are
produced here so the shell side stays a thin consumer and every decision is
testable on a host.

Profiles are named by the operating systems they serve, never by the USB class
name:

    0  ECM    Linux + macOS
    1  RNDIS  Linux + Windows   (default: what every shipped device already runs)
    2  NCM    Linux + macOS + Windows

Windows only binds RNDIS without a driver: ``usbncm.inf`` matches
``USB\\MS_COMP_WINNCM`` and this kernel refuses an MS OS descriptor on the ECM and
NCM functions, so the third profile works on Windows only where an NCM driver is
present.
"""

import ipaddress

ROLE_GATEWAY = 0
ROLE_CLIENT = 1

DRIVER_ECM = 0
DRIVER_RNDIS = 1
DRIVER_NCM = 2

FUNCTION_BY_DRIVER = {
    DRIVER_ECM: 'ecm.usb0',
    DRIVER_RNDIS: 'rndis.usb0',
    DRIVER_NCM: 'ncm.usb0',
}

# Menu presets for the Gateway role. The Client role learns its subnet from the
# lease, because the host's sharing subnet is not ours to choose.
SUBNETS = {
    0: ('10.1.1.0', 24),
    1: ('192.168.7.0', 24),
    2: ('172.16.0.0', 24),
}

POOL_FIRST = 100
POOL_LAST = 150
LEASE_TIME = '12h'

# Fixed-last-octet values the Client role offers. 0 means "take what is offered".
FIXED_OCTETS = (0, 2, 10, 20, 50)

# In the Client role the subnet is not ours to choose, but the host's sharing
# software uses a fixed range per operating system. Naming it lets the device ask
# for its address on the first try instead of learning the subnet from a lease.
# 0 keeps whatever the upstream server hands out and is the only safe default.
CLIENT_NETWORKS = {
    0: ('auto', None),
    1: ('win', '192.168.137.0'),   # Windows Internet Connection Sharing
    2: ('mac', '192.168.2.0'),     # macOS Internet Sharing
    3: ('linux', '10.42.0.0'),     # NetworkManager 'ipv4.method shared'
}

CLIENT_NETWORK_LABELS = {
    0: 'Auto',
    1: 'Windows',
    2: 'macOS',
    3: 'Linux',
}

# Compact status strings for the panel; the menu translates them.
STATUS_NO_LEASE = 'no lease'
STATUS_NO_LINK = 'no link'

DEFAULTS = {
    'role': ROLE_GATEWAY,
    'driver': DRIVER_RNDIS,
    'subnet': 0,
    'client_network': 0,
    'fixed_octet': 2,
}


def function_name(driver):
    """Gadget function instance name for a profile."""
    return FUNCTION_BY_DRIVER.get(driver, FUNCTION_BY_DRIVER[DRIVER_RNDIS])


def menu_label(driver):
    """Profile name as the panel shows it."""
    return {
        DRIVER_ECM: 'Linux + macOS',
        DRIVER_RNDIS: 'Linux + Windows',
        DRIVER_NCM: 'Linux + macOS + Windows',
    }.get(driver, 'Linux + Windows')


def client_network_label(index):
    """Panel label of a host-network preset (an OS name, or Auto)."""
    return CLIENT_NETWORK_LABELS.get(index, CLIENT_NETWORK_LABELS[0])


def client_network_range(index):
    """'192.168.137.x'-style range, or None when the host decides."""
    base = CLIENT_NETWORKS.get(index, CLIENT_NETWORKS[0])[1]
    if base is None:
        return None
    return base.rsplit('.', 1)[0] + '.x'


def preset_request(index, fixed_octet):
    """Address to ask for first, when a host preset and an octet are both set."""
    base = CLIENT_NETWORKS.get(index, CLIENT_NETWORKS[0])[1]
    if base is None or not _valid_octet(fixed_octet) or fixed_octet == 0:
        return None
    net = ipaddress.ip_network('%s/24' % base, strict=False)
    return str(net.network_address + fixed_octet)


def device_ip(subnet):
    """The device's own address in the Gateway role: first host of the preset."""
    base, _ = SUBNETS.get(subnet, SUBNETS[0])
    return str(ipaddress.ip_network('%s/24' % base, strict=False).network_address + 1)


def pool(subnet):
    """(first, last) lease address of the preset's DHCP pool."""
    base, _ = SUBNETS.get(subnet, SUBNETS[0])
    net = ipaddress.ip_network('%s/24' % base, strict=False)
    return str(net.network_address + POOL_FIRST), str(net.network_address + POOL_LAST)


def dnsmasq_args(subnet, interface='usb0'):
    """dnsmasq arguments for the Gateway role (same shape as the shipped unit)."""
    base, _ = SUBNETS.get(subnet, SUBNETS[0])
    net = ipaddress.ip_network('%s/24' % base, strict=False)
    first, last = pool(subnet)
    return [
        '--keep-in-foreground',
        '--interface=%s' % interface,
        '--bind-interfaces',
        '--dhcp-range=%s,%s,%s,%s' % (first, last, net.netmask, LEASE_TIME),
        '--dhcp-option=3,%s' % device_ip(subnet),
        '--dhcp-option=1,%s' % net.netmask,
        '--dhcp-option=28,%s' % net.broadcast_address,
        '--no-resolv',
        '--no-hosts',
        '--port=0',
    ]


def render_conf(role, driver, subnet, fixed_octet, client_network=0):
    """Text of ``/etc/icopy/rndis.conf``.

    The file is generated: the app is its only writer and the boot script reads
    it. Absent or unreadable, the script keeps today's behaviour.
    """
    if role not in (ROLE_GATEWAY, ROLE_CLIENT):
        role = DEFAULTS['role']
    if driver not in FUNCTION_BY_DRIVER:
        driver = DEFAULTS['driver']
    if subnet not in SUBNETS:
        subnet = DEFAULTS['subnet']
    if client_network not in CLIENT_NETWORKS:
        client_network = DEFAULTS['client_network']
    if not _valid_octet(fixed_octet):
        fixed_octet = DEFAULTS['fixed_octet']

    base, prefix = SUBNETS[subnet]
    first, last = pool(subnet)
    return (
        '# generated by iCopy-X - edit the Settings menu instead\n'
        'role=%s\n'
        'driver=%s\n'
        'function=%s\n'
        'subnet=%s/%d\n'
        'device_ip=%s\n'
        'client_network=%s\n'
        'pool_start=%s\n'
        'pool_end=%s\n'
        'lease=%s\n'
        'fixed_octet=%d\n'
        % ('gateway' if role == ROLE_GATEWAY else 'client',
           {DRIVER_ECM: 'ecm', DRIVER_RNDIS: 'rndis', DRIVER_NCM: 'ncm'}[driver],
           function_name(driver), base, prefix,
           device_ip(subnet), CLIENT_NETWORKS[client_network][0],
           first, last, LEASE_TIME, fixed_octet)
    )


def parse_conf(text):
    """Read ``rndis.conf`` back; anything unreadable falls back to the defaults.

    The boot script relies on this tolerance: a half-written or hand-edited file
    must never leave the device without a working link.
    """
    conf = dict(DEFAULTS)
    if not isinstance(text, str):
        return conf
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if key == 'role':
            if value in ('gateway', 'client'):
                conf['role'] = ROLE_GATEWAY if value == 'gateway' else ROLE_CLIENT
        elif key == 'driver':
            if value in ('ecm', 'rndis', 'ncm'):
                conf['driver'] = {'ecm': DRIVER_ECM, 'rndis': DRIVER_RNDIS,
                                  'ncm': DRIVER_NCM}[value]
        elif key == 'client_network':
            for index, (name, _) in CLIENT_NETWORKS.items():
                if value == name:
                    conf['client_network'] = index
                    break
        elif key == 'fixed_octet':
            try:
                octet = int(value, 10)
            except ValueError:
                continue
            if _valid_octet(octet):
                conf['fixed_octet'] = octet
    return conf


def requested_address(leased_ip, prefix, fixed_octet):
    """Address to ask the host's DHCP server for, or None for "take what is offered".

    The sharing subnet differs per host (Windows ICS 192.168.137.0/24, NM shared
    10.42.0.0/24, macOS 192.168.2.0/24), so the request is built from the subnet
    the first lease revealed, keeping only the last octet fixed.
    """
    if not _valid_octet(fixed_octet) or fixed_octet == 0:
        return None
    try:
        net = ipaddress.ip_network('%s/%s' % (leased_ip, prefix), strict=False)
    except ValueError:
        return None
    host = int(net.network_address) + fixed_octet
    if host <= int(net.network_address) or host >= int(net.broadcast_address):
        return None
    return str(ipaddress.ip_address(host))


def subnet_conflicts(subnet, routes):
    """True when the chosen preset overlaps a route the device already has."""
    base, _ = SUBNETS.get(subnet, SUBNETS[0])
    wanted = ipaddress.ip_network('%s/24' % base, strict=False)
    for route in routes or ():
        try:
            other = ipaddress.ip_network(str(route), strict=False)
        except ValueError:
            continue
        if wanted.overlaps(other):
            return True
    return False


def _valid_octet(value):
    try:
        octet = int(value)
    except (TypeError, ValueError):
        return False
    return octet == 0 or 2 <= octet <= 254


def parse_status(text):
    """Read ``/run/icopy-net.status`` into a mapping.

    The file is written by the boot script and by the DHCP hook. A missing or
    malformed file is indistinguishable from "nothing configured yet", so both
    yield an empty mapping and the menu shows "no link".
    """
    status = {}
    if not isinstance(text, str):
        return status
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if key in ('driver', 'role', 'address', 'msg', 'ts') and value:
            status[key] = value
    return status


def status_text(status):
    """What the Status row shows: the live address, or why there is none."""
    address = (status or {}).get('address', '')
    if address and address != 'none':
        return address
    if 'fallback' in (status or {}).get('msg', ''):
        return STATUS_NO_LEASE
    return STATUS_NO_LINK
