# outbound-send Specification

## Purpose

The path an outbound SMS travels: `POST /sms/send` → in-memory queue → the sender loop →
AT/PDU transport → the `messages` status a consuming app polls or receives by webhook.

`delivery-dispatch` owns *how* a status change reaches the owning app; this seam owns
*which* status a message ends up in and *when*.

**Adoption note.** Reverse-engineered from code on 2026-07-24 at `1c95cad` (`adopt-code`),
then promoted with the operator. Changes `add-send-retries`, `add-send-failure-recovery` and
`hold-sends-while-unregistered` archived into it the same day. Every requirement carries a status tag: only `normative`
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
app/admin/router.py:196-233 · conf: high · resolves U3]

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

A poll that could not be completed SHALL count as a failed poll rather than as no poll at
all. The watchdog acts on doubt, and an exception is a stronger form of doubt than a
negative answer; a poll whose failure is discarded leaves the ladder standing still for as
long as the fault lasts.

A remedy the gateway could not carry out SHALL be recorded as attempted and SHALL NOT stop
the ladder. Escalation must not depend on the modem cooperating with its own recovery: if
an unperformable remedy aborts the step, escalation halts at exactly the fault that most
needs it.

The ladder's rungs SHALL name escalation levels, and the remedy at each level SHALL be
chosen by the cause. Losing the link is a distinct cause from a failed registration, with
its own remedies — no rung of it issues AT commands, because none can reach the modem.

The number of failed observations required before acting SHALL belong to the cause. Three
consecutive polls exist to avoid reacting to one unlucky registration sample; a port that
cannot be written is not a sample, and waiting three minutes to act on it buys nothing. A
lost link SHALL be acted upon on the first observation.

[normative · evidence: app/modem/health.py:decide, app/modem/manager.py:_watchdog_step,
watchdog_loop, _recover · conf: high]

#### Scenario: Registration keeps failing
- **WHEN** three consecutive registration polls fail
- **THEN** a soft recovery runs before any hard reset is considered

#### Scenario: The registration poll raises instead of answering
- **WHEN** the poll cannot be completed at all
- **THEN** it counts as a failed poll and the ladder advances

#### Scenario: A recovery remedy cannot be carried out
- **WHEN** a remedy's AT commands cannot reach the modem
- **THEN** it counts as attempted and the ladder continues to its next level

#### Scenario: The link is lost rather than the registration
- **WHEN** the watchdog finds the link to the modem gone
- **THEN** it acts on the first observation, on the remedies belonging to a lost link, rather than spending the registration ladder on it

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

The record of whether message bytes reached the modem SHALL be carried by every failure
that can occur after they were written, however that failure is classified. This fact is
what the rule above is decided on, and a failure class that cannot carry it would report
a transmitted message as untransmitted — turning a rule that exists to prevent a duplicate
SMS into the thing that causes one.

A remedial action taken while a failure is on its way to the caller SHALL NOT replace it.
Restoring modem state after a failed send is best-effort, and if it fails in turn it would
substitute its own error for the original — discarding both the reason the send failed and
the record of whether the message was written.

[normative · evidence: app/db/queries.py:begin_message_attempt,
app/modem/at_commands.py:send_sms_pdu, app/modem/manager.py:_send_one · conf: high]

#### Scenario: The process dies mid-send
- **WHEN** the service is killed after a message's PDU was written and before its status was updated
- **THEN** the message is not re-queued after the restart, and is swept to `failed` once past its deadline

#### Scenario: The second part of a two-part message fails
- **WHEN** part 1 is accepted and part 2 fails with a timeout
- **THEN** the message becomes `failed` at once and no retry is scheduled

#### Scenario: The link is lost after the message was written
- **WHEN** the link to the modem is lost after a message's PDU and Ctrl-Z were written
- **THEN** the failure reports that the message was written, and the message is failed rather than retried

#### Scenario: Restoring modem state fails after a failed send
- **WHEN** the attempt to restore the modem's default mode itself fails against a lost link
- **THEN** the caller still receives the original failure, still carrying whether the message was written

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

