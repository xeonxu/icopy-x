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
#
# "Nothing answers" is decided over a window, not by one attempt: the host's
# sharing DHCP server restarts on the adapter instance the gadget just created,
# so the first seconds after a profile switch always go unanswered. Asking once
# and giving up would turn every switch into a fallback.
IFACE=${1:-usb0}
CONF=${ICOPY_NET_CONF:-/etc/icopy/rndis.conf}
STATUS=${ICOPY_NET_STATUS:-/run/icopy-net.status}
HOOK=${ICOPY_UDHCPC_HOOK:-/etc/icopy/udhcpc.script}
RNDIS_SCRIPT=${ICOPY_RNDIS_SCRIPT:-/home/pi/rndis.sh}
NET_SYSFS=${ICOPY_NET_SYSFS:-/sys/class/net}
UDC_PATH=${ICOPY_UDC:-/sys/kernel/config/usb_gadget/icopy/UDC}
# Seconds to keep asking before declaring that no host serves this link, and the
# pause between attempts.
DEADLINE=${ICOPY_NET_DEADLINE:-30}
RETRY_SLEEP=${ICOPY_NET_RETRY_SLEEP:-1}

driver=rndis
fixed_octet=2
client_network=auto
if [ -r "$CONF" ]; then
    driver=$(sed -n 's/^driver=//p' "$CONF" | tail -1)
    fixed_octet=$(sed -n 's/^fixed_octet=//p' "$CONF" | tail -1)
    client_network=$(sed -n 's/^client_network=//p' "$CONF" | tail -1)
fi
case "$driver" in ecm|rndis|ncm) ;; *) driver=rndis ;; esac
case "$client_network" in auto|win|mac|linux) ;; *) client_network=auto ;; esac
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

START=$(date +%s)

elapsed() {
    echo $(( $(date +%s) - START ))
}

lease_once() {  # extra udhcpc options, e.g. -r <address>
    udhcpc -i "$IFACE" -n -q -t 1 -T 2 -s "$HOOK" "$@" >/dev/null 2>&1
}

# Keep asking until a lease appears or the soft deadline passes. The status file
# is rewritten on every attempt so the menu can show that we are still waiting
# instead of a stale "pending".
acquire() {  # $1 = soft deadline in seconds, then udhcpc options
    limit=$1
    shift
    while :; do
        lease_once "$@"
        granted=$(address)
        [ -n "$granted" ] && return 0
        now=$(elapsed)
        [ "$now" -ge "$limit" ] && return 1
        sleep "$RETRY_SLEEP"
    done
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

# Asking before the gadget is bound to a UDC cannot succeed: the host has not
# enumerated the interface yet, so its DHCP server has nothing to answer on.
if [ -e "$UDC_PATH" ]; then
    i=0
    while [ ! -s "$UDC_PATH" ] && [ $i -lt 50 ]; do
        sleep 0.2
        i=$((i + 1))
    done
fi

# The address must come from the DHCP client: an address left over from the
# gateway role would otherwise look like a lease.
ip addr flush dev "$IFACE" 2>/dev/null || true

# Host networks this device is told to expect. Windows ICS, macOS sharing and
# NetworkManager each use a fixed range, so naming the host lets us ask for the
# final address on the first try instead of spending a lease just to learn the
# subnet. Servers are free to refuse; then the learn path takes over.
preset_base=""
case "$client_network" in
    win)   preset_base=192.168.137.0 ;;
    mac)   preset_base=192.168.2.0 ;;
    linux) preset_base=10.42.0.0 ;;
esac

granted=""
bits=24
msg="lease from host"
if [ -n "$preset_base" ] && [ -n "$fixed_octet" ]; then
    want=$(echo "$preset_base" | awk -F. -v o="$fixed_octet" '{
        printf "%s.%s.%s.%d", $1, $2, $3, o
    }')
    # A third of the window is enough to prove the preset wrong; the rest pays
    # for learning the subnet the host actually uses.
    slice=$(( DEADLINE / 3 ))
    [ "$slice" -ge 1 ] || slice=1
    if acquire "$slice" -r "$want"; then
        if [ "$granted" = "$want" ]; then
            msg="lease $want"
        else
            ip addr flush dev "$IFACE" 2>/dev/null || true
            granted=""
        fi
    fi
fi

# 1. any lease at all, so we can learn the host's subnet.
if [ -z "$granted" ]; then
    if ! acquire "$DEADLINE"; then
        write_status "none" "no lease - gateway fallback"
        for pid in $(pgrep -f "udhcpc -i $IFACE" 2>/dev/null); do
            kill "$pid" 2>/dev/null
        done
        export ICOPY_NET_ROLE=gateway
        export ICOPY_NET_MSG="no lease - gateway fallback"
        exec sh "$RNDIS_SCRIPT"
    fi
fi

# 2. ask for the fixed last octet inside the subnet we just learned
if [ -n "$fixed_octet" ] && [ "${msg#lease }" != "${want:-}" ]; then
    bits=$(prefix)
    [ -n "$bits" ] || bits=24
    want=$(echo "$granted" | awk -F. -v o="$fixed_octet" -v b="$bits" '{
        if (b == 24) printf "%s.%s.%s.%d", $1, $2, $3, o;
        else printf "%s", "";
    }')
    if [ -n "$want" ] && [ "$want" != "$granted" ]; then
        held=$granted
        acquire "$DEADLINE" -r "$want"
        now=$(address)
        if [ "$now" = "$want" ]; then
            granted=$now
            msg="lease $want"
        elif [ -n "$now" ]; then
            granted=$now
            msg="requested $want ignored"
        else
            granted=$held
            msg="requested $want refused"
        fi
    fi
fi

# 3. keep the lease renewed; the hook refreshes the status file
udhcpc -i "$IFACE" -b -s "$HOOK" >/dev/null 2>&1 &

write_status "$granted/${bits:-24}" "$msg"
echo "USB network: client role on $IFACE, $granted (${msg})"
