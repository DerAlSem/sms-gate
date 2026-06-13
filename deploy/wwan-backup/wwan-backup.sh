#!/usr/bin/env bash
# wwan-backup — backup internet channel via Quectel EM06 (QMI, /dev/cdc-wdm0).
#
# Data flows through qmi_wwan (wwan0) and does NOT touch AT ports ttyUSB2/3, which
# are used by sms-gate. ModemManager is intentionally not used — it interferes with AT ports.
#
# Design: the data session is kept up at all times with a standby default route
# (metric 700). Watchdog pings the outside world every 30s strictly via the primary
# interface (enp2s0); after FAIL_THRESHOLD consecutive failures it inserts a default via
# wwan0 at metric 50 (overrides the primary metric 100) and switches DNS; after
# OK_THRESHOLD consecutive successes — restores everything back.
#
# Subcommands: up | down | watchdog | status
set -u

# --- config (can be overridden in /etc/default/wwan-backup) -------------------
DEVICE="/dev/cdc-wdm0"
IFACE="wwan0"
APN="internet.tele2.ru"
MAIN_IFACE="enp2s0"
BACKUP_METRIC=700      # standby route in normal mode (ignored by the kernel)
FAILOVER_METRIC=50     # overrides the primary (metric 100) during failover
PING_TARGETS="1.1.1.1 8.8.8.8"
FAIL_THRESHOLD=3       # consecutive failures before switching (3 x 30s = ~1.5 min)
OK_THRESHOLD=3         # consecutive successes before restoring
STATE_DIR="/run/wwan-backup"
ENV_FILE="/opt/sms-gate/.env"   # ALERT_BOT_TOKEN/ALERT_CHAT_ID for notifications
SRC_TABLE=100          # routing table for reply traffic sourced from enp2s0
# ------------------------------------------------------------------------------
[ -f /etc/default/wwan-backup ] && . /etc/default/wwan-backup

log() { logger -t wwan-backup "$*"; echo "wwan-backup: $*" >&2; }

read_env() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2-; }

alert() {
    # Telegram notification on channel switch. Skipped if no credentials.
    # NB: from the backup channel (T2) api.telegram.org may not respond
    # (mobile carrier blocks) — hence retries and a log entry on failure.
    local token chat attempt
    token="${ALERT_BOT_TOKEN:-$(read_env ALERT_BOT_TOKEN)}"
    chat="${ALERT_CHAT_ID:-$(read_env ALERT_CHAT_ID)}"
    [ -n "$token" ] && [ -n "$chat" ] || return 0
    for attempt in 1 2 3; do
        if curl -sS --max-time 15 "https://api.telegram.org/bot${token}/sendMessage" \
            --data-urlencode "chat_id=${chat}" \
            --data-urlencode "text=📡 $(hostname): $*" >/dev/null 2>&1; then
            return 0
        fi
        sleep 5
    done
    log "alert: Telegram unreachable after 3 attempts (default: $(ip route show default | head -1))"
}

mask2prefix() {
    # 255.255.255.252 -> 30
    local x bits=0 IFS=.
    for x in $1; do
        case "$x" in
            255) bits=$((bits+8));;
            254) bits=$((bits+7));;
            252) bits=$((bits+6));;
            248) bits=$((bits+5));;
            240) bits=$((bits+4));;
            224) bits=$((bits+3));;
            192) bits=$((bits+2));;
            128) bits=$((bits+1));;
            0) ;;
        esac
    done
    echo "$bits"
}

qmi() { qmicli -p -d "$DEVICE" "$@"; }

setup_src_routing() {
    # Replies to inbound connections via MAIN_IFACE (SSH, port-forwarded 443) must
    # leave via MAIN_IFACE even during failover — asymmetric routing would kill them.
    local src gw
    src=$(ip -4 -br addr show "$MAIN_IFACE" | awk '{print $3}' | cut -d/ -f1)
    gw=$(ip route show default dev "$MAIN_IFACE" | awk '/via/ {print $3; exit}')
    [ -n "$src" ] && [ -n "$gw" ] || { log "src-routing: no address/gateway on $MAIN_IFACE — skipping"; return 0; }
    ip route replace default via "$gw" dev "$MAIN_IFACE" table "$SRC_TABLE"
    ip rule del from "$src" lookup "$SRC_TABLE" 2>/dev/null || true
    ip rule add from "$src" lookup "$SRC_TABLE" priority 100
}

