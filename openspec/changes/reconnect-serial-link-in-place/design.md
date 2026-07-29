## Context

After `recover-from-serial-transport-loss`, a lost link is detected, classified, escalated
on its own cause, and cured by restarting the service. The restart is what reopens the
port, re-runs `init()` including the URC subscription, drains the modem's stored inbound
messages via `scan_inbox()`, and recovers queued messages from the database.

This change replaces the restart with an in-place reopen for the common case, which means
every one of those four things must now be provided explicitly. Three of them are the
design's real content; the reopen itself is the easy part.

## Goals / Non-Goals

**Goals:**

- A re-enumeration becomes a pause rather than a restart cycle.
- Inbound delivery is no worse than it is with the restart remedy — the bar this change is
  most likely to fail.
- One reopen mechanism, not one per port.

**Non-Goals:**

- Removing the restart remedy. It stays as the outcome of exhausted attempts.
- Surviving a device that returns under a different name.
- Recovering `+CDS` delivery reports lost during the outage — see the accepted gap below.

## Decisions

### Reopen and init are one act under the lock, through a lock-free init path

`ATSerial._lock` is an `asyncio.Lock`, which is not reentrant, and `init()` issues its
commands through `command()`, which acquires it. A reopen that holds the lock and calls
`init()` deadlocks outright.

Where it deadlocks is what makes it dangerous rather than obvious: wrapped in the recovery
timeout, it surfaces as "recovery took five minutes and achieved nothing" — close enough to
the original incident to be mistaken for it. Called from the send path it hangs
indefinitely.

The codebase already has the convention: `_cmgr_unlocked`, `_cmgl_unlocked`,
`_set_cmgf_unlocked`, `_abort_prompt_unlocked`. An `_init_unlocked` joins them, and reopen
holds the lock across close, open and init as one indivisible act.

### The reopen budget is fixed against the recovery timeout, not left open

The chain is: `_recover` wraps the remedy in a 300-second timeout, `_await_reattach` adds
30 seconds after it, and the sender's own gate wait is 390 seconds. The binding constraint
is therefore the 300, not the 390 — an earlier draft named the wrong one.

Roughly five attempts three seconds apart, plus the init sequence, is about 30 seconds
worst case: an order of magnitude inside the wrapper, so cancellation is an exception
rather than the ordinary outcome. Each attempt gets its own timeout too, because
`wait_closed()` on a vanished device and `open()` on a node udev has not finished can both
block, and a bound on the number of attempts does not bound the wait.

### Cancellation safety is a requirement, not an implementation detail

If the reopen is cancelled between close and open, `_recover`'s `finally` reopens the gate
regardless and the sender resumes against a link with no reader and no writer. The
usable/unusable state introduced in the previous change is what makes that a defined
condition: on every exit path the link is either fully open and initialised, or explicitly
unusable, so the next send fails immediately instead of discovering the truth one timeout
at a time.

### Reconciliation after a restored link is the point, not a detail

This is the requirement most likely to be dropped as an optimisation and it is the one that
decides whether the change is a net improvement. During a dead-link window the modem stores
inbound SMS and the `+CMTI` announcing them are lost. The restart remedy drains them at
startup. A reopen that does not scan leaves them unread until some later restart — and the
living spec already names this failure mode, from the other direction, as "silent and
total".

The queued indexes cannot substitute for the scan: they only describe what was announced
before the link died, not what arrived while nothing was listening.

### Frequent scanning forces inbound deduplication

A stored message is persisted first and deleted from the modem second, so an interruption
between them leaves it to be found again. That is latent today because scanning happens
once per restart. Making it happen on every restored link converts a rare duplicate into a
likely one — so deduplication ships with the mechanism that makes it necessary, not after.

### The unsolicited-result port is recovered by the shared mechanism

It is opened directly today with no lock and no manager. Giving it its own reopen loop
produces two independent budgets, each able to restart the service, and a reopen that can
race the settling period after a deliberate hard reset — a window that exists precisely so
nothing touches a rebooting modem.

So its recovery is coordinated with the command port's and waits on the recovery gate.
Whether it needs an init sequence of its own has to be settled rather than assumed: it has
no writer, so it cannot issue the URC subscription, which is applied through the command
port and appears to take effect for both.

## Risks / Trade-offs

- **Reopening reintroduces state that a restart would have cleared.** → In-flight message
  ids, the inbound index queue and assembler state all survive a reopen. The first two are
  covered by the never-transmitted-twice rule and by the reconciliation scan; assembler
  state lives in the database and its stale-part flush already handles gaps.
- **Two ports, one mechanism, more coupling.** → Accepted deliberately: two mechanisms that
  can each end the process is the worse failure.
- **Deduplication needs a key on inbound messages.** → Small schema addition, shipped with
  migration and back-compat as the living spec requires.
- **Reopening could mask a genuinely failing modem** by making the fault quieter. → The
  reopen count is exposed on the diagnostics page and the restart remedy still fires when
  attempts are exhausted.

## Accepted gaps

- **Delivery reports lost during the outage are not recoverable.** The URC subscription
  routes `+CDS` directly rather than storing it, so a report arriving on a dead port is
  gone. The affected messages stay `sent` and are moved to `expired` by the existing sweep,
  which notifies the application — so a delivered message can be reported `expired`. Making
  this recoverable means switching to stored delivery reports and reading them back, which
  is a different change with its own trade-offs. Recorded here so it is not rediscovered as
  a defect.

## Open Questions

- **Does the unsolicited-result port need its own init, and in what order relative to the
  command port's?** It cannot issue commands as it stands.
- **What is the deduplication key for a re-read inbound message** — modem index plus
  timestamp, or a hash of the PDU? The index alone is reused by the modem.
