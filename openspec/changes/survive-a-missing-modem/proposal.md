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
