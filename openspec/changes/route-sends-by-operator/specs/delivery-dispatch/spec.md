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

A verification's outcome SHALL be pushed over these same per-application routes, and its body
SHALL carry an explicit kind naming it a verification, with the verification's identifier in a
field distinct from `id`. A receiver SHALL NOT be able to read a verification identifier as a
message identifier: the two are separate sequences of small integers, and a body that looks
like the one above with a foreign number in `id` is worse than an unrecognised body, because
the receiver acts on it.

A message that belongs to a verification SHALL NOT be pushed as a message status change; the
verification notifies instead, so the application that asked for a verification never receives
an identifier it has not seen. An application that has not created a verification SHALL never
receive a notification for one.

[partly backed for the verification clause · `push_verification` in
`app/verification/dispatch.py` carries `"object": "verification"` and the verification's
identifier in `verification_id`; `id` is absent from the body entirely. 🔴 **Built wrong and
corrected 21.09.2026:** the kind was named but the number still travelled in `id`, which is
exactly the body this paragraph calls worse than an unrecognised one. Guarded by
`test_a_verification_push_carries_nothing_a_message_receiver_reads_as_a_message_id` in
`tests/test_verification_outcome_reaches_the_app.py`, which reads the message contract off a
real message push rather than off a description of it, and by the census of terminal
verification writers in the same file. Still unbacked: the clause forbidding a verification's
own message from being pushed as a message status change — that path needs the door]

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
  the pair as ordered reaches the same conclusion the gateway did

#### Scenario: The expiry sweep expires several messages at once
- **WHEN** one sweep moves five messages to `expired`
- **THEN** five notifications are sent, one per message

#### Scenario: A verification outcome is pushed over the same route
- **WHEN** a verification owned by app `app1` is confirmed, failed or expired
- **THEN** a POST is made to app `app1`'s configured route with a body naming its kind as a verification and carrying the verification's identifier outside `id`

#### Scenario: A verification's own message does not notify twice
- **WHEN** the message carrying a verification's code changes status
- **THEN** no message-status notification is sent for it, and the application hears the outcome once, as a verification

### Requirement: Every status writer notifies

Every code path that writes `messages.status` SHALL trigger a delivery notification, and
a test SHALL enumerate those paths and fail when one of them does not, except for messages
belonging to a verification, which notify as verifications instead.

Every code path that writes a verification's state SHALL likewise trigger a notification, and
the same enumerating test SHALL cover those paths and fail when one of them does not.

#### Scenario: A new status writer is added without a notification
- **WHEN** a code path that sets `messages.status` is added with no delivery dispatch
- **THEN** the test suite fails

#### Scenario: A new verification state writer is added without a notification
- **WHEN** a code path that sets a verification's state is added with no notification
- **THEN** the test suite fails
