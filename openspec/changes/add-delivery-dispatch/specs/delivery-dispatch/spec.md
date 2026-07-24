## ADDED Requirements

### Requirement: Delivery routes are configured per application

The gateway SHALL read outbound delivery routes from the `delivery_dispatch` setting: a
JSON list of objects with `app_id`, `webhook_url` and an optional `bearer`.

A route SHALL be rejected at save time unless `app_id` is non-empty and `webhook_url`
begins with `http://` or `https://`, both checked after stripping surrounding
whitespace. Route fields SHALL be stripped before storage and on read, exactly as
`inbound_dispatch` routes are.

At most one route SHALL apply to a given `app_id`; the first match wins.

#### Scenario: A route is saved with a pasted url
- **WHEN** an operator saves `[{"app_id":"gmb","webhook_url":" https://gmplus.ru/webhooks/sms-gate/delivery ","bearer":"t"}]`
- **THEN** the route is stored with the surrounding whitespace removed
- **AND** delivery notifications for app `gmb` POST to `https://gmplus.ru/webhooks/sms-gate/delivery`

#### Scenario: A route is saved without a scheme
- **WHEN** an operator saves a route whose `webhook_url` is `gmplus.ru/webhooks/sms-gate/delivery`
- **THEN** the save is rejected with an error naming the offending route
- **AND** no route is written

#### Scenario: An app has no route
- **WHEN** a message owned by an app with no `delivery_dispatch` route changes status
- **THEN** no webhook is attempted and no alert is raised

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

#### Scenario: A message is delivered
- **WHEN** the delivery report for every part of message 42 (owned by app `gmb`) arrives
- **THEN** exactly one POST is made to app `gmb`'s route with `"id": 42` and `"status": "delivered"` and `"error": null`

#### Scenario: A message fails
- **WHEN** message 42 transitions to `failed` with error `service rejected (temporary, st=99)`
- **THEN** the POST body carries `"status": "failed"` and that text as `error`

#### Scenario: A message is created
- **WHEN** `POST /sms/send` creates a message in status `pending`
- **THEN** no delivery webhook is sent

#### Scenario: The first part of a multipart message is delivered
- **WHEN** part 1 of a two-part message is reported delivered and part 2 is not
- **THEN** no `delivered` notification is sent yet

#### Scenario: A delivery report arrives after the message expired
- **WHEN** message 42 is swept to `expired`, and a delivery report for it arrives later
- **THEN** an `expired` notification is sent, followed by a `delivered` one
- **AND** the second notification's `occurred_at` is later, so a receiver that treated
  `expired` as terminal can still correct itself

#### Scenario: The expiry sweep expires several messages at once
- **WHEN** one sweep moves five messages to `expired`
- **THEN** five notifications are sent, one per message

### Requirement: Every notification carries the time of the status change

Every notification body SHALL carry `occurred_at`: the moment the status changed, as an
ISO-8601 timestamp in UTC.

The gateway SHALL NOT guarantee the order in which notifications for the same message
arrive, and SHALL NOT delay one notification to preserve order with another. A receiver
that cares about order is expected to compare `occurred_at` against the state it holds.

#### Scenario: A delivery report overtakes a retrying send notification
- **WHEN** the `sent` notification for message 42 is still working through its retry ladder
- **AND** message 42 is reported delivered
- **THEN** the `delivered` notification is sent immediately rather than queued behind `sent`
- **AND** its `occurred_at` is later than the `sent` notification's

### Requirement: A re-sent message is linked to its original

When a message was created by the admin Resend action, the gateway SHALL persist the id
of the source message and SHALL include it as `resent_from` in every notification for
the new message. The field SHALL be absent for messages the application created itself
through `POST /sms/send`.

#### Scenario: An operator re-sends a failed message
- **WHEN** an operator re-sends failed message 42, creating message 57
- **THEN** notifications for message 57 carry `"resent_from": 42`
- **AND** the application can attribute the outcome to its original message 42

#### Scenario: An application sends a message through the API
- **WHEN** message 42 is created by `POST /sms/send`
- **THEN** its notifications carry no `resent_from` field

### Requirement: Delivery notification is best-effort and never blocks the modem

Each notification SHALL be attempted with the same retry ladder as inbound dispatch,
governed by `inbound_dispatch_retries` and `inbound_dispatch_timeout`, and SHALL run
detached from the modem's send and receive loops, holding a strong reference to its task
so a sleeping retry cannot be garbage-collected.

A notification that fails every attempt SHALL be dropped rather than persisted for later
retry. `GET /sms/{id}` SHALL remain the authoritative status source, so a consumer can
recover any dropped notification by polling.

#### Scenario: The receiver is down
- **WHEN** every POST attempt for message 42 fails
- **THEN** the message's own status in the database is unaffected
- **AND** `GET /sms/42` still reports the true status
- **AND** the modem's send and receive loops are unaffected

#### Scenario: A notification is in flight when the gateway restarts
- **WHEN** the gateway restarts while a retry ladder is sleeping
- **THEN** the notification is lost and not resumed
- **AND** the consumer's next poll of `GET /sms/{id}` returns the true status

### Requirement: A failed delivery notification alerts the operator

When a notification for a routed message fails every attempt, the gateway SHALL raise a
`dispatch_error` operator notification carrying the app id, the url, the message id, the
status being reported and the reason for the last failure, deduplicated on the webhook
url so a dead endpoint alerts once per dedup window rather than once per message.

A message whose app has no route SHALL NOT raise an alert — an unconfigured app is not a
gateway fault.

#### Scenario: A dead endpoint receives a burst
- **WHEN** twenty messages for app `gmb` change status while its webhook returns 500
- **THEN** one alert is raised within the dedup window, not twenty

### Requirement: Every status writer notifies

Every code path that writes `messages.status` SHALL trigger a delivery notification, and
a test SHALL enumerate those paths and fail when one of them does not.

#### Scenario: A new status writer is added without a notification
- **WHEN** a code path that sets `messages.status` is added with no delivery dispatch
- **THEN** the test suite fails
