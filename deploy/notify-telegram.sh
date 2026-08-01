#!/usr/bin/env bash
# Telegram notifier for systemd OnFailure=. Self-contained: no app venv/config needed.
# Usage: notify-telegram.sh <unit-name>
# Decides what to say about a unit and how often. Delivery — routes, retention, credentials —
# belongs to the sender it hands the text to (deploy/alert-send.sh).
set -u

UNIT="${1:-unknown.service}"
THROTTLE_FILE="/tmp/sms-gate-notify.last"
THROTTLE_SECONDS=60
MAX_LEN=3500

# Credentials are read in one place only, by the sender. A script that does not deliver has no
# business holding a token — and the fewer copies of that read, the fewer places to rotate.

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

# Delivery is not this script's job any more. What it knows is *what to say about a unit* and
# *how often*; which route carries it, and what happens when none will, belong to the one
# sender all three raisers share — see deploy/alert-send.sh. Keeping a private copy here is
# what let the relay reach some scripts and not others.
ALERT_SENDER="${ALERT_SENDER:-/usr/local/sbin/sms-gate-alert}"
if [ ! -x "$ALERT_SENDER" ]; then
    logger -t notify-telegram "no alert sender at $ALERT_SENDER for ${UNIT}" 2>/dev/null || true
    exit 0
fi
"$ALERT_SENDER" "$TEXT" || logger -t notify-telegram \
    "alert for ${UNIT} held for later delivery" 2>/dev/null || true
exit 0
