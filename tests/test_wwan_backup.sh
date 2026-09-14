#!/usr/bin/env bash
# Tests for deploy/wwan-backup/wwan-backup.sh.
#
# The script's whole job is deciding what to ask of a modem and how to react to the
# three ways it can answer — succeed, refuse, time out — so the stubs below record
# every invocation and let each subcommand be scripted independently. Nothing here
# touches a real modem, a real interface or the network.
#
# Run this on Linux. The script locks with flock(1), which macOS does not ship, so every
# watchdog subcommand there exits at its first line and the suite reports a failure that
# says nothing about the code: `docker run --rm -v "$PWD":/w -w /w debian:stable-slim
# bash -c 'apt-get -qq update && apt-get -qq install -y util-linux && bash /w/tests/test_wwan_backup.sh'`
set -u

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/deploy/wwan-backup/wwan-backup.sh"
PASSED=0
fail() { echo "FAIL: $1"; exit 1; }
ok() { PASSED=$((PASSED + 1)); }

# --- harness ------------------------------------------------------------------

setup() {
    # Fresh sandbox per test: stub binaries on PATH, a temp state dir, and a log
    # each stub appends to so assertions can be made about what was asked.
    SANDBOX=$(mktemp -d)
    BIN="$SANDBOX/bin"
    mkdir -p "$BIN"
    CALLS="$SANDBOX/calls"
    : > "$CALLS"

    # qmicli: behaviour per subcommand via QMI_<TAG>=ok|refuse|timeout.
    # Defaults to ok. `timeout` mimics a wedged stack: no output, non-zero, slow
    # enough to be distinguishable but not slow enough to drag the suite.
    cat > "$BIN/qmicli" <<'STUB'
#!/usr/bin/env bash
echo "qmicli $*" >> "$CALLS"
mode_for() {
    case "$*" in
        *--wds-start-network*) echo "${QMI_START:-ok}" ;;
        *--wds-noop*) echo "${QMI_NOOP:-ok}" ;;
        *--wds-get-packet-service-status*) echo "${QMI_STATUS:-ok}" ;;
        *--wds-get-current-settings*) echo "${QMI_SETTINGS:-ok}" ;;
        *--wds-stop-network*) echo "${QMI_STOP:-ok}" ;;
        *) echo ok ;;
    esac
}
case "$(mode_for "$@")" in
    refuse)
        echo "error: couldn't start network: QMI protocol error (14): 'CallFailed'" >&2
        echo "call end reason (3): generic-no-service" >&2
        exit 1 ;;
    timeout)
        echo "error: operation failed: Transaction timed out" >&2
        exit 1 ;;
esac
case "$*" in
    *--wds-start-network*)
        echo "[/dev/cdc-wdm0] Network started"
        echo "        Packet data handle: '${FAKE_PDH:-111}'"
        echo "        CID: '${FAKE_CID:-20}'" ;;
    *--wds-get-packet-service-status*)
        echo "[/dev/cdc-wdm0] Connection status: '${FAKE_CONN:-disconnected}'" ;;
    *--wds-get-current-settings*)
        echo "IPv4 address: 10.0.0.2"
        echo "IPv4 subnet mask: 255.255.255.252"
        echo "IPv4 gateway address: 10.0.0.1"
        echo "IPv4 primary DNS: 10.0.0.9"
        echo "MTU: 1500" ;;
    *--wds-get-default-profile-number*)
        echo "[/dev/cdc-wdm0] Default profile number: '${FAKE_PROFILE:-1}'" ;;
    *--wds-noop*)
        echo "[/dev/cdc-wdm0] Client ID: '${FAKE_CID:-20}'"
        echo "        CID: '${FAKE_CID:-20}'" ;;
    *--wds-get-profile-list*)
        echo "[1] 3gpp - profile1"
        echo "        APN: 'internet.tele2.ru'" ;;
