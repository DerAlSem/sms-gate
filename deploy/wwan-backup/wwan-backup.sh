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
# `${VAR:-default}` so a test can point the script at a sandbox without a root-owned
# /etc file. /etc/default is sourced afterwards and still wins over both, so the
# deployed behaviour is unchanged.
DEVICE="${DEVICE:-/dev/cdc-wdm0}"
IFACE="${IFACE:-wwan0}"
# Empty means "use the modem's default profile", which is the form that works from a
# cold start. Set it only to override the profile — see APN_OVERRIDE below.
APN_OVERRIDE="${APN_OVERRIDE:-}"
MAIN_IFACE="${MAIN_IFACE:-enp2s0}"
BACKUP_METRIC="${BACKUP_METRIC:-700}"    # standby route in normal mode (ignored by the kernel)
FAILOVER_METRIC="${FAILOVER_METRIC:-50}" # overrides the primary (metric 100) during failover
PING_TARGETS="${PING_TARGETS:-1.1.1.1 8.8.8.8}"
FAIL_THRESHOLD="${FAIL_THRESHOLD:-3}"    # consecutive failures before switching (3 x 30s = ~1.5 min)
OK_THRESHOLD="${OK_THRESHOLD:-3}"        # consecutive successes before restoring
# How many consecutive failed session attempts before the uplink stops retrying on its
# normal schedule and tells the operator. Unbounded retrying is what exhausted the
# modem's QMI client pool on 2026-07-29 and turned a recoverable outage into one that
# needed the modem rebooted.
MAX_SESSION_FAILS="${MAX_SESSION_FAILS:-10}"
# How many consecutive *timeouts* — never refusals — before access to the device is
# renewed, proxy included. A refusal is the network answering; reacting to it by
# killing a process we do not own would make an ordinary carrier outage escalate.
STALE_AFTER_TIMEOUTS="${STALE_AFTER_TIMEOUTS:-3}"
MAX_RENEWALS="${MAX_RENEWALS:-2}"        # renewal is bounded like any other retry
# Once given up, still probe this often (in watchdog passes) so a channel that could
# recover is not stopped forever — ~10 min at the 30s cadence.
SLOW_RETRY_EVERY="${SLOW_RETRY_EVERY:-20}"
STATE_DIR="${STATE_DIR:-/run/wwan-backup}"
ENV_FILE="${ENV_FILE:-/opt/sms-gate/.env}"  # ALERT_BOT_TOKEN/ALERT_CHAT_ID for notifications
SRC_TABLE="${SRC_TABLE:-100}"            # routing table for reply traffic sourced from enp2s0
SYS_NET="${SYS_NET:-/sys/class/net}"     # overridable so the interface check is testable
QMI_PROXY_PATTERN="${QMI_PROXY_PATTERN:-/usr/libexec/qmi-proxy}"
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

# How the last QMI request ended: ok | refused | timeout.
#
# The distinction is the safeguard that keeps recovery from becoming the next incident.
# A refusal (`no-service`, `CallFailed`) is the modem answering: the stack is healthy and
# the network has said no. A timeout is the stack not answering, which is what a
# descriptor pointing at a replaced device looks like from outside. Reacting to a refusal
# by renewing access would mean any carrier-side outage — the very condition this channel
# exists for — sends us into killing a process we do not own.
# Recorded in a file rather than a variable: every caller reads a QMI reply through
# `$(...)`, which is a subshell, so an exported variable would never reach the code that
# has to act on the distinction.
qmi_run() {
    local out rc status
    out=$(qmi "$@" 2>&1); rc=$?
    if [ "$rc" -eq 0 ]; then
        status=ok
    elif printf '%s' "$out" | grep -qi "timed out"; then
        status=timeout
    else
        status=refused
    fi
    printf '%s' "$status" > "$STATE_DIR/.qmi_status" 2>/dev/null || true
    printf '%s\n' "$out"
    return "$rc"
}

qmi_last_status() { cat "$STATE_DIR/.qmi_status" 2>/dev/null || echo ok; }

# One client, acquired once and reused.
#
# `--client-no-release-cid` is deliberate — a later teardown has to address the session it
# started — but the id is only ever printed by a *successful* reply. So a script that
# learns its client only from success acquires a fresh one on every failure and can never
# name what it leaked: 131 refused attempts consumed ~150 of the modem's finite pool until
# every WDS request timed out and only rebooting the modem cleared it. Allocating the
# client explicitly, up front, is what makes "release it on failure" unnecessary.
# The modem's own default profile number.
#
# `--wds-start-network` requires an argument (qmicli 1.35.2: `["key=value,..."]`, allowed
# keys apn, 3gpp-profile, ip-type, ...), so "use the default profile" has to be asked for
# explicitly, by number. Passing the flag bare is a parse error — and passing it bare with
# another flag behind it is worse, because that flag is swallowed as the value and the
# request silently becomes something nobody wrote.
default_profile() {
    local out n
    out=$(qmi_run --wds-get-default-profile-number=3gpp) || return 1
    n=$(awk -F"'" '/Default profile number:/ {print $2}' <<<"$out")
    [ -n "$n" ] || return 1
    printf '%s' "$n"
}

