## ADDED Requirements

### Requirement: Every delivery report is recorded, and only a report about nothing wakes an operator

The gateway SHALL write a record for every `+CDS` line it reads, before or at the moment it
acts on it, and SHALL keep that record whether or not the report changed anything. Only the
raw line and the time of receipt SHALL be required in a record; every parsed field SHALL be
optional, so a line the parser cannot read is recorded too rather than becoming the one
event that leaves no trace.

A record SHALL carry the outcome of attribution, the values the window and the strict switch
held when the decision was made, and **every part whose reference matched**, each with its
own outcome — chosen, contradicted, outside the window, or superseded.

Every part sharing the reference SHALL therefore be collected **before** the window and
message-status filters are applied, and those filters SHALL be recorded as outcomes rather
than performed as a database `WHERE` clause that discards the rows unseen. A lookup that
filters first cannot name what it excluded: the record answers "nothing matched" where the
truth was "one match, too old", the question the switch is flipped on becomes unanswerable,
and — worse — a superseded report becomes indistinguishable from a report about nothing and
starts waking an operator on ordinary traffic.

Attribution SHALL end in exactly one of three outcomes, and only the last of them notifies
an operator:

- **attributed** — a part was chosen and updated;
- **superseded** — the reference matched a part whose message has already reached
  `delivered` or `failed`, or a part whose status a report has already set. This is ordinary
  network behaviour, not a fault: a multipart message completed at the timeout still
  receives its remaining reports afterwards. Recorded, silent;
- **unplaced** — no part matched, every candidate was eliminated, or the only match fell
  outside the window. Recorded **and notified**, under a toggle of its own that SHALL
  default to on, and de-duplicated on the report's reference so a wrapped counter cannot
  turn one fault into a storm.

An unplaced report is notified because every consequence of discarding one is otherwise
invisible: a message still `sent` goes on to `expired` and its application is told so, and a
negative report that is discarded also suppresses the destination's failure count and the
delivery alert that would have named it.

The reference and status a parsed report yields SHALL NOT change when further fields are
captured from the same line. The values are read by position, and a capture added ahead of
them silently shifts every later one — a failure that turns every delivery in the system
into its opposite while every test that builds a report by hand still passes.

Records SHALL be pruned on a named retention with a stated default, on a recurring schedule
that runs while the gateway is running normally — not only at startup and not on modem link
recovery, either of which leaves a gateway that stays up pruning nothing for months.

A line the parser cannot read SHALL be recorded under an outcome of its own and SHALL be
logged at error level. It is not a quiet fourth case of attribution: our own parser failing
on a line the network sent is either a wire-format change or the group-renumbering fault
above, and that fault presents as every delivery in the system turning into a failure. It
SHALL NOT be the one class of event that reaches nobody.

Writing a record SHALL NOT be able to undo or prevent an attribution: the status write is
the commitment, the record is the account of it, and a record that fails to write SHALL be
logged and abandoned rather than allowed to fail the report.

