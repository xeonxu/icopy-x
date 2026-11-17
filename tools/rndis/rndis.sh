#!/bin/sh
# USB network link for iCopy-X: one gadget function, chosen by /etc/icopy/rndis.conf.
#
#   driver=rndis  iCopy-X appears as RNDIS   -> Windows + Linux, no driver needed
#   driver=ecm    iCopy-X appears as CDC-ECM -> macOS + Linux
#   driver=ncm    iCopy-X appears as CDC-NCM -> macOS + Linux, Windows 11 only
#
# role=gateway (default) puts a DHCP server on the interface; role=client asks
# the host's internet sharing for a lease instead (see icopy-netclient).
#
# The script is idempotent: it tears down every gadget function it finds, not
# just the one it is about to build, so a half-switched state cannot survive.
G=${ICOPY_GADGET_DIR:-/sys/kernel/config/usb_gadget/icopy}
CONF=${ICOPY_NET_CONF:-/etc/icopy/rndis.conf}
STATUS=${ICOPY_NET_STATUS:-/run/icopy-net.status}
DNSMASQ_CONF=${ICOPY_DNSMASQ_CONF:-/run/icopy-dnsmasq.conf}

# ---- defaults: byte-for-byte the behaviour of the first release -------------
driver=rndis
role=gateway
subnet=10.1.1.0/24
device_ip=10.1.1.1
pool_start=10.1.1.100
pool_end=10.1.1.150
lease=12h
fixed_octet=2

if [ -r "$CONF" ]; then
    while IFS='=' read -r key value; do
        case "$key" in
            ''|\#*) continue ;;
        esac
        case "$key" in
            driver|role|subnet|device_ip|client_network|pool_start|pool_end|lease|fixed_octet)
                eval "$key=\$value" ;;
        esac
    done < "$CONF"
fi

# The client role falls back here when no host answers, without touching the
# persisted choice, and passes the reason it wants recorded.
[ -n "${ICOPY_NET_ROLE:-}" ] && role=$ICOPY_NET_ROLE
STATUS_MSG=${ICOPY_NET_MSG:-}

case "$driver" in
    ecm)  FUNCTION=ecm.usb0 ;  PRODUCT='iCopy-X ECM'  ;  NEEDS_OS_DESC=0 ;;
    ncm)  FUNCTION=ncm.usb0 ;  PRODUCT='iCopy-X NCM'  ;  NEEDS_OS_DESC=0 ;;
    *)    driver=rndis
          FUNCTION=rndis.usb0 ; PRODUCT='iCopy-X RNDIS'; NEEDS_OS_DESC=1 ;;
esac

status() {
    {
        echo "driver=$driver"
        echo "role=$role"
        echo "address=$1"
        echo "msg=$2"
        echo "ts=$(date +%s)"
    } > "$STATUS"
}

FUNCTION_DIR="$G/functions/$FUNCTION"
NET_SYSFS=${ICOPY_NET_SYSFS:-/sys/class/net}

# ---- is the running gadget already the one we want? -------------------------
# Switching role keeps the same USB function, so rebuilding the gadget would
# only make the host re-enumerate the interface - which restarts its internet
# sharing and, with it, the very DHCP server the client role is waiting for.
# Reuse the bound gadget when it already provides this function; only a driver
# change needs a new device.
reuse=0
if [ -s "$G/UDC" ] && [ -L "$G/configs/c.1/$FUNCTION" ] && [ -d "$FUNCTION_DIR" ]; then
    reuse=1
    if [ "$NEEDS_OS_DESC" = "1" ] && [ ! -d "$FUNCTION_DIR/os_desc/interface.rndis" ]; then
        reuse=0
    fi
fi

if [ ! -e "$G" ]; then
    mountpoint -q /sys/kernel/config || mount -t configfs none /sys/kernel/config
fi

