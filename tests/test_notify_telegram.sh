#!/usr/bin/env bash
# Smoke test for deploy/notify-telegram.sh using ALERT_DRY_RUN (no network, no real units).
set -u
SCRIPT="$(dirname "$0")/../deploy/notify-telegram.sh"
fail() { echo "FAIL: $1"; exit 1; }

# 1. A dry run previews the payload whether or not credentials exist. This script decides what
#    to say about a unit; whether it can be delivered is the sender's business, and the
#    no-credentials behaviour is covered in tests/test_alert_send_sh.py. It used to exit early
#    here on missing creds, which coupled "what to say" to "can we say it" for no reason.
out=$(ALERT_BOT_TOKEN="" ALERT_CHAT_ID="" ALERT_DRY_RUN=1 "$SCRIPT" some.service 2>&1)
rc=$?
[ "$rc" -eq 0 ] || fail "dry-run should exit 0 (got $rc)"
echo "$out" | grep -q "some.service" || fail "dry-run should preview the payload"

# 1b. With no sender installed it says so where an operator will find it, and still exits 0 —
#     a notifier that fails loudly on OnFailure= turns one fault into two.
out=$(ALERT_SENDER=/nonexistent/sms-gate-alert "$SCRIPT" some.service 2>/dev/null)
rc=$?
[ "$rc" -eq 0 ] || fail "missing sender should exit 0 (got $rc)"
[ -z "$out" ] || fail "missing sender should print nothing on stdout (got: $out)"

# 2. Failed unit (ActiveState/Result forced) -> 🔴 FAILED header with the unit name.
out=$(ALERT_BOT_TOKEN="t" ALERT_CHAT_ID="c" ALERT_DRY_RUN=1 \
      ALERT_TEST_ACTIVE="failed" ALERT_TEST_RESULT="exit-code" "$SCRIPT" my-unit.service 2>&1)
rc=$?
[ "$rc" -eq 0 ] || fail "dry-run should exit 0 (got $rc)"
echo "$out" | grep -q "my-unit.service" || fail "payload missing unit name"
echo "$out" | grep -q "FAILED" || fail "failed unit should get FAILED header"

# 3. Healthy unit (active + success) -> soft header, NOT FAILED (manual test / auto-recovered).
out=$(ALERT_BOT_TOKEN="t" ALERT_CHAT_ID="c" ALERT_DRY_RUN=1 \
      ALERT_TEST_ACTIVE="active" ALERT_TEST_RESULT="success" "$SCRIPT" my-unit.service 2>&1)
rc=$?
[ "$rc" -eq 0 ] || fail "dry-run should exit 0 (got $rc)"
echo "$out" | grep -q "currently healthy" || fail "healthy unit should get the soft 'currently healthy' header"
echo "$out" | grep -q "FAILED" && fail "healthy unit must NOT say FAILED"

echo "PASS"
