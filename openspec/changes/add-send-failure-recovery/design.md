# Design — add-send-failure-recovery

## R1 — What counts as evidence the modem is sick

**Decided: three distinct messages failing transiently, or one exhausting its whole retry
budget — either way with no successful send in between.**

The first attempt at this change counted "three consecutive transient failures", which a
single message reaches on its own: with a four-attempt budget, one unreachable destination
timing out three times would trigger modem recovery. That is a category error — the
evidence is about the destination, not the hardware.

So the sender records the *id* of each message that fails transiently into a set. But
distinct messages alone are not enough of a signal **at this gateway's traffic**, which is
the correction measurement forced on the first draft of this design: 12.8 messages a day,
a mean gap of **112 minutes** between them, and most busy hours carrying one or two.
Waiting for three distinct messages would declare a stall after roughly four hours — inert
in practice, which is exactly the failure the earlier attempt was rejected for, arrived at
from the other direction.

So there are two ways to reach the threshold, and a stall needs either:

- **three distinct messages** failed transiently — the multi-message case, which is what
  matters when traffic is heavy; or
- **one message that exhausted its whole retry budget** on transient failures — roughly
  eight minutes during which the gateway could not get anything out. On a quiet gateway
  this is the clause that actually fires.

Both are gated on the same precondition: **no send has succeeded since the first of those
failures**.

The single-message clause is defensible because of *which* failures count. A transient
failure here is a timeout, a lost prompt, or a network refusal — symptoms of the local
radio far more often than of a destination, since a bad destination shows up as a
permanent `+CMS` code (neutral) or as a delivery-report failure (a different layer
entirely). And the cost of being wrong is small: a false stall buys a soft recovery three
watchdog ticks later, which cycles the radio for tens of seconds on a gateway that by
definition has just failed to send anything.

A permanent failure is **neutral** — neither added nor clearing. `+CMS ERROR 1` and a
message over the part budget say nothing about the modem, and letting them clear the set
would let a stream of bad numbers mask a genuinely dead radio.

Any successful send empties the set. A modem that just sent something is not stalled.

## R2 — Acting on it without a second ladder

**Decided: the stall is one more term in the watchdog's health check.**

```
healthy = registration_ok() and not stalled
```

Everything downstream is untouched: three failing checks → `soft_recover`, then the
hard reset gated to once per 30 minutes, then the service exit. Duplicating the ladder for
send failures would put two independent recovery paths on one modem, racing each other
over one serial port.

This also answers the "inert" objection. The stall is not a one-shot flag that a single
successful `AT+CEREG?` erases; it is cleared by a successful *send*, which is the thing it
is actually about. During a real stall the health check keeps failing, so the counter
climbs to the threshold and the ladder runs.

## R3 — Breaking the feedback loop: the quiesce gate

**Decided: the watchdog closes a gate around recovery; the sender waits on it before
claiming a message.**

This is the part that made the earlier design dangerous. `soft_recover` issues
`CFUN=4 → CFUN=1 → COPS=0`: the radio is deliberately off for tens of seconds. The serial
lock stops the sender interleaving *bytes*, but nothing stopped it from acquiring the lock
the moment recovery released it and firing `AT+CMGS` into a radio that had not
re-registered yet. Those failures then fed the stall that caused the recovery.

An `asyncio.Event` — set means "sending allowed" — is cleared by the watchdog before it
recovers and set again afterwards. Two properties matter:

- **The sender waits before `begin_message_attempt`.** A message held by the gate has not
  been claimed, so it consumes no attempt and no retry budget. Recovery therefore costs
  the message time, not chances. Waiting after claiming would have been the same bug in a
  new place.
- **The wait is bounded.** If the gate somehow stays closed, the sender proceeds anyway
  after `_SEND_GATE_TIMEOUT`. A gateway that tries and fails is recoverable; one that
  silently never tries is not, and `retry_loop`'s deadline would quietly fail everything.

The gate is closed only around recovery operations, not for the whole time the modem is
unregistered — see the deliberate exclusion in the proposal.

## R4 — Why not a settle delay instead of a gate

Rejected: `await asyncio.sleep(n)` after recovery inside the watchdog. It blocks the
watchdog rather than the sender, so the sender keeps sending during the sleep — it fixes
nothing. The gate has to be held by the party that recovers and observed by the party that
sends; those are different loops, so it has to be shared state.

## R5 — Interaction with the disabled watchdog

`watchdog_loop` already skips its step when `modem_watchdog_enabled` is false, and clears
its counters. The stall set is cleared there too, and the gate is never closed because
nothing recovers. So with the watchdog off the coupling is inert, which matches
`AGENTS.md`: "Disabling it means manual recovery only."

## R6 — What this cannot do

A stall is only detectable once messages exist to fail. On an idle gateway with a wedged
modem, nothing is attempted, so nothing is detected — registration polling remains the
only signal, exactly as today. That is acceptable: a modem that cannot send and has
nothing to send is not yet hurting anyone, and the first message to arrive starts the
clock. Worth stating so nobody reads the requirement as a general modem-health monitor.
