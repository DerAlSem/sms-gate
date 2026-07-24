## Why

The watchdog decides the modem is unhealthy on one piece of evidence: `AT+CEREG?` stops
reporting registration. That misses the failure mode where the modem answers every
command politely and refuses to send — a wrong SMSC address, a SIM problem below the
registration layer, a wedged radio. The gateway then fails message after message while
its health check reports "ok" and no recovery is ever attempted.

`add-send-retries` recorded this as a known gap rather than shipping it, because the
obvious coupling is broken in two different ways:

- **Inert.** `_watchdog_step` needs three consecutive failing checks to soft-recover and
  resets its counter whenever registration succeeds. A flag that survives one check never
  reaches the threshold, so the coupling would change the spec and do nothing.
- **Looping.** A flag that persists escalates, and `soft_recover` cycles the radio off and
  on for tens of seconds. Every send attempted in that window fails — feeding the counter
  that triggered the recovery — and the ladder ends at `os._exit(1)`. The 30-minute
  hard-reset gate bounds it to a cycle rather than a spiral, which is not much comfort.

Both problems have the same root: the counter measured the wrong thing, and nothing stopped
the sender from firing into a radio the gateway had just switched off.

## What Changes

- **The signal is distinct messages, not attempts.** The gateway counts messages that have
  failed transiently with no successful send in between. Three *different* messages failing
  is evidence about the modem; one message failing its four attempts is evidence about one
  destination, and must not trigger recovery.
- **A permanent failure is neutral.** It neither counts toward the stall nor clears it —
  `+CMS ERROR 1` says something about the number, not the modem. A message rejected before
  any AT command (over the part budget) is likewise ignored.
- **Any successful send clears the signal**, and with it the modem's health suspicion.
- **Sending is quiesced while recovery runs.** The sender waits rather than attempting, so
  a send is never issued into a radio that is off or has just come back — and, because it
  waits *before* claiming the message, a recovery window consumes none of the retry budget
  it would otherwise burn. This is what breaks the feedback loop.
- **No second recovery ladder.** A stall makes the watchdog's existing health check fail;
  escalation, the soft→hard progression and the once-per-30-minutes hard-reset gate are
  untouched. There is exactly one thing in the system that recovers the modem.
- **With the watchdog disabled the coupling is inert**, as the rest of the watchdog is.

## Impact

- `app/modem/manager.py` — a stall signal fed by the send path, a quiesce gate the sender
  respects and the watchdog owns, and one extra term in the health check.
- No schema change, no API change, no new setting: the thresholds that matter
  (`_WD_FAIL_THRESHOLD`, the hard-reset cooldown) already exist and are reused.

## Not in this change

- **Holding sends back while the modem is merely known to be unregistered.** Tempting —
  it would have deferred prod message 976 instead of failing it, since the modem was
  deregistered for about three minutes — but registration state is only sampled once a
  minute, so acting on it means sending on stale information and risks stranding traffic
  during a long outage. It deserves its own change, with a bound on how long the gateway
  may decline to try at all.
- Any change to what counts as a transient failure; `app/modem/errors.py` is reused as-is.

## Capabilities

### Modified Capabilities
- `outbound-send`: replaces the `descriptive` requirement "Send outcomes do not influence
  modem recovery", recorded at adoption and carried as a known gap since.