teardown_src_routing() {
    local src
    src=$(ip -4 -br addr show "$MAIN_IFACE" | awk '{print $3}' | cut -d/ -f1)
    [ -n "$src" ] && ip rule del from "$src" lookup "$SRC_TABLE" 2>/dev/null || true
    ip route flush table "$SRC_TABLE" 2>/dev/null || true
}

session_connected() {
    qmi --wds-get-packet-service-status 2>/dev/null | grep -q "Connection status: 'connected'"
}

apply_addressing() {
    # Extract IP/GW/DNS/MTU from the current QMI session and apply to wwan0.
    local settings ip mask prefix gw dns1 dns2 mtu
    # NB: unlike start-network, here qmicli prints values WITHOUT quotes
    settings=$(qmi --wds-get-current-settings) || { log "wds-get-current-settings failed"; return 1; }
    ip=$(awk '/IPv4 address:/ {print $NF}' <<<"$settings")
    mask=$(awk '/IPv4 subnet mask:/ {print $NF}' <<<"$settings")
    gw=$(awk '/IPv4 gateway address:/ {print $NF}' <<<"$settings")
    dns1=$(awk '/IPv4 primary DNS:/ {print $NF}' <<<"$settings")
    dns2=$(awk '/IPv4 secondary DNS:/ {print $NF}' <<<"$settings")
    mtu=$(awk '/MTU:/ {print $NF}' <<<"$settings")
    [ -n "$ip" ] && [ -n "$gw" ] || { log "no IPv4 settings in session"; return 1; }
    prefix=$(mask2prefix "${mask:-255.255.255.252}")

    ip addr flush dev "$IFACE"
    ip addr add "$ip/$prefix" dev "$IFACE"
    [ -n "$mtu" ] && ip link set "$IFACE" mtu "$mtu"
    ip route replace default via "$gw" dev "$IFACE" metric "$BACKUP_METRIC" onlink

    echo "$gw" > "$STATE_DIR/gw"
    # Operator DNS is assigned to the link, but default-route is off: in normal mode
    # resolution goes via the primary channel; these servers are activated only on failover.
    resolvectl dns "$IFACE" ${dns1:+$dns1} ${dns2:+$dns2} 2>/dev/null || true
    resolvectl default-route "$IFACE" false 2>/dev/null || true
    log "session up: $ip/$prefix gw=$gw mtu=${mtu:-?} dns=${dns1:-?},${dns2:-?}"
}

cmd_up() {
    mkdir -p "$STATE_DIR"
    [ -c "$DEVICE" ] || { log "$DEVICE not found — modem not in QMI mode?"; exit 1; }
    setup_src_routing

    # idempotency: session already connected (unit restart) — just re-apply addressing
    if session_connected; then
        log "session already connected — re-applying addressing"
        apply_addressing
        return
    fi

    # raw-ip is required for qmi_wwan on modern kernels; can only be changed while the link is down
    ip link set "$IFACE" down
    echo Y > "/sys/class/net/$IFACE/qmi/raw_ip" 2>/dev/null || true
    ip link set "$IFACE" up

    local out pdh cid
    out=$(qmi --wds-start-network="apn=$APN,ip-type=4" --client-no-release-cid) \
        || { log "wds-start-network failed: $out"; exit 1; }
    pdh=$(awk -F"'" '/Packet data handle:/ {print $2}' <<<"$out")
    cid=$(awk -F"'" '/CID:/ {print $2}' <<<"$out")
    echo "${pdh:-}" > "$STATE_DIR/pdh"
    echo "${cid:-}" > "$STATE_DIR/cid"

    apply_addressing || exit 1
}

