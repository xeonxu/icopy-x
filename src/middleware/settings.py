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

"""Typed settings accessors wrapping config module.

OSS reimplementation of settings.so.
Binary source: settings.so (Cython)
Ground truth: V1090_MODULE_AUDIT.txt lines 329-343

Functions:
    getBacklight() / setBacklight(value)   — 0=Low, 1=Middle, 2=High
    getVolume() / setVolume(value)          — 0=Off, 1=Low, 2=Middle, 3=High
    getSleepTime() / setSleepTime(value)
    fromLevelGetBacklight(level)            — UI level → HW value
    fromLevelGetVolume(level)               — UI level → audio param
    fromLevelGetSleepTime(level)            — UI level → seconds
    getScreenMirror() / setScreenMirror(v)  — 0=off, 1=on
    getLanguage() / setLanguage(code)       — UI language code
    getUsbNetRole() / setUsbNetRole(v)      — 0=Gateway, 1=Client
    getUsbNetDriver() / setUsbNetDriver(v)  — 0=ECM, 1=RNDIS, 2=NCM
    getUsbNetSubnet() / setUsbNetSubnet(v)  — Gateway preset index 0-2
    getUsbNetFixedOctet() / setUsbNetFixedOctet(v) — 0=Auto, 2-254
    getUsbNetLinkTimeout() / setUsbNetLinkTimeout(v) — minutes, 0=off
"""

import config


def getBacklight():
    """Get current backlight level (0-2).

    Returns:
        int: 0=Low, 1=Middle, 2=High (default 2)
    """
    val = config.getValue('backlight', '2')
    try:
        return int(val)
    except (TypeError, ValueError):
        return 2


def setBacklight(value):
    """Set backlight level (0-2) and apply to hardware.

    Ground truth (trace_original_backlight_volume_20260410.txt):
    The original settings.so persists AND applies the hardware change.
    Every UP/DOWN navigation calls setBacklight() which both saves
    to conf.ini and sends the HMI serial command.

    Args:
        value: int 0=Low, 1=Middle, 2=High
    """
    config.setKeyValue('backlight', value)
    # Apply to hardware — original .so does this internally
    hw_val = int(fromLevelGetBacklight(value))
    try:
        import hmi_driver
        hmi_driver.setbaklight(hw_val)
    except Exception:
        pass


def getVolume():
    """Get current volume level (0-3).

    Returns:
        int: 0=Off, 1=Low, 2=Middle, 3=High (default 2)
    """
    val = config.getValue('volume', '2')
    try:
        return int(val)
    except (TypeError, ValueError):
        return 2


def setVolume(value):
    """Set volume level (0-3).

    Args:
        value: int 0=Off, 1=Low, 2=Middle, 3=High
    """
    config.setKeyValue('volume', value)


def getSleepTime():
    """Get current sleep timeout.

    Returns:
        int: sleep time value (default 1)
    """
    val = config.getValue('sleep_time', '1')
    try:
        return int(val)
    except (TypeError, ValueError):
        return 1


def setSleepTime(value):
    """Set sleep timeout.

    Args:
        value: int sleep time value
    """
    config.setKeyValue('sleep_time', value)


def fromLevelGetBacklight(level):
    """Convert UI backlight level to hardware brightness byte.

    Ground truth (strace of original firmware, 2026-04-10):
    setbaklight sends B + chr(brightness) + A over serial.
    Observed: Low=B\\x14A (20), Middle=B2A (50), High=BdA (100).

    Level 0 (Low) → 20, Level 1 (Middle) → 50, Level 2 (High) → 100

    Args:
        level: int 0-2

    Returns:
        int: hardware brightness value (raw byte, 1-100)
    """
    mapping = {0: 20, 1: 50, 2: 100}
    return mapping.get(level, 100)


def fromLevelGetVolume(level):
    """Convert UI volume level to audio parameter.

    Ground truth (trace_original_backlight_volume_20260410.txt):
    Level 0→0, Level 1→20, Level 2→50, Level 3→100
    Confirmed: playVolumeExam(20), setVolume(20) for level 1, etc.

    Args:
        level: int 0-3

    Returns:
        int: volume parameter
    """
    mapping = {0: 0, 1: 20, 2: 50, 3: 100}
    return mapping.get(level, 50)


