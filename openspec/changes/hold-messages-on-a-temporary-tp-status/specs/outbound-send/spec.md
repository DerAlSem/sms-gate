## MODIFIED Requirements

### Requirement: A message is `delivered` only when every part is reported delivered

On a positive `+CDS` the part SHALL be marked delivered, and the message SHALL move to
`delivered` only once no part is outstanding.

A `+CDS` SHALL be classified by the **range** its TP-status falls in, not by whether it is
zero. GSM 03.40 §9.2.3.15 gives three classes and this gateway already implements the
classifier (`_tp_status_class`); the decision point did not consult it.

- **Completed** (`0x00–0x1F`): the part is delivered, as above.
- **Permanent** (`0x40–0x5F`): the message SHALL move to `failed` carrying the decoded
  TP-status, and SHALL count toward the destination's blacklist threshold — **except where
  attribution chose that part by recency alone**, because blocking a destination is
  irreversible in practice and may not rest on a tiebreak.
- **Temporary** (`0x20–0x3F` and `0x60–0x7F`): the service centre is still trying. The
  message SHALL NOT move to `failed`, and SHALL remain in a status the real verdict can
  still be applied to. A temporary status SHALL NOT count toward the destination's
  blacklist threshold.

A message SHALL NOT be left outstanding for ever because the network said it was still
trying and then said nothing more. A held message SHALL reach a terminal state at
`delivery_timeout_seconds`, and that state SHALL be one that records that the outcome was
never learned rather than one that asserts an outcome.

This holds while reports are still expected. It SHALL NOT survive the timeout: a network
that reports one segment of a multipart message and no more would otherwise leave every
such message outstanding for ever, and the sweep would call a delivery a failure.

Both writes SHALL address the part by its message and segment — the part attribution chose —
and SHALL NOT address parts by the reference they share.

A message with no part records at all SHALL NOT be treated as having every part delivered:
"nothing is outstanding" and "nothing is known" are different answers, and only the first is
a delivery.

[normative · evidence: app/modem/parser.py, app/modem/manager.py, app/db/queries.py · conf: medium — the temporary-status branch is not yet implemented]

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

#### Scenario: The network says it is still trying
- **WHEN** a report arrives carrying a TP-status in the temporary band, such as `0x21` (recipient busy)
- **THEN** the message does not become `failed`, and the destination's failure count is not incremented

#### Scenario: The verdict arrives after the network said it was still trying
- **WHEN** a temporary report is followed by a definitive one for the same part
- **THEN** the definitive report is applied — which the current behaviour makes impossible, because `failed` is not a status attribution considers

#### Scenario: The verdict never arrives
- **WHEN** a message held on a temporary status reaches `delivery_timeout_seconds` with nothing further from the network
- **THEN** it reaches a terminal state recording that the outcome was never learned, rather than staying outstanding
