## Context

The gateway talks to a Quectel EM06 over two AT ports: `/dev/ttyUSB2` for commands, behind
`ATSerial` and its lock, and `/dev/ttyUSB3` for unsolicited results, opened directly by
`reader_loop` with no lock and no manager. When the modem re-enumerates on USB both nodes
are destroyed and recreated, and descriptors held across that boundary refer to a device
that is gone.

Nothing in the codebase models that event. `app/modem/at_commands.py` has exactly one
failure type, `ATCommandError`; a `serial.SerialException` from the transport underneath is
caught nowhere. The watchdog's `except Exception: continue`, the sender's broad
`except Exception`, and `main.py`'s `asyncio.gather(..., return_exceptions=True)` then
absorb it at three layers, each converting a fatal condition into silence or a
wrongly-classified message failure.

Constraints that shape the design:

- **One serial port, one lock.** `ATSerial` serialises all AT traffic through `self._lock`,
  which is not reentrant — `init()` goes through `command()`, which takes it.
- **`ModemHealth.decide()` is pure and table-tested.** Keeping I/O out of it is what makes
  the ladder testable as a table of histories. A new cause enters as an observation.
- **The never-transmitted-twice invariant outranks recovery.** Once a PDU is written, or any
  part accepted, the message fails whatever the cause.
- **`.env` is not readable or writable by the operator's account**, so port paths cannot be
  changed as part of recovery.
- **`deploy/sms-gate.service` has `RestartSec=10`, `StartLimitIntervalSec=300`,
  `StartLimitBurst=5`.** Five failed starts inside five minutes stop the unit permanently.

## Goals / Non-Goals

**Goals:**

- A modem that re-enumerates costs minutes, not hours, and no operator action.
- A transport failure is a named condition with one obvious handler at each call site.
- No message is failed at zero attempts because the link was gone, and none is transmitted
  twice because it was held.
- No background loop can die without a trace.

**Non-Goals:**

- Reopening the port in place. Separate change; see Out of scope in the proposal.
- Detecting *why* the modem re-enumerates. Firmware and USB behaviour are outside our
  reach; the design assumes it recurs.
- Surviving a device that returns under a different name. That needs a `.env` change or a
  by-id symlink and is separate work.
- The QMI backup uplink. Separate change.

## Decisions

### `ModemTransportError` is a sibling of `ATCommandError`, not a subclass

Both derive from a common base so a caller with no stake in the distinction can catch one
thing, but neither is an instance of the other.

Subclassing was rejected because it defeats the distinction silently and in the worst
place. `registration_state()` catches `ATCommandError` and returns `None`, meaning "could
not tell" — and the send path is required by spec to read that as permission to transmit,
on the deliberate reasoning that not knowing is not a refusal. A transport failure absorbed
there would make the gateway write messages into a port that no longer exists, and would do
it without a line of code looking wrong.

The cost is that transport failures now propagate through every existing
`except ATCommandError`. There are **nine**, not the four an earlier draft claimed. Only
three need the distinction — `registration_state`, `_send_one`, `_watchdog_step`. The other
six (`scan_inbox` twice, the inbound path, `keepalive_loop`, `collect_diagnostics`,
`_restore_cmgf_unlocked`) should catch the shared base, which turns "revisit nine sites and
hope" into "three decide, six widen".

### The written-bytes record must survive the class split

`send_sms_pdu` sets `pdu_submitted` under `isinstance(exc, ATCommandError)`. A sibling class
fails that check, so a link lost after the PDU and Ctrl-Z were written would surface as
"nothing was written" — and the new hold rule would retry it. That is a duplicate SMS to a
real handset, produced by a change written to prevent harm.

Two paths lead there and both must close: the `isinstance` check moves to the shared base,
and `_restore_cmgf_unlocked` — which runs in a `finally` and today catches only
`ATCommandError` — must not raise a transport failure that replaces the exception already
on its way to the caller.

The multipart case is the same rule at a finer grain. `submitted` resets after each accepted
part, so a link lost between parts reports "nothing written" while part 1 is already at the
SMSC. Holding is therefore permitted only when no byte has been written **and** no part has
been accepted; the existing `already_sent` fact governs the rest.

### Holding must not strand the message

`begin_message_attempt` increments the attempt and sets `next_attempt_at = NULL` before any
byte goes out, deliberately: a message with no schedule is never re-queued, which is what
makes a half-finished attempt safe. A hold decided *after* that point therefore both counts
an attempt it promised not to and leaves the message invisible to the scheduler until its
deadline — the precise outcome holding exists to prevent, reached by the code meant to
provide it.

So the hold decision belongs *before* the attempt is claimed, or it must restore both the
count and the schedule. The first is simpler and is what the spec requires as the default.

### Transport loss is a cause in `ModemHealth`, supplied as an observation

`decide()` gains a `link_lost` observation and a `TRANSPORT` cause, staying pure: the caller
performs the remedy, as it already does for the soft recovery.

