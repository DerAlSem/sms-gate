## Context

The gateway is one process: FastAPI serves the API and the admin console, and the same
process owns the serial link to the modem. Today the link is established during
`lifespan`, before `yield`, which makes a reachable modem a precondition for serving
HTTP at all.

There are currently **three** ways the link gets established, and they do different
amounts of work:

1. `ModemManager.connect()` at startup — opens both ports, runs the init sequence
   including the URC subscription, then `scan_inbox()` drains what the modem stored.
2. `ATSerial.reconnect()` from `_reopen_link` during recovery — opens and initialises,
   and the manager follows it with a reconciliation scan.
3. **Restarting the process** — the blunt remedy, which gets path 1 for free.

Path 3 is the one this change removes, and the living spec is explicit about why it
existed: *"A restart is the one remedy that reliably works, because it opens the port
afresh, runs the init sequence including the URC subscription, reconciles the modem's
stored messages, and recovers queued messages from the database."* Removing it without
moving that work elsewhere would trade a crude remedy for none.

The queue itself is already durable: `sender_loop` reads pending messages from SQLite,
so "recovers queued messages from the database" needs no new machinery — it needs the
sender to still be running, which it will be.

## Goals / Non-Goals

**Goals:**

- HTTP is served whenever the process is up, regardless of the modem.
- An unreachable modem is a state the operator can see, on every admin page.
- One code path establishes the link, used at startup and after a loss alike.
- Outbound messages survive a missing modem as `pending`, keeping their deadline.
- Nothing that the process restart used to accomplish is quietly lost.

**Non-Goals:**

- Splitting the admin console into its own process. The coupling being fixed is
  ordering inside `lifespan`, not co-location.
- Changing how a *registered but unhealthy* modem is recovered. The radio-cycle and
  reset rungs stay as they are; only the terminal rung changes.
- Fixing the three send-diagnosis defects found in the same incident (the 30 s `CMGS`
  timeout, `_clear_stall` erasing evidence, `_read_until` swallowing a late
  `+CMS ERROR`). Separate change, `outbound-send`.

## Decisions

### The link is established by a loop, not by startup

`lifespan` stops awaiting the modem. A supervised background task owns establishing and
re-establishing the link, and every other loop waits on the existing recovery gate,
which starts **closed** instead of open.

*Alternative considered:* keep `connect()` in `lifespan` but catch the failure and carry
on. Cheaper, but it leaves two establishment paths that must stay in step — and they
already drifted once (the startup wait is 60 s, the reopen budget had to be pinned to
the same number by hand after a prod incident). One path removes the class of bug.

### Establishing the link is one operation with one definition of "done"

A single `ensure_link()` is the only way the link comes up: open the command port, open
the URC port, run the init sequence including `AT+CNMI`, and reconcile the modem's
stored messages. It is not "done" until all of that has happened, and a partial result
counts as a failed attempt.

This is what makes retiring the restart safe: the restart's whole value was that it did
these things in one indivisible sweep. The requirement moves to `ensure_link()`.

*Note:* the spec already warns that a port which opens but is not re-initialised is the
worst available outcome — health checks pass while no delivery reports and no inbound
notifications arrive. That warning now applies to every startup, not just to reopens.

### Retrying is unbounded, but backs off and is loud

The reopen budget stops being a deadline that ends in a restart, and becomes a retry
cadence that never gives up: frequent attempts at first, then a ceiling interval, so an
unplugged modem does not spin the CPU or fill the journal.

The gateway loses its self-healing exit, so the operator must learn about it another
way. Absence raises an alert once per episode — not per attempt — and the snapshot
already carries `link=`, `link_last_good=` and `link_reopens=` for the console.

*Alternative considered:* keep the restart after a much longer budget. Rejected: the
restart cannot help when the device is genuinely gone, and its only observable effect
in that case is to churn the supervisor's restart limits — the exact failure the spec
already describes, where "the gateway restarts, cannot open the port, exits, and repeats
until its supervisor stops trying altogether."

### A message is held before its attempt is claimed

`outbound-send` already holds a message when the modem is definitively off the network,
and does it *before* claiming an attempt so the message keeps its whole budget. No modem
at all is the same shape of fact, checked in the same place: hold, schedule a retry,
keep the deadline. The existing deadline is what stops holding from becoming forever.

The distinction matters for the reason the spec already gives: `_hold_after_claim`
exists for a link that dies *mid-send* and must give the claim back. A link that was
never there is cheaper — it is known before anything is claimed.

### The console reports the modem's absence in its shared layout

The state comes from the existing health snapshot, and the banner lives in the base
template so it appears on every page, not only on the diagnostics page. The banner is
rendered from the same snapshot the diagnostics page reads, so the two cannot disagree.

## Risks / Trade-offs

- **The restart's hidden work is lost.** → `ensure_link()` is specified as one
  operation that must include the URC subscription and the inbox reconciliation, and
  is tested against exactly that: a link established late must leave the gateway able
  to receive `+CDS` and `+CMTI`, not merely able to answer `AT`.

- **A silently dead gateway.** Today a modem that cannot be reached eventually restarts
  the process, which is at least visible in the journal. After this change the process
  sits there looking healthy. → The banner on every page, the alert on entering the
  absent state, and `link_last_good` in the snapshot exist for this. The gateway must
  never report itself healthy while it has no link.

- **Queue build-up.** Holding instead of failing means an outage accumulates messages
  that all fire when the modem returns. → Their existing pending deadline already
  bounds this, and messages that outlive it expire as they do now. Worth watching on
  the first long outage.

- **Loops running before there is a link.** Every loop now starts before the modem
  exists, so any of them that assumes an open port will fail on the first tick instead
  of never being started. → They wait on the recovery gate, which now starts closed;
  the gate opens only once `ensure_link()` has completed.

- **`deploy/` reasoning goes stale.** The unit's restart settings were chosen against a
  startup path that deliberately exited. → Revisit them in the same change rather than
  leaving a comment that no longer describes the code.

## Migration Plan

No schema change and no data migration. The change is behavioural and takes effect on
deploy.

Rollback is a redeploy of the previous version: nothing persisted changes shape, and a
message held as `pending` by the new code is an ordinary pending message to the old
code.

## Open Questions

- What the retry ceiling should be. It trades journal noise against how quickly a
  returning modem is noticed; a returning device is announced by the node reappearing,
  so the ceiling can be generous.
- Whether the absent-modem alert should repeat on a long outage, or fire once and stay
  quiet until the link returns.
