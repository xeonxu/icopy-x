"""The mirror listener must survive a network profile change.

Field risk: the socket used to bind 10.1.1.1, the Gateway default. Pick another
Range, or let the device take a lease from the host, and that address no longer
belongs to the device - bind() fails and the mirror never listens, while nothing
in the UI says so. The socket is now pinned to the usb0 interface instead of an
address, so any profile works.
"""

import socket

import mirror_service


class FakeSocket:
    """Records the calls bind_link makes; never touches the network."""

    def __init__(self, refuse_pin=False):
        self.calls = []
        self._refuse_pin = refuse_pin

    def setsockopt(self, level, option, value):
        if self._refuse_pin:
            raise OSError(1, 'Operation not permitted')
        self.calls.append(('setsockopt', level, option, value))

    def bind(self, address):
        self.calls.append(('bind', address))


def test_the_listener_is_pinned_to_the_usb_link():
    sock = FakeSocket()

    mirror_service.bind_link(sock, 7767)

    pin = [c for c in sock.calls if c[0] == 'setsockopt']
    assert pin, 'the socket must be pinned to an interface'
    _, level, option, value = pin[0]
    assert level == socket.SOL_SOCKET
    assert option == socket.SO_BINDTODEVICE
    assert value == b'usb0\x00', 'configfs and the kernel want a C string'
    assert ('bind', ('0.0.0.0', 7767)) in sock.calls, \
        'the address comes from the profile, so the bind must not name one'


def test_a_refused_pin_still_listens():
    """Without CAP_NET_RAW the pin fails; the mirror must still come up."""
    sock = FakeSocket(refuse_pin=True)

    mirror_service.bind_link(sock, 7767)

    assert ('bind', ('0.0.0.0', 7767)) in sock.calls


def test_the_default_port_is_the_documented_one():
    sock = FakeSocket()

    mirror_service.bind_link(sock)

    assert ('bind', ('0.0.0.0', mirror_service.TCP_PORT)) in sock.calls
