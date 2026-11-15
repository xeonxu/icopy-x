# USB network profiles — design

Status: draft for review. Target: iCopy-X HW 1.7, OSS v1.1.7, kernel 4.14.111.

## Problem

The `usb0` link is fixed in three places (`rndis.sh`, `rndis-dhcp.service`,
`mirror_service.TCP_BIND_ADDRESS`): RNDIS gadget, `10.1.1.1/24`, `dnsmasq`
serving `10.1.1.100-150`. Three consequences:

1. **macOS cannot use the link at all.** Apple has no RNDIS driver; the current
   gadget never enumerates there.
2. **The device has no internet.** It is a DHCP server with no uplink, so
   on-device plugin download has no route and no resolver.
3. **Any change of subnet or role means editing files over SSH**, which is the
   link being changed.

## Goals

- Offer three **host profiles**, named in the menu by the operating systems
  they serve rather than by the USB class name, and chosen by the user:

  | Menu label | USB function | Compatibility |
  |---|---|---|
  | `Linux + macOS` | CDC-ECM (`ecm.usb0`) | macOS and Linux bind it out of the box. Windows does not. |
  | `Linux + Windows` | RNDIS (`rndis.usb0`) | Every Windows and Linux. Today's default. macOS does not. |
  | `Linux + macOS + Windows` | CDC-NCM (`ncm.usb0`) | Linux and macOS out of the box; Windows only where an NCM driver is present (Windows 10 22H2 has one but does not bind it to a custom gadget, and this kernel cannot advertise the compatible id it looks for). |

  The project does **not** install or ship a Windows driver: the third profile is
  offered with its limitation stated, not backed by a manual install step. Each
  row carries its compatibility line on the panel, so the choice is informed
  without the protocol names `rndis`/`ecm`/`ncm` ever appearing.
  The class names (`rndis`/`ecm`/`ncm`) stay in the config file and the code;
  they never appear on the 240×240 panel.
- A **role switch**: `Gateway` (the device runs the DHCP server, today's
  behaviour) or `Client` (the device takes a lease from the host's internet
  sharing, which is what gives it a route and a resolver).
- In `Client` role, keep the device's address **predictable** as a last octet,
  even though the three operating systems use different sharing subnets.
- **Show the address that was actually obtained**, so an operator never has to
  guess where `ssh` is.
- **Never lock the operator out**: any failure keeps a reachable configuration.

## Non-goals

- An `eth0` uplink and NAT for the USB host. Separate change.
- The plugin downloader itself (transport, trust model, install/rollback).
- mDNS/`avahi` discovery, IPv6, per-device DHCP reservations, Wi-Fi.

## Constraints (measured on the device)

| Fact | Value | Consequence |
|---|---|---|
| Kernel gadget functions | `CONFIG_USB_F_NCM=y`, `CONFIG_USB_CONFIGFS_NCM=y`, `CONFIG_USB_F_ECM=y`, `CONFIG_USB_CONFIGFS_ECM=y`, `..._ECM_SUBSET=y`, `CONFIG_USB_F_RNDIS=y`, `CONFIG_USB_G_NCM=m`, `CONFIG_USB_ETH_EEM=y` | All three USB network functions are available **without a kernel change**; built in, no module load (kallsyms has `ncm_bind`, `ecm_bind`, `rndis_bind`). |
| Windows 10 22H2 (19045) NCM | `UsbNcm.sys` + `usbncm.inf` present in `DriverStore\FileRepository\usbncm.inf_amd64_*`; its model line is `%UsbNcm.DeviceDesc%=UsbNcm_Device,USB\MS_COMP_WINNCM`, and the class/subclass/protocol line (`USB\Class_02&SubClass_0d&Prot_00`) is **commented out** | NCM binds on Windows through an **MS OS descriptor with `compatible_id = WINNCM`**, not through a VID/PID. A plain NCM gadget enumerates as `CDC NCM` with no driver (observed) — and this kernel cannot advertise it (next row). |
| Windows 10 22H2 RNDIS | `netrndis.inf` + `RNDISMP.sys` | Unchanged: binds through the `RNDIS`/`5162001` compatible id, which is why the current gadget works with a stock `1d6b:0104` id. |
| MS OS descriptor support per function | probe: `mkdir functions/ncm.usb0/os_desc/...` → `EPERM`, same for `ecm.usb0`; `rndis.usb0` accepts it | **Windows cannot auto-bind NCM or ECM on this kernel** — there is no compatible id to advertise for them. |
| DHCP client with requested address | `/sbin/udhcpc` (`-r, --request IP`), `/sbin/dhclient` | Option 50 is reachable from user space. |
| NetworkManager | 1.2.6 active; `usb0` deliberately `managed no` | NM's internal client cannot send option 50 and is kept away from `usb0`. |
| `dnsmasq` today | `--interface=usb0 --bind-interfaces --dhcp-range=10.1.1.100,10.1.1.150,255.255.255.0,12h --dhcp-option=3,10.1.1.1 --dhcp-option=1,255.255.255.0 --dhcp-option=28,10.1.1.255 --no-resolv --no-hosts --port=0` | Same shape is generated for other subnets; `--port=0` stays while the device has no uplink. |
| Host sharing defaults | Windows ICS `192.168.137.0/24` gw `.1`; NM `shared` `10.42.0.0/24` gw `.1`; macOS Internet Sharing `192.168.2.0/24` gw `.1` | The device must not hard-code a subnet; it learns one per lease. |
| UI | 240×240, 5-way + OK/M1/M2; `LanguageActivity` already implements a radio sub-menu via `CheckedListView` | The new screen reuses that pattern; no free-text input. |

