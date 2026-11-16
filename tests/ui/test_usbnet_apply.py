"""Contract tests for the USB network settings glue.

Three layers, each with an observable failure mode:

  * ``settings`` accessors — defaults keep today's behaviour, and a corrupted
    value must never reach the boot script;
  * ``netconfig.parse_status`` / ``status_text`` — the panel must never claim an
    address the device does not have;
  * ``usbnet.apply`` — the profile file is written before the unit restarts, so
    a restart cannot read a stale or half-written profile.
"""

import pytest

import netconfig
import settings
import usbnet


@pytest.fixture
def conf(monkeypatch):
    """In-memory replacement for the persisted config keys."""
    values = {}

    def get(key, default=None):
        return values.get(key, default)

    def put(key, value):
        values[key] = str(value)

    monkeypatch.setattr(settings.config, 'getValue', get)
    monkeypatch.setattr(settings.config, 'setKeyValue', put)
    return values


class TestSettingsAccessors:

    def test_defaults_keep_the_shipped_behaviour(self, conf):
        assert settings.getUsbNetRole() == netconfig.ROLE_GATEWAY
        assert settings.getUsbNetDriver() == netconfig.DRIVER_RNDIS
        assert settings.getUsbNetSubnet() == 0
        assert settings.getUsbNetFixedOctet() == 2
        assert settings.getUsbNetLinkTimeout() == 0

    def test_a_corrupted_value_falls_back_to_the_default(self, conf):
        conf['usb_net_driver'] = '99'
        conf['usb_net_role'] = 'client'
        conf['usb_net_subnet'] = ''
        assert settings.getUsbNetDriver() == netconfig.DRIVER_RNDIS
        assert settings.getUsbNetRole() == netconfig.ROLE_GATEWAY
        assert settings.getUsbNetSubnet() == 0

    def test_values_survive_a_write_read_round_trip(self, conf):
        settings.setUsbNetRole(netconfig.ROLE_CLIENT)
        settings.setUsbNetDriver(netconfig.DRIVER_NCM)
        settings.setUsbNetSubnet(2)
        settings.setUsbNetFixedOctet(50)
        settings.setUsbNetLinkTimeout(5)
        assert settings.usbNetwork() == {'role': 1, 'driver': 2, 'subnet': 2,
                                         'fixed_octet': 50}
        assert settings.getUsbNetLinkTimeout() == 5


class TestStatusParsing:

    def test_reads_the_file_the_boot_script_writes(self):
        text = ('driver=rndis\nrole=client\naddress=192.168.137.2/24\n'
                'msg=lease 192.168.137.2\nts=1794789435\n')
        status = netconfig.parse_status(text)
        assert status['address'] == '192.168.137.2/24'
        assert status['role'] == 'client'

    def test_garbage_is_empty_not_an_error(self):
        assert netconfig.parse_status('') == {}
        assert netconfig.parse_status(None) == {}
        assert netconfig.parse_status('not a status file') == {}

    def test_the_panel_shows_the_address_when_there_is_one(self):
        assert netconfig.status_text({'address': '10.1.1.1/24'}) == '10.1.1.1/24'

    def test_the_panel_never_shows_the_placeholder_address(self):
        assert netconfig.status_text({'address': 'none'}) == netconfig.STATUS_NO_LINK

    def test_a_fallback_is_reported_as_no_lease(self):
        status = {'address': 'none', 'msg': 'no lease - gateway fallback'}
        assert netconfig.status_text(status) == netconfig.STATUS_NO_LEASE


class TestApply:

    def _apply(self, tmp_path, **kwargs):
        calls = []

        def runner(argv, **opts):
            calls.append((argv, opts))

        conf_path = tmp_path / 'rndis.conf'
        status_path = tmp_path / 'status'
        status_path.write_text('driver=ecm\nrole=gateway\naddress=10.1.1.1/24\n')
        status = usbnet.apply(0, netconfig.DRIVER_ECM, 1, 2,
                              path=str(conf_path), runner=runner, **kwargs)
        return conf_path, status_path, calls, status

    def test_writes_the_generated_profile(self, tmp_path):
        conf_path, _, _, _ = self._apply(tmp_path)
        expected = netconfig.render_conf(0, netconfig.DRIVER_ECM, 1, 2)
        assert conf_path.read_text() == expected
        assert 'driver=ecm' in expected
        assert 'device_ip=192.168.7.1' in expected

    def test_restarts_the_unit_without_a_reboot(self, tmp_path):
        conf_path = tmp_path / 'rndis.conf'
        seen = []

        def runner(argv, **opts):
            # The profile must already be on disk when the unit restarts, or the
            # script reads the previous one.
            seen.append((list(argv), conf_path.read_text()))

        usbnet.apply(0, netconfig.DRIVER_ECM, 1, 2,
                     path=str(conf_path), runner=runner)
        assert [argv for argv, _ in seen] == [['systemctl', 'restart', 'rndis.service']]
        assert 'driver=ecm' in seen[0][1]

    def test_leaves_no_temporary_file_behind(self, tmp_path):
        conf_path, _, _, _ = self._apply(tmp_path)
        assert not conf_path.with_name('rndis.conf.tmp').exists()

    def test_reports_the_status_the_script_wrote(self, tmp_path, monkeypatch):
        status_path = tmp_path / 'status'
        status_path.write_text('driver=ecm\nrole=gateway\naddress=192.168.7.1/24\n')
        monkeypatch.setattr(usbnet, 'STATUS_PATH', str(status_path))
        conf_path = tmp_path / 'rndis.conf'
        status = usbnet.apply(0, netconfig.DRIVER_ECM, 1, 2,
                              path=str(conf_path), runner=lambda *a, **k: None)
        assert status['address'] == '192.168.7.1/24'

    def test_a_failing_restart_does_not_lose_the_profile(self, tmp_path):
        conf_path = tmp_path / 'rndis.conf'

        def boom(argv, **opts):
            raise OSError('systemctl missing')

        usbnet.apply(1, netconfig.DRIVER_RNDIS, 0, 2,
                     path=str(conf_path), runner=boom)
        assert 'role=client' in conf_path.read_text()

    def test_an_unreadable_status_is_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(usbnet, 'STATUS_PATH', str(tmp_path / 'absent'))
        assert usbnet.read_status() == {}