A message SHALL be failed, and its owning app notified, once it has been `pending` longer
than the retry deadline — the sum of the configured backoff delays plus a margin for a
slow final attempt.

[normative · evidence: app/modem/manager.py:226-236, app/db/queries.py:184-203 · conf: high]

#### Scenario: A message outlives its budget
- **WHEN** a message has been `pending` for longer than the retry deadline
- **THEN** it becomes `failed` and its app receives one notification

### Requirement: An unexpected error does not stop the sender

The sender SHALL survive any error while sending a message, not only a failed AT
exchange: the message SHALL be failed, the error logged with a traceback, and the loop
SHALL continue. Whatever the outcome, the sender SHALL release its claim on the message.

Losing the link to the modem SHALL be the one exception to failing the message, and only
when no byte of that message has been written and no part of it has been accepted. Such a
message was never offered to the modem, so failing it would spend its whole retry budget at
zero attempts on a moment when transmission was impossible, and would tell the owning app
the message had finally failed.

In every other case — bytes written, or any part already accepted — the
never-transmitted-twice rule SHALL keep precedence and the message SHALL fail. A multipart
message whose first part was accepted SHALL NOT be held, because holding it schedules a
retry that would transmit that part a second time under the same concatenation reference.

[normative · evidence: app/modem/manager.py:sender_loop, _send_one · conf: high]

#### Scenario: The database errors mid-send
- **WHEN** recording a transmitted part raises a database error
- **THEN** the message is failed, the sender keeps running, and the message is no longer held

#### Scenario: The link is lost before the message is written
- **WHEN** the link to the modem is lost while a message is due and before any of its bytes are written
- **THEN** the message is held rather than failed, and no attempt is counted against it

#### Scenario: The link is lost after the PDU was written
- **WHEN** the link is lost after a message's PDU and Ctrl-Z were written
- **THEN** the message fails immediately, because the SMSC may already hold it

#### Scenario: The link is lost between the parts of a multipart message
- **WHEN** part 1 has been accepted and the link is lost before part 2 is written
- **THEN** the message fails immediately rather than being held, so part 1 is never transmitted twice

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

### Requirement: Repeated send failures are evidence the modem needs recovery

The gateway SHALL track the messages that have failed transiently since the last
successful send, and SHALL treat the modem as unhealthy when, with no send having
succeeded in between, either three *different* messages have failed transiently, or one
message has exhausted its entire retry budget on transient failures.

Attempts of a single message SHALL count once toward the three, however many it makes:
repeated failure against one destination is evidence about that destination. The
budget-exhaustion clause exists because this gateway carries around a dozen messages a
day, roughly two hours apart, so waiting for three distinct messages would take hours —
long enough to be no signal at all.

A failure counts when its error is not a permanent one, whether or not the message was
eligible for a retry — a timeout after the PDU was written is not retryable, but it is
still evidence about the modem. A permanent failure, a message rejected before any AT
command is issued, an internal error that never reached the modem, and a message failed
by the pending sweep SHALL neither count toward this nor clear it. A successful send
SHALL clear it.

An unhealthy modem in this sense SHALL make the watchdog's health check fail exactly as a
failed registration poll does, so that recovery escalates on the existing ladder — soft
recovery, then a hard reset gated to once per thirty minutes, then the service exit. No
separate recovery path SHALL be introduced.

The ladder's progress SHALL belong to the problem that earned it: when the reason the
modem is unhealthy changes between a failed registration and a send stall, the escalation
SHALL start again from the first rung. Otherwise a soft recovery performed for a
registration outage would let the next stall open with a hard reset and a service restart.

Because recovery consumes the evidence, a single stall SHALL escalate no further than one
soft recovery; reaching a hard reset SHALL require messages to fail again afterwards.

The gateway SHALL provide a setting that disables this coupling on its own, leaving
recovery driven by registration alone. A mechanism able to restart the service needs a
switch that does not also give up the rest of the watchdog.

