# Changelog

All notable changes to this project are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- **Messages were reported as failures while arriving whole.** The gateway called a
  multipart message delivered only once every part had been reported, and one network on
  this SIM reports the final segment and no more. Those messages never completed, sat until
  the timeout, and were swept to `expired` — a status the owning application was then told
  over the webhook. Twenty-two of them in the existing record: twenty-two deliveries
  reported as failures.
  On that operator, single-part messages were 180 delivered and 0 expired while two-part
  messages were 1 delivered and 21 expired; every other operator was unremarkable. Four test
  messages to a consenting recipient reproduced it exactly, and the recipient confirmed all
  four arrived.
  At the timeout — and only there — a message with at least one part confirmed and none
  failed is now completed as `delivered` rather than expired. Until the timeout fires there
  is no evidence the remaining reports are not coming, so the ordinary path is untouched. A
  message with nothing confirmed still expires: silence about everything is absence of
  evidence, and inventing a delivery from it would trade a wrong `expired` for a wrong
  `delivered`.
  The conclusion is recorded as one. A delivery the gateway worked out is distinguishable
  from a delivery the network reported, because the first question on a complaint is which
  of the two you are reading.

## [0.14.0] - 2026-07-30

The gateway stops depending on which uplink is alive.

### Added
- **Reachable over whichever uplink is carrying traffic.** The backup uplink is an LTE modem
  behind carrier-grade NAT: no address to resolve to, no port that can be opened. So a wired
  outage took the gateway with it — modem, SIM and service healthy, and nobody able to reach
  them, or to log in and see why. A permanent tunnel dialled *outward* to a machine with a
  static address is the only shape that survives, because its return traffic rides a
  connection the carrier already permitted.
- **The tunnel is up at all times, not raised on failure.** A path used only during an outage
  is first tested by the outage — the same class of fault as a loop that dies in silence or a
  data session reporting `connected` while carrying nothing, both of which this project has
  already paid for. Always-on means a failover changes no DNS record at all, so there is no
  propagation window in either direction and no state machine to get right twice.
  **Measured across a failover: no interrupted request at five-second resolution, in either
  direction.** The session outlives the address change, so there is no handshake to redo.
- **The tunnel joins two endpoints, not two networks.** A tunnel is a route by default, and
  the constraint that matters is not the one most guides supply: `AllowedIPs` limits routing,
  not access, so everything bound to `0.0.0.0` still answers on the address the tunnel adds.
  Closed with a filter on the interface — including a `forward` chain, without which
  container ports reached by NAT stay open while the check appears to pass.
- `deploy/wg-watchdog/` — asks whether the tunnel is **carrying**, not whether its unit is
  active. WireGuard has no connection to lose: with the interface deleted, `systemctl
  is-active` still answers `active`. Verified live.
- `deploy/reachability/` — asks from outside whether the public hostname answers, and requires
  a marker only the application emits. A front end returns its own error page when it cannot
  reach the origin, and a name that answers with somebody else's error is a name that answers.
  Also warns before the certificate expires.
- `deploy/nginx/` — both server blocks and the alert relay, with placeholder values. They had
  existed only on the machines, which is how three separate changes came to be committed,
  deployed and inert at the same time.
- Administrative access survives the loss of the primary uplink, over the same tunnel, keys
  only — the far end hosts other public applications, and a compromise of any of them would
  otherwise become a brute-force attempt over a channel nobody watches.

### Fixed
- **Alerts get out during the outage they describe.** The mobile carrier cannot reach
  Telegram, so every alert raised while the backup uplink carries was lost. Observed: the
  failover alert never arrived and the restore alert, eight minutes later, did — being told an
  outage ended and never that it began. The gateway now sends through a relay at the far end,
  over the tunnel, which works on either uplink. Tried **first**, so it is the route ordinary
  traffic exercises; the direct route is the fallback and covers the relay being down.
- **An alert that no route could carry is held and delivered later**, bounded, and stamped
  with its age — a late alert read without one is read as current, and sends an operator after
  a fault that has already ended.
