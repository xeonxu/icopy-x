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

"""Apply a USB network profile on the device (the only I/O in this area).

``netconfig`` decides, this module writes and restarts. Keeping the two apart
lets the decisions be tested without a device while every side effect stays in
one place, small enough to read in full.
"""

import os
import subprocess

import netconfig

CONF_PATH = '/etc/icopy/rndis.conf'
STATUS_PATH = '/run/icopy-net.status'
SERVICE = 'rndis.service'
RESTART_TIMEOUT = 30


def write_conf(role, driver, subnet, fixed_octet, path=None):
    """Write ``rndis.conf`` atomically; the boot script tolerates 0-byte files.

    A reader must never observe a half-written file, so the text goes to a
    sibling and is renamed over the target.
    """
    path = path or CONF_PATH
    text = netconfig.render_conf(role, driver, subnet, fixed_octet)
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    tmp = path + '.tmp'
    with open(tmp, 'w') as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return text


def read_status(path=None):
    """Current ``/run/icopy-net.status`` as a mapping; empty when unreadable."""
    path = path or STATUS_PATH
    try:
        with open(path) as handle:
            return netconfig.parse_status(handle.read())
    except (IOError, OSError):
        return {}


def apply(role, driver, subnet, fixed_octet, path=None, runner=None):
    """Persist the profile and re-apply it live, then report the new status.

    Restarting the unit never requires a reboot: measured on hardware, the link
    re-enumerates and the host re-leases within seconds.
    """
    write_conf(role, driver, subnet, fixed_octet, path=path)
    run = runner or subprocess.run
    try:
        run(['systemctl', 'restart', SERVICE], timeout=RESTART_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        pass
    return read_status()
