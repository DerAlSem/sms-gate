# outbound-send Specification

## Purpose

The path an outbound SMS travels: `POST /sms/send` → in-memory queue → the sender loop →
AT/PDU transport → the `messages` status a consuming app polls or receives by webhook.

`delivery-dispatch` owns *how* a status change reaches the owning app; this seam owns
*which* status a message ends up in and *when*.

**Adoption note.** Reverse-engineered from code on 2026-07-24 at `1c95cad` (`adopt-code`),
then promoted with the operator. Change `add-send-retries` archived into it the same day. Every requirement carries a status tag: only `normative`
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

[normative · evidence: app/modem/manager.py:139-171, app/db/queries.py:108-152,
app/admin/router.py:73-105 · conf: high · resolves U3]

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

### Requirement: A send failure is classified by phase before it is classified by text

The gateway SHALL treat a failure as un-retryable whenever message bytes had already
been written to the modem when it occurred, regardless of the error text. The failing
exchange SHALL carry that fact to the caller; the caller SHALL NOT infer it from the
error text, which is identical either side of the write.

Among failures that occurred before any message byte was written, a failure SHALL be
permanent when retrying it cannot change the outcome: a message over the `max_sms_parts`
budget; `+CMS` 1, 21, 28, 50, 69 or 96; `+CMS` 301-305, 321 or 330; `+CMS` 310, 311 or
313 and the `+CME` codes for the same conditions, 10, 11 and 13.

Every other pre-transmission failure SHALL be treated as transient, and an unrecognised
failure SHALL default to transient.

This classification SHALL be independent of the TP-status classification applied to
delivery reports.

[normative · evidence: app/modem/errors.py, app/modem/at_commands.py:14-26, 158-183 · conf: high]

#### Scenario: The modem goes silent after the PDU was written
- **WHEN** a send fails with `no response from modem (timeout)` after the PDU and its Ctrl-Z were written
- **THEN** the failure is un-retryable, because the SMSC may hold the message

#### Scenario: An unlisted code arrives
- **WHEN** a pre-transmission send fails with a `+CMS` code that is in no classification list
- **THEN** the failure is transient

### Requirement: Transient send failures are retried before the message is failed

A transient failure on a message that has not been transmitted SHALL schedule another
attempt instead of failing the message. The message SHALL stay `pending`, SHALL keep its
id, and SHALL NOT produce a `failed` webhook for that attempt.

The number of attempts SHALL be one more than the number of delays configured in
`send_retry_backoff`, and the n-th retry SHALL be scheduled for the n-th delay after the
failure. An empty `send_retry_backoff` SHALL disable retrying. The setting SHALL be
re-read per use so a change applies without a restart.

A message SHALL become `failed` — notifying the owning app and alerting the operator,
naming the last error and how many attempts it took — when the failure is not retryable
or the attempts are exhausted.

[normative · evidence: app/modem/manager.py:173-215, app/settings_store.py · conf: high]

#### Scenario: A transient failure with budget left
- **WHEN** the first attempt fails with a prompt timeout and `send_retry_backoff` is `30,120,300`
- **THEN** the message stays `pending`, no `failed` webhook is emitted, and another attempt is scheduled 30 seconds later

#### Scenario: The budget is exhausted
- **WHEN** the fourth attempt fails and `send_retry_backoff` is `30,120,300`
- **THEN** the message becomes `failed`, its app is notified once, and the alert names four attempts

### Requirement: A message is never transmitted twice

An attempt SHALL be recorded, and the message's schedule cleared, before any byte of it
is written to the modem. A message with no schedule SHALL NOT be re-queued.

Consequently a message whose attempt did not conclude — because the process was killed,
the modem was hard-reset, or the code raised between transmission and the status write —
SHALL never be automatically re-attempted. Recovering such a message SHALL require an
operator.

Independently, once any part of a message has been accepted by the modem, a later failure
SHALL fail the message immediately whatever its classification, because re-sending would
deliver an already-transmitted part a second time and reuse its concatenation reference.

