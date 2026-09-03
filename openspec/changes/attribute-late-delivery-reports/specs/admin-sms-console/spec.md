## MODIFIED Requirements

### Requirement: Deletion is refused while anything still depends on the message

Deleting an outbound message SHALL be permitted only when **all** of the following hold:

- its status is `delivered` or `failed`. **`expired` is not deletable.** While the message's
  most recent part is inside `delivery_report_max_age_hours` it remains eligible for a late
  delivery report, which `delivery-dispatch` requires to correct itself. Past that window it
  is no longer eligible, and the refusal SHALL stand on a second reason: an `expired` message
  is one whose outcome the gateway never learned, and the record of an unanswered question is
  not the operator's routine tidying — the eligibility rule may acquire a bound without the
  deletion rule acquiring one;
- no message re-sent from it is still in flight — that is, every message whose `resent_from`
  names it is itself `delivered` or `failed`. `delivery-dispatch` requires `resent_from` in
  **every** notification for the re-sent message, and that field is read at notification
  time;
- it is at least 24 hours old. `GET /sms/{id}` is the authoritative status source an
  application polls to recover a dropped webhook; deleting a fresh message replaces that
  answer with a 404 indistinguishable from "no such message".

Deleting an outbound message SHALL remove its per-part delivery records in the same
transaction, and SHALL clear the `resent_from` reference of any message that named it. If
the request is refused, nothing SHALL be removed.

The delivery reports `outbound-send` records SHALL survive the deletion of the message they
name, and SHALL NOT hold a database reference that makes deleting it fail. They are the
account of what the network said, not part of the message; they carry the recipient's number
and outlive the row, and they are removed by their own retention rather than by this
operation. The claim that no soft delete exists is about the message and its parts.

Deleting an inbound message SHALL remove that message.

Deletion and manual blocking SHALL each be recorded in the log with the number, the
direction, the id and the beginning of the text. There is no soft delete, so the log is the
only trace that survives.

#### Scenario: An in-flight message cannot be deleted

- **WHEN** deletion is requested for a message in `sent` or `pending` state
- **THEN** the request is refused and the message remains

#### Scenario: An expired message cannot be deleted

- **WHEN** deletion is requested for a message in `expired` state
- **THEN** the request is refused

#### Scenario: An expired message past the report window still cannot be deleted

- **WHEN** deletion is requested for an `expired` message whose most recent part is older than `delivery_report_max_age_hours`
- **THEN** the request is still refused, even though no delivery report can arrive for it any more

#### Scenario: Deleting a message leaves its delivery reports

- **WHEN** an eligible message with recorded delivery reports is deleted
- **THEN** the deletion succeeds and those records remain until their own retention removes them

#### Scenario: A fresh message cannot be deleted

- **WHEN** deletion is requested for a `delivered` message created an hour ago
- **THEN** the request is refused

#### Scenario: A message with an in-flight re-send cannot be deleted

- **WHEN** deletion is requested for a `failed` message whose re-sent copy is still `sent`
- **THEN** the request is refused, so the copy's notifications keep carrying `resent_from`

#### Scenario: Deleting takes the part records with it

- **WHEN** an eligible multipart message with recorded parts is deleted
- **THEN** the message and its part records are gone, and no orphaned part record remains

#### Scenario: A refused deletion changes nothing

- **WHEN** deletion is refused for any reason
- **THEN** the message, its part records and every reference to it are unchanged

#### Scenario: Telegram notification references are untouched

- **WHEN** an outbound message is deleted
- **THEN** rows in `notify_refs` are unaffected — its `message_id` is a Telegram message id,
  not a gateway message id

#### Scenario: Deleting an inbound message

- **WHEN** deletion is requested for a received message
- **THEN** that message is removed and the conversation no longer shows it