def fromLevelGetSleepTime(level):
    """Convert UI sleep level to timeout in seconds.

    Args:
        level: int

    Returns:
        int: timeout in seconds
    """
    mapping = {0: 30, 1: 60, 2: 120, 3: 300, 4: 0}
    return mapping.get(level, 60)


def getScreenMirror():
    """Get screen mirror enabled state.

    Returns:
        int: 0=disabled, 1=enabled (default 0)
    """
    val = config.getValue('screen_mirror', '0')
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def setScreenMirror(value):
    """Set screen mirror setting.

    The mirror service starts/stops on next app restart, not immediately.
    This avoids USB gadget conflicts during live operation.

    Args:
        value: int 0=disabled, 1=enabled
    """
    config.setKeyValue('screen_mirror', str(int(value)))


def getLanguage():
    """Get the configured UI language code.

    Returns:
        str: language code (e.g. 'en', 'fr'); default 'en'
    """
    return config.getValue('language', 'en')


def setLanguage(code):
    """Set the UI language.

    The saved language is applied at boot — application.startApp() reads
    this value and calls resources.setLanguage() before the first screen
    builds — and is applied live when picked from the Settings menu.

    Args:
        code: language-code string (e.g. 'en', 'fr')
    """
    config.setKeyValue('language', str(code))


# ── USB network profile ──────────────────────────────────────────────
# The defaults mirror netconfig.DEFAULTS: a device that never opened the
# Network menu keeps today's behaviour (RNDIS, gateway, 10.1.1.x, .2).

def _get_int(key, default, allowed=None):
    """Config read helper: int value, clamped to *allowed* when given."""
    val = config.getValue(key, str(default))
    try:
        value = int(val)
    except (TypeError, ValueError):
        return default
    if allowed is not None and value not in allowed:
        return default
    return value


def getUsbNetRole():
    """0 = the device shares its network (gateway), 1 = it uses the host's."""
    return _get_int('usb_net_role', 0, (0, 1))


def setUsbNetRole(value):
    config.setKeyValue('usb_net_role', str(int(value)))


def getUsbNetDriver():
    """Host profile: 0 = Linux+macOS, 1 = Linux+Windows (default), 2 = all three."""
    return _get_int('usb_net_driver', 1, (0, 1, 2))


def setUsbNetDriver(value):
    config.setKeyValue('usb_net_driver', str(int(value)))


def getUsbNetSubnet():
    """Gateway preset index (0 = 10.1.1.x, 1 = 192.168.7.x, 2 = 172.16.0.x)."""
    return _get_int('usb_net_subnet', 0, (0, 1, 2))


def setUsbNetSubnet(value):
    config.setKeyValue('usb_net_subnet', str(int(value)))


def getUsbNetClientNetwork():
    """Client role: which host OS preset to ask on (0 = take what is offered)."""
    return _get_int('usb_net_client_network', 0, (0, 1, 2, 3))


def setUsbNetClientNetwork(value):
    config.setKeyValue('usb_net_client_network', str(int(value)))


def getUsbNetFixedOctet():
    """Client role: last octet to request, 0 = take whatever the host offers."""
    return _get_int('usb_net_fixed_octet', 2)


def setUsbNetFixedOctet(value):
    config.setKeyValue('usb_net_fixed_octet', str(int(value)))


def getUsbNetLinkTimeout():
    """Minutes without a USB host before the backlight goes off (0 = off)."""
    return _get_int('usb_net_link_timeout', 0)


def setUsbNetLinkTimeout(value):
    config.setKeyValue('usb_net_link_timeout', str(int(value)))


def usbNetwork():
    """The four persisted network keys as one mapping for netconfig."""
    return {
        'role': getUsbNetRole(),
        'driver': getUsbNetDriver(),
        'subnet': getUsbNetSubnet(),
        'client_network': getUsbNetClientNetwork(),
        'fixed_octet': getUsbNetFixedOctet(),
    }