## Design

### Settings (app config keys, `src/middleware/settings.py`)

| Key | Values | Default |
|---|---|---|
| `usb_net_role` | `0` Gateway, `1` Client | `0` |
| `usb_net_driver` | `0` ECM (`Linux + macOS`), `1` RNDIS (`Linux + Windows`), `2` NCM (`Linux + macOS + Windows`) | `1` |
| `usb_net_fixed_octet` | `0` Auto, else `2..254` | `2` |
| `usb_net_subnet` | `0` `10.1.1.x`, `1` `192.168.7.x`, `2` `172.16.0.x` | `0` |

`usb_net_subnet` applies to `Gateway` role only; in `Client` role the subnet
comes from the lease.

### Derived runtime file

`/etc/icopy/rndis.conf` — generated, never hand-edited (header says so), written
by the app on every apply and by `install.sh` as a starting point:

```ini
# generated by iCopy-X — edit the Settings menu instead
role=gateway          # gateway | client
driver=rndis          # ecm | rndis | ncm
subnet=10.1.1.0/24    # gateway role
device_ip=10.1.1.1    # gateway role
pool_start=10.1.1.100
pool_end=10.1.1.150
lease=12h
fixed_octet=2         # client role; 0 = auto
```

Absent or unreadable file ⇒ the defaults above ⇒ byte-for-byte today's
behaviour.

### Boot and apply flow

Files live in `tools/rndis/` and are copied by `install.sh`:

| Source | Installed as |
|---|---|
| `rndis.sh` | `/home/pi/rndis.sh` (as today) |
| `rndis-dhcp.service` | `/etc/systemd/system/rndis-dhcp.service` |
| `icopy-net.service` | `/etc/systemd/system/icopy-net.service` |
| `icopy-netclient.py` | `/usr/local/sbin/icopy-netclient` |
| `udhcpc.script` | `/etc/icopy/udhcpc.script` |

1. `rndis.service` runs `rndis.sh`, which reads `/etc/icopy/rndis.conf`.
2. `rndis.sh` builds one network function: `ecm.usb0`, `rndis.usb0` or
   `ncm.usb0`. Only the RNDIS profile writes the MS OS descriptor (`RNDIS` /
   `5162001`), which is what makes Windows bind it without a driver; ECM and NCM
   need none (macOS and Linux match them by class), and the vendor kernel refuses
   an MS OS descriptor on those two functions anyway. The product string names
   the profile. The single network function is expected to come up
   as `usb0` in both profiles; if the name ever differs, the script resolves the
   netdev instead by matching `readlink -f /sys/class/net/*/device` against the
   gadget's function directory, so nothing depends on the name.
3. `Gateway` role: `ip addr add <device_ip>/<prefix> dev usb0`, write
   `/run/icopy-dnsmasq.conf`, then
   `systemctl --no-block restart rndis-dhcp.service`.