- **A rejected Telegram token no longer loses every alert in silence.** A non-200 returned
  `None` from the sender, which the caller reads as delivered-without-an-id.

### Changed
- **BREAKING for deployment:** `deploy/sms-gate.service` binds uvicorn to the loopback and
  trusts the forwarding header from it. Requires `systemctl daemon-reload` **and** re-copying
  the unit — the installed unit is a copy, not a link, so a deploy alone leaves it untouched.
- **Requests are logged with the caller's own address** rather than the proxy's. Nothing
  recorded where a request came from, which was survivable while reaching the gateway meant
  being on this network — not with one public entrance and long-lived tokens behind it.
- `HOST` and `PORT` are documented as what they are: unused. The bind has always come from the
  unit file while the README promised they controlled it.
- Configuration files carry placeholder hostnames and addresses. The reasoning generalises;
  one installation's origin address does not.

### Notes
- **Not yet verified: the cold start.** Whether the tunnel comes up after a reboot, and in
  particular after a reboot while the wired link is already down, is the one path still owed a
  live test. It is the most likely real scenario and the only one where failure means the
  machine is unreachable until somebody stands in front of it.
- The direct path still serves the hostname by address. It is retired after a soak, so that
  rollback stays real while the new path is unproven.
- A delivery report arriving during an outage is still unrecoverable, as before.

## [0.13.0] - 2026-07-29

### Changed
- **A re-enumerating modem is now a pause, not a restart cycle.** The gentle rung for a
  lost link reopens the port in place — bounded attempts, each bounded in time as well —
  and the service restart stays as what an exhausted reopen earns. Reopening and
  initialising are one act under the serial lock, issued through a new `_init_unlocked`:
  `init()` goes through `command()`, which takes the same non-reentrant lock, so the naive
  version deadlocks — and wrapped in the recovery timeout that reads as "recovery took
  five minutes and achieved nothing".
- **The reopen budget is a deadline, and it is the wait the startup path already gives the
  same device.** Found in live verification: five attempts three seconds apart is twelve
  seconds, and a modem unbound from USB was still absent at twelve — so the gateway
  restarted over a device that was merely still coming back, which is the outcome this
  change exists to remove. `connect()` waits 60 s for that same node at startup, for that
  same reason; two answers to one question drift, and the smaller one governed the path
  where it mattered more. The budget is now `_DEVICE_WAIT` by identity, pinned by a test,
  with each attempt still bounded on its own.
- **Giving up on a lost link restarts at once, without the hard-reset settling period.**
  That 40-second wait exists so nothing touches a modem the gateway has just deliberately
  reset. A lost link is reached without issuing a single AT command, so there is nothing
  rebooting to wait for — and on prod 2026-07-29 the device came back five seconds after
  the reopen gave up, while the gateway spent the next forty seconds not looking. The
  settle now belongs to the remedy that needs it rather than to the rung.
- **A node that is absent and one that is not yet permitted count alike as "not back
  yet".** A recreated node carries its ownership only once udev has applied its rules, so
  the first attempts after a re-enumeration can fail on permission rather than absence.
- **Reopening is cancellation-safe.** Every exit path leaves the link either fully open and
  initialised or explicitly unusable. Recovery reopens the gate that suspends sending
  however the reopen ended, so a link left merely undefined is one the sender discovers
  one command timeout at a time.
- **A restored link is reconciled with the modem's stored messages.** Inbound SMS
  accumulate in modem memory during an outage and the `+CMTI` announcing them go with the
  link; the restart's startup scan is what used to drain them. Indexes queued before the
  outage are dropped rather than trusted — they describe what was announced, not what
  arrived while nothing was listening.
- **The unsolicited-result port is recovered by the same mechanism**, waiting on the
  recovery gate instead of growing a reopen loop of its own. Two bounded budgets, each able
  to end the service, is the worse failure — and a second reopener could race the settling
  period after a deliberate modem reset. It is reopened after the command port and without
  an init sequence: it has no writer, so the URC subscription is applied through the
  command port and takes effect for both.

