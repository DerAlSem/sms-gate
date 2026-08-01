#!/bin/sh
#
# The one place an alert leaves this host from.
#
# Usage:  sms-gate-alert "text"      raise an alert
#         sms-gate-alert --drain     deliver anything held, send nothing new
#
# Why one place. Three scripts raise alerts here — the uplink watchdog, the tunnel watchdog and
# the systemd notifier — and each carried its own copy of the delivery path. When the relay was
# added, it reached two of them. The third was the uplink watchdog, whose failover alert was the
# one that had actually been lost, and it kept posting directly for months while the README and
# a ticked spec task both said otherwise. Copies do not drift evenly; they drift in whichever
# one nobody remembers.
#
# Two routes, in this order:
#   the relay at the far end   reached over the tunnel, works on either uplink
#   api.telegram.org           direct, blocked by the carrier the backup uplink runs on
#
# Relay first is deliberate. It is the route that survives the outage the alert is about, so it
# should be the one ordinary traffic exercises rather than the one first tried during a fault.
#
# And when neither answers, the alert is held rather than logged and lost. That is the case the
# whole thing is for: an alert raised while nothing can carry it is exactly the alert worth
# keeping, because it is the one saying the outage began.

set -u

SPOOL="${ALERT_SPOOL:-/var/lib/sms-gate/alert-spool}"
SPOOL_MAX="${ALERT_SPOOL_MAX:-50}"
ENV_FILE="${ALERT_ENV_FILE:-/opt/sms-gate/.env}"
AGE_NOTE_AFTER=60

log() { logger -t sms-gate-alert "$*" 2>/dev/null || true; echo "sms-gate-alert: $*" >&2; }

# grep, not source: tolerant of a malformed file, which is the failure that started the
# alerting work in the first place.
read_env() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2-; }

TOKEN="${ALERT_BOT_TOKEN:-$(read_env ALERT_BOT_TOKEN)}"
CHAT="${ALERT_CHAT_ID:-$(read_env ALERT_CHAT_ID)}"
RELAY="${ALERT_RELAY_BASE:-$(read_env ALERT_RELAY_BASE)}"

# The spool keeps one record per line so it can be read by a person during an incident, which
# is when someone will want to know what was held. Newlines are escaped rather than the record
# encoded, for the same reason.
encode() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' | sed -e ':a' -e 'N' -e '$!ba' -e 's/\n/\\n/g'; }
decode() { printf '%s' "$1" | sed -e 's/\\n/\n/g' -e 's/\\\\/\\/g'; }

send_via() {
    curl -sS --max-time 15 "${1}/bot${TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${CHAT}" \
        --data-urlencode "text=${2}" >/dev/null 2>&1
}

deliver() {
    for base in "${RELAY%/}" "https://api.telegram.org"; do
        [ -n "$base" ] || continue
        if send_via "$base" "$1"; then
            return 0
        fi
    done
    return 1
}

hold() {
    mkdir -p "$(dirname "$SPOOL")" 2>/dev/null || true
    printf '%s %s\n' "$(date +%s)" "$(encode "$1")" >> "$SPOOL" 2>/dev/null || return 0
    # Bounded, because a spool that grows without limit is a second fault: on a long outage it
    # becomes the thing that fills the disk the gateway keeps its database on.
    if [ "$(wc -l < "$SPOOL" 2>/dev/null || echo 0)" -gt "$SPOOL_MAX" ]; then
        tail -n "$SPOOL_MAX" "$SPOOL" > "$SPOOL.trim" 2>/dev/null && mv "$SPOOL.trim" "$SPOOL"
    fi
}

# Stamped with its age, because a late alert read without one is read as current — and sends
# the operator after a fault that has already ended.
with_age() {
    age=$(( $(date +%s) - $1 ))
    [ "$age" -lt "$AGE_NOTE_AFTER" ] && { printf '%s' "$2"; return; }
    printf '\342\217\263 delayed %s min (raised %s)\n\n%s' \
        "$(( age / 60 ))" "$(date -d "@$1" '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || echo "$1")" "$2"
}

drain() {
    [ -s "$SPOOL" ] || return 0
    stuck=0
    : > "$SPOOL.next"
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        # Once one send fails the rest stay held: they are older, and reordering an incident is
        # worse than delaying it.
        if [ "$stuck" = 1 ]; then
            printf '%s\n' "$line" >> "$SPOOL.next"
            continue
        fi
        stamp=${line%% *}
        body=$(decode "${line#* }")
        if deliver "$(with_age "$stamp" "$body")"; then
            continue
        fi
        stuck=1
        printf '%s\n' "$line" >> "$SPOOL.next"
    done < "$SPOOL"
    mv "$SPOOL.next" "$SPOOL"
    [ "$stuck" = 1 ] && return 1
    return 0
}

if [ "${1:-}" = "--drain" ]; then
    drain
    exit $?
fi

TEXT="${1:-}"
[ -n "$TEXT" ] || { log "nothing to send"; exit 0; }

# No credentials means nobody to deliver to later either, so this is not held.
if [ -z "$TOKEN" ] || [ -z "$CHAT" ]; then
    log "no alert credentials; would have said: $TEXT"
    exit 0
fi

# Held first and delivered from the spool, so the ordinary path and the recovery path are the
# same code. Anything already waiting goes out ahead of this, in the order it was raised.
hold "$TEXT"
drain
exit $?
