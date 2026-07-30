#!/usr/bin/env bash
# Telegram notifier for systemd OnFailure=. Self-contained: no app venv/config needed.
# Usage: notify-telegram.sh <unit-name>
# Reads ALERT_BOT_TOKEN / ALERT_CHAT_ID from the environment, falling back to /opt/sms-gate/.env.
set -u

UNIT="${1:-unknown.service}"
ENV_FILE="/opt/sms-gate/.env"
THROTTLE_FILE="/tmp/sms-gate-notify.last"
THROTTLE_SECONDS=60
MAX_LEN=3500

# Pull creds from .env if not already in the environment (grep, not source: tolerant of a
# malformed file — which is exactly the failure that started all this).
read_env() {
    local key="$1"
    grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2-
}
TOKEN="${ALERT_BOT_TOKEN:-$(read_env ALERT_BOT_TOKEN)}"
CHAT="${ALERT_CHAT_ID:-$(read_env ALERT_CHAT_ID)}"
# A route that can reach Telegram when this host cannot. The mobile carrier the backup
# uplink runs on cannot, so during a wired outage every alert raised here is lost — which is
# how the failover alert of 2026-07-29 never arrived while the restore alert did. Tried
# first, so it is the route ordinary traffic exercises rather than one first tested by the
# outage; the direct route stays as the fallback.
RELAY="${ALERT_RELAY_BASE:-$(read_env ALERT_RELAY_BASE)}"

# No creds -> nothing to do.
[ -n "$TOKEN" ] && [ -n "$CHAT" ] || exit 0

HOST=$(hostname)
WHEN=$(date '+%Y-%m-%d %H:%M:%S %Z')
STATE=$(timeout 5 systemctl show "$UNIT" -p ActiveState,SubState,NRestarts,ExecMainStatus 2>/dev/null | tr '\n' ' ')
LOGS=$(timeout 5 journalctl -u "$UNIT" -n 30 --no-pager -o cat 2>/dev/null)

# Header reflects the unit's ACTUAL state when sampled, not the trigger. A failed unit gets
# 🔴 FAILED; but a manual test (`systemctl start sms-gate-notify@...`) or a unit that already
# auto-restarted (Restart=on-failure) before we sampled is healthy now — say so instead of
# crying FAILED. (ALERT_TEST_* override the probes so the smoke test can drive both branches.)
ACTIVE="${ALERT_TEST_ACTIVE:-$(timeout 5 systemctl show "$UNIT" -p ActiveState --value 2>/dev/null)}"
RESULT="${ALERT_TEST_RESULT:-$(timeout 5 systemctl show "$UNIT" -p Result --value 2>/dev/null)}"
if [ "$ACTIVE" = "active" ] && [ "$RESULT" = "success" ]; then
    HEADER=$(printf '⚠️ %s on %s — notifier fired, but the service is currently healthy (test or already recovered)' "$UNIT" "$HOST")
else
    HEADER=$(printf '\U0001F534 %s — FAILED on %s' "$UNIT" "$HOST")
fi

TEXT=$(printf '%s\n%s\n%s\n\n%s' "$HEADER" "$WHEN" "$STATE" "$LOGS")
TEXT="${TEXT:0:$MAX_LEN}"

# Dry-run prints the payload and sends nothing (bypasses throttle — used by the smoke test).
if [ "${ALERT_DRY_RUN:-0}" = "1" ]; then
    printf '%s\n' "$TEXT"
    exit 0
fi

# Throttle: skip a real send if we alerted < THROTTLE_SECONDS ago (bounds flood regardless
# of how often OnFailure fires during the restart cycle).
if [ -f "$THROTTLE_FILE" ]; then
    now=$(date +%s)
    last=$(date -r "$THROTTLE_FILE" +%s 2>/dev/null || echo 0)
    if [ $((now - last)) -lt "$THROTTLE_SECONDS" ]; then
        exit 0
    fi
fi

touch "$THROTTLE_FILE" 2>/dev/null || true

send_via() {
    curl -sS --max-time 15 "${1}/bot${TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${CHAT}" \
        --data-urlencode "text=${TEXT}" >/dev/null 2>&1
}

# Both routes are attempted before giving up. `|| true` on a single route made a lost alert
# indistinguishable from a delivered one, which is the failure this script exists to prevent
# applied to the script itself.
if [ -n "$RELAY" ] && send_via "${RELAY%/}"; then
    exit 0
fi
send_via "https://api.telegram.org" || logger -t notify-telegram \
    "no route delivered the alert for ${UNIT}" 2>/dev/null || true
exit 0