### Fixed
- **Re-reading the modem's memory cannot deliver an inbound SMS twice.** A stored message
  is deleted only after it has been persisted, so an interruption between the two left it
  to be found again — latent while scanning happened once per restart, likely now that a
  restored link scans every time. Keyed on a hash of the PDU, not the modem index, which
  names a slot rather than a message.
- **A settings override in the test suite no longer leaks into every test after it.**
  `monkeypatch.setattr(store, ...)` on a `__getattr__`-served setting restores the value it
  read *through* `__getattr__`, pinning it as a real instance attribute for the rest of the
  session — so later tests silently ran against the wrong setting.

- **One operator alert per outage, sent once the outcome is known.** Found in live
  verification: the reopen sent three red alerts for a pause that healed itself in 14
  seconds, where the restart it replaces sent one — alerting *more* for a better outcome,
  which is how an operator learns to stop reading them. The steps on the way to a reopen
  are now WARNING; a single `link` notification reports the restored port with its reopen
  count and how long it took; the rungs that give up and restart the service stay at ERROR.
  Deduplicated per port, so a flapping modem yields one message per window carrying the
  count of the ones it stood in for.

### Added
- The diagnostics page reports the link itself: its state, when it was last known good, how
  often it has been reopened, and the state of the URC port. Until now it said what the
  gateway believed about the *modem* and nothing about the link underneath — during the
  incident the only external symptom was silence.

## [0.12.0] - 2026-07-29

### Fixed
- **A modem that disappears from USB no longer takes the gateway down with it.** On
  2026-07-29 at 01:28 the modem re-enumerated, every device node was recreated, and the
  gateway's file descriptors went stale. It stayed down for **5 hours 10 minutes** while
  reporting `active (running)`, until an operator restarted it by hand.
- **A lost link is now a named failure, distinct from a modem that answers badly.** The
  modem layer had exactly one word — `ATCommandError` — so `serial.SerialException` was
  caught nowhere: it escaped `registration_state()` and the watchdog step before the
  recovery ladder was consulted, and was swallowed 316 times. `ModemTransportError` is a
  **sibling**, not a subclass, because a subclass would be absorbed by
  `registration_state()`, which reports "could not tell" — and the send path reads that as
  permission to transmit.
- **A cleanly closed port counts as a lost link.** It raises nothing at all: reads return
  no bytes, immediately and for ever, so the reader spun to its deadline and reported an
  ordinary AT timeout — routing the fault back into handling that cannot fix it.
- **The ladder's rungs are escalation levels, and the remedy is chosen by cause.** Every
  rung is an AT command, so a missing port made every rung raise and abort the step that
  returns the level which ends the process. A lost link now acts on the first observation,
  spends no AT remedy, and its exit is not gated by the hard-reset cooldown — restarting
  is not a reset, so nothing is being hammered.
- **A message is held, not failed, when the link goes.** It used to be failed at zero
  attempts with a `failed` webhook — which the caller answers by SMS-ing an operator — bypassing
  the whole retry ladder. Holding is allowed only when no byte was written *and* no part
  was accepted; a multipart whose first part is at the SMSC still fails, because a retry
  would transmit it again under the same concatenation reference.
- **A device absent at startup is waited for.** A restart provoked by a lost link lands
  while the modem is still re-enumerating; treating that as fatal turned the remedy into
  an indefinite outage, since five failed starts stop the unit permanently. The 60s wait
  is paired with `RestartSec`, raised to 30s, so five failed starts span 450s and cannot
  exhaust the start limit. A fast crash still trips it in seconds.
- **A background loop can no longer die unnoticed.** `gather(..., return_exceptions=True)`
  returned each loop's exception and dropped it, which is how the URC reader — no `+CDS`,
  no `+CMTI` — died in total silence. Cancellation during shutdown is not treated as a
  death, and a deliberate exit delivers its own explanation before ending.