ensure_client() {
    local cid out
    cid=$(cat "$STATE_DIR/cid" 2>/dev/null || true)
    [ -n "$cid" ] && return 0
    out=$(qmi_run --wds-noop --client-no-release-cid) || return 1
    cid=$(awk -F"'" '/CID:/ {print $2}' <<<"$out")
    [ -n "$cid" ] || return 1
    echo "$cid" > "$STATE_DIR/cid"
}

client_args() {
    local cid
    ensure_client >/dev/null 2>&1 || true
    cid=$(cat "$STATE_DIR/cid" 2>/dev/null || true)
    if [ -n "$cid" ]; then
        printf -- '--client-cid=%s --client-no-release-cid' "$cid"
    else
        printf -- '--client-no-release-cid'
    fi
}

# Drop the descriptor-bound state and the proxy holding it. Called only after repeated
# timeouts (see qmi_last_status), never after a refusal.
renew_device_access() {
    log "renewing access to $DEVICE after repeated timeouts"
    pkill -f "$QMI_PROXY_PATTERN" 2>/dev/null || true
    # Both belonged to the connection just dropped; a re-enumerated modem does not know them.
    rm -f "$STATE_DIR/cid" "$STATE_DIR/pdh"
}

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
    # Asked through the client that owns the session. A fresh client is not bound to it and
    # reports no session, which sent every run down the cold-start path — tearing the
    # interface down and requesting a new session — instead of the idempotent one this
    # check exists to provide.
    qmi_run $(client_args) --wds-get-packet-service-status 2>/dev/null \
        | grep -q "Connection status: 'connected'"
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
    [ -c "$DEVICE" ] || { log "$DEVICE not found — modem not in QMI mode?"; return 1; }
    # A re-enumeration recreates the netdev as well as the control device, and it may be
    # absent for a while or come back under another name. Addressing applied to an absent
    # interface fails quietly, leaving a session we believe is up and no traffic path —
    # indistinguishable in the logs from a working backup channel.
    [ -d "$SYS_NET/$IFACE" ] || { log "$IFACE not present — netdev has not reappeared?"; return 1; }
    setup_src_routing

    # idempotency: session already connected (unit restart) — just re-apply addressing
    if session_connected; then
        log "session already connected — re-applying addressing"
        apply_addressing
        return
    fi

    # raw-ip is required for qmi_wwan on modern kernels; can only be changed while the link is down
    ip link set "$IFACE" down
    echo Y > "$SYS_NET/$IFACE/qmi/raw_ip" 2>/dev/null || true
    ip link set "$IFACE" up

    local out pdh cid profile start_arg
    # Empty override means the modem's default profile, asked for by number. That is the
    # form that works from a cold start: on 2026-07-29 an explicit
    # `apn=internet.tele2.ru,ip-type=4` was refused with `no-service` for six hours
    # straight, while the default profile — holding that identical APN and that identical
    # IPv4 PDP type — succeeded on the first attempt. The values were never in dispute; the
    # form of the request was.
    if [ -n "$APN_OVERRIDE" ]; then
        start_arg="apn=$APN_OVERRIDE,ip-type=4"
    else
        profile=$(default_profile) \
            || { log "could not read the default profile number ($(qmi_last_status))"; return 1; }
        start_arg="3gpp-profile=$profile"
    fi
    out=$(qmi_run $(client_args) --wds-start-network="$start_arg") \
        || { log "wds-start-network failed ($(qmi_last_status)): $out"; return 1; }
    pdh=$(awk -F"'" '/Packet data handle:/ {print $2}' <<<"$out")
    cid=$(awk -F"'" '/CID:/ {print $2}' <<<"$out")
    echo "${pdh:-}" > "$STATE_DIR/pdh"
    # Only when we do not already hold one: this file is what makes the client reused
    # rather than re-acquired.
    [ -s "$STATE_DIR/cid" ] || echo "${cid:-}" > "$STATE_DIR/cid"

    apply_addressing || return 1
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

read_counter() { cat "$STATE_DIR/$1" 2>/dev/null || echo 0; }

