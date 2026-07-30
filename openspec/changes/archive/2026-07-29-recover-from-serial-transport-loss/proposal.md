## Why

On 2026-07-29 at 01:28 the USB modem re-enumerated. Every `/dev/ttyUSB*` node was
recreated, the gateway's open file descriptors went stale, and the gateway stayed down for
**5 hours 10 minutes** — until an operator restarted it by hand. The service reported
`active (running)` throughout.

The cause is a single missing distinction. The modem layer's error vocabulary has exactly
one word — `ATCommandError`, "the modem answered badly" — and no word for "there is no
modem". `serial.SerialException` is therefore caught nowhere and handled nowhere, and it
falls through three separate places:

1. **The watchdog never climbs a rung.** `registration_state()` catches only
   `ATCommandError`, so the exception escapes `_watchdog_step()` *before*
   `ModemHealth.decide()` is reached, and `watchdog_loop` swallows it with
   `except Exception: continue`. No failure is counted, no recovery runs, and the rung
   whose service exit is the only thing that would have reopened the port is unreachable.
   Worse, every rung speaks AT into the same dead port, so even a corrected failure count
   would abort on the next rung.

2. **The sender burns messages instead of holding them.** A transport failure reaches
   `sender_loop`'s broad `except Exception` and the message is failed at `attempt=0` with
   `internal error while sending` — no retry, and a `failed` webhook that makes the calling application SMS an
   operator (U1). The entire retry ladder built in 0.9.0–0.11.0 is bypassed because the
   exception is of the wrong class. Nothing was lost this time only because no send was
   attempted during the outage.

3. **The URC reader dies in total silence.** `reader_loop` has no exception handling
   inside its `while True`, and `main.py` collects the background tasks with
   `asyncio.gather(..., return_exceptions=True)`. A raising loop disappears without a log
   line. Losing it means no `+CDS` and no `+CMTI` — every message expires and every inbound
   SMS is missed — which is precisely the failure the `outbound-send` spec already calls
   out as "silent and total, with no health check able to notice".

## What Changes

- **A transport failure becomes a named failure class**, a **sibling** of `ATCommandError`
  rather than a subclass. A subclass would be absorbed silently by every existing
  `except ATCommandError`, including `registration_state()`, which would report "could not
  tell" and let the sender transmit into a dead port. Both derive from one base so the
  callers that do not care can still handle them together.
- **A cleanly closed link counts as a lost link.** A closed stream returns nothing rather
  than raising, so watching only for exceptions produces a spin followed by an ordinary AT
  timeout — routing the fault straight back into the handling this change exists to bypass.
- **A link known to be lost fails fast** instead of every consumer rediscovering it through
  its own timeout.
- **The ladder counts a failure it could not observe, and continues past a remedy it could
  not perform.** Its rungs become escalation levels whose remedy is chosen by cause; for a
  lost link no rung issues AT commands, and it acts on the first observation rather than
  the third.
- **Restarting the service is the remedy for a lost link.** It is what reopens the port,
  re-runs the init sequence including the URC subscription, reconciles the modem's stored
  messages and recovers queued messages — all of which the gateway already does at startup.
- **A link absent at startup is treated as the same fault**, bounded and reconciled with
  the supervisor's restart limits. Without this the remedy becomes the failure: a restart
  provoked by a lost link lands while the device is still absent, and the unit stops
  permanently after five such attempts — turning a five-hour outage into an indefinite one.
- **A held-back message is not a failed message**, and holding leaves it schedulable. A
  transport failure before any byte was written and before any part was accepted holds the
  message with no attempt counted. After bytes are written, or when a part has already been
  accepted, the never-transmitted-twice rule keeps precedence and the message fails.
- **The record of whether message bytes reached the modem survives the new class.** It is
  set today by an `isinstance` check against `ATCommandError`, which a sibling class fails —
  and a best-effort state restore in a `finally` would replace the original failure
  outright. Either alone turns the rule that prevents a duplicate SMS into the cause of one.
- **A background loop can no longer die in silence**, a shutdown cancellation is not
  mistaken for a death, and a fatal alert is delivered before the process exits.

## Capabilities

### New Capabilities
- `modem-link`: the serial transport between the gateway and the modem — recognising its
  loss as a class of failure distinct from a misbehaving modem, refusing to spend AT
  remedies on it, restarting the service when it cannot be used, and treating a link absent
  at startup as the same fault.
- `service-runtime`: the process's background tasks and its exits — supervision that cannot
  discard a loop's failure, cancellation distinguished from death, fatal alerts delivered
  before exit, and dropped notifications recorded.

### Modified Capabilities
- `outbound-send`: the recovery ladder counts unobservable polls, survives unperformable
  remedies, and chooses its remedy by cause; the sender holds a message on a lost link
  instead of failing it at zero attempts, bounded by the never-transmitted-twice rule; and
  that rule gains the requirement that the written-bytes record survives however a failure
  is classified.

## Impact

- `app/modem/at_commands.py` — the new class and shared base; serial reads, writes and
  drains classified; empty-read detection; a usable/unusable link state.
- `app/modem/health.py` — a transport cause, and a per-cause threshold rather than one
  shared count.
- `app/modem/manager.py` — `_watchdog_step`, `_recover`, `hard_reset`, `sender_loop`,
  `_send_one`, `reader_loop`, and the nine `except ATCommandError` sites.
- `app/main.py` — startup wait for the device; per-task supervision replacing silent
  `gather(..., return_exceptions=True)`; supervision extracted from the lifespan so it can
  be tested.
- `app/alerting.py` — dropped and undeliverable notifications recorded; delivery drained
  before a fatal exit.
- `deploy/sms-gate.service` — `RestartSec` and `StartLimitBurst` reconciled with the
  startup wait.
- No schema change, no API change, no change to the `messages` status vocabulary a
  consuming app sees.

## Out of scope

- **Reopening the port in place.** Split into `reconnect-serial-link-in-place`. Restarting
  the service closes the whole of the observed incident; reconnecting turns a few seconds
  plus a restart into a few seconds, and brings its own hazards — lock reentrancy,
  half-open state, a second reconnector on the read port, and the loss of the startup inbox
  reconciliation. It is worth building, second.
- **The QMI backup uplink.** Split into `fix-backup-uplink-recovery`. Same root cause,
  different language, deploy path and rollback; it ships first because it is smaller and its
  watchdog is currently disabled.
- **Re-alerting on a persistent fault.** Dropped. The proposal originally claimed one alert
  covered the whole outage; the operator confirms dozens arrived, so deduplication behaved
  as designed and the requirement would have added a second rate limiter on top of a working
  one.

## Incident of record

`/dev/cdc-wdm0` was recreated at 01:28:27 — the modem re-enumerated on USB while the server
itself stayed up. Three consumers held descriptors to the device it replaced, and none of
them noticed:

| consumer | outcome |
|---|---|
| `sms-gate` | 316 swallowed watchdog failures, no sends, no inbound, 5h10m until restarted by hand |
| `qmi-proxy` | stale for 5h55m; every QMI request through it timed out |
| `wwan-backup` | 131 unbounded retries, one leaked QMI client each, pool exhausted, cleared only by rebooting the modem |

Nothing reached a user: the primary uplink stayed healthy and no send was attempted during
the window. The gateway would have failed every one of them at zero attempts.
