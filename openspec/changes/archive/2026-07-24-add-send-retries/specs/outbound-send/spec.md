## ADDED Requirements

### Requirement: A send failure is classified by phase before it is classified by text

The gateway SHALL treat a failure as un-retryable whenever message bytes had already
been written to the modem when it occurred, regardless of the error text. The failing
exchange SHALL carry that fact to the caller; the caller SHALL NOT infer it from the
error text, which is identical either side of the write.

Among failures that occurred before any message byte was written, a failure SHALL be
permanent when retrying it cannot change the outcome: a message over the `max_sms_parts`
budget; `+CMS` 1, 21, 28, 50, 69 or 96 (the network refuses this message or this
destination); `+CMS` 301–305, 321 or 330 (a malformed or misconfigured request that will
fail identically); `+CMS` 310, 311 or 313, and the `+CME` codes for the same conditions,
10, 11 and 13 (the SIM is absent, locked or failed).

Every other pre-transmission failure — no response, a prompt timeout, `+CMS` 38, 41, 42,
331, 332, 350 or 500, a bare `ERROR`, an unrecognised or unparseable reply — SHALL be
treated as transient. An unrecognised failure SHALL default to transient.

This classification SHALL be independent of the TP-status classification applied to
delivery reports.

#### Scenario: The modem goes silent while waiting for the prompt
- **WHEN** a send fails with `no response from modem (timeout)` before the `> ` prompt
- **THEN** the failure is transient

#### Scenario: The modem goes silent after the PDU was written
- **WHEN** a send fails with `no response from modem (timeout)` after the PDU and its Ctrl-Z were written
- **THEN** the failure is un-retryable, because the SMSC may hold the message

#### Scenario: The network refuses the destination
- **WHEN** a send fails with `+CMS ERROR: 1 (unassigned number)`
- **THEN** the failure is permanent

#### Scenario: An unlisted code arrives
- **WHEN** a pre-transmission send fails with a `+CMS` code that is in no classification list
- **THEN** the failure is transient

### Requirement: Transient send failures are retried before the message is failed

A transient failure on a message that has not been transmitted SHALL schedule another
attempt instead of failing the message. The message SHALL stay `pending`, SHALL keep its
id, and SHALL NOT produce a `failed` webhook for that attempt.

The number of attempts SHALL be one more than the number of delays configured in
`send_retry_backoff`, and the *n*-th retry SHALL be scheduled for the *n*-th delay after
the failure. An empty `send_retry_backoff` SHALL disable retrying, giving each message a
single attempt. The setting SHALL be re-read per use so a change applies without a
restart.

A message SHALL become `failed` — notifying the owning app and alerting the operator,
naming the last error and how many attempts it took — when the failure is not retryable
or the attempts are exhausted.

#### Scenario: A transient failure with budget left
- **WHEN** the first attempt fails with a prompt timeout and `send_retry_backoff` is `30,120,300`
- **THEN** the message stays `pending`, no `failed` webhook is emitted, and another attempt is scheduled 30 seconds later

#### Scenario: The budget is exhausted
- **WHEN** the fourth attempt fails and `send_retry_backoff` is `30,120,300`
- **THEN** the message becomes `failed` with that error, the owning app is notified once, and the operator alert names four attempts

#### Scenario: Retrying is disabled
- **WHEN** `send_retry_backoff` is empty and an attempt fails transiently
- **THEN** the message becomes `failed` on that attempt

### Requirement: A message is never transmitted twice

An attempt SHALL be recorded, and the message's schedule cleared, before any byte of it
is written to the modem. A message with no schedule SHALL NOT be re-queued.

Consequently a message whose attempt did not conclude — because the process was killed,
the modem was hard-reset, or the code raised between transmission and the status write —
SHALL never be automatically re-attempted. Recovering such a message SHALL require an
operator.

Independently, once any part of a message has been accepted by the modem, a later
failure SHALL fail the message immediately whatever its classification, because
re-sending would deliver an already-transmitted part a second time and reuse its
concatenation reference.

#### Scenario: The process dies mid-send
- **WHEN** the service is killed after a message's PDU was written and before its status was updated
- **THEN** the message is not re-queued after the restart, and is swept to `failed` once it is past its deadline

#### Scenario: The second part of a two-part message fails
- **WHEN** part 1 is accepted and part 2 fails with a timeout
- **THEN** the message becomes `failed` at once and no retry is scheduled

### Requirement: Retries are scheduled and never block other messages

A message awaiting a retry SHALL leave the send queue, so no other message waits behind
it for the length of a backoff delay.

A scheduler SHALL re-queue messages whose scheduled time has passed, and SHALL NOT
re-queue a message the sender already holds queued or in flight. It SHALL NOT re-queue a
message whose destination has been blacklisted since the message was accepted; such a
message SHALL be failed instead.

Each scheduler pass SHALL be bounded in batch size, and SHALL NOT re-queue a message
older than the retry deadline — a message delivered long after its moment is worse than
one never delivered.

A scheduler pass that raises SHALL be logged and SHALL NOT stop the scheduler.

#### Scenario: A short message follows a deferred one
- **WHEN** a message is deferred for five minutes and another send arrives immediately after
- **THEN** the second message is transmitted without waiting for the first

#### Scenario: The destination is blacklisted mid-ladder
- **WHEN** a message is due for a retry and its number has been blacklisted since acceptance
- **THEN** the message is failed rather than re-queued

#### Scenario: A scheduler pass fails
- **WHEN** a scheduler pass raises a database error
- **THEN** the failure is logged and the next pass still runs

### Requirement: A message may not stay `pending` indefinitely

A message that has been `pending` longer than the retry deadline — the sum of the
configured backoff delays plus a margin for a slow final attempt — SHALL be failed and
its owning app notified.

#### Scenario: A message outlives its budget
- **WHEN** a message has been `pending` for longer than the retry deadline
- **THEN** it becomes `failed` and its app receives one notification

### Requirement: An unexpected error does not stop the sender

The sender SHALL survive any error while sending a message, not only a failed AT
exchange: the message SHALL be failed, the error logged with a traceback, and the loop
SHALL continue. Whatever the outcome, the sender SHALL release its claim on the message
so the scheduler can see it again.

#### Scenario: The database errors mid-send
- **WHEN** recording a transmitted part raises a database error
- **THEN** the message is failed, the sender keeps running, and the message is no longer held

### Requirement: A message still on its way does not report an error

While a message is `pending`, the reason its last attempt failed SHALL be recorded
separately from the `error` field that a consuming application reads. `error` SHALL
continue to mean "why this message finally failed".

#### Scenario: An app polls a message between attempts
- **WHEN** an app reads a message whose first attempt failed and whose retry is scheduled
- **THEN** its status is `pending` and its `error` is null

## MODIFIED Requirements

### Requirement: Queued messages survive a restart

A message accepted as `pending` and never transmitted SHALL be transmitted after a
service restart, subject to the retry deadline and to the never-transmitted-twice
requirement above.

#### Scenario: The service restarts before transmission
- **WHEN** a message is accepted and the service restarts before it is handed to the modem
- **THEN** the message is transmitted after the restart rather than staying `pending` forever

#### Scenario: A message is accepted normally
- **WHEN** a message is accepted and handed straight to the queue
- **THEN** the scheduler does not enqueue it a second time

## REMOVED Requirements

### Requirement: A message gets exactly one transmission attempt

**Reason**: replaced by the retry policy above. It was adopted as `descriptive` and never
promoted.
