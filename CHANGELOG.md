# Changelog

All notable changes to this project are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

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
  label shown in notifications, e.g. `sms.deralsem.ru`.

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