4. `Client` role: `systemctl --no-block stop rndis-dhcp.service`, then
   `systemctl --no-block restart icopy-net.service`, whose oneshot command is
   `icopy-netclient` (the acquisition sequence below).
5. Both roles write `/run/icopy-net.status`
   (`role=`, `driver=`, `addr=`, `gw=`, `dns=`, `msg=`, `ts=`), which the UI
   reads. The status file is the only thing the UI trusts about the live link.

### Two-step address acquisition (`Client` role)

1. `udhcpc -n -q -t 5 -T 2 -i usb0 -s /etc/icopy/udhcpc.script` — take any
   lease, then read `usb0`'s address to learn the host's subnet.
2. If `fixed_octet != 0`, request `<learned network>.<fixed_octet>` with
   `udhcpc -n -q -t 5 -T 2 -r <addr> …`.
3. If that second run fails, or the granted address differs from the requested
   one, keep the step-1 lease and set `msg=requested <addr> ignored`; the
   address is still shown.
4. Start `udhcpc -b` for lease renewal; the script hook rewrites the status file
   on every renewal so a changed address is visible immediately.
5. Deadline 30 s for the whole sequence. On expiry: stop trying, reconfigure as
   `Gateway` (static address + `dnsmasq`), and set
   `msg=no lease — gateway fallback`. The persisted settings are untouched, so
   the next boot retries the requested role and the UI keeps showing the
   fallback until the user changes something.

The two-step sequence is the whole point of the `Client` role: option 50 needs a
full address, and the sharing subnet is a property of the host, not of the
device. Windows ICS, NM `shared` and macOS Internet Sharing may all ignore the
request; the design therefore treats the request as a hint and always reports
what was granted.

### UI

`Settings` gains a fourth row, `Network`, which opens `NetworkActivity`
(`CheckedListView`, same pattern as `LanguageActivity`):

| Row | Values |
|---|---|
| Role | `Gateway` / `Client` |
| Host OS | `Linux + macOS` / `Linux + Windows` / `Linux + macOS + Windows` |
| Fixed IP | `Auto` / `.2` / `.10` / `.20` / `.50` (last octet; `Client` role only) |
| Subnet | `10.1.1.x` / `192.168.7.x` / `172.16.0.x` (Gateway role only) |
| Status (read-only) | `usb0 192.168.137.2/24 gw 192.168.137.1` or `no lease — gateway fallback` |

Choosing a value applies immediately: persist the key, regenerate
`/etc/icopy/rndis.conf`, `systemctl restart rndis.service`, and re-read the status
after about a second while the footer shows `applying…`. `PWR` leaves without
changes. Rows that the current role makes irrelevant are drawn dimmed and
refuse input rather than being hidden, so the layout never jumps.

A driver or role change re-enumerates the USB device, and **Windows does not
recover from that by itself**: after a rebuild the RNDIS function instance sits
at `CM_PROB_FAILED_START` and the link stays dead — observed twice on
2026-11-15, and a cable re-plug did not clear it while a device reboot did. The
menu therefore only *persists* the choice and prompts `Restart to apply`; the
switch happens on the next boot, when `rndis.service` builds the new gadget from
a clean configfs. That is why the Shutdown/Reboot menu entries are a
prerequisite for this feature rather than a separate nicety.

### Link timeout and the panel backlight

A profile or role change can leave the device on battery with the panel lit and
no host attached. The Network menu therefore gains a timeout:

| Key | Values | Default |
|---|---|---|
| `usb_net_link_timeout` | `0` Off, `1` 1 min, `2` 2 min, `5` 5 min, `10` 10 min | `0` |

The condition is the USB host link, not user input: the gadget netdev exists and
its carrier is up. When the link has been absent for longer than the timeout the
device turns the backlight off and leaves the network configuration untouched;
the next key press turns the backlight back on. Nothing is retried or reverted
because of this timeout — it is a panel power decision, not a link-health one.

If the intent is a general "screen off when idle" setting instead, it belongs
beside the existing `getSleepTime()` row rather than here; the row above is
scoped to the USB link.
 If a serial mirror session is running it
takes the UDC, so the restart sequence must run after `_restore_rndis()` and a
running mirror session is stopped first.

### i18n