- Dropped and undeliverable notifications are counted and logged, instead of vanishing.

### Changed
- **BREAKING for deployment:** `deploy/sms-gate.service` changed (`RestartSec` 10 → 30).
  Requires `systemctl daemon-reload`; a plain restart will not pick it up.
- The hard-reset cooldown marker is no longer tracked in git. It is runtime state written
  by the running gateway, so a deploy would overwrite the server's own cooldown with
  whatever the repository happened to hold.
- **The backup uplink re-addresses its interface when a session outlives its netdev.** Same
  re-enumeration, seen from the other side: the QMI data session survived while `wwan0`
  was recreated without an address, so the channel looked connected and carried nothing.

## [0.11.1] - 2026-07-29

### Fixed
- **The backup uplink survives the modem being replaced underneath it.** A USB
  re-enumeration at 01:28 recreated every device node; the QMI proxy kept a descriptor to
  the device that no longer existed, and every request through it was accepted and then
  timed out. The channel stayed down for six hours.
- **A cold start now uses the modem's default profile, named by number.** With no session
  present, a start request carrying an explicit `apn=internet.tele2.ru,ip-type=4` was
  refused with `no-service` continuously, while the default profile succeeded on the first
  attempt — holding that identical APN and that identical IPv4 PDP type. The values were
  never in dispute; the form of the request was. The profile number is read from the modem
  rather than assumed, because `--wds-start-network` requires an argument: passing the flag
  bare is a parse error, and passing it bare in front of another flag is worse — that flag
  is swallowed as the value and the request silently becomes something nobody wrote. An
  explicit APN survives as an override.
- **One QMI client, acquired once and reused.** The id is only ever printed by a
  *successful* reply, so a script that learns its client from success alone acquires a
  fresh one on every failure and can never name what it leaked: 131 refused attempts
  consumed roughly 150 of the modem's finite pool until every WDS request timed out, and
  only rebooting the modem cleared it. The client is now allocated explicitly, up front.
- **A broken session no longer disables failover.** `cmd_up` exited the whole script on
  failure, so while QMI was down the primary uplink was never tested and its counters never
  advanced. The incident hid this because only one thing was broken at a time.
- **Retrying is bounded**, and slows rather than stops: a channel that gave up entirely
  could never notice it had recovered. Giving up alerts the operator and shows in `status`.
- **Access to the device is renewed on repeated timeouts, never on refusals.** A refusal is
  the network answering; reacting to it by restarting a process we do not own would turn an
  ordinary carrier outage into an escalation.
- The network interface is confirmed present before it is configured, as the control
  device already was.

### Added
- `tests/test_wwan_backup.sh` — 13 assertions against stubbed `qmicli`/`ip`/`ping`, which
  record what was asked so the tests can assert the *form* of each request, not just its
  result. The script's config is overridable from the environment so it can run in a
  sandbox; `/etc/default/wwan-backup` still wins over both.

## [0.11.0] - 2026-07-24

### Added
- **The gateway no longer transmits into a network it knows is missing.** Before sending,
  it asks the modem whether it is registered and holds the message back on a definite
  no — rescheduling it shortly, without counting an attempt, because a message never
  offered to the network should lose time rather than chances.
- The check is made **fresh, at send time**, inside the serial session the send needs
  anyway. An earlier sketch of this leaned on the watchdog's once-a-minute sample and was
  rejected: declining to send must not rest on minute-old information.
- A check that cannot be completed does not hold the message. `registration_state()`
  distinguishes "not registered" from "could not tell", where `registration_ok()` folds
  both into False — right for the watchdog, which acts on doubt, wrong here, since a
  gateway that stops sending whenever it cannot ask a question is worse than one that
  tries and reports a real failure.

### Notes
- **The measured value is small, and the change is scoped accordingly.** Registration was
  lost four times in thirty days, never long enough to reach even a soft recovery — about
  ten minutes of outage a month, most of which contain no message at all. This is worth
  single-digit messages a year.
