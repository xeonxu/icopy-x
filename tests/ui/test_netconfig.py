"""USB network profile decisions must survive a hostile config file.

The boot script trusts ``/etc/icopy/rndis.conf``; a half-written or hand-edited
file must never leave the device without a working link, and the Gateway profile
must generate exactly the dnsmasq arguments the shipped unit carries.
"""

import netconfig


def test_profiles_map_to_gadget_functions():
    assert netconfig.function_name(netconfig.DRIVER_ECM) == 'ecm.usb0'
    assert netconfig.function_name(netconfig.DRIVER_RNDIS) == 'rndis.usb0'
    assert netconfig.function_name(netconfig.DRIVER_NCM) == 'ncm.usb0'


def test_menu_labels_name_operating_systems_not_protocols():
    labels = [netconfig.menu_label(d) for d in
              (netconfig.DRIVER_ECM, netconfig.DRIVER_RNDIS, netconfig.DRIVER_NCM)]
    assert labels == ['Linux + macOS', 'Linux + Windows', 'Linux + macOS + Windows']
    for label in labels:
        for jargon in ('rndis', 'ecm', 'ncm', 'NDIS'):
            assert jargon not in label.lower()


def test_gateway_preset_addresses():
    assert netconfig.device_ip(0) == '10.1.1.1'
    assert netconfig.device_ip(1) == '192.168.7.1'
    assert netconfig.device_ip(2) == '172.16.0.1'
    assert netconfig.pool(1) == ('192.168.7.100', '192.168.7.150')


def test_dnsmasq_args_match_the_shipped_unit():
    args = netconfig.dnsmasq_args(0)
    assert '--interface=usb0' in args
    assert '--bind-interfaces' in args
    assert '--dhcp-range=10.1.1.100,10.1.1.150,255.255.255.0,12h' in args
    assert '--dhcp-option=3,10.1.1.1' in args
    assert '--dhcp-option=28,10.1.1.255' in args
    assert '--port=0' in args


def test_dnsmasq_args_follow_the_preset():
    args = netconfig.dnsmasq_args(1, interface='usb0')
    assert '--dhcp-range=192.168.7.100,192.168.7.150,255.255.255.0,12h' in args
    assert '--dhcp-option=3,192.168.7.1' in args
    assert '--dhcp-option=28,192.168.7.255' in args, 'broadcast must follow the preset'


def test_render_conf_round_trips():
    text = netconfig.render_conf(netconfig.ROLE_CLIENT, netconfig.DRIVER_ECM, 0, 2)
    assert 'role=client' in text and 'driver=ecm' in text
    assert 'function=ecm.usb0' in text and 'fixed_octet=2' in text
    conf = netconfig.parse_conf(text)
    assert conf == {'role': netconfig.ROLE_CLIENT, 'driver': netconfig.DRIVER_ECM,
                    'subnet': 0, 'fixed_octet': 2}


def test_parse_conf_falls_back_to_defaults():
    for junk in ('', 'garbage', 'role=banana\ndriver=isoc\nfixed_octet=999\n',
                 None, 'role=\n=\n#'):
        conf = netconfig.parse_conf(junk)
        assert conf == netconfig.DEFAULTS, junk


def test_render_conf_rejects_out_of_range_fixed_octet():
    text = netconfig.render_conf(netconfig.ROLE_CLIENT, netconfig.DRIVER_RNDIS, 0, 1)
    assert 'fixed_octet=2' in text, 'octet 1 is the gateway and must not be offered'


def test_requested_address_keeps_the_last_octet():
    assert netconfig.requested_address('192.168.137.23', 24, 2) == '192.168.137.2'
    assert netconfig.requested_address('10.42.0.57', 24, 2) == '10.42.0.2'
    assert netconfig.requested_address('192.168.2.9', 24, 10) == '192.168.2.10'


def test_requested_address_auto_and_invalid_prefix():
    assert netconfig.requested_address('10.42.0.57', 24, 0) is None
    assert netconfig.requested_address('10.42.0.57', 24, 255) is None
    assert netconfig.requested_address('not-an-ip', 24, 2) is None


def test_subnet_conflict_detection():
    assert netconfig.subnet_conflicts(0, ['10.1.1.0/24']) is True
    assert netconfig.subnet_conflicts(0, ['192.168.1.0/24', '10.1.1.0/25']) is True
    assert netconfig.subnet_conflicts(0, ['192.168.1.0/24', '172.16.0.0/24']) is False
    assert netconfig.subnet_conflicts(2, ['172.16.0.0/12']) is True
    assert netconfig.subnet_conflicts(0, []) is False