New keys in `en`, `fr`, `zh`: `network`, `net_role`, `net_gateway`,
`net_client`, `net_driver`, `net_driver_win`, `net_driver_mac`, `net_fixed`,
`net_fixed_auto`, `net_subnet`, `net_status`, `net_applying`,
`net_link_restarts`, `net_no_lease`.

### Error handling

| Condition | Behaviour |
|---|---|
| `rndis.conf` absent/garbled | Defaults (`gateway`/`rndis`/`10.1.1.1`), `msg=defaults` |
| Chosen subnet overlaps `eth0`'s address or route | Refuse the apply, keep the previous configuration, `msg=subnet conflict` |
| `dnsmasq` bind failure | Log, `msg=dhcp server failed`; the address stays, so the link remains usable by static configuration |
| `Client` role, no lease within 30 s | `Gateway` fallback, `msg=no lease — gateway fallback` |
| ECM profile on a Windows host | Expected: no driver. The panel still works and the user switches back; no reboot needed |
| `udhcpc` granted a different address | Keep it, show it, `msg=requested <addr> ignored` |

## Testing

Host tests, `tests/ui/test_netconfig.py` and `tests/ui/activities/test_network_menu.py`,
against pure functions in `src/middleware/netconfig.py`:

- role/driver/subnet/fixed-octet → `rndis.conf` text, including the defaults when
  the file is absent;
- `dnsmasq` argument list per subnet preset (range, gateway, mask, broadcast);
- requested address from a learned prefix (`.2` of `10.42.0.0/24` → `10.42.0.2`,
  `.2` of `192.168.2.0/24` → `192.168.2.2`);
- overlap rejection given a route table;
- status parsing, and the fallback message after the deadline;
- the menu: four rows, dimmed rows refusing input, apply persisting and
  restarting, status footer.

Each test is mutation-checked: the behaviour is reverted and exactly one test
must fail.

Device verification (iCopy-X HW 1.7):

| Check | Expectation |
|---|---|
| `Gateway` + `Windows/Linux` | Today's behaviour, Windows lease `10.1.1.102`, SSH and TCP mirror unchanged |
| `Gateway` + other subnet | `usb0` and the lease move to the chosen subnet |
| `Client` on Windows ICS | Lease in `192.168.137.0/24`, requested `.2` honoured or reported, default route and resolver present |
| `Client` on NM `shared` | Same in `10.42.0.0/24` |
| `Client` with sharing off | 30 s, then gateway fallback, link reachable again |
| RNDIS profile after a reboot | Binds, `10.1.1.102` lease, SSH and TCP mirror work (observed repeatedly) |
| A profile switch | The choice persists, nothing is rebuilt live, the new gadget appears on the next boot |
| `macOS` + ECM | On Linux (`cdc_ether`) the link enumerates; on macOS a Network service appears and Internet Sharing reaches the device — **requires a Mac, not available here** |
| Switch back | RNDIS profile restores with no reboot; PC mode round trip still hands the UDC back and returns it |

macOS ECM binding is the only goal that cannot be verified in this environment.
It is recorded as a release risk rather than assumed.

## Compatibility and migration

- Defaults reproduce today's behaviour exactly; no migration step, no new
  mandatory file (`rndis.conf` absent ⇒ gateway/RNDIS/`10.1.1.1`).
- `install.sh` continues to work; the new files are additive and the units keep
  their names.
- An image built without these files behaves as before: `rndis.sh` falls back to
  its built-in defaults.
- Recovery without the UI: delete `/etc/icopy/rndis.conf` and run
  `systemctl restart rndis rndis-dhcp`; the device returns to `10.1.1.1/24`.

## Rollout

1. `src/middleware/netconfig.py` + host tests (pure logic, no device needed).
2. `tools/rndis/rndis.sh` reading the conf: driver profile, address, generated
   `dnsmasq` arguments, role-specific unit actions, `/run/icopy-net.status`.
3. `tools/rndis/icopy-netclient.py`, `tools/rndis/udhcpc.script` and
   `tools/rndis/icopy-net.service`: two-step acquisition, renewal, fallback.
4. `src/lib/activity_main.py` (`NetworkActivity`) + `src/middleware/settings.py`
   accessors + i18n keys + tests.
5. `tools/rndis/install.sh` installing the new files, then the device matrix
   above, then the IPK.