- What makes it worth doing is *which* messages. Retries already recover a send that
  never reached the modem. The one class they cannot recover is a multipart whose first
  part was accepted before the network went away — and that failure is created by
  starting a send into a network about to refuse it. Prod message 976 was exactly this.
- Holding stays bounded by the existing pending deadline, so a message held through a
  long outage still reaches a terminal status and its application is still told. No new
  setting: the deadline and the backoff already bound it.

## [0.10.1] - 2026-07-24

### Changed
- **No behaviour change.** `ModemHealth` is extracted from `ModemManager`: the gateway's
  belief about the modem and the escalation ladder were one invariant spread across four
  methods written at different times, which is where this feature's sharpest bug came
  from — a single "have we tried the gentle thing" bit answering for two different
  problems, so a soft recovery performed for a lost registration let the next send stall
  open with a hard reset.
- Deciding is now free of I/O: `decide()` is a pure state transition over *is it
  registered*, *is it stalled* and *may we hard-reset*, returning the rung to act on.
  Performing the recovery, reading the cooldown marker and driving the serial port stay
  with the caller — so the ladder is asserted as a table of histories rather than only
  through a live modem.
- 17 tests added for rungs the previous shape could reach only indirectly, including the
  symmetric case that had no coverage at all: a registration outage must not inherit the
  ladder a send stall climbed.

Evidence this preserves behaviour: the existing suite passes with a single line changed,
and that line is a moved attribute's path — not a scenario and not an assertion.
384 → 401 tests.

## [0.10.0] - 2026-07-24

### Added
- **Repeated send failures now drive modem recovery.** Until now the watchdog judged the
  modem on one thing: whether `AT+CEREG?` reported registration. A modem that answers
  every command politely and refuses to send looked healthy while message after message
  failed. A *stall* — three different messages failing, or one exhausting its whole retry
  budget, with no successful send in between — now fails the health check and escalates
  on the existing ladder. Permanent failures are neutral: they describe the destination.
- `send_stall_recovery_enabled` switches the coupling off on its own. A mechanism that
  can restart the service needs a switch that does not also give up registration-driven
  recovery.
- The admin modem page reports what the gateway itself believes — whether a recovery is
  running, how many messages have failed since the last success, and why the modem is
  considered unhealthy. Taken mid-recovery, a diagnostics run otherwise shows an
  unregistered modem with no signal: a true reading of a radio the gateway switched off
  itself, and an easy one to misread as dead hardware.

### Fixed
- **The fourth retry could never run.** The pending deadline was `sum(backoff) + 120`,
  but between two scheduled attempts the clock also absorbs the failing attempt, one
  scheduler tick, and possibly a wait for the serial port behind a six-part send. With
  slow attempts the last one fell outside the deadline and the message was swept as
  `never transmitted` having used three of its four — a four-attempt budget that
  delivered three. Shipped in 0.9.0; the margin is now derived per attempt.
- **A soft recovery no longer risks silencing the modem.** `CFUN=4 → CFUN=1` is followed
  by re-issuing the `CNMI` subscription. If a firmware drops it, the gateway stops
  receiving `+CDS` and `+CMTI` — every message expires, every inbound SMS is missed, and
  no health check notices. This mattered more once recovery became frequent.
- The watchdog task is always started and consults its setting each tick, so toggling
  `modem_watchdog_enabled` takes effect without a restart.

### Safety
- **Recovery can no longer manufacture the failures it reacts to.** Sending and inbound
  reading are suspended while recovery runs, and resume only once the modem reports
  registration again — `AT+COPS=0` acknowledges a request to reselect, not a completed
  attach. A message held back this way consumes no attempt, so recovery costs it time
  rather than chances. Recovery is bounded, and the sender's backstop is derived from
  that bound.