One ladder rather than two mechanisms — but not for the reason an earlier draft gave. Port
contention is already prevented by the recovery gate and `ATSerial._lock`, and would be
prevented for a separate mechanism too. The real reason is singular: **one escalation
counter and one place that decides to end the process.** Two mechanisms each able to exit
would fight over restart policy and each would re-enter the other's window.

The threshold belongs to the cause, not to the ladder: three polls exist to absorb one
unlucky registration sample, and a port that cannot be written is not a sample.

### The rungs are levels; the remedy is chosen by cause

`decide()` returns an escalation level. The caller maps `(cause, level)` to an action.
For a lost link the gentle level is to stop using the link and the blunt level is to exit —
no radio cycle, no modem reset, because both are AT commands into a port that is not there.

Without this mapping an implementer wires the new cause into the existing dispatch and
produces a ladder that spends its escalation issuing AT commands into a dead port — the
incident's exact failure mode, reached by a different route.

### Restarting is the remedy, not a fallback

What the restart already gives, for free: a freshly opened port, a full `init()` including
the URC subscription, `scan_inbox()` draining messages the modem stored during the outage,
and pending messages recovered from the database. Reopening in place provides none of those
without adding them explicitly — which is why it is a separate change rather than a
paragraph in this one.

### The startup path is part of this change, not the next one

This is the interaction that makes the exit remedy safe, and it is easy to miss because each
half looks harmless. Exiting on a lost link produces a restart in ten seconds; a
re-enumerating modem is absent for longer than that; `connect()` at startup raises; five
such starts inside five minutes and systemd stops the unit for good. The remedy for a
five-hour outage would be an indefinite one.

So startup waits for the device on the same bounded terms as any other lost link, and the
bound is reconciled with `RestartSec` and `StartLimitBurst` rather than assumed compatible.

### Background tasks are supervised individually, with two guards

`asyncio.gather(*tasks, return_exceptions=True)` is replaced by per-task supervision that
logs and alerts; essential loops exit the service. Two guards are not optional:

- **Cancellation is not death.** Shutdown cancels every task by design. Without this guard
  every deploy alerts on every loop and exits instead of closing the modem and the database.
- **The alert must outlive the decision to exit.** Alerts are queued and delivered by a
  background worker; an immediate exit discards the queue, so the loud new exit would be as
  silent as the failure it replaces.

`reader_loop` does not reconnect in this change. It is an essential loop, so on a lost link
it alerts and exits the service — which is the same remedy, arrived at without a second
bounded reconnector racing the first and without duplicating close/open logic on a port that
has no `ATSerial` behind it.

### A udev-triggered restart is deliberately not the mechanism

Reacting to the device node being recreated would cover every consumer at once, including
`qmi-proxy`. It is not used here because it puts the gateway's recovery outside the gateway:
untestable by the suite, invisible to anyone reading the service, and silently absent if the
rule is lost in a rebuild. Left as a possible second echelon.

## Risks / Trade-offs

- **A sibling class means transport failures propagate through nine handlers.** → Three
  decide, six widen to the base. Enumerated by file and line in the tasks rather than
  described, because the risk is missing one.
- **The exit remedy costs the in-memory queue and a restart cycle.** → Pending messages are
  recovered from the database by an existing normative requirement; the cost is seconds and
  a restart against hours and an operator.
- **Exit-on-death plus a slow device could still exhaust the restart limit.** → The startup
  wait exists precisely for this, and reconciling it with the unit file is a task, not an
  assumption. This was the earlier draft's worst error: it claimed systemd's limits "already
  bound" the risk, when they are what makes it permanent.
- **Holding messages on link loss delays them.** → Bounded by the existing pending deadline,
  which already guarantees a terminal status and a notification.
- **Empty-read detection could misfire on a slow modem.** → An empty read is distinguishable
  from a slow one: a closed stream returns immediately and repeatedly, a slow modem returns
  nothing and blocks. The classification keys on the former.
- **Inbound SMS stored during an outage still wait for the restart.** → Unchanged from
  today, because the remedy is still a restart and `scan_inbox()` still runs. It becomes a
  live risk in the reconnect change, which must add reconciliation explicitly.

## Migration Plan

No schema change and no API change; deployment is an ordinary restart.

1. Reconcile the startup wait with `deploy/sms-gate.service` **before** shipping — the exit
   remedy is unsafe without it.
2. Ship, then verify on the live modem by re-enumerating it deliberately (`AT+CFUN=1,1`) and
   observing the gateway escalate, exit, restart, and come back with `CNMI` intact and
   inbound delivered. The tests cover classification and the ladder; only the live modem
   covers the hardware.
3. `fix-backup-uplink-recovery` ships independently and may go first.

Rollback is a redeploy of the previous commit.

## Open Questions

- **How long should startup wait for the device, against `RestartSec=10` and
  `StartLimitBurst=5`?** The two must be chosen together; either may move.
- **Should `reader_loop` eventually share `ATSerial`?** It currently duplicates raw
  `serial_asyncio` usage with no lock. Not needed while its remedy is to exit, but it is the
  precondition for reconnecting it in the next change.