# Keep the data session up, bounded. Returns non-zero when the session is not up, but
# never exits: the caller has a second duty that must run regardless.
session_step() {
    local fails timeouts renewals

    fails=$(read_counter session_fails)
    timeouts=$(read_counter timeouts)
    renewals=$(read_counter renewals)

    if session_connected; then
        # A live session is not a working channel. A re-enumeration recreates the netdev
        # and its address goes with it, while the QMI session survives and keeps
        # reporting `connected` — so every check passes and nothing carries traffic.
        #
        # This used to be repaired by accident: the liveness check was broken, always
        # reported "no session", and so every pass ran the cold path, which re-applies
        # addressing on its way through. Fixing that check removed the accident, which is
        # how this surfaced. Two defects had been holding each other up.
        if ! ip -4 -br addr show "$IFACE" 2>/dev/null | grep -q "[0-9]"; then
            log "session is up but $IFACE has no address — re-applying"
            apply_addressing || true
        fi
        if [ "$fails" -ne 0 ]; then
            log "session recovered after $fails failed attempt(s)"
            alert "backup uplink recovered after $fails failed attempt(s)"
        fi
        # A success clears the allowance, so a later unrelated outage gets a full one.
        echo 0 > "$STATE_DIR/session_fails"
        echo 0 > "$STATE_DIR/timeouts"
        echo 0 > "$STATE_DIR/renewals"
        return 0
    fi
    [ "$(qmi_last_status)" = timeout ] && timeouts=$((timeouts + 1))

    # Past the bound the uplink stops trying on its normal schedule. Unbounded retrying is
    # what exhausted the modem's client pool: a mechanism that can neither succeed nor stop
    # makes the problem it was built to solve strictly worse. It still probes occasionally,
    # because a channel that has stopped trying entirely can never notice it could recover.
    if [ "$fails" -ge "$MAX_SESSION_FAILS" ]; then
        local since
        since=$(read_counter since_giveup)
        since=$((since + 1))
        echo "$since" > "$STATE_DIR/since_giveup"
        echo "$timeouts" > "$STATE_DIR/timeouts"
        if [ "$since" -lt "$SLOW_RETRY_EVERY" ]; then
            return 1
        fi
        echo 0 > "$STATE_DIR/since_giveup"
    fi

    # Renew only on repeated timeouts, never on refusals — see qmi_last_status.
    if [ "$timeouts" -ge "$STALE_AFTER_TIMEOUTS" ] && [ "$renewals" -lt "$MAX_RENEWALS" ]; then
        renew_device_access
        renewals=$((renewals + 1))
        timeouts=0
        echo "$renewals" > "$STATE_DIR/renewals"
    fi
    echo "$timeouts" > "$STATE_DIR/timeouts"

    log "QMI session dropped — re-establishing"
    if cmd_up; then
        echo 0 > "$STATE_DIR/session_fails"
        echo 0 > "$STATE_DIR/since_giveup"
        # if we were in failover — restore the priority route
        [ -f "$STATE_DIR/failover" ] && enter_failover
        return 0
    fi

    [ "$(qmi_last_status)" = timeout ] && { timeouts=$((timeouts + 1)); echo "$timeouts" > "$STATE_DIR/timeouts"; }
    fails=$((fails + 1))
    echo "$fails" > "$STATE_DIR/session_fails"
    if [ "$fails" -eq "$MAX_SESSION_FAILS" ]; then
        log "giving up after $fails consecutive failures — retrying slowed"
        alert "backup uplink down: $fails consecutive failures, retrying slowed"
    fi
    return 1
}

cmd_watchdog() {
    mkdir -p "$STATE_DIR"
    exec 9>"$STATE_DIR/lock"
    flock -n 9 || exit 0   # previous run still in progress

    # 1) keep QMI session alive.
    #
    # Never with `exit`: this run has a second, independent duty below, and `cmd_up`'s own
    # `exit 1` used to take the whole script down with it — so while QMI was broken the
    # primary uplink was never tested, its counters never advanced, and failover could not
    # happen. The 2026-07-29 incident hid that because only one thing was broken at a time.
    session_step || true

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
    qmi $(client_args) --wds-get-packet-service-status 2>&1 || true
    echo "=== state ==="
    for f in pdh cid gw fails oks failover session_fails timeouts renewals; do
        [ -e "$STATE_DIR/$f" ] && echo "$f: $(cat "$STATE_DIR/$f" 2>/dev/null)"
    done
    [ -f "$STATE_DIR/failover" ] && echo ">>> FAILOVER MODE <<<"
    # A channel that has given up looks identical to a healthy one from the outside; say so.
    if [ "$(read_counter session_fails)" -ge "$MAX_SESSION_FAILS" ]; then
        echo ">>> GAVE UP after $(read_counter session_fails) consecutive failures — retrying slowed to 1 in $SLOW_RETRY_EVERY passes <<<"
    fi
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