- **The escalation ladder is per problem.** A soft recovery performed for a registration
  outage no longer lets the next stall skip straight to a hard reset and a service
  restart. Recovery also consumes the stall evidence, so reaching a hard reset requires
  messages to fail again — on a gateway with two hours between messages, an unconsumed
  stall would otherwise have driven a restart with nothing able to clear it.
- Escalation is logged with the cause under distinct templates, so Telegram's
  deduplication cannot hide a stall behind an earlier registration failure.

### Notes
- Two independent reviews rejected the first design of this coupling as either inert or
  self-amplifying; the findings and what was done about them are recorded in
  `openspec/changes/archive/2026-07-24-add-send-failure-recovery/`.
- Still deliberately out of scope: holding sends back while the modem is merely known to
  be unregistered, and a dedicated operator alert when a stall is declared.

## [0.9.0] - 2026-07-24

### Added
- **Automatic retry of transient send failures.** A message that never reached the modem
  — no response, a prompt timeout, `+CMS` 38/41/42/331/332/350/500, a bare `ERROR` — is
  re-attempted with growing delays instead of being failed on the first try. The delays
  live in the new `send_retry_backoff` setting (default `30,120,300`: four attempts
  inside about eight minutes), and their count fixes the attempt count. An empty value
  disables retrying and is the rollback switch.
- `failed` now means "the gateway stopped trying". The status, its `delivery-dispatch`
  webhook and the operator alert are emitted only once the budget is exhausted or the
  failure is not retryable, so a brief network blip no longer reads as a delivery
  failure to the consuming app. The message keeps its `id` throughout.
- `messages.attempts`, `messages.next_attempt_at` and `messages.last_attempt_error`
  (additive migration). `GET /sms/{id}` gains an additive `attempts` field, and the admin
  message list shows the attempt count and last error on a message still being retried.
- `pending` is swept for the first time: a message past the retry deadline is failed and
  its app notified, instead of sitting in `pending` forever.
- A message left `pending` by a restart is picked up and transmitted.

### Fixed
- **One AT timeout no longer desyncs every command after it.** A read that gave up left
  its reply in flight, so the next command read the previous command's answer and every
  reply after it was one out of phase; a timeout at the `> ` prompt additionally left the
  modem treating our next writes as message text. Failed reads now drain the port, the
  send path cancels a pending prompt with ESC, and the mode restore can no longer mask
  the real send error. Observed in production on 2026-07-24: id 976 timed out during a
  brief deregistration and id 977 then failed with `timeout waiting for '> ', got: 'OK'`
  — a reply belonging to an earlier command.
- The sender loop caught only `ATCommandError`, so an encoder or database error killed it
  permanently and in silence. It now fails the message, logs a traceback and keeps going.

### Safety
- **A message is never transmitted twice.** Three independent vetoes: a failure carrying
  `pdu_submitted` (the SMSC may hold a message whose confirmation never came back — six
  historical failures have this shape), a multipart whose first part was already
  accepted, and `next_attempt_at` cleared before transmission so an attempt cut short by
  a crash or a hard reset is never rescheduled. The scheduler is additionally bounded by
  message age and batch size, so no deploy can resurrect old traffic.

### Notes
- Coupling send failures to the modem watchdog was designed, reviewed and **deliberately
  left out**: as specified it either never escalated or produced a loop in which recovery
  switches the radio off, the interrupted sends feed the counter that triggered it, and
  the service exits every 30 minutes. It needs sending quiesced across recovery and a
  counter over distinct messages — its own change.
- The outbound send path now has a normative spec (`openspec/specs/outbound-send`),
  adopted from the existing code before it was changed.

## [0.8.1] - 2026-07-24