cmd_down() {
    local pdh cid
    pdh=$(cat "$STATE_DIR/pdh" 2>/dev/null || true)
    cid=$(cat "$STATE_DIR/cid" 2>/dev/null || true)
    if [ -n "$pdh" ] && [ -n "$cid" ]; then
        qmi --wds-stop-network="$pdh" --client-cid="$cid" 2>/dev/null || true
    fi
    restore_main_route
    teardown_src_routing
    ip route del default dev "$IFACE" metric "$BACKUP_METRIC" 2>/dev/null || true
    ip addr flush dev "$IFACE" 2>/dev/null || true
    ip link set "$IFACE" down 2>/dev/null || true
    rm -rf "$STATE_DIR"
    log "session down"
}

main_uplink_ok() {
    local t
    for t in $PING_TARGETS; do
        ping -c1 -W2 -I "$MAIN_IFACE" "$t" >/dev/null 2>&1 && return 0
    done
    return 1
}

enter_failover() {
    local gw
    gw=$(cat "$STATE_DIR/gw" 2>/dev/null || true)
    [ -n "$gw" ] || { log "failover: no gw in state — session not up?"; return 1; }
    ip route replace default via "$gw" dev "$IFACE" metric "$FAILOVER_METRIC" onlink
    resolvectl default-route "$MAIN_IFACE" false 2>/dev/null || true
    resolvectl default-route "$IFACE" true 2>/dev/null || true
    touch "$STATE_DIR/failover"
    log "FAILOVER: primary channel is down, traffic via $IFACE (T2)"
    alert "primary internet is down — switched to backup via T2"
}

restore_main_route() {
    ip route del default dev "$IFACE" metric "$FAILOVER_METRIC" 2>/dev/null || true
    resolvectl default-route "$MAIN_IFACE" true 2>/dev/null || true
    resolvectl default-route "$IFACE" false 2>/dev/null || true
    rm -f "$STATE_DIR/failover"
}

cmd_watchdog() {
    mkdir -p "$STATE_DIR"
    exec 9>"$STATE_DIR/lock"
    flock -n 9 || exit 0   # previous run still in progress

    # 1) keep QMI session alive
    if ! session_connected; then
        log "QMI session dropped — re-establishing"
        cmd_up || { log "re-up failed"; exit 1; }
        # if we were in failover — restore the priority route
        [ -f "$STATE_DIR/failover" ] && enter_failover
    fi

    # 2) primary channel health (strictly via MAIN_IFACE, routing table does not affect this)
    local fails oks
    fails=$(cat "$STATE_DIR/fails" 2>/dev/null || echo 0)
    oks=$(cat "$STATE_DIR/oks" 2>/dev/null || echo 0)
    if main_uplink_ok; then
        oks=$((oks+1)); fails=0
    else
        fails=$((fails+1)); oks=0
    fi
    echo "$fails" > "$STATE_DIR/fails"
    echo "$oks" > "$STATE_DIR/oks"

    # 3) hysteresis
    if [ ! -f "$STATE_DIR/failover" ] && [ "$fails" -ge "$FAIL_THRESHOLD" ]; then
        enter_failover
    elif [ -f "$STATE_DIR/failover" ] && [ "$oks" -ge "$OK_THRESHOLD" ]; then
        restore_main_route
        log "RESTORE: primary channel is back, traffic returned via $MAIN_IFACE"
        alert "primary internet restored — switched back from backup"
    fi
}

cmd_status() {
    echo "=== QMI ==="
    qmi --wds-get-packet-service-status 2>&1 || true
    echo "=== state ==="
    for f in pdh cid gw fails oks failover; do
        [ -e "$STATE_DIR/$f" ] && echo "$f: $(cat "$STATE_DIR/$f" 2>/dev/null)"
    done
    [ -f "$STATE_DIR/failover" ] && echo ">>> FAILOVER MODE <<<"
    echo "=== routes ==="
    ip route show default
    echo "=== resolved ==="
    resolvectl status "$IFACE" 2>/dev/null | head -8 || true
}

case "${1:-}" in
    up)       cmd_up ;;
    down)     cmd_down ;;
    watchdog) cmd_watchdog ;;
    status)   cmd_status ;;
    *) echo "usage: $0 up|down|watchdog|status" >&2; exit 2 ;;
esac
