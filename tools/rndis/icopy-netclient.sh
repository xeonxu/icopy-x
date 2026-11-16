#!/bin/sh
# Client role: take the address from the host's internet sharing.
#
# Windows ICS, NetworkManager's shared mode and macOS Internet Sharing all run a
# DHCP server on their end of the cable, but each uses a different subnet
# (192.168.137.0/24, 10.42.0.0/24, 192.168.2.0/24). So the device cannot know
# which address to ask for until it has seen one lease: it takes whatever is
# offered, learns the subnet from it, then re-requests the same subnet with the
# last octet the operator picked. Servers may ignore the request, in which case
# the offered address is kept and reported.
#
# If nothing answers within the deadline the link would be dead, so the script
# re-applies the gateway configuration: the device stays reachable and the
# menu says why.
IFACE=${1:-usb0}
CONF=${ICOPY_NET_CONF:-/etc/icopy/rndis.conf}
STATUS=${ICOPY_NET_STATUS:-/run/icopy-net.status}
HOOK=${ICOPY_UDHCPC_HOOK:-/etc/icopy/udhcpc.script}
RNDIS_SCRIPT=${ICOPY_RNDIS_SCRIPT:-/home/pi/rndis.sh}
NET_SYSFS=${ICOPY_NET_SYSFS:-/sys/class/net}

driver=rndis
fixed_octet=2
if [ -r "$CONF" ]; then
    driver=$(sed -n 's/^driver=//p' "$CONF" | tail -1)
    fixed_octet=$(sed -n 's/^fixed_octet=//p' "$CONF" | tail -1)
fi
case "$driver" in ecm|rndis|ncm) ;; *) driver=rndis ;; esac
case "$fixed_octet" in ''|*[!0-9]*) fixed_octet=2 ;; esac
[ "$fixed_octet" = "0" ] && fixed_octet=""

write_status() {  # $1 = address, $2 = message
    {
        echo "driver=$driver"
        echo "role=client"
        echo "address=$1"
        echo "msg=$2"
        echo "ts=$(date +%s)"
    } > "$STATUS"
}

lease() {  # extra udhcpc options, e.g. -r <address>
    udhcpc -i "$IFACE" -n -q -t 3 -T 2 -s "$HOOK" "$@" >/dev/null 2>&1
}

address() {
    ip -4 addr show "$IFACE" 2>/dev/null | awk '/inet /{split($2, a, "/"); print a[1]; exit}'
}

prefix() {
    ip -4 addr show "$IFACE" 2>/dev/null | awk '/inet /{split($2, a, "/"); print a[2]; exit}'
}

# The netdev appears asynchronously after the gadget binds.
i=0
while [ ! -e "$NET_SYSFS/$IFACE" ] && [ $i -lt 25 ]; do
    sleep 0.2
    i=$((i + 1))
done
if [ ! -e "$NET_SYSFS/$IFACE" ]; then
    write_status "none" "no network interface"
    exit 1
fi

# 1. any lease at all, so we can learn the host's subnet.
# The address must come from the DHCP client: an address left over from the
# gateway role would otherwise look like a lease.
ip addr flush dev "$IFACE" 2>/dev/null || true
lease
rc=$?
granted=$(address)
if [ "$rc" -ne 0 ] || [ -z "$granted" ]; then
    write_status "none" "no lease - gateway fallback"
    for pid in $(pgrep -f "udhcpc -i $IFACE" 2>/dev/null); do
        kill "$pid" 2>/dev/null
    done
    export ICOPY_NET_ROLE=gateway
    export ICOPY_NET_MSG="no lease - gateway fallback"
    exec sh "$RNDIS_SCRIPT"
fi

msg="lease from host"
# 2. ask for the fixed last octet inside the subnet we just learned
if [ -n "$fixed_octet" ]; then
    bits=$(prefix)
    [ -n "$bits" ] || bits=24
    want=$(echo "$granted" | awk -F. -v o="$fixed_octet" -v b="$bits" '{
        if (b == 24) printf "%s.%s.%s.%d", $1, $2, $3, o;
        else printf "%s", "";
    }')
    if [ -n "$want" ] && [ "$want" != "$granted" ]; then
        lease -r "$want"
        now=$(address)
        if [ "$now" = "$want" ]; then
            granted=$now
            msg="lease $want"
        else
            msg="requested $want ignored"
        fi
    fi
fi

# 3. keep the lease renewed; the hook refreshes the status file
udhcpc -i "$IFACE" -b -s "$HOOK" >/dev/null 2>&1 &

write_status "$granted/${bits:-24}" "$msg"
echo "USB network: client role on $IFACE, $granted (${msg})"
