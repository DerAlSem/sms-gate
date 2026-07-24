# outbound-send Specification

## Purpose

The path an outbound SMS travels: `POST /sms/send` → in-memory queue → the sender loop →
AT/PDU transport → the `messages` status a consuming app polls or receives by webhook.

`delivery-dispatch` owns *how* a status change reaches the owning app; this seam owns
*which* status a message ends up in and *when*.

**Adoption note.** Reverse-engineered from code on 2026-07-24 at `1c95cad` (`adopt-code`),
then promoted with the operator. Every requirement carries a status tag: only `normative`
is binding and swept. `descriptive` records what the code does today without endorsing it;
`unbacked` marks an accepted gap with no code behind it yet.

## Requirements

### Requirement: A send request is accepted synchronously and queued

`POST /sms/send` SHALL reject a blacklisted destination with HTTP 422 and body
`{"error": "number_blacklisted", "phone": <phone>}` without persisting a message.

Otherwise it SHALL persist the message in status `pending`, return its id immediately,
and hand it to the modem queue for asynchronous sending. Acceptance SHALL NOT wait for
the modem.

[normative · evidence: app/api/router.py:15-30, app/db/queries.py:32-41 · conf: high]

#### Scenario: A send is accepted
- **WHEN** an app POSTs a send for a number that is not blacklisted
- **THEN** the response is `{"id": <id>, "status": "pending"}` before the modem is touched

#### Scenario: A send targets a blacklisted number
- **WHEN** an app POSTs a send for a blacklisted number
- **THEN** the response is HTTP 422 with `error: number_blacklisted` and no message row is created

### Requirement: A message too long for the configured part budget is rejected without touching the modem

The sender SHALL encode the text to SMS-SUBMIT PDUs and, when the result needs more parts
than the `max_sms_parts` setting, SHALL mark the message `failed` with an error naming
both counts, notify the owning app, and raise an operator alert — without issuing any AT
command.

[normative · evidence: app/modem/manager.py:109-121 · conf: high]

#### Scenario: A message exceeds the part budget
- **WHEN** a text encodes to 5 parts and `max_sms_parts` is 4
- **THEN** the message is `failed` with `message too long: 5 parts > max 4` and no `AT+CMGS` is sent

### Requirement: A message becomes `sent` when its first part is accepted by the modem

Parts SHALL be transmitted sequentially within one serial session. Each part's `+CMGS`
reference SHALL be recorded before the next part is transmitted, and the message SHALL
move to `sent` on the first part's reference.

[normative · evidence: app/modem/manager.py:123-132, app/modem/at_commands.py:145-180 · conf: high]

#### Scenario: A two-part message is transmitted
- **WHEN** part 1 of a two-part message receives `+CMGS: 10`
- **THEN** the message is `sent` and part 1 is recorded before part 2 is transmitted

### Requirement: A message identity survives every automatic delivery attempt

The id returned by `POST /sms/send` SHALL identify one delivery intent for its whole
life. Automatic re-attempts SHALL reuse that id and SHALL NOT create additional rows —
an app that polls `GET /sms/{id}` or receives a webhook always looks at the same message.

Creating a new message linked by `resent_from` SHALL remain reserved for the operator's
explicit admin resend, which is a decision taken *after* a message has finally failed.

[normative · evidence: app/admin/router.py:73-105, app/api/router.py:33-41 · conf: high
· resolves U3]

#### Scenario: An automatic attempt follows a transient failure
- **WHEN** the gateway re-attempts a message after a transient failure
- **THEN** `GET /sms/{id}` for the original id reflects the outcome and no new row exists

### Requirement: A failed read leaves the port usable for the next command

A read that ends without its expected terminator SHALL drain the port until it goes quiet
before raising, so a late reply is never handed to the next command.

A send that fails SHALL cancel any pending `> ` prompt with ESC before issuing further
commands, because a modem left at the prompt consumes subsequent writes as message text.

Restoring the text-mode default after a send SHALL be best-effort and SHALL NOT replace
the error that caused the send to fail.

