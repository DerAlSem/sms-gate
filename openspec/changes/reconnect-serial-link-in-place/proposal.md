## Why

`recover-from-serial-transport-loss` makes the gateway survive a modem that re-enumerates,
by classifying the fault correctly and letting the recovery ladder reach the rung that
restarts the service. That closes the whole of the 2026-07-29 outage: five hours become
minutes, unattended.

It leaves the remedy blunt. Every re-enumeration costs a process restart, which drops the
in-memory send queue, re-runs startup, and produces a restart cycle in the journal for what
is physically a device disappearing for a few seconds. Reopening the port in place turns
that into a pause.

This is deliberately second. The reopen is where the hazards live — a non-reentrant lock
that the init sequence would deadlock on, a half-open state if the operation is cancelled,
a second reopener on the unsolicited-result port racing a deliberate modem reset, and the
loss of the startup inbox scan that the restart currently provides for free. None of them
are hard; all of them are ways to make inbound delivery worse than it is today, in the name
of making outbound recovery faster.

## What Changes

- The gateway **reopens the port in place** on a lost link, with bounded attempts, a bound
  on each attempt as well as on their number, and a restart only once reopening has failed.
- A node that is absent **or not yet permitted** counts as "not back yet" — a recreated node
  gets its ownership from udev, so early attempts can fail on permission rather than
  absence.
- **Reopening and initialising are one indivisible act** under the serial lock, issued
  through the path that assumes the lock is held. The init sequence goes through the
  lock-acquiring path today, so a naive implementation deadlocks.
- **Reopening is cancellation-safe**: it leaves the link either fully usable or explicitly
  unusable, never undefined, and its budget sits well inside the recovery timeout that
  wraps it.
- **A restored link is reconciled with the modem's stored messages.** The restart's startup
  scan is what drains inbound accumulated during an outage; removing the restart without
  replacing the scan would strand them.
- **Re-reading the modem's memory cannot deliver an inbound message twice.** A message is
  deleted only after it is persisted, so an interruption between the two leaves it to be
  found again — latent today, likely once scanning becomes frequent.
- **The unsolicited-result port is recovered by the same mechanism**, waiting on the
  recovery gate, rather than growing an independent reopen loop that could restart the
  service on its own or reopen during a deliberate modem reset.
- **The link's state becomes visible** on the diagnostics page — state, last known good,
  reopen count.

## Capabilities

### New Capabilities

None.

### Modified Capabilities
- `modem-link`: gains reopening in place as the first remedy, its safety properties, the
  reconciliation that the restart used to provide implicitly, coordinated recovery of the
  second port, and visibility of the link's state.

## Impact

- `app/modem/at_commands.py` — reopen under the lock; a lock-free init path; cancellation
  safety.
- `app/modem/manager.py` — the transport remedy becomes reopen-then-restart; `reader_loop`
  recovered by the shared mechanism; inbox reconciliation after a restored link.
- `app/modem/health.py` — the link fields in the snapshot.
- `app/db/queries.py` — deduplication of a re-read inbound message.
- No schema change beyond whatever the inbound deduplication key requires, and no API
  change.

## Depends on

`recover-from-serial-transport-loss`, which introduces the failure class, the link's
usable/unusable state, the per-cause remedy mapping and the startup wait this change builds
on. Shipping this first would mean reopening a link whose loss is still not detected.
