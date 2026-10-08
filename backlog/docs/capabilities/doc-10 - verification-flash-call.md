---
id: doc-10
title: verification-flash-call
type: specification
created_date: '2026-10-08 16:02'
updated_date: '2026-10-08 16:28'
---
# verification-flash-call Specification

## Purpose
The `flash_call` rung of the verification ladder: a paid flash call by uCaller, where the
code is the last four digits of the calling number the person sees on their screen. Code:
`app/verification/flash_carrier.py` (ladder semantics and the late sweep),
`app/verification/ucaller.py` (the wire), driven by `app/verification/ladder.py`.
Introduced by the `route-sends-by-operator` claim (SG-6). The comparison norm here was
re-measured 08.10 (SG-42): the vendor's `code` report is an honest echo, and the six
production "different digits" rungs were this gateway's sweep comparing it against a code
the verification had already spent (evidence: `HANDOFF-sg42.md`, control probes v121/v122).

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

### Requirement: The digits are compared where they are comparable

The carrier SHALL read the vendor's `code` at both places it is stated — `initCall`'s
echo and `getInfo` — and compare it against the code the verification holds live. A
genuine disagreement — the vendor will dial digits the person cannot be matched against —
SHALL fail the rung and the verification with that reason and wake the operator: every
instance of it is paid for, and the carrier's comparison cannot produce the artefact
below. The digits check SHALL sit after the call's own outcome, so a call the vendor
could not connect is failed for that reason and not for digits nobody saw.

#### Scenario: The echo names other digits
- **WHEN** `initCall`'s echo reports a `code` other than the one requested
- **THEN** the rung is failed with the different-digits reason and the operator is woken
- **AND** the paid authorisation's id stays on the rung

#### Scenario: A call that never connected
- **WHEN** `getInfo` says the call was not connected, whatever its `code` says
- **THEN** the rung is failed for the connection, not for the digits

### Requirement: An unresolved outcome is unknown, not an ending

The rung SHALL bound its wait by the ladder's bound and record an undecided vendor as
`unresolved` with the vendor reference kept, failing nothing.

#### Scenario: The vendor is still deciding at the bound
- **WHEN** `call_status` is still `-1` when the ladder's bound runs out
- **THEN** the rung says `unresolved` and the verification stays pending

### Requirement: The late settle compares only a code that is still alive

The sweep SHALL compare the report against the verification's code only while the
verification still holds it: every ending — confirmation, failure, expiry — spends the
code, a person confirms within seconds while the vendor reports within a minute, and a
report read against a spent code manufactures a disagreement out of an honest echo. That
artefact failed six delivered, paid-for rungs on verifications this gateway's own code
had already confirmed (08.10). A rung whose verification is already confirmed SHALL be
recorded as carried whatever the late report says — the confirmation is this gateway's
own evidence and outranks it — with what the report did say kept in the reason, for a
denial of the call under a live confirmation is evidence against the vendor.

#### Scenario: Confirmed, then the sweep runs
- **WHEN** a verification is confirmed at `/check` and the sweep later reads the rung
- **THEN** the rung is recorded as carried with the confirmation named and the verification stays confirmed

#### Scenario: The vendor denies the call under a confirmation
- **WHEN** a confirmed verification's rung is settled and the vendor reports the call was not connected
- **THEN** the rung is carried by the confirmation and the reason names the vendor's denial as kept evidence

#### Scenario: The verification has ended and spent its code
- **WHEN** the sweep settles the rung of a failed or expired verification and reads the call as placed
- **THEN** the rung is carried with its cost and a reason saying the digits are not comparable

#### Scenario: A genuine disagreement while the code is alive
- **WHEN** the sweep reads `call_status` as placed and a `code` other than the one the open verification still holds
- **THEN** the rung is failed with the different-digits reason and the open verification fails with it

#### Scenario: The vendor could not connect
- **WHEN** the sweep reads a `call_status` saying the call was not connected and the verification is still open
- **THEN** the rung is failed with that reason and the verification fails with the same reason