[normative · evidence: app/modem/at_commands.py:60-113, 124-180 · conf: high]

#### Scenario: A reply arrives after its read gave up
- **WHEN** `AT+CSQ` times out and its reply lands afterwards
- **THEN** the next command reads its own reply, not the stale one

#### Scenario: A send times out at the prompt
- **WHEN** the modem never emits `> ` after `AT+CMGS`
- **THEN** ESC is written before the mode restore, and the caller sees the original timeout error

### Requirement: A message is `delivered` only when every part is reported delivered

On a positive `+CDS` the part SHALL be marked delivered, and the message SHALL move to
`delivered` only once no part is outstanding. On a negative `+CDS` the message SHALL move
to `failed` carrying the decoded TP-status, and a permanent status SHALL count toward the
destination's blacklist threshold.

[normative · evidence: app/modem/manager.py:177-215 · conf: high]

#### Scenario: One part of two is reported delivered
- **WHEN** part 1 is reported delivered and part 2 is outstanding
- **THEN** the message stays `sent`

### Requirement: A `sent` message with no delivery report expires

A sweep SHALL run every 60 seconds and move every message that has been `sent` longer
than `delivery_timeout_seconds` to `expired`, notifying the owning app per message. The
timeout SHALL be re-read each sweep so a settings change applies without a restart.

[normative · evidence: app/modem/manager.py:371-382, app/db/queries.py:310-324 · conf: high]

#### Scenario: No report arrives in time
- **WHEN** a message has been `sent` for longer than the configured timeout
- **THEN** it becomes `expired` and its app is notified once

### Requirement: The modem recovery ladder escalates and is rate-limited

The watchdog SHALL poll registration every 60 seconds, SHALL soft-recover
(`CFUN=4→1`, `COPS=0`) after 3 consecutive failures, and SHALL escalate to a hard reset
plus service exit, gated to at most one hard reset per 30 minutes.

[normative · evidence: app/modem/manager.py:303-345 · conf: high]

#### Scenario: Registration keeps failing
- **WHEN** three consecutive registration polls fail
- **THEN** a soft recovery runs before any hard reset is considered

### Requirement: A message gets exactly one transmission attempt

On the first AT failure the sender marks the message `failed` with the modem's error
text, does not transmit the remaining parts, notifies the owning app, and raises an
operator alert deduplicated on the error text. The message is not re-queued.

[descriptive · evidence: app/modem/manager.py:133-144 · conf: high
· superseded-by change `add-send-retries` — recorded to make the replacement auditable,
never promoted]

### Requirement: Send outcomes do not influence modem recovery

A failing send neither advances nor resets the watchdog's counters, so a modem that
answers `AT+CEREG?` while refusing to send is never recovered.

[descriptive · evidence: app/modem/manager.py:133-144, 303-345 · conf: high
· superseded-by change `add-send-retries`]

## Known gaps

Accepted as real, with no code behind them yet.

### Requirement: Queued messages survive a restart

A message accepted as `pending` SHALL be transmitted after a service restart.

[unbacked · absent? · promoted 2026-07-24 · rationale: the queue is `asyncio.Queue`
in-memory only (app/modem/manager.py:87); a restart between acceptance and transmission
strands the message in `pending` forever, and the expiry sweep only covers `sent`]

## Resolved intent

- **U1 — When may `failed` reach the app?** Resolved 2026-07-24: only once the retry
  budget is exhausted. Retries are transparent to consumers and `delivery-dispatch` keeps
  its current status vocabulary. Motivation: GM+ reacts to `failed` by SMS-ing an operator
  (prod id 977), and a transient failure must not trigger that.
- **U2 — What is the retry budget?** Resolved 2026-07-24: at most 4 attempts, backing off
  to roughly 8 minutes total, so the observed ~3-minute deregistration window is covered
  with margin while a payment link is still fresh.
- **U3 — Does a retry keep the message id?** Resolved 2026-07-24: yes — see the message
  identity requirement above.
