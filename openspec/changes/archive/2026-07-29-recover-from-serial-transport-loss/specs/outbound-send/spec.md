## MODIFIED Requirements

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