Performing a recovery SHALL discard the tracked evidence, so escalating further requires
messages to fail again. Without this a stall declared on a quiet gateway would survive
untouched — there being nothing to send that could clear it — and drive the ladder to a
service restart on evidence already acted upon.

When the watchdog is disabled this SHALL have no effect, and the tracked evidence SHALL be
discarded.

#### Scenario: The modem answers but will not send
- **WHEN** three different messages fail transiently with no successful send between them, while every registration poll succeeds
- **THEN** the watchdog's next check fails and escalates on its own ladder

#### Scenario: One message uses up its whole ladder
- **WHEN** a single message fails transiently on all four of its attempts and no send succeeds in between
- **THEN** the modem is treated as unhealthy, because nothing has got out for the length of the budget

#### Scenario: A message fails its ladder but other sends succeed
- **WHEN** a message exhausts its attempts transiently but other messages send successfully in between
- **THEN** the modem is not treated as unhealthy — the evidence points at the destination

#### Scenario: A send succeeds between failures
- **WHEN** two messages fail transiently and the next message sends successfully
- **THEN** the evidence is discarded and no recovery is triggered

#### Scenario: The failures are permanent
- **WHEN** three different messages fail with `+CMS ERROR: 1 (unassigned number)`
- **THEN** the modem is not treated as unhealthy

#### Scenario: Nothing is sent after a recovery
- **WHEN** a stall triggers a soft recovery and no message is sent for the next hour
- **THEN** no further recovery is triggered, because the evidence was consumed

#### Scenario: A stall follows a registration outage
- **WHEN** registration failures have already caused a soft recovery, registration returns, and the sends that failed meanwhile declare a stall
- **THEN** the stall begins its own escalation rather than proceeding straight to a hard reset

#### Scenario: The coupling is switched off
- **WHEN** the stall-recovery setting is disabled and messages fail transiently
- **THEN** the health check depends on registration alone

#### Scenario: The watchdog is disabled
- **WHEN** `modem_watchdog_enabled` is false and three different messages fail transiently
- **THEN** no recovery is attempted and the evidence is discarded

### Requirement: Sending is suspended while the modem is being recovered

The gateway SHALL NOT begin transmitting a message, nor read an inbound message from the
modem, while recovery is in progress, and SHALL resume when it completes. An inbound read
issued against a switched-off radio fails and its notification is discarded, leaving the
message unread until the next restart.

Recovery SHALL NOT be considered complete when its commands return: reselecting an
operator is a request, not a completed attach. The gateway SHALL wait for the modem to
report registration, up to a bound, before resuming — sending during the reattach
produces exactly the failures the recovery was meant to stop, which would re-arm the
stall that triggered it.

A recovery that restores the modem SHALL also restore the subscription that delivers
`+CDS` and `+CMTI`. Losing it is silent and total: every message would expire and every
inbound SMS would be missed, with no health check able to notice.

A message held back this way SHALL NOT have an attempt counted against it, because it was
never offered to the modem — a recovery window SHALL cost a message time, never chances.

Recovery itself SHALL be bounded, so the suspension has a stated ceiling rather than an
open-ended one — it must first take the serial port, which a long multipart send can hold
for minutes. The sender's own wait SHALL be bounded by more than that ceiling: releasing
it during a legitimate recovery is worse than not suspending at all, because the wait was
spent as well. A gateway that tries and fails can be diagnosed; one that
silently stops trying cannot. That timeout SHALL exceed the longest legitimate closure —
a hard reset and its settling period — so the bound never releases a send into a modem
that is still rebooting.

Sending SHALL be resumed even if recovery fails, so a raised exception cannot leave the
gateway permanently unable to send.

#### Scenario: Recovery runs while messages are queued
- **WHEN** soft recovery is cycling the radio and a message is due
- **THEN** the message is not transmitted until recovery finishes, and its attempt count is unchanged