### Documentation
- Delivery dispatch shipped in 0.8.0 but only `docs/api.md` and
  `docs/delivery-webhook.md` described it — the rest of the docs still read as if the
  gateway only ever *received* webhooks and never sent them. Now covered in:
  - **README** (RU+EN) — a Features entry for outbound status webhooks (what the body
    carries, that routing is by `app_id`, that `GET /sms/{id}` stays authoritative), and
    Configuration names both `inbound_dispatch` and `delivery_dispatch`.
  - **`docs/architecture.md`** — the system diagram never showed the gateway calling out
    at all; adds that arrow plus a *Webhook Dispatch* component explaining why the two
    directions route differently (an inbound SMS carries no application identity, so it
    routes by prefix; an outbound message already knows its owner, so it routes by
    `app_id`).
  - **`docs/database.md`** — `messages.resent_from` was missing from the schema.
  - **`docs/project-structure.md`** — `delivery_dispatch.py` and `webhook.py` were absent,
    and the send/report flow did not mention the status push.

## [0.8.0] - 2026-07-24

### Added
- **Delivery dispatch** — the outbound counterpart of `inbound_dispatch`. When a message
  changes status (`sent`, `delivered`, `failed`, `expired`) the gateway POSTs
  `{id, status, error, occurred_at, resent_from?}` to the owning application's webhook,
  routed by `messages.app_id`. Configure routes under `delivery_dispatch` on
  `/admin/settings`; `pending` is never pushed (the API already returns it). Best-effort
  with the same retry ladder and `dispatch_error` alert as inbound — `GET /sms/{id}`
  stays authoritative, so a dropped notification self-heals on the next poll. Full
  receiving-side contract in [`docs/delivery-webhook.md`](docs/delivery-webhook.md).
- `messages.resent_from` (nullable) links an admin re-send to the message it replaces, so
  an application can attribute the outcome of a re-sent SMS to its original id.

### Changed
- Settings of type `json` are now typed `routes` with a `route_key`, shared by
  `inbound_dispatch` (`prefix`) and `delivery_dispatch` (`app_id`); the "Inbound
  dispatch" section is now "Dispatch". The webhook retry/timeout transport moved to a
  shared `app/modem/webhook.py`.
- `expire_stale_messages` returns the ids it expired, so the bulk sweep notifies each
  affected app instead of changing status silently.

## [0.7.0] - 2026-07-23

### Added
- **Alert on a failed inbound webhook.** A dispatch that never reached the receiving
  application was visible only as WARNING lines in `journalctl` — the SMS is stored and
  the modem is fine, so nothing raised the alarm. A `dispatch_error` notification now
  carries the prefix, url, phone, text and the reason for the last failure, deduplicated
  on the url so a dead endpoint alerts once per window rather than once per message.
  Toggle `notify_dispatch_errors`, default **on**. An SMS with no matching prefix stays
  silent — that is not a gateway fault.
- First `openspec/` change in the repo: `add-delivery-dispatch` specifies the outbound
  counterpart of `inbound_dispatch` (push message status to the owning app's webhook,
  routed by `messages.app_id`). Spec only — not implemented yet.

## [0.6.0] - 2026-07-23

### Added
- **Resend** button on failed/expired rows in the outbox. It queues a *new*
  message rather than reviving the old one: the failed attempt keeps its error as
  history, and delivery reports key off `modem_ref`, which a re-send changes anyway.

### Fixed
- **Inbound dispatch silently dropped messages when `webhook_url` held stray
  whitespace.** A leading space made httpx raise `UnsupportedProtocol` before the
  request left the box — three retry warnings in the log and nothing else. Routes
  are now validated on save (each entry must be an object with a non-empty `prefix`
  and an `http://`/`https://` `webhook_url`), stripped before storing, and stripped
  again on read so rows written earlier start routing without a manual edit.
- The dialogs list rendered last activity as raw UTC while every other page shows
  Moscow time; it now goes through the same `msk` filter.

### Changed
- Dropped the 160-char cap on the dialog reply form — an artificial GSM-7
  single-part limit. The sender already splits long texts into parts (UCS2 for
  Cyrillic) and the manager rejects anything over `max_sms_parts` with a clear error.

## [0.5.0] - 2026-06-20

