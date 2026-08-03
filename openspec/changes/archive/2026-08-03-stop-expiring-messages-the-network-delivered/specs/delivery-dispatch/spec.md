## MODIFIED Requirements

### Requirement: Status changes are pushed to the owning application

The gateway SHALL POST to the route matching a message's `app_id` whenever that
message's status changes to `sent`, `delivered`, `failed` or `expired`, with body
`{"id": <message id>, "status": <new status>, "error": <string or null>,
"occurred_at": <ISO-8601 UTC>}` and, when the route has a bearer, the header
`Authorization: Bearer <bearer>`.

The gateway SHALL NOT push the `pending` status, which `POST /sms/send` already returns
synchronously.

The gateway SHALL send exactly one notification per message per status change,
regardless of how many parts a multipart message has.

A message the sweep completes as delivered on partial reports SHALL notify `delivered`,
and SHALL NOT notify `expired` first. The application is owed the conclusion, not the
reasoning that reached it — and a pair of contradicting notifications is worse than the
wrong one alone, because a receiver that acts on the first has already acted.

#### Scenario: A message is delivered
- **WHEN** the delivery report for every part of message 42 (owned by app `app1`) arrives
- **THEN** exactly one POST is made to app `app1`'s route with `"id": 42` and `"status": "delivered"` and `"error": null`

#### Scenario: A message fails
- **WHEN** message 42 transitions to `failed` with error `service rejected (temporary, st=99)`
- **THEN** the POST body carries `"status": "failed"` and that text as `error`

#### Scenario: A message is created
- **WHEN** `POST /sms/send` creates a message in status `pending`
- **THEN** no delivery webhook is sent

#### Scenario: The first part of a multipart message is delivered
- **WHEN** part 1 of a two-part message is reported delivered and part 2 is not
- **THEN** no `delivered` notification is sent yet

#### Scenario: The remaining reports never arrive
- **WHEN** the timeout is reached for that message and no part was reported failed
- **THEN** one `delivered` notification is sent, and no `expired` notification is sent for it

#### Scenario: A delivery report arrives after the message expired
- **WHEN** message 42 is swept to `expired`, and a delivery report for it arrives later
- **THEN** an `expired` notification is sent, followed by a `delivered` one
- **AND** the second notification's `occurred_at` is later, so a receiver that treated
  `expired` as terminal can still correct itself

#### Scenario: The expiry sweep expires several messages at once
- **WHEN** one sweep moves five messages to `expired`
- **THEN** five notifications are sent, one per message
