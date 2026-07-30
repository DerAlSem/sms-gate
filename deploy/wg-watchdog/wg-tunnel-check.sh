#!/usr/bin/env bash
# Is the tunnel carrying anything?
#
# `systemctl is-active wg-quick@wg-burns` answers a question nobody is asking. WireGuard has
# no connection to lose: the interface stays up whether or not the peer is there, so the unit
# reports active over a tunnel that moves nothing. That is the shape that has cost this
# project two changes already — a data session reporting `connected` over an interface with
# no address, and a background loop that died with its exception discarded — and it is the
# most likely way the only route into this host fails.
#
# So the test is reachability, not liveness. The peer's own address either answers or it does
# not, and nothing about that can be true while the tunnel is broken.
#
# Handshake age was the other candidate and is worse: it advances only on rekey, so it lags a
# working tunnel and reads as stale on an idle one. Reachability is the property; handshake
# age is a proxy for it.
set -u

PEER_ADDR="${PEER_ADDR:-10.67.67.1}"
UNIT="${UNIT:-wg-quick@wg-burns}"
ENV_FILE="${ENV_FILE:-/opt/sms-gate/.env}"
STATE_FILE="${STATE_FILE:-/run/wg-tunnel-check.state}"
# Two minutes of silence before touching anything. A failover is ~90s of detection plus the
# tunnel dialling out from its new address, and restarting during that would interrupt a
# recovery already in progress.
FAILS_BEFORE_RESTART="${FAILS_BEFORE_RESTART:-2}"
# Restarting twice without success means the fault is not the kind a restart fixes.
ALERT_AFTER_RESTARTS="${ALERT_AFTER_RESTARTS:-2}"
PING_TIMEOUT="${PING_TIMEOUT:-5}"

log() { logger -t wg-tunnel-check "$*" 2>/dev/null || true; echo "wg-tunnel-check: $*" >&2; }

read_env() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2-; }
TOKEN="${ALERT_BOT_TOKEN:-$(read_env ALERT_BOT_TOKEN)}"
CHAT="${ALERT_CHAT_ID:-$(read_env ALERT_CHAT_ID)}"

notify() {
    local text="$1"
    [ -n "$TOKEN" ] && [ -n "$CHAT" ] || { log "no alert credentials; would have said: $text"; return 0; }
    curl -sS --max-time 15 "https://api.telegram.org/bot${TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${CHAT}" --data-urlencode "text=${text}" >/dev/null 2>&1 \
        || log "could not deliver the alert"
}

fails=0
restarts=0
if [ -f "$STATE_FILE" ]; then
    # shellcheck disable=SC1090
    . "$STATE_FILE" 2>/dev/null || true
    fails="${fails:-0}"; restarts="${restarts:-0}"
fi
save_state() { printf 'fails=%s\nrestarts=%s\n' "$fails" "$restarts" > "$STATE_FILE" 2>/dev/null || true; }

if ping -c1 -W "$PING_TIMEOUT" "$PEER_ADDR" >/dev/null 2>&1; then
    if [ "$restarts" -ge "$ALERT_AFTER_RESTARTS" ]; then
        notify "$(printf '\U00002705 tunnel to %s is carrying again, after %s restart(s)' \
            "$PEER_ADDR" "$restarts")"
    fi
    [ "$fails" -gt 0 ] && log "carrying again after $fails silent check(s)"
    fails=0; restarts=0
    save_state
    exit 0
fi

fails=$((fails + 1))
log "peer $PEER_ADDR did not answer ($fails)"

if [ $(( fails % FAILS_BEFORE_RESTART )) -eq 0 ]; then
    restarts=$((restarts + 1))
    log "restarting $UNIT (attempt $restarts)"
    systemctl restart "$UNIT" >/dev/null 2>&1 || log "could not restart $UNIT"
    if [ "$restarts" -eq "$ALERT_AFTER_RESTARTS" ]; then
        # Said once, at the point the evidence stops being "a blip" and starts being "a fault
        # a restart does not fix". The gateway itself may be perfectly healthy — which is
        # exactly why this has to be said out loud.
        notify "$(printf '\U0001F534 tunnel to %s is not carrying\n%s\non %s\n%s restart(s) did not fix it — the gateway may be healthy and unreachable' \
            "$PEER_ADDR" "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$(hostname)" "$restarts")"
    fi
fi

save_state
exit 1