### Added
- **Modem diagnostics** — `/admin/modem` (page, in the nav) and `/admin/modem.json`
  show live registration, signal, operator and SMSC (`CEREG/CREG/CGREG/CSQ/COPS/CSCA`
  plus Quectel `QNWINFO/QCSQ`), collected under the existing serial lock with an `AT`
  liveness short-circuit.
- **Modem registration watchdog** — a loop checks `AT+CEREG?` every 60 s and
  auto-recovers a modem that lost the network: soft recovery (`CFUN=4→1` + `COPS=0`)
  after 3 failures, escalating to a hard reset (`CFUN=1,1`) + service restart, gated to
  at most one hard reset per 30 min. Toggle `modem_watchdog_enabled` (default on).

### Changed
- `describe_at_error` now names `+CMS ERROR 350` and gives a generic
  "network/SMSC rejection" description for other unrecognised CMS 300-511 codes.

## [0.4.0] - 2026-06-16

### Added
- Reply-to-SMS over Telegram: reply to a notification post in the channel and the
  gateway sends that text back as an SMS to the number the notification was about.
  Uses long polling (`getUpdates`, CGNAT-friendly), a `notify_refs` message_id→phone
  map, and a `telegram_replies_enabled` toggle (default off; takes effect after
  restart). Replies are accepted only from the configured `alert_chat_id`.

## [0.3.2] - 2026-06-15

### Changed
- Delivery-failure status is now human-readable everywhere it surfaces
  (Telegram notification, `messages.error` / admin, blacklist `last_error`):
  e.g. `service rejected (temporary, st=99)` instead of a bare `st=99`.
  Decoded via the new `describe_tp_status` (GSM 03.40 TP-Status).

## [0.3.1] - 2026-06-14

### Changed
- Telegram notifications are now HTML-formatted: a bold title line
  (`📨 Inbound` / `🔴 Send failed` / `🚫 Delivery failed`) and a clean
  `+phone: text` body, removing the previous doubled event type. Sent with
  `parse_mode=HTML`; all dynamic fields are escaped and truncated before
  wrapping so the markup is always well-formed.

### Added
- `instance_name` setting (section "Alerting", blank = server hostname) — the
  label shown in notifications, e.g. `gateway.example.com`.

## [0.3.0] - 2026-06-14

### Added
- Per-type Telegram notifications, each toggled in the admin UI (section
  "Alerting"): system errors (default on), send failures, delivery
  failures / blacklist, and inbound SMS (the last three default off).
- `notify(event_type, text, dedup_extra=None)` for typed event notifications,
  sharing the Telegram delivery machinery with the log handler.

### Changed
- Refactored alerting: delivery (bounded queue + daemon worker + windowed
  dedup + truncation) extracted into a reusable `TelegramNotifier`;
  `TelegramAlertHandler` is now a thin ERROR-level adapter over it.
- Send-failure logs downgraded ERROR→WARNING so they no longer also fire the
  system-error alert (the typed `send_error` notification covers them).

## [0.2.0] - 2026-06-14

### Added
- Outbound Cyrillic and Unicode SMS via PDU-mode sending, with automatic
  GSM 7-bit / UCS2 encoding (`app/modem/pdu_encode.py`, `app/modem/gsm7.py`).
- Multipart (UDH-concatenated) outbound SMS, reassembled into one message on
  the recipient's handset.
- Per-part delivery tracking via the new `message_parts` table; a message is
  marked `delivered` only when every part's `+CDS` report arrives.
- `max_sms_parts` setting (default 6) capping multipart length.

### Changed
- Outbound send path moved from AT text mode to PDU mode (`send_sms_pdu`).
- API `text` field limit raised from 160 to 1000 characters.
- `+CMS`/`+CME` errors are now surfaced as clean, human-readable messages
  instead of raw byte dumps, and no longer block for the full send timeout.
- Admin UI gained a favicon.

## [0.1.0]

- Initial release: HTTP SMS API, delivery tracking, inbound PDU decoding with
  multipart reassembly, admin UI, operator/region lookup, auto-blacklist.