[normative · evidence: app/db/migrate.py:240-268 (the ledger and its indexes), app/db/queries.py:271-334 (record and prune), app/modem/manager.py:741-848 (`_on_cds_line`, `_record_report`, `_handle_cds`), app/modem/manager.py:87 (retention), app/modem/manager.py:1233-1258 (pruned on the sweep), app/alerting.py:386,398 (the `delivery_unplaced` event), app/settings_store.py:51 (`notify_unplaced_reports`, default on), app/modem/parser.py:33-42 (the positional capture groups the record's fields depend on) · conf: high]

#### Scenario: A report is attributed
- **WHEN** a report is applied to a part
- **THEN** a record exists naming that message and segment, and no operator notification is raised

#### Scenario: A late report for a message already completed
- **WHEN** a report arrives for a part of a message the timeout already completed as `delivered`
- **THEN** the record says superseded and names that part, no status changes, and no operator notification is raised

#### Scenario: A report about nothing
- **WHEN** no part matches a report's reference at all
- **THEN** the record carries the reference, the recipient address and the reason, and an operator notification is raised

#### Scenario: A storm of unplaced reports
- **WHEN** several unplaced reports carrying the same reference arrive inside the alert de-duplication window
- **THEN** the operator is notified once

#### Scenario: A line the parser cannot read
- **WHEN** a `+CDS` line does not match the expected shape
- **THEN** a record exists holding the raw line and the time it arrived

#### Scenario: Capturing more fields does not move the old ones
- **WHEN** the captured sample `+CDS: 6,42,"+79991234567",145,"26/04/17,12:00:01+12","26/04/17,12:00:03+12",0` is parsed
- **THEN** the reference is 42 and the status is 0, before and after the recipient address and submit timestamp are captured from the same line

#### Scenario: The record cannot be written
- **WHEN** writing a record fails
- **THEN** the attribution it describes still stands, and the failure is logged

#### Scenario: A record outlives its retention
- **WHEN** a record is older than the retention
- **THEN** it is pruned, and pruning removes no record newer than that

### Requirement: A delivery report is attributed to one part, by more than its reference

The modem's message reference SHALL NOT be the identity of a part record. A part SHALL be
addressed by its message and its segment number. Recording a part SHALL NOT change or remove
the recorded status of any part already recorded — including another segment of the same
message — and SHALL NOT silently discard the reference or submit time it was given: where a
part record for that message and segment already exists, the attempt is a fault to be
raised, not a conflict to be resolved. That fault SHALL be logged and SHALL NOT fail the
message: it can only fire after a segment the network already accepted, so failing the
message would invite an operator resend and a second delivery to the recipient.

A part is a **candidate** for a report when its reference matches, its message is `sent` or
`expired`, and its own submit time is not older than `delivery_report_max_age_hours`. A part
whose submit time is unknown SHALL count as inside the window: unknown is not old, and a
comparison that answers "does not qualify" for a missing value fails closed in a rule that
must fail open.

A part whose status a report has already set SHALL NOT be preferred over a candidate no
report has reached. Where such a part is the only match, the outcome is superseded and its
status stands.

**Where a candidate is chosen — whether it was the only one, or was selected by the rules
below — the gateway SHALL apply the report to it.** The obligation is positive: a gateway
that attributed nothing at all would satisfy every necessary condition above.

#### Contradiction

A candidate addressed to a different number than the report names SHALL be eliminated,
**including when it is the only candidate** — a rule applied only to ties would leave the
single-candidate misattribution exactly where it is.

The two numbers SHALL be compared by their significant digits: every non-digit removed from
each, the last ten digits of each taken, those two tails compared. They SHALL NOT be
compared by canonicalizing the report's address against a configured region, which raises on
a valid foreign number — silently switching the rule off — or resolves a national-format
address into a *different* valid number, which would eliminate the correct sole candidate.
Where **either** side yields fewer than ten digits, nothing SHALL be eliminated: a length
difference is not a disagreement.

This is the only rule in this capability that can refuse a delivery, and it SHALL be
governed by `delivery_report_strict_attribution`, which SHALL default to **off** and SHALL
be re-read for each report. While it is off, a contradiction SHALL be recorded and SHALL NOT
eliminate.

#### Choosing between candidates

Where more than one candidate remains and the report's submit time is known, the gateway
SHALL prefer the candidate whose own submit time is nearest to it. Otherwise, and where that
does not separate them, the gateway SHALL take the most recently sent, and SHALL record that
the choice was made by recency alone.

The chosen candidate SHALL carry how it was chosen out of attribution, because two
consumers depend on it: the record, and the blacklist. **A report attributed by recency
alone SHALL NOT count toward the destination's blacklist.** An irreversible penalty may not
rest on a tiebreak.

The report's submit timestamp SHALL be read as `YY/MM/DD,hh:mm:ss` followed by a signed
offset in **quarter-hours** from UTC — `+12` is UTC+03:00 — and one that does not parse SHALL
be treated as absent rather than as any particular time. **The distance between the two
clocks** SHALL NOT eliminate a candidate, however large it is; the window, which is about a
part's age and not about that distance, is the only rule that excludes on time.

[normative · evidence: app/modem/attribution.py:49-66 (significant digits), app/modem/attribution.py:104-200 (the chain), app/modem/attribution.py:202-217 (nearest, then recency), app/db/queries.py:336-360 (`parts_matching_ref`, unfiltered by design), app/db/queries.py:244-269 (the part insert), app/modem/manager.py:795-848 (the decision reaching its three consumers), app/modem/manager.py:869-882 (the recency blacklist carve-out), app/modem/parser.py:176-202 (`scts`, quarter-hours), app/settings_store.py:83-95 (both settings) · conf: high]

#### Scenario: The reference has been reused since the message was sent
- **WHEN** message A was sent under reference 42, message B is later sent under reference 42, and a report for reference 42 naming A's recipient arrives while strict attribution is on
- **THEN** A's part is updated and B is left untouched

#### Scenario: The only candidate is addressed to someone else
- **WHEN** strict attribution is on, a report for reference 42 names a number differing in its last ten digits from the only qualifying part's message
- **THEN** no part and no message change, the record carries both numbers, and an operator notification is raised

#### Scenario: The same report while the switch is off
- **WHEN** strict attribution is off and that same contradicting report arrives
- **THEN** the part is updated as it would have been before this change, and the contradiction is recorded

#### Scenario: A qualifying candidate is updated
- **WHEN** one part qualifies and nothing contradicts it
- **THEN** that part's status is set from the report

#### Scenario: A chosen candidate is updated
- **WHEN** two parts qualify and the rules select one of them
- **THEN** that part's status is set from the report — choosing is not the obligation, applying is

#### Scenario: The address is national where ours is international
- **WHEN** a report names `89031680015` and the only candidate is addressed to `+79031680015`
- **THEN** the candidate is not eliminated, because the last ten digits agree

#### Scenario: One side is too short to compare
- **WHEN** a report names an address of six digits, or the candidate's stored number holds fewer than ten
- **THEN** nothing is eliminated

#### Scenario: The network sends no recipient address
- **WHEN** a report carries an empty address and one part qualifies on reference and window
- **THEN** that part is updated exactly as it is today

#### Scenario: The clocks disagree
- **WHEN** a report's submit timestamp is hours away from the submit time of the only qualifying part
- **THEN** that part is still updated

#### Scenario: The timestamp offset is quarter-hours
- **WHEN** a report carries `"26/04/17,12:00:01+12"`
- **THEN** it is read as 12:00:01 at UTC+03:00, not UTC+12:00

#### Scenario: The report carries no usable timestamp
- **WHEN** two candidates qualify and the report's submit time cannot be read
- **THEN** the most recently sent is chosen and the record says the choice was made by recency

#### Scenario: Two parts qualify
- **WHEN** two parts share a reference, agree with the report's address and fall inside the window
- **THEN** the one whose submit time is nearest the report's is updated, and both are named in the record

#### Scenario: Two parts qualify and nothing separates them
- **WHEN** two such parts cannot be separated by submit time and the report is a permanent failure
- **THEN** the most recently sent is updated, the record says recency, and the destination's failure count is not incremented

#### Scenario: A part's submit time is unknown
- **WHEN** the only part matching a reference has no recorded submit time
- **THEN** it qualifies, rather than being excluded as too old

#### Scenario: An already-reported part does not shadow an unreported one
- **WHEN** two parts share a reference, one already reported delivered and one never reported, and both otherwise qualify
- **THEN** the unreported one is chosen

#### Scenario: The report is older than the window
- **WHEN** the only part matching a reference belongs to a message sent longer ago than `delivery_report_max_age_hours`
- **THEN** no status changes, and the record says unplaced **and names the part it bounded out** — not that nothing matched

#### Scenario: The same report arrives twice
- **WHEN** a second report arrives for a part already reported delivered, and no other part matches
- **THEN** the part keeps that status, the outcome is superseded, and no operator notification is raised

### Requirement: The delivery-report window is a positive number of hours or it is the default

`delivery_report_max_age_hours` SHALL be a positive integer with a stated default and SHALL
be re-read for each report. It SHALL be refused when saved as zero or below, and a stored
value that cannot be read as a positive integer SHALL fall back to the default rather than
be taken literally.

A window of zero discards every report the gateway receives and would announce itself only
as every message expiring — a setting whose worst value looks like a network outage is one
the settings layer has to refuse rather than the operator has to remember.

[normative · evidence: app/settings_store.py:83-89 (the spec, default 168), app/settings_store.py:98-118 (the `posint` type: refused at zero or below), app/settings_store.py:255-274 (`get` falls back to the default rather than taking a broken row literally), app/modem/manager.py:799 (re-read per report) · conf: high]

#### Scenario: The window is set to zero
- **WHEN** an operator saves `delivery_report_max_age_hours` as `0` or a negative number
- **THEN** the save is refused and the previous value stands

#### Scenario: The stored window is unusable
- **WHEN** the stored value cannot be read as a positive integer
- **THEN** the default is used and every report is still considered

### Requirement: A malformed delivery report SHALL NOT stop the gateway receiving reports

Parsing a report's fields and attributing it SHALL NOT be able to end the loop that reads
unsolicited results from the modem. A report the gateway cannot parse or cannot process
SHALL be recorded, logged and abandoned, and reading SHALL continue.

Losing that loop is silent and total — no `+CDS` and no `+CMTI` — and this change makes the
loop read text chosen by the network and hand it to a number parser that raises. The sibling
loops already hold this line; this one does not.

[normative · evidence: app/modem/manager.py:741-777 (`_on_cds_line`: unparsable recorded and logged, handling wrapped and the report abandoned), app/modem/manager.py:682-697 (the reader loop that calls it) · conf: high]

#### Scenario: The recipient address is not a number
- **WHEN** a report arrives whose address field cannot be interpreted
- **THEN** it is recorded and abandoned, and the next `+CDS` on the port is still processed

#### Scenario: Attribution raises
- **WHEN** processing a report raises an unexpected error
- **THEN** the error is logged, the reader loop continues, and a later `+CMTI` is still handled

## MODIFIED Requirements

### Requirement: A message becomes `sent` when its first part is accepted by the modem

Parts SHALL be transmitted sequentially within one serial session. Each part's `+CMGS`
reference SHALL be recorded before the next part is transmitted, and the message SHALL
move to `sent` on the first part's reference.

Each part recorded from this change onward SHALL record the time its own `+CMGS` reference
was received. The message's `sent_at` dates the message and is set once, on the first part;
a later segment is not that time.

Parts that predate this rule SHALL carry the message's `sent_at`, because a per-segment
submit time was never recorded and cannot be recovered. The approximation can only make a
later segment look older than it was, never newer, and a part that looks too old is kept by
the unknown-and-late rules rather than dropped by them.

[normative · evidence: app/modem/manager.py:509-527 (`on_part_sent`, and the conflict that is logged without failing the message), app/db/queries.py:244-269 (plain INSERT, each part's own `sent_at`), app/db/migrate.py:200-222 (the base DDL), app/db/migrate.py:20-119 (the rebuild, its guard and the backfill) · conf: high]

#### Scenario: A two-part message is transmitted
- **WHEN** part 1 of a two-part message receives `+CMGS: 10`
- **THEN** the message is `sent` and part 1 is recorded before part 2 is transmitted

#### Scenario: A reference is reused by a later message
- **WHEN** a part is recorded under a reference some earlier message also used
- **THEN** both part records exist afterwards, each against its own message, and the earlier one keeps its status

#### Scenario: The second segment carries its own time
- **WHEN** part 2 of a message is accepted a minute after part 1
- **THEN** part 2's recorded time is when part 2 was accepted, not the message's `sent_at`

#### Scenario: A part carried over from before the rule
- **WHEN** an existing part record is carried forward
- **THEN** it holds its message's `sent_at`, and that value is treated as a submit time like any other

### Requirement: A message is `delivered` only when every part is reported delivered

On a positive `+CDS` the part SHALL be marked delivered, and the message SHALL move to
`delivered` only once no part is outstanding. On a negative `+CDS` the message SHALL move
to `failed` carrying the decoded TP-status, and a permanent status SHALL count toward the
destination's blacklist threshold — **except where attribution chose that part by recency
alone**, because blocking a destination is irreversible in practice and may not rest on a
tiebreak.

This holds while reports are still expected. It SHALL NOT survive the timeout: a network
that reports one segment of a multipart message and no more would otherwise leave every
such message outstanding for ever, and the sweep would call a delivery a failure.

Both writes SHALL address the part by its message and segment — the part attribution chose —
and SHALL NOT address parts by the reference they share.

A message with no part records at all SHALL NOT be treated as having every part delivered:
"nothing is outstanding" and "nothing is known" are different answers, and only the first is
a delivery.

[normative · evidence: app/db/queries.py:362-384 (both writes address `(message_id, seq)`), app/db/queries.py:386-400 (no part rows is not a delivery), app/modem/manager.py:850-882 (`_apply_report`) · conf: high]

#### Scenario: One part of two is reported delivered
- **WHEN** part 1 is reported delivered and part 2 is outstanding
- **THEN** the message stays `sent`

#### Scenario: The remaining reports never come
- **WHEN** the timeout is reached with at least one part confirmed and none failed
- **THEN** the message is `delivered`, not `expired`

#### Scenario: Another message's part shares the reference
- **WHEN** a report is attributed to one part and another message's part carries the same reference
- **THEN** only the attributed part changes status

#### Scenario: A message has no part records
- **WHEN** `message_parts_all_delivered` is asked about a message with no part rows
- **THEN** the answer is that parts are outstanding, not that all are delivered

#### Scenario: A late negative report after expiry
- **WHEN** a message swept to `expired` receives a negative report inside the window
- **THEN** it becomes `failed`, its app is notified after the `expired` notification, and a permanent status counts toward the destination's blacklist — unless that part was chosen by recency alone

### Requirement: A `sent` message with no delivery report expires

A sweep SHALL run every 60 seconds and move every message that has been `sent` longer
than `delivery_timeout_seconds` to `expired`, notifying the owning app per message. The
timeout SHALL be re-read each sweep so a settings change applies without a restart.

A message SHALL expire only when **nothing** about it was confirmed. Where at least one
part was reported delivered and none was reported failed, the sweep SHALL complete it as
`delivered` instead — the network said it handed over part of the message and never said
otherwise about the rest, which is evidence of delivery rather than of its absence. Absence
of *any* report remains absence of evidence, and still expires.

The evidence SHALL be evidence about *that* message. A message SHALL NOT be completed as
`delivered` on the strength of a part record no report attributed to that message ever set —
otherwise a single misattributed positive report manufactures a delivery for a message no
report ever named, and the record states that the gateway concluded it.

A message completed this way SHALL be distinguishable afterwards from one whose every part
was confirmed. "We were told" and "we concluded" are different facts, and an operator
diagnosing a complaint needs to know which one they are reading.

[normative · evidence: app/db/queries.py:704-746 (`complete_partly_reported_messages`, now fed only by parts a report attributed to that message), app/db/queries.py:749-769 (`expire_stale_messages`), app/modem/manager.py:1233-1258 (the sweep, and the ledger prune on it) · conf: high]

#### Scenario: No report arrives in time
- **WHEN** a message has been `sent` for longer than the configured timeout and no part was ever confirmed
- **THEN** it becomes `expired` and its app is notified once

#### Scenario: Some parts were confirmed and the rest never were
- **WHEN** the timeout is reached, one part of two is confirmed delivered, and neither is failed
- **THEN** the message becomes `delivered`, its app is notified once, and the record shows the status was inferred rather than reported

#### Scenario: A part was reported failed
- **WHEN** a part has been reported failed
- **THEN** the timeout does not turn the message into a delivery

#### Scenario: The confirmation belongs to another message
- **WHEN** the timeout is reached for a message whose parts no report was attributed to
- **THEN** it expires, and is not completed as `delivered`
