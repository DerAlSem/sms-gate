---
id: doc-10
title: verification-flash-call
type: specification
created_date: '2026-10-08 16:02'
updated_date: '2026-10-08 16:20'
---
# verification-flash-call Specification

## Purpose
The `flash_call` rung of the verification ladder: a paid flash call by uCaller, where the
code is the last four digits of the calling number the person sees on their screen. Code:
`app/verification/flash_carrier.py` (ladder semantics and the late sweep),
`app/verification/ucaller.py` (the wire), driven by `app/verification/ladder.py`.
Introduced by the `route-sends-by-operator` claim (SG-6); the code-report norm here was
re-measured and inverted 08.10 (SG-42; the evidence trail lives in SG-29's notes).

Scope: only the `flash_call` rung and the sweep that settles it. Route selection, the
check door and the other rungs are not described here.

## Requirements
### Requirement: An authorisation exists whatever `status` said

The gateway SHALL treat any `initCall` answer carrying a `ucaller_id` as a paid,
followable authorisation, record the id on the rung row before waiting for any outcome,
and SHALL NOT read `status: false` without an `error` as a refusal.

#### Scenario: `status: false` with an id
- **WHEN** `initCall` answers `status: false` carrying a `ucaller_id` and no `error`
- **THEN** the rung records the id and the vendor is asked later what became of the call

### Requirement: The vendor's `code` report is not the dialled digits

The verification SHALL be matched only against the code this gateway requested. The
vendor's `code` — on `initCall`, on `getInfo`, in the cabinet — SHALL NOT be treated as
the digits that were dialled: measured 08.10 over every rung to date, all six where the
report disagreed were confirmed by this gateway's own `/check` within seconds, and all
eight where it agreed expired unconfirmed. The report is evidence for the claim against
the vendor, not authority over the outcome. The digits the vendor named SHALL be written
wherever the disagreement is named.

#### Scenario: The report disagrees while the call's outcome is unknown
- **WHEN** `initCall`'s echo names a `code` other than the one requested
- **THEN** the rung says `unresolved` with the disagreement and the digits named
- **AND** the verification stays confirmable against the requested code for the rest of its window
- **AND** the ladder does not advance to buy the code again

#### Scenario: The report disagrees once the vendor has spoken about the call
- **WHEN** `getInfo` names a `code` other than the one requested
- **THEN** a call reported placed is carried with the disagreement and the digits named in the reason
- **AND** a call reported not connected is failed for that reason alone — a known delivery failure is not silenced by a report that cannot be trusted about the digits
- **AND** no alert wakes the operator; the journal line is the whole record

### Requirement: An unresolved outcome is unknown, not an ending

The rung SHALL bound its wait by the ladder's bound and record an undecided vendor as
`unresolved` with the vendor reference kept, failing nothing. The reason the walk records
SHALL say what actually left the rung unresolved rather than asserting the vendor was
silent.

#### Scenario: The vendor is still deciding at the bound
- **WHEN** `call_status` is still `-1` when the ladder's bound runs out
- **THEN** the rung says `unresolved` and the verification stays pending

### Requirement: The late settle records facts and cannot outrank a confirmation

`resolve_outstanding` SHALL ask the vendor about every unresolved rung within the
verification's own lifetime and record the placement and the cost it learns. A
verification confirmed by this gateway's own code check SHALL have its rung recorded as
carried whatever the vendor reports afterwards, with what the report said kept in the
reason — a vendor denying the call under a live confirmation is evidence against it. A
`code` disagreement SHALL NOT fail the rung or the verification, and SHALL be decided
only while the verification still holds its code: every ending spends it, and a spent
code is not compared. Only a call the vendor says it could not connect ends an open
verification, and it ends with that reason.

#### Scenario: Confirmed, then the sweep runs
- **WHEN** a verification is confirmed at `/check` and the sweep later reads a report that disagrees
- **THEN** the rung is recorded as carried with the confirmation named and the verification stays confirmed

#### Scenario: The vendor denies the call under a confirmation
- **WHEN** a confirmed verification's rung is settled and the vendor reports the call was not connected
- **THEN** the rung is carried by the confirmation and the reason names the vendor's denial as kept evidence

#### Scenario: Placed with a disagreeing report, nobody confirmed yet
- **WHEN** the sweep reads `call_status` as placed and a `code` other than the one requested
- **THEN** the rung is recorded as carried with the disagreement named and its cost
- **AND** the verification is left pending until its own window ends it

#### Scenario: The verification has ended and spent its code
- **WHEN** the sweep settles the rung of a failed or expired verification and reads the call as placed
- **THEN** the rung is carried with the plain placement reason and no disagreement is claimed

#### Scenario: The vendor could not connect
- **WHEN** the sweep reads a `call_status` saying the call was not connected and the verification is still open
- **THEN** the rung is failed with that reason and the verification fails with the same reason
