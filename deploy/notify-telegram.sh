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
curl -sS --max-time 15 \
    "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT}" \
    --data-urlencode "text=${TEXT}" \
    >/dev/null 2>&1 || true
exit 0
