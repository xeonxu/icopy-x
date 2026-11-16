"""The app writes rndis.conf; the shell script reads it. They must agree.

A silent drift between the two - the app writing ``device_ip`` while the script
waits for ``deviceip`` - would leave the device on the defaults with no error
anywhere, so the key set and the file grammar are pinned here.
"""

import pathlib
import re

import netconfig

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / 'tools/rndis/rndis.sh'

# Written for whoever reads the file; the script derives it from ``driver``.
DERIVED_KEYS = {'function'}


def _consumed_keys():
    text = SCRIPT.read_text()
    match = re.search(r'case "\$key" in\s*\n\s*(driver\|[a-z_|]+)\)', text)
    assert match, 'the key whitelist disappeared from rndis.sh'
    return {key.strip() for key in match.group(1).split('|')}


def _emitted_keys():
    text = netconfig.render_conf(netconfig.ROLE_CLIENT, netconfig.DRIVER_NCM, 2, 10)
    keys = set()
    for line in text.splitlines():
        if line.startswith('#') or '=' not in line:
            continue
        keys.add(line.split('=', 1)[0])
    return keys


def test_script_consumes_only_keys_the_app_writes():
    unknown = _consumed_keys() - _emitted_keys()
    assert not unknown, 'rndis.sh reads keys the app never writes: %s' % sorted(unknown)


def test_app_writes_no_key_the_script_ignores():
    ignored = _emitted_keys() - DERIVED_KEYS - _consumed_keys()
    assert not ignored, 'the app writes keys rndis.sh ignores: %s' % sorted(ignored)


def test_conf_grammar_is_shell_parseable():
    """`while IFS='=' read -r key value` must see one plain assignment per line."""
    text = netconfig.render_conf(netconfig.ROLE_GATEWAY, netconfig.DRIVER_RNDIS, 0, 2)
    for line in text.splitlines():
        assert re.match(r'^(#.*|[a-z_]+=[^\s]+)$', line), 'unparseable line: %r' % line


def test_rendered_driver_names_match_the_script_case_arms():
    text = SCRIPT.read_text()
    for name in ('ecm', 'rndis', 'ncm'):
        assert re.search(r'^\s*%s\)' % name, text, re.M), 'rndis.sh has no %s arm' % name
