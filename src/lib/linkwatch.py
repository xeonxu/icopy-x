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

"""Panel power while no USB host is attached.

The condition is the USB link, not user input: the gadget netdev exists and its
carrier is up. When the link has been absent for longer than the configured
timeout the backlight goes off; the next key press turns it back on and restarts
the dwell time. Nothing about the network is retried or reverted because of this
— it is a panel decision, not a link-health one.

The decisions are pure functions and the driver is injected, so the whole
behaviour is testable on a host with no serial port and no gadget.
"""

import os
import threading
import time

# The gadget netdev the USB network binds to. A missing interface counts as "no
# host": that is exactly the state of a device in the Client role whose gadget
# has not come up yet.
GADGET_INTERFACES = ('usb0',)
SYSFS_NET = '/sys/class/net'
INTERVAL = 5.0


def carrier_up(path):
    """True when the carrier file exists and reports a link."""
    try:
        with open(path) as handle:
            return handle.read().strip() == '1'
    except (IOError, OSError):
        return False


def link_present(names=GADGET_INTERFACES, root=SYSFS_NET, reader=None):
    """True when at least one gadget netdev has carrier (a host is attached)."""
    read = reader or carrier_up
    for name in names:
        if read(os.path.join(root, name, 'carrier')):
            return True
    return False


def should_blank(absent_seconds, timeout_minutes):
    """True when the link has been gone for longer than the timeout allows."""
    if not timeout_minutes or timeout_minutes <= 0:
        return False
    if absent_seconds is None:
        return False
    return absent_seconds >= timeout_minutes * 60


def _backlight_off():
    """Darken the panel; 0 is the brightness byte the HMI accepts for off."""
    try:
        import hmi_driver
        hmi_driver.setbaklight(0)
    except Exception:
        pass


def _backlight_on():
    """Restore the brightness the user chose in Settings."""
    try:
        import hmi_driver
        import settings
        hmi_driver.setbaklight(settings.fromLevelGetBacklight(settings.getBacklight()))
    except Exception:
        pass


def _configured_timeout():
    """Minutes chosen in the Network screen; 0 (off) when unreadable."""
    try:
        import settings
        return settings.getUsbNetLinkTimeout()
    except Exception:
        return 0


class PanelSleep:
    """Watch the USB link and drive the backlight.

    Everything device-specific is injected (``present``, ``blank``, ``unblank``,
    ``timeout_minutes``, ``clock``, ``interval``), which keeps the state machine
    under test without a gadget or a serial port.
    """

    def __init__(self, present=None, blank=None, unblank=None, timeout_minutes=None,
                 interval=INTERVAL, clock=None, schedule=None):
        self.present_source = present or link_present
        self.blank_action = blank or _backlight_off
        self.unblank_action = unblank or _backlight_on
        self.timeout_source = timeout_minutes or _configured_timeout
        self.interval = interval
        self.clock = clock or time.monotonic
        self.schedule = schedule or (lambda action: action())
        self._lock = threading.Lock()
        self._absent_since = None
        self._blanked = False
        self._stop = threading.Event()
        self._thread = None

    # ── state ────────────────────────────────────────────────────────

    @property
    def blanked(self):
        with self._lock:
            return self._blanked

    def _set_blanked(self, value):
        with self._lock:
            changed = self._blanked != value
            self._blanked = value
        if changed:
            self.schedule(self.blank_action if value else self.unblank_action)

    def poll(self):
        """One decision step. Returns True when the panel state changed."""
        now = self.clock()
        with self._lock:
            was_blanked = self._blanked
        if self.present_source():
            with self._lock:
                self._absent_since = None
            self._set_blanked(False)
        else:
            with self._lock:
                if self._absent_since is None:
                    self._absent_since = now
                absent_for = now - self._absent_since
            if should_blank(absent_for, self.timeout_source()):
                self._set_blanked(True)
        return self.blanked != was_blanked

    def note_key(self):
        """A key press brings the panel back and restarts the dwell time."""
        if not self.blanked:
            return False
        with self._lock:
            self._absent_since = self.clock() if not self.present_source() else None
        self._set_blanked(False)
        return True

    # ── lifecycle ────────────────────────────────────────────────────

    def use_ui_thread(self, root):
        """Run the backlight changes on the Tk thread when a root exists."""
        if root is not None and hasattr(root, 'after'):
            self.schedule = lambda action: root.after(0, action)

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name='linkwatch')
        self._thread.start()
        return self

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                self.poll()
            except Exception:
                pass

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None


_WATCH = None


def get_watch():
    """The process-wide watcher the key handler wakes and startup starts."""
    global _WATCH
    if _WATCH is None:
        _WATCH = PanelSleep()
    return _WATCH
