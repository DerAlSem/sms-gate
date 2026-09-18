## Why

On 2026-08-28 the modem was unplugged from USB. The gateway did not merely lose the
modem — it stopped serving HTTP entirely, and the admin console answered `502 Bad
Gateway` with no explanation. The operator went looking for what was wrong with the
modem and was told nothing at all.

The cause is placement: `main.py` awaits `modem_manager.connect()` inside `lifespan`
*before* `yield`, so uvicorn never begins listening. A missing device raises
`ModemTransportError: /dev/ttyUSB2 did not appear within 60s`, startup fails, the
process exits, systemd restarts it, and it fails again. The admin console does not
depend on the modem for anything — it reads the database — but it shares a process with
the modem and dies with it.

This already contradicts a normative requirement the living spec makes of us: *"The
link's state is visible where an operator looks."* A page that cannot be opened shows
nothing. The one condition the requirement exists for — the modem being unreachable —
is exactly the condition that takes the page away.

## What Changes

- The HTTP server starts unconditionally. Connecting to the modem moves out of the
  startup path and becomes work the gateway does in the background, so no state of the
  hardware can stop the console from being served.
- A modem that is absent, or that cannot be opened, becomes a **reported state** rather
  than a failure to start. The admin console shows it plainly on every page.
- **BREAKING (spec):** the gateway no longer exits when the link cannot be used —
  neither at startup nor in flight. Reopening continues indefinitely instead of
  escalating to a process restart. This retires the restart as a recovery remedy, so
  everything the restart used to accomplish must now be accomplished by connecting
  late: the init sequence including the URC subscription, the scan of the modem's
  stored messages, and the recovery of queued messages from the database.
- Outbound messages are **held as `pending`** while there is no modem, keeping their
  ordinary deadline, rather than being failed. Absent hardware is not a refusal by the
  network, and a brief unplug must not turn into lost SMS.

## Capabilities

### New Capabilities

None. This changes how existing capabilities behave; it introduces no new area of
behaviour.

### Modified Capabilities

- `modem-link`: the gateway no longer exits when the link cannot be established or
  reopened; a link that is absent at startup no longer prevents the service from
  serving; connecting late must carry the full weight the restart used to carry.
- `admin-sms-console`: the console is served whether or not the modem is reachable, and
  an unreachable modem is shown on every page rather than only on the diagnostics page.
- `outbound-send`: a message is held rather than failed while the gateway has no modem
  at all, distinct from the existing hold for a modem that is off the network.

## Impact

- `app/main.py` — `lifespan` no longer awaits the modem before yielding; the connect
  becomes a supervised background task.
- `app/modem/manager.py` — `connect()`, the recovery ladder's terminal rung, and
  `_await_reattach`; the sender must consult "is there a modem at all" before claiming
  an attempt.
- `app/modem/at_commands.py` — `connect()`'s bounded device wait, and the reopen budget
  that today ends in a restart.
- `app/admin/` — templates and the health snapshot that feeds them.
- `deploy/` — the unit's `Restart=`/`StartLimitBurst=` reasoning changes, because the
  gateway no longer uses its own exit as a remedy.
- Every route in `app/api/` keeps working with no modem, since accepting and queueing a
  send never touched the modem.

## Two acceptance clauses refused, not forgotten — owner's decision, 2026-09-18

Tasks 7.3 and 7.4 asked for a rehearsal on prod hardware. The rehearsal happened, but it
was not staged: on 2026-09-17 at 12:00 MSK the EP06-E lost USB three times (12:00:09,
12:00:21, 12:00:26) while its neighbour EM12-G was being pulled, and both AT ports went
with it. What that episode proves, read out of the journal on 2026-09-18, is three of
7.3's four clauses:

- **The console stayed up.** `POST /sms/send` answered 200 at 12:01:00 and `GET /sms/2288`
  at 12:01:10 and 12:03:10 — served with no device node present, which is the whole point
  of moving the connect out of `lifespan`.
- **No restart was used as a remedy.** `NRestarts=0`, and
  `ExecMainStartTimestamp=Thu 2026-09-17 06:37:26 MSK`: the process that served the outage
  is the one that started five hours before it.
- **Sending resumed unaided.** Message 2288 was held seven times (`held: modem not
  registered`) while still on attempt 1 — no retry budget spent — then sent at 12:03:44 and
  reported `+CDS delivered` at 12:03:45, both delivery webhooks answering 200.

Two clauses are refused rather than checked, and the reason is the same in both: the
evidence costs a second deliberate outage on a gateway carrying live customer traffic.

- **The notice on the console was not witnessed.** For the whole absence the only client was
  the application (178.250.157.233), sixteen requests, none to `/admin/*`. Nobody opened an
  admin page while the link was out. The notice is left standing on tests 5.1 and 5.4 — that
  it renders on every page, and that it disappears when the link is back.
- **7.4 — inbound arriving mid-absence — never ran.** `Inbox scan: empty` at each
  reconciliation of the episode (12:00:15, 12:00:24, 12:00:44): nothing arrived while the
  ports were gone, so the once-not-twice path was not exercised. Waiting for the coincidence
  is not a plan: inbound runs 2–19 a day (median 4 over the preceding 21 days) against an
  absence of ~3.5 minutes, which puts a natural overlap near 1% per episode. Its guard stays
  the reconciliation tests of section 7 alone.

Recorded here rather than left as two open boxes, so a later reader does not mistake a
priced decision for an oversight. If the dedup on reconciliation is ever suspected in
earnest, the way to buy the evidence is named: unplug, text the gateway's own number while
the ports are gone, replug. Not worth an outage on its own account.

One measurement worth keeping, because it looks like a defect and is not: inbound has been
silent since 2026-09-16 14:58, about forty hours across the modem swap. The four largest
inbound gaps of the preceding 45 days are 178.8h, 106.4h, 75.1h and 75.0h, so the quiet
says nothing about the swap.
