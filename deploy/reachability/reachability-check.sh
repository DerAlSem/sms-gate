#!/usr/bin/env bash
# Does sms.deralsem.ru actually answer, from outside the house?
#
# Everything else watching this gateway runs on the gateway, which answers "is the process
# up" and never "can anyone reach it". Those two diverge exactly when it matters: the wired
# link can be healthy, the service can be answering on its own port, every check can pass,
# and the tunnel that is now the only way in can be dead.
#
# This runs on the machine that publishes the hostname, which is inside the failure domain
# for one case only — that machine dying. That case is not a silent failure: it takes the
# eleven sites it hosts with it, including the application that calls this gateway, so there
# is nobody left to be affected and no way for it to go unnoticed. Every other failure this
# change introduces is visible from here.
#
# A 200 is not enough. A publishing front end answers its own error page when it cannot
# reach the origin, and a name that answers with somebody else's error is a name that
# answers. So the body has to carry a marker only the application produces.
set -u

URL="${URL:-https://sms.deralsem.ru/docs}"
HOSTNAME_CHECKED="${HOSTNAME_CHECKED:-sms.deralsem.ru}"
# A string the application emits and a front-end error page cannot.
MARKER="${MARKER:-SMS Gate}"
ENV_FILE="${ENV_FILE:-/etc/reachability-check.env}"
STATE_FILE="${STATE_FILE:-/run/reachability-check.state}"
# Three in a row before shouting. A failover is ~90s of detection plus the tunnel dialling
# out again, so a healthy failover trips one or two checks — it is a pause, not an incident,
# and alerting on it would teach the operator to ignore the alerts.
FAIL_THRESHOLD="${FAIL_THRESHOLD:-3}"
# While it stays broken, remind rather than repeat: one line an hour at a 60s cadence.
REMIND_EVERY="${REMIND_EVERY:-60}"
# The certificate at the far end started life as a copy of the house's, as a bridge. If it
# is never replaced it expires quietly, and this is what notices.
CERT_WARN_DAYS="${CERT_WARN_DAYS:-14}"
TIMEOUT="${TIMEOUT:-15}"

log() { logger -t reachability-check "$*" 2>/dev/null || true; echo "reachability-check: $*" >&2; }

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

# ---------------------------------------------------------------- state
fails=0
cert_warned=""
if [ -f "$STATE_FILE" ]; then
    # shellcheck disable=SC1090
    . "$STATE_FILE" 2>/dev/null || true
    fails="${fails:-0}"
    cert_warned="${cert_warned:-}"
fi
save_state() { printf 'fails=%s\ncert_warned=%s\n' "$fails" "$cert_warned" > "$STATE_FILE" 2>/dev/null || true; }

# ---------------------------------------------------------------- probe
body=$(curl -sS --max-time "$TIMEOUT" -w '\n%{http_code}' "$URL" 2>/dev/null) || body=""
code="${body##*$'\n'}"
body="${body%$'\n'*}"

reason=""
if [ -z "$code" ] || [ "$code" = "000" ]; then
    reason="no response (connection failed or timed out)"
elif [ "$code" != "200" ]; then
    reason="HTTP $code"
elif ! printf '%s' "$body" | grep -qF "$MARKER"; then
    # The dangerous case, and the reason a status code alone is not the check: something
    # answered, so the name looks alive, but it was not the gateway.
    reason="HTTP 200 without the application's own marker — answered by something other than the gateway"
fi

# ---------------------------------------------------------------- act
if [ -n "$reason" ]; then
    fails=$((fails + 1))
    log "unreachable ($fails/$FAIL_THRESHOLD): $reason"
    if [ "$fails" -eq "$FAIL_THRESHOLD" ]; then
        notify "$(printf '\U0001F534 %s is unreachable\n%s\nchecked from %s\n%s' \
            "$HOSTNAME_CHECKED" "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$(hostname)" "$reason")"
    elif [ "$fails" -gt "$FAIL_THRESHOLD" ] \
        && [ $(( (fails - FAIL_THRESHOLD) % REMIND_EVERY )) -eq 0 ]; then
        notify "$(printf '\U0001F534 %s still unreachable after %s checks\n%s' \
            "$HOSTNAME_CHECKED" "$fails" "$reason")"
    fi
    save_state
    exit 1
fi

if [ "$fails" -ge "$FAIL_THRESHOLD" ]; then
    notify "$(printf '\U00002705 %s is reachable again after %s failed checks' \
        "$HOSTNAME_CHECKED" "$fails")"
    log "reachable again after $fails failed checks"
fi
fails=0

# ---------------------------------------------------------------- certificate
# Cheap, and it guards a hazard this change created: the bridge certificate.
expiry=$(echo | timeout "$TIMEOUT" openssl s_client -connect "${HOSTNAME_CHECKED}:443" \
    -servername "$HOSTNAME_CHECKED" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
if [ -n "$expiry" ]; then
    left=$(( ( $(date -d "$expiry" +%s 2>/dev/null || echo 0) - $(date +%s) ) / 86400 ))
    today=$(date '+%Y-%m-%d')
    if [ "$left" -le "$CERT_WARN_DAYS" ] && [ "$cert_warned" != "$today" ]; then
        notify "$(printf '\U000026A0 certificate for %s expires in %s day(s) — %s' \
            "$HOSTNAME_CHECKED" "$left" "$expiry")"
        cert_warned="$today"
    fi
fi

save_state
exit 0