build_gadget() {
    # ---- tear down whatever is there -------------------------------------------
    if [ -d "$G" ]; then
        echo "" > "$G/UDC" 2>/dev/null || true
        for link in "$G"/configs/c.1/*; do
            [ -L "$link" ] && rm -f "$link"
        done
        for function in "$G"/functions/*; do
            [ -d "$function" ] || continue
            for group in "$function"/os_desc/interface.*; do
                [ -d "$group" ] && rmdir "$group" 2>/dev/null
            done
            rmdir "$function/os_desc" "$function" 2>/dev/null || true
        done
        rm -f "$G/os_desc/c.1" 2>/dev/null || true
        rmdir "$G/configs/c.1/strings/0x409" "$G/configs/c.1" "$G/strings/0x409" \
              "$G/os_desc" "$G" 2>/dev/null || true
    fi

    for module in g_ether g_serial g_acm_ms g_mass_storage; do
        modprobe -r "$module" 2>/dev/null || true
    done

    # ---- build the requested function ------------------------------------------
    mkdir -p "$G"
    echo 0x1d6b > "$G/idVendor"
    echo 0x0104 > "$G/idProduct"
    echo 0x0100 > "$G/bcdDevice"
    echo 0x0201 > "$G/bcdUSB"
    mkdir -p "$G/strings/0x409"
    echo "icopyx-0001" > "$G/strings/0x409/serialnumber"
    echo "Lab401" > "$G/strings/0x409/manufacturer"
    echo "$PRODUCT" > "$G/strings/0x409/product"

    mkdir -p "$FUNCTION_DIR"
    case "$driver" in
        rndis)
            # The vendor kernel defaults these to CDC-ECM (02/06/00), which Windows
            # cannot drive; RNDIS needs e0/01/03.
            echo e0 > "$FUNCTION_DIR/class"
            echo 01 > "$FUNCTION_DIR/subclass"
            echo 03 > "$FUNCTION_DIR/protocol"
            ;;
    esac
    echo "02:11:22:33:44:55" > "$FUNCTION_DIR/dev_addr"
    echo "02:11:22:33:44:66" > "$FUNCTION_DIR/host_addr"

    if [ "$NEEDS_OS_DESC" = "1" ]; then
        # What makes Windows bind without a driver: USB\MS_COMP_RNDIS. The kernel
        # refuses an MS OS descriptor on the ecm/ncm functions, and macOS does not
        # use one, so only RNDIS writes it.
        mkdir -p "$FUNCTION_DIR/os_desc/interface.rndis"
        echo "RNDIS" > "$FUNCTION_DIR/os_desc/interface.rndis/compatible_id" 2>/dev/null || true
        echo "5162001" > "$FUNCTION_DIR/os_desc/interface.rndis/sub_compatible_id" 2>/dev/null || true
        echo 1 > "$G/os_desc/use" 2>/dev/null || true
    fi

    mkdir -p "$G/configs/c.1/strings/0x409"
    echo "$driver" > "$G/configs/c.1/strings/0x409/configuration"
    ln -s "$FUNCTION_DIR" "$G/configs/c.1/" 2>/dev/null || true
    if [ "$NEEDS_OS_DESC" = "1" ]; then
        ln -s "$G/configs/c.1" "$G/os_desc/c.1" 2>/dev/null || true
    fi

    if ! echo musb-hdrc.4.auto > "$G/UDC"; then
        status "none" "udc bind failed"
        echo "RNDIS gadget: UDC bind failed" >&2
        exit 1
    fi
}

if [ "$reuse" = "1" ]; then
    echo "USB network: keeping the bound $driver gadget, no USB re-enumeration"
else
    build_gadget
fi

# ---- resolve the netdev the function created --------------------------------
# The single network function normally comes up as usb0, which is what the
# units, dnsmasq and the mirror service expect. Only if that name is missing do
# we look for the interface whose gadget link points into this gadget.
NETDEV=""
i=0
while [ $i -lt 25 ] && [ -z "$NETDEV" ]; do
    [ -e "$NET_SYSFS/usb0" ] && NETDEV=usb0
    if [ -z "$NETDEV" ]; then
        for candidate in "$NET_SYSFS"/*; do
            name=${candidate##*/}
            case "$name" in lo|eth0) continue ;; esac
            case "$(readlink -f "$candidate/device" 2>/dev/null)" in
                *"/usb_gadget/icopy/"*) NETDEV=$name; break ;;
            esac
        done
    fi
    [ -z "$NETDEV" ] && sleep 0.2
    i=$((i + 1))
done

if [ -z "$NETDEV" ]; then
    status "none" "no network interface"
    echo "USB network: no interface appeared" >&2
    exit 1
fi

nmcli device set "$NETDEV" managed no 2>/dev/null || true
ip link set "$NETDEV" up

if [ "$role" = "client" ]; then
    # No DHCP server: the host's internet sharing gives us the address.
    systemctl --no-block stop rndis-dhcp.service >/dev/null 2>&1 || true
    systemctl --no-block restart icopy-net.service >/dev/null 2>&1 || true
    status "pending" "${STATUS_MSG:-asking the host for a lease}"
    echo "USB network: $driver in client role on $NETDEV"
    exit 0
fi

# ---- gateway role: address + DHCP server ------------------------------------
# Leaving the client role behind means dropping its DHCP client: a live
# `udhcpc -b` would keep renewing (and re-adding) the host's address.
systemctl --no-block stop icopy-net.service >/dev/null 2>&1 || true
netmask=$(ipcalc -n -m "$device_ip/24" 2>/dev/null | sed -n 's/^Netmask=//p')
[ -n "$netmask" ] || netmask=255.255.255.0
case "$subnet" in
    */24) prefix=24 ;;
    *)    prefix=24 ;;
esac

ip addr flush dev "$NETDEV" 2>/dev/null || true
ip addr add "$device_ip/$prefix" dev "$NETDEV" 2>/dev/null || true

{
    echo "interface=$NETDEV"
    echo "bind-interfaces"
    echo "dhcp-range=$pool_start,$pool_end,$netmask,$lease"
    echo "dhcp-option=3,$device_ip"
    echo "dhcp-option=1,$netmask"
    echo "dhcp-option=28,$(echo "$device_ip" | awk -F. '{printf "%s.%s.%s.255", $1, $2, $3}')"
    echo "no-resolv"
    echo "no-hosts"
    echo "port=0"
    echo "log-dhcp"
} > "$DNSMASQ_CONF"

systemctl --no-block restart rndis-dhcp.service >/dev/null 2>&1 || true

address=$(ip -4 addr show "$NETDEV" 2>/dev/null | awk '/inet /{print $2; exit}')
status "${address:-none}" "${STATUS_MSG:-gateway on $NETDEV}"
echo "USB network: $driver gateway, $NETDEV ${address:-no address}, udc=$(cat /sys/class/udc/musb-hdrc.4.auto/state 2>/dev/null)"