#### Scenario: The modem has not come back yet
- **WHEN** the recovery commands have returned but the modem does not yet report registration
- **THEN** sending stays suspended until it does, or until the bound elapses

#### Scenario: An inbound notification arrives during recovery
- **WHEN** an inbound message is announced while the radio is being cycled
- **THEN** it is read after recovery rather than lost

#### Scenario: Recovery raises
- **WHEN** a recovery operation raises an exception
- **THEN** sending is resumed rather than left suspended

#### Scenario: Recovery never finishes
- **WHEN** the recovery gate stays closed beyond the sender's timeout
- **THEN** the sender attempts the message rather than holding it indefinitely

### Requirement: A message is not transmitted while the modem is known to be off the network

Before transmitting, the gateway SHALL determine whether the modem is currently
registered, and SHALL hold the message back when the answer is a definitive negative.

The determination SHALL be made at send time rather than taken from the watchdog's
periodic sample: refusing to send is a decision that must not rest on information that
may be a minute old.

A held message SHALL NOT have an attempt counted against it, and SHALL be rescheduled to
be tried again shortly. Holding costs a message time, never chances — spending its retry
budget on a period when delivery was impossible would leave it finally failed having
never been transmitted at all.

A check that cannot be completed — an AT error, a timeout, an unparseable reply — SHALL
NOT hold the message. Not knowing is not a refusal, and a gateway that stops sending
whenever it cannot ask a question is worse than one that tries and reports a real failure.

A lost link SHALL NOT be read as "not knowing". It is not a question the modem failed to
answer but the absence of anything to ask, and it SHALL hold the message on the same terms
as a definitive negative. Transmitting into a port that no longer exists cannot succeed, so
the reasoning that favours trying over refusing does not apply to it.

Holding SHALL leave the message schedulable. An attempt is recorded and the message's
schedule cleared before any byte is written, and a message left with no schedule is never
re-queued by design — so a decision to hold taken after that point SHALL restore both the
attempt count and the schedule, or SHALL be taken before either is disturbed. A held
message that is neither counted nor scheduled is invisible to the scheduler and reaches its
deadline having never been offered to the modem again, which is the outcome holding exists
to prevent.

Holding SHALL remain bounded by the existing pending deadline, so a message the gateway
declines to attempt still reaches a terminal status and its application is still told.
This bound SHALL apply to a message held for a lost link exactly as it does to one held
for an unregistered modem.

[normative · evidence: app/modem/manager.py:_hold_while_unregistered,
app/db/queries.py:begin_message_attempt, app/modem/at_commands.py:registration_state · conf: high]

#### Scenario: The modem is off the network
- **WHEN** a message is due and the modem reports it is not registered
- **THEN** the message stays `pending` with its attempt count unchanged, and is tried again shortly

#### Scenario: The network comes back
- **WHEN** a message was held and the modem is registered on the next try
- **THEN** it is transmitted normally

#### Scenario: The registration check fails with an AT error
- **WHEN** the registration query times out or returns an unparseable reply while the link is usable
- **THEN** the message is attempted rather than held

#### Scenario: The registration check finds no link at all
- **WHEN** the registration query fails because the link to the modem is gone
- **THEN** the message is held with its attempt count unchanged, rather than attempted

#### Scenario: A held message remains due
- **WHEN** a message is held after its attempt was recorded and its schedule cleared
- **THEN** it is left with an attempt count and a schedule that bring it back to the sender, not stranded until its deadline

#### Scenario: The outage outlives the message
- **WHEN** the modem stays unregistered until the message is past its deadline
- **THEN** the message becomes `failed` and its application is notified, rather than being held indefinitely

#### Scenario: The link stays lost until the message expires
- **WHEN** the link cannot be restored before the held message passes its deadline
- **THEN** the message becomes `failed` and its application is notified

#### Scenario: A multipart send during an outage
- **WHEN** a two-part message is due while the modem is not registered
- **THEN** no part is transmitted, so the message cannot end up with one part delivered and no way to retry

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