[normative · evidence: app/db/queries.py:108-130, app/modem/manager.py:150-171 · conf: high]

#### Scenario: The process dies mid-send
- **WHEN** the service is killed after a message's PDU was written and before its status was updated
- **THEN** the message is not re-queued after the restart, and is swept to `failed` once past its deadline

#### Scenario: The second part of a two-part message fails
- **WHEN** part 1 is accepted and part 2 fails with a timeout
- **THEN** the message becomes `failed` at once and no retry is scheduled

### Requirement: Retries are scheduled and never block other messages

A message awaiting a retry SHALL leave the send queue.

A scheduler SHALL re-queue messages whose scheduled time has passed, and SHALL NOT
re-queue a message the sender already holds queued or in flight, nor one whose
destination has been blacklisted since acceptance — such a message SHALL be failed.

Each scheduler pass SHALL be bounded in batch size and SHALL NOT re-queue a message older
than the retry deadline. A pass that raises SHALL be logged and SHALL NOT stop the
scheduler.

[normative · evidence: app/modem/manager.py:217-250, app/db/queries.py:155-203 · conf: high]

#### Scenario: The destination is blacklisted mid-ladder
- **WHEN** a message is due for a retry and its number has been blacklisted since acceptance
- **THEN** the message is failed rather than re-queued

#### Scenario: A scheduler pass fails
- **WHEN** a scheduler pass raises a database error
- **THEN** the failure is logged and the next pass still runs

### Requirement: A message may not stay `pending` indefinitely

A message `pending` longer than the retry deadline — the sum of the configured backoff
delays plus a margin for a slow final attempt — SHALL be failed and its owning app
notified.

[normative · evidence: app/modem/manager.py:226-236, app/db/queries.py:184-203 · conf: high]

#### Scenario: A message outlives its budget
- **WHEN** a message has been `pending` for longer than the retry deadline
- **THEN** it becomes `failed` and its app receives one notification

### Requirement: An unexpected error does not stop the sender

The sender SHALL survive any error while sending a message, not only a failed AT
exchange: the message SHALL be failed, the error logged with a traceback, and the loop
SHALL continue. Whatever the outcome, the sender SHALL release its claim on the message.

[normative · evidence: app/modem/manager.py:117-137 · conf: high]

#### Scenario: The database errors mid-send
- **WHEN** recording a transmitted part raises a database error
- **THEN** the message is failed, the sender keeps running, and the message is no longer held

### Requirement: A message still on its way does not report an error

While a message is `pending`, the reason its last attempt failed SHALL be recorded
separately from the `error` field a consuming application reads. `error` SHALL continue
to mean "why this message finally failed".

[normative · evidence: app/db/queries.py:133-152 · conf: high]

#### Scenario: An app polls a message between attempts
- **WHEN** an app reads a message whose first attempt failed and whose retry is scheduled
- **THEN** its status is `pending` and its `error` is null

### Requirement: Queued messages survive a restart

A message accepted as `pending` and never transmitted SHALL be transmitted after a
service restart, subject to the retry deadline and to the never-transmitted-twice
requirement above.

[normative · evidence: app/db/queries.py:32-47, app/modem/manager.py:238-250 · conf: high]

#### Scenario: The service restarts before transmission
- **WHEN** a message is accepted and the service restarts before it is handed to the modem
- **THEN** the message is transmitted after the restart rather than staying `pending` forever

### Requirement: Send outcomes do not influence modem recovery

A failing send neither advances nor resets the watchdog's counters, so a modem that
answers `AT+CEREG?` while refusing to send is never recovered.

[descriptive · evidence: app/modem/manager.py:303-345 · conf: high
· known gap — the coupling was designed under `add-send-retries` and deliberately
carved out: as specified it either never escalated or looped through a service exit
every 30 minutes. Needs sending quiesced across recovery and a counter over distinct
messages.]

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