esac
exit 0
STUB

    # ip: records, answers the two queries the script parses, otherwise succeeds.
    cat > "$BIN/ip" <<'STUB'
#!/usr/bin/env bash
echo "ip $*" >> "$CALLS"
case "$*" in
    *"-br addr show wwan"*|*"-br addr show ${IFACE:-wwan0}"*)
        [ -n "${FAKE_WWAN_ADDR:-}" ] && echo "wwan   UNKNOWN   ${FAKE_WWAN_ADDR}" ;;
    *"-br addr show"*) echo "${FAKE_MAIN_IFACE:-eth0}   UP   192.168.1.2/24" ;;
    *"route show default dev"*) echo "default via 192.168.1.1 dev ${FAKE_MAIN_IFACE:-eth0}" ;;
    *"route show default"*) echo "default via 192.168.1.1 dev ${FAKE_MAIN_IFACE:-eth0} metric 100" ;;
esac
exit 0
STUB

    for tool in resolvectl logger pkill; do
        cat > "$BIN/$tool" <<STUB
#!/usr/bin/env bash
echo "$tool \$*" >> "\$CALLS"
exit 0
STUB
    done

    # ping: PING_RESULT=0 means the primary uplink is healthy.
    cat > "$BIN/ping" <<'STUB'
#!/usr/bin/env bash
echo "ping $*" >> "$CALLS"
exit "${PING_RESULT:-0}"
STUB

    chmod +x "$BIN"/*

    STATE="$SANDBOX/state"
    DEVICE_NODE="$SANDBOX/cdc-wdm0"
    # The script requires a character device; /dev/null is one and always exists.
    DEVICE_NODE=/dev/null
    IFACE_NAME="wwan-test0"
    mkdir -p "$SANDBOX/sys/class/net/$IFACE_NAME/qmi"
    echo N > "$SANDBOX/sys/class/net/$IFACE_NAME/qmi/raw_ip"
}

teardown() { rm -rf "$SANDBOX"; }

# Run the script with the sandbox in place. Extra env comes from the caller.
run() {
    local sub="$1"; shift
    PATH="$BIN:$PATH" CALLS="$CALLS" \
    DEVICE="$DEVICE_NODE" IFACE="$IFACE_NAME" STATE_DIR="$STATE" \
    MAIN_IFACE="${FAKE_MAIN_IFACE:-eth0}" SYS_NET="$SANDBOX/sys/class/net" \
    "$@" "$SCRIPT" "$sub" 2>&1
}

called() { grep -qF -e "$1" "$CALLS"; }

# --- 1.1 cold start uses the modem's default profile ---------------------------

setup
run up >/dev/null
called "--wds-start-network" || fail "1.1: no start-network was issued at all"
if grep -F -e "--wds-start-network" "$CALLS" | grep -q "apn="; then
    fail "1.1: cold start passed an explicit apn=, which is the form the network refused"
fi
# qmicli requires an argument here, so "the default profile" must be asked for by number.
grep -F -e "--wds-start-network" "$CALLS" | grep -q "3gpp-profile=1" \
    || fail "1.1: cold start must name the modem's default profile explicitly"
if grep -F -e "--wds-start-network=" "$CALLS" | grep -qE -- "--wds-start-network( |$)"; then
    fail "1.1: --wds-start-network was passed without an argument, which qmicli rejects"
fi
ok
teardown

# --- 1.2 an explicitly configured APN is still honoured -------------------------

setup
APN_OVERRIDE="my.custom.apn" run up >/dev/null
grep -F -e "--wds-start-network" "$CALLS" | grep -q "apn=my.custom.apn" \
    || fail "1.2: an explicitly configured APN must still be used as an override"
ok
teardown

# --- 1.3 a live session is recognised, so the cold path is skipped --------------

setup
FAKE_CONN=connected run up >/dev/null
if called "--wds-start-network"; then
    fail "1.3: a session already connected must not be started again"
fi
called "--wds-get-current-settings" || fail "1.3: addressing should still be re-applied"
ok
teardown

# --- 2.3 repeated failures do not consume additional clients --------------------

setup
for _ in 1 2 3 4 5; do QMI_START=refuse run watchdog >/dev/null; done
starts=$(grep -c -e "--wds-start-network" "$CALLS")
[ "$starts" -ge 1 ] || fail "2.3: expected the watchdog to try starting the session"
allocs=$(grep -c -e "--wds-noop" "$CALLS")
[ "$allocs" -le 1 ] || fail "2.3: $allocs clients allocated across repeated failures — one is reused, not acquired per attempt"
while read -r line; do
    case "$line" in *--client-cid=*) ;; *) fail "2.3: a request went out without the reused client: $line" ;; esac
done < <(grep -e "--wds-start-network" "$CALLS")
ok
teardown

# --- 3.2 a session failure does not cancel the failover duty --------------------

setup
QMI_START=refuse PING_RESULT=1 run watchdog >/dev/null
called "ping" || fail "3.2: the primary uplink was never tested because the session failed first"
[ -f "$STATE/fails" ] || fail "3.2: failure counters never advanced"
ok
teardown

setup
# The counters must actually reach the threshold while the session is broken — that is
# what proves the failover duty ran rather than being skipped. (Failover itself cannot
# complete without a session: there is no route to switch to, and enter_failover
# correctly refuses. What must not happen is never getting that far.)
for _ in 1 2 3; do QMI_START=refuse PING_RESULT=1 run watchdog >/dev/null; done
[ "$(cat "$STATE/fails")" -ge 3 ] || fail "3.2: failure counters stalled while the session was broken"
ok
teardown

setup
# And with a working session, failover still happens as before.
for _ in 1 2 3; do PING_RESULT=1 run watchdog >/dev/null; done
[ -f "$STATE/failover" ] || fail "3.2: failover regressed for a healthy session with a down primary"
ok
teardown

# --- 4.1 retrying is bounded ----------------------------------------------------

setup
for _ in 1 2 3 4 5 6 7 8 9 10; do QMI_START=refuse run watchdog >/dev/null; done
attempts_before=$(grep -c -e "--wds-start-network" "$CALLS")
QMI_START=refuse run watchdog >/dev/null
attempts_after=$(grep -c -e "--wds-start-network" "$CALLS")
[ "$attempts_after" -eq "$attempts_before" ] \
    || fail "4.1: retrying is unbounded — attempt $attempts_after followed a long run of failures"
ok
teardown

# --- 4.2 the bound is reset by a success ---------------------------------------

setup
# A success clears the allowance so a later, unrelated outage gets a full one.
for _ in 1 2 3; do QMI_START=refuse run watchdog >/dev/null; done
[ "$(cat "$STATE/session_fails")" -eq 3 ] || fail "4.2: failures were not counted"
FAKE_CONN=connected run watchdog >/dev/null
[ "$(cat "$STATE/session_fails")" -eq 0 ] || fail "4.2: a success must clear the failure count"
ok
teardown

# --- 4.3 giving up slows retrying, it does not stop it forever ------------------

setup
# Past the bound, plus a full slow-retry interval, one more probe must be made — a
# channel that stopped trying entirely could never notice it had recovered.
for _ in $(seq 1 10); do QMI_START=refuse SLOW_RETRY_EVERY=3 run watchdog >/dev/null; done
paused=$(grep -c -e "--wds-start-network" "$CALLS")
for _ in 1 2 3; do QMI_START=refuse SLOW_RETRY_EVERY=3 run watchdog >/dev/null; done
resumed=$(grep -c -e "--wds-start-network" "$CALLS")
[ "$resumed" -gt "$paused" ] || fail "4.3: retrying stopped forever instead of slowing down"
ok
teardown

# --- 5.4 a refusal does not restart the proxy ----------------------------------

setup
for _ in 1 2 3 4 5; do QMI_START=refuse run watchdog >/dev/null; done
if called "pkill" || grep -q "qmi-proxy" "$CALLS"; then
    fail "5.4: a refused request must never restart the proxy — that is the network answering"
fi
ok
teardown

# --- 5.1/5.2 repeated timeouts do renew access ---------------------------------

setup
for _ in 1 2 3 4 5; do QMI_STATUS=timeout QMI_START=timeout run watchdog >/dev/null; done
grep -q "qmi-proxy" "$CALLS" \
    || fail "5.1/5.2: repeated timeouts should renew access to the device, including the proxy"
ok
teardown

# --- 6.1 a missing interface is reported, not configured ------------------------

setup
IFACE_NAME="wwan-absent0" run up >/dev/null 2>&1
if called "link set wwan-absent0 up"; then
    fail "6.1: the interface was configured without confirming it exists"
fi
ok
teardown

# --- 1.4 a live session with a bare interface is re-addressed -------------------

setup
# The re-enumeration case: the QMI session survived and reports connected, but the
# netdev was recreated and lost its address. Nothing carries traffic, and the channel
# looks healthy from every angle the script checks.
FAKE_CONN=connected FAKE_WWAN_ADDR="" run watchdog >/dev/null
called "--wds-get-current-settings" \
    || fail "1.4: a connected session with no address on the interface was left alone"
ok
teardown

setup
# And the opposite: a session that is up *and* addressed must not be touched every pass.
FAKE_CONN=connected FAKE_WWAN_ADDR="10.0.0.2/30" run watchdog >/dev/null
if called "--wds-get-current-settings"; then
    fail "1.4: a healthy channel was re-addressed on an ordinary pass"
fi
ok
teardown

# --- 4.4 the supervised entry point is bounded too ------------------------------

setup
# "up" is what systemd runs, and it runs it again on every failure. The allowance
# tested in 4.1 lives in session_step, which only the watchdog reaches — so the path
# the supervisor actually drives had no bound at all. That is what let a restart
# counter reach 1122 while every attempt asked the modem for another client.
for _ in $(seq 1 6); do QMI_START=refuse MAX_SESSION_FAILS=3 run up >/dev/null 2>&1; done
attempts_before=$(grep -c -e "--wds-start-network" "$CALLS")
QMI_START=refuse MAX_SESSION_FAILS=3 run up >/dev/null 2>&1
attempts_after=$(grep -c -e "--wds-start-network" "$CALLS")
[ "$attempts_after" -eq "$attempts_before" ] \
    || fail "4.4: the supervised path is unbounded — attempt $attempts_after followed a long run of failures"
ok
teardown

setup
# The paired positive control: below the bound it must still be trying, or 4.4 above
# would pass just as well against an "up" that never does anything at all.
for _ in 1 2; do QMI_START=refuse MAX_SESSION_FAILS=3 run up >/dev/null 2>&1; done
[ "$(grep -c -e "--wds-start-network" "$CALLS")" -ge 2 ] \
    || fail "4.4: the supervised path stopped trying before its allowance was spent"
ok
teardown

# --- 2.4 the supervised path does not manage the session behind the watchdog ----

setup
# Both run on a 30s cadence: the timer, and the unit's own Restart=. The watchdog
# takes a lock before touching the session; "up" did not, so the two could allocate
# a client each against one modem, and only one of them could be recorded as held.
mkdir -p "$STATE"
exec 9>"$STATE/lock"
flock -n 9 || fail "2.4: the harness could not take the lock it means to hold"
QMI_START=refuse run up >/dev/null 2>&1
exec 9>&-
if called "--wds-start-network"; then
    fail "2.4: the supervised path managed the session while another run held the lock"
fi
ok
teardown

setup
# Paired positive control: with the lock free, "up" must go ahead as before.
QMI_START=refuse run up >/dev/null 2>&1
called "--wds-start-network" || fail "2.4: the supervised path refused to work with the lock free"
ok
teardown

# --- 4.5 the supervisor's own restart policy can actually reach its limit -------

# Not a check that the keys are spelled somewhere: the arithmetic is the defect.
# systemd counts starts in a window (StartLimitIntervalSec, default 10s) and gives up
# after StartLimitBurst of them (default 5). With RestartSec=30 no two restarts ever
# land in one 10s window, so the default limiter cannot trip and the unit restarts for
# ever. The window has to be wide enough to hold a whole burst of them.
# Both keys are [Unit]-section settings; systemd ignores them in [Service] silently.
UNIT="$(cd "$(dirname "$0")/.." && pwd)/deploy/wwan-backup/wwan-backup.service"
unit_key() { awk -F= -v k="$1" '$1==k {print $2; exit}' "$UNIT"; }
if [ -n "$(unit_key Restart)" ]; then
    restart_sec=$(unit_key RestartSec)
    burst=$(unit_key StartLimitBurst)
    window=$(unit_key StartLimitIntervalSec)
    [ -n "$burst" ] && [ -n "$window" ] \
        || fail "4.5: the unit restarts on failure with no start limit — nothing stops the loop"
    awk -v s="${restart_sec:-0}" -v b="$burst" -v w="$window" \
        'BEGIN { exit !(w > s * (b - 1)) }' \
        || fail "4.5: RestartSec=$restart_sec x StartLimitBurst=$burst does not fit in StartLimitIntervalSec=$window — the limiter can never trip"
    if awk '/^\[Service\]/ {svc=1} svc && /^StartLimit/ {found=1} END {exit !found}' "$UNIT"; then
        fail "4.5: StartLimit* sits in [Service], where systemd ignores it"
    fi
    ok
fi

# --- 2.5 a client that cannot be recorded is not held either --------------------

setup
# When the allocation itself fails there is no id to reuse, and the fallback asked for
# the next best thing: a client qmicli allocates and is told not to release. Nothing
# on the host then names it, so no teardown can ever free it — the modem holds it until
# the module loses power. The flag only earns its keep when we have an id to preserve.
# --wds-noop is the one call allowed to pin without naming an id: it is the allocator,
# and it exists precisely to read that id back and write it down. Every other call has
# to carry a recorded id or not pin at all.
QMI_NOOP=refuse QMI_START=refuse run up >/dev/null 2>&1
while read -r line; do
    case "$line" in
        *--wds-noop*|*--client-cid=*) ;;
        *--client-no-release-cid*)
            fail "2.5: a client was pinned with nothing recorded to release it later: $line" ;;
    esac
done < "$CALLS"
ok
teardown

setup
# Paired positive control: when the id *is* known, the flag must still be used — that is
# what keeps the session addressable by a later teardown.
run up >/dev/null 2>&1
grep -F -e "--wds-start-network" "$CALLS" | grep -q -e "--client-no-release-cid" \
    || fail "2.5: a recorded client must still be preserved across invocations"
ok
teardown

# --- 2.6 asking for status does not consume a client ----------------------------

setup
# The command that exists to diagnose a modem must not be a way to exhaust it. Status
# ran through the same allocator as everything else, so reading the state of a channel
# whose client could not be recorded cost another one each time it was asked — and it
# gets asked most when things are already going wrong.
QMI_NOOP=refuse run status >/dev/null 2>&1
if called "--wds-noop"; then
    fail "2.6: status allocated a client just to report what the session is doing"
fi
while read -r line; do
    case "$line" in
        *--wds-noop*|*--client-cid=*) ;;
        *--client-no-release-cid*) fail "2.6: status pinned a client it cannot release: $line" ;;
    esac
done < "$CALLS"
ok
teardown

setup
# Paired positive control: status must still ask the modem something, or 2.6 would pass
# against a status command that had quietly stopped working.
run status >/dev/null 2>&1
called "--wds-get-packet-service-status" || fail "2.6: status stopped asking the modem anything"
ok
teardown

echo "PASS ($PASSED assertions)"