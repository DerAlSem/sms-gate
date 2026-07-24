## 1. The stall signal

- [x] 1.1 Track distinct message ids that failed transiently since the last successful
      send; a permanent failure, a pre-modem rejection, an internal error and a
      sweep-driven fail are all neutral; a success clears.
- [x] 1.2 A message that exhausts its whole retry budget stalls on its own — measurement
      showed three distinct messages would take about four hours at this gateway's
      traffic (12.8/day, 112-minute mean gap), i.e. no signal at all.
- [x] 1.3 `_watchdog_step` treats a stall as a failed health check, with no change to
      escalation, cooldown or exit.
- [x] 1.4 The ladder restarts when the *cause* changes, so a stall cannot inherit a soft
      recovery performed for a registration outage and open with a hard reset.
- [x] 1.5 `watchdog_loop` clears the evidence when the watchdog is disabled, and the loop
      is now always started so that branch actually runs and the toggle is live.
- [x] 1.6 `send_stall_recovery_enabled` — its own switch, since this mechanism can
      restart the service and the alternative was giving up registration recovery too.
- [x] 1.7 Tests: three distinct messages; one exhausted budget; a success clears;
      permanent and pre-modem failures neutral; a stall does not inherit the registration
      ladder; a persistent stall still reaches a hard reset; the switch; disabled watchdog.

## 2. The quiesce gate

- [x] 2.1 An event meaning "the modem is usable", closed by the watchdog around recovery
      and reopened in `finally` so an exception cannot leave the gateway mute.
- [x] 2.2 The sender waits on it **before** claiming a message, so a held message
      consumes no attempt.
- [x] 2.3 Inbound reading waits too — a read against a switched-off radio fails and its
      notification is discarded, losing the message until the next inbox scan.
- [x] 2.4 Recovery is bounded by a timeout, and the sender's backstop is derived from that
      ceiling rather than guessed; it necessarily outlasts the hard-reset settle.
- [x] 2.5 After recovery the gate stays shut until the modem reports registration (or a
      bound elapses) — `AT+COPS=0` acknowledges a request to reselect, not an attach.
- [x] 2.6 `soft_recover` re-issues the `CNMI` subscription; losing it would silently stop
      every delivery report and every inbound message.
- [x] 2.7 Tests: the gate closes around recovery and reopens; it reopens on an exception;
      the hard path leaves it shut; a stuck gate releases the sender; the reattach wait
      polls with the gate shut; CNMI is restored; inbound waits.

## 3. Verify and ship

- [x] 3.1 Full suite green (384).
- [x] 3.2 Conformance: the requirements this change adds are backed, and the
      `descriptive` "Send outcomes do not influence modem recovery" is removed.
- [x] 3.3 Docs: README (RU+EN), `CHANGELOG.md`, version 0.10.0.
- [x] 3.4 Deployed 2026-07-24 with the owner's confirmation; no migration in this
      release, DB backed up anyway (983 rows). All loops started clean, watchdog task up
      with `enabled=True`, zero errors, `send_stall_recovery_enabled` seeded true. Smoke:
      message 984 sent on attempt 1 and reported delivered in 3s. The stall path itself
      is untested on live hardware — it needs a real modem that answers but will not
      send. Rollback is `send_stall_recovery_enabled` = false, no code rollout.

## 4. Deliberately out of scope

- Holding sends back while the modem is merely known-unregistered. Would have saved prod
  message 976, but acts on once-a-minute sampling and risks stranding traffic through a
  long outage; needs its own bound and its own change.
- A dedicated operator alert when a stall is declared. The escalation ERROR lines now
  name the cause with distinct templates so Telegram cannot collapse them, which is the
  floor; a first-class alert is a separate conversation about the alert vocabulary.
- Extracting a `ModemHealth` collaborator. `ModemManager` is doing too much and this
  change adds to it; the escalation state would be far easier to reason about as a small
  state machine of its own. Worth doing before the next change to this seam.
