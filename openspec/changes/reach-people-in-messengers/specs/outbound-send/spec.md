## MODIFIED Requirements

### Requirement: A send request is accepted synchronously and queued

`POST /sms/send` SHALL reject a blacklisted destination with HTTP 422 and body
`{"error": "number_blacklisted", "phone": <phone>}` without persisting a message. The
blacklist SHALL continue to gate **every** route, not only the modem: a number is refused
before any route is considered.

Otherwise it SHALL persist the message in status `pending`, determine and record the
message's class, return its id immediately, and hand it to the **route ladder** for
asynchronous sending. Acceptance SHALL NOT wait for any route, and the accepted response
SHALL NOT name a route: which route carries the message is not known at acceptance and
becomes observable only afterwards.

[unbacked · the blacklist refusal and the synchronous acceptance are backed at
app/api/router.py:15-30 and app/db/queries.py:32-41; the class, the recording and the
hand-off to a ladder instead of the modem queue are added by this change]

#### Scenario: A send is accepted
- **WHEN** an app POSTs a send for a number that is not blacklisted
- **THEN** the response is `{"id": <id>, "status": "pending"}` before any route is touched

#### Scenario: A send targets a blacklisted number
- **WHEN** an app POSTs a send for a blacklisted number
- **THEN** the response is HTTP 422 with `error: number_blacklisted` and no message row is created

### Requirement: A message is `delivered` only when every part is reported delivered

On a positive `+CDS` the part SHALL be marked delivered, and the message SHALL move to
`delivered` only once no part is outstanding. On a negative `+CDS` the message SHALL move
to `failed` carrying the decoded TP-status, and a permanent status SHALL count toward the
destination's blacklist threshold.

This holds while reports are still expected. It SHALL NOT survive the timeout: a network
that reports one segment of a multipart message and no more would otherwise leave every
such message outstanding for ever, and the sweep would call a delivery a failure.

**A message accepted by a route other than the modem SHALL move to `delivered` at once,
with the delivery marked as inferred rather than reported.** No delivery report will ever
arrive for it, and there is no part to outstand. It SHALL NOT be written as `sent`: the
expiry sweep selects on `status = 'sent'` with no route predicate
(app/db/queries.py:749), and every messenger delivery would otherwise be reported to the
owning application as `expired` once `delivery_timeout_seconds` had passed.

[unbacked · the `+CDS` half is backed at app/modem/delivery_dispatch.py and
app/db/queries.py:749; the non-modem terminal status is added by this change, and reuses
the existing `delivery_inferred` column added for the "we were told versus we concluded"
distinction]

#### Scenario: One part of two is reported delivered
- **WHEN** part 1 is reported delivered and part 2 is outstanding
- **THEN** the message stays `sent`

#### Scenario: The remaining reports never come
- **WHEN** the timeout is reached with at least one part confirmed and none failed
- **THEN** the message is `delivered`, not `expired`

#### Scenario: A messenger route accepts a message
- **WHEN** `tg_user` accepts a message
- **THEN** the message is `delivered` with delivery inferred, and the expiry sweep never sees it

## ADDED Requirements

### Requirement: A message's class is determined at acceptance from a stated rule and recorded

The class of a message SHALL be determined at acceptance, from the request and the text,
by a rule stated in this specification, and SHALL be recorded on the message. A text
matching no class SHALL take a named default class; it SHALL NOT be left without a route
list.

The rule SHALL be tested against the two live templates **by their literal text**: the
parking template is `SokolParking: ####` and carries a four-digit code, so a rule keyed on
the text being nothing but four digits is wrong for 446 of the 448 messages this change
was measured on.

Without the recorded class, no later question about the ladder's behaviour on a given
message is answerable.

[unbacked · the request carries only phone and text today, app/api/schemas.py:12-22]

#### Scenario: The parking template is classified as a code
- **WHEN** the text is `SokolParking: 1234`
- **THEN** the class is the four-digit code class, not free text

#### Scenario: A text matching no class
- **WHEN** the text matches no configured class
- **THEN** the named default class is used and the message is offered to that class's routes

### Requirement: Every path that creates an outbound message offers it to the ladder

Every code path that creates an outbound message SHALL offer it to the ladder. A test
SHALL enumerate those paths and SHALL fail when a new one bypasses it.

Today there are four: `POST /sms/send` (app/api/router.py:29), an operator's reply to a
notification post (app/telegram_poll.py:70), the admin console's send and resend
(app/admin/router.py:229 and :264), and the retry step (app/modem/manager.py:680). An
invariant placed on one of them is not an invariant.

[unbacked · all four call `modem.enqueue` directly today]

#### Scenario: An operator replies to a notification about a МегаФон number
- **WHEN** the operator's reply creates an outbound message
- **THEN** it is offered to the ladder, not only to the modem

#### Scenario: A new creating path is added without the ladder
- **WHEN** a path creates a message and enqueues it to the modem directly
- **THEN** the enumerating test fails

### Requirement: The modem is always the last rung, and the ladder never writes a terminal status

The configured order SHALL place the modem last and SHALL NOT permit it anywhere else.
When no earlier rung accepts a message, the ladder SHALL hand it to the modem path
unchanged, and every existing requirement of that path — the part budget, the hold while
the modem is off the network, the retry budget, the classification of failures by phase,
and `failed` being written in one place — SHALL apply to it exactly as before.

The ladder itself SHALL NOT write `sent`, `failed` or `expired`. "Every route is
exhausted" is therefore not a terminal state of its own: the modem's own rules decide
whether such a message is held, retried or failed.

This is what keeps a rung from short-circuiting the modem's rules — an over-long message
refused by the part budget must not be a rung's verdict on the message, and a modem that
is temporarily off the network must hold the message at its full budget rather than have
the ladder call it failed.

[unbacked · today `POST /sms/send` hands straight to the modem queue at app/api/router.py:29]

#### Scenario: No messenger rung accepts the message
- **WHEN** `tg_user` and `max_user` both report a miss
- **THEN** the message is handed to the modem path and is subject to its retry budget and hold rules

#### Scenario: The modem is off the network when the ladder reaches it
- **WHEN** the modem rung is reached while the modem is deregistered
- **THEN** the message is held at its full budget, and is not failed by the ladder

### Requirement: A message is offered to routes in a configured order and stops at the first acceptance

The gateway SHALL hold, per message class, an ordered list of routes, and SHALL offer the
message to them in that order until one accepts it. A route that cannot carry the
message's class, reports a miss, or is unavailable SHALL be skipped and the next route
tried.

The order SHALL be configuration, not a branch in code: adding or reordering a route SHALL
NOT require a deployment. A route-order rule that cannot be parsed SHALL raise an alert and
SHALL NOT be read as an empty list. **An absent or empty list SHALL mean the modem alone**,
never "no routes": settings are seeded from code defaults for any key with no row
(app/settings_store.py:349-367), and an empty default would fail every message on the
first restart after deployment, on a host carrying live customer traffic.

The rule SHALL be refused at save time with the offending part named, in the manner every
other structured setting in this gateway is (app/settings_store.py:152-179), rather than
accepted and alerted about mid-traffic.

[unbacked]

#### Scenario: The first route misses and the modem delivers
- **WHEN** the list for this class is `tg_user, modem` and the recipient has no Telegram account
- **THEN** `tg_user` reports a miss and the message is handed to the modem path

#### Scenario: No route list is configured
- **WHEN** a message's class has no configured route list
- **THEN** the message is offered to the modem alone, and no message is failed for want of a route

#### Scenario: A malformed route order is saved
- **WHEN** an operator saves a route-order rule that does not parse
- **THEN** the save is refused naming the offending part, and the stored rule is unchanged

### Requirement: Every rung and the ladder as a whole are bounded in time

Each route call SHALL be bounded by a configured deadline, and the ladder as a whole SHALL
be bounded by a budget **shorter than the first retry interval** of the modem path.

A rung that exceeds its deadline SHALL be treated as indeterminate, not as unavailable.

Two mechanisms already act on a message on a timer and know nothing of rungs: the retry
scheduler becomes due at `next_attempt_at`, and the pending sweep fails a message older
than the retry deadline. A ladder that can outlive either produces a message sent twice or
a `failed` webhook for a message a rung is still sending. An exception cannot express a
client library that never returns, so the bound is required, not advisory.

[unbacked · app/modem/manager.py:441-461 and app/db/queries.py:222 derive their deadlines
from the modem backoff alone]

#### Scenario: A messenger client hangs
- **WHEN** a route call does not return
- **THEN** the rung is abandoned at its deadline, the outcome is indeterminate, and the send path is not blocked

#### Scenario: The ladder would outlive the first retry interval
- **WHEN** the sum of the configured rung deadlines exceeds the first retry interval
- **THEN** the configuration is refused at save time

### Requirement: The route that carried a message is recorded and reported

The gateway SHALL record on the message the route that accepted it, **before** the status
write that notifies the owning application, and SHALL report that route in
`GET /sms/{id}`, in the delivery webhook and in the admin console's conversation view. The
field SHALL be additive: a consumer that ignores it SHALL be unaffected.

A message no route has yet accepted SHALL report no route rather than a guess. So that
absence has exactly one meaning, the migration SHALL backfill `modem` on every message
that reached `sent` before this change: every one of them was carried by the modem, and
that is known without inference.

This is what allows a consuming application to tell a person where their code went, which
is the only defence against a code delivered into an abandoned chat: no messenger route
can report that a message was read. It has a second consumer — the share of messages not
carried by the modem is the only observable measure of whether the ladder is working at
all — and a third, the operator diagnosing "the customer says nothing arrived".

[unbacked · messages carry no route column today; the admin conversation view is built at
app/db/queries.py:526-534]

#### Scenario: A code delivered by Telegram is reported as such
- **WHEN** `tg_user` accepted the message
- **THEN** `GET /sms/{id}`, the delivery webhook and the admin conversation all report route `tg_user`

#### Scenario: A message predating this change
- **WHEN** a message that reached `sent` before this change is read
- **THEN** its route is `modem`, not absent

#### Scenario: Nothing has accepted the message yet
- **WHEN** the message is still `pending` and no route has accepted it
- **THEN** the reported route is absent, not a default and not the first route in the list

### Requirement: A send request may name routes to skip, and the names are validated

A send request MAY name routes to be skipped for this message, and MAY instead name the
intent `force_sms`, which SHALL remain stable when routes are added or reordered.

An unrecognised route name SHALL be refused with HTTP 422 naming the offending value. A
request that would skip every route SHALL be refused with HTTP 422. Each refusal SHALL
carry its own `error` key in the existing `{"error": …}` body shape, so that a blacklisted
number, a brand that is not permitted, an unknown route name and an empty ladder are
distinguishable by a client that already has the contract.

Silently ignoring an unknown name is the failure this forbids: an application's "it never
arrived — send me an SMS" action would send by the same messenger again, and the person
who pressed it would receive nothing new.

[unbacked · no such parameter exists today, app/api/schemas.py:12-22]

#### Scenario: An application forces SMS
- **WHEN** a send names the intent `force_sms`
- **THEN** the message is offered to the modem path alone

#### Scenario: A route name is misspelled
- **WHEN** a send names `tg-user` for `tg_user`
- **THEN** the response is HTTP 422 naming `tg-user`, and no message row is created

#### Scenario: Every route is excluded
- **WHEN** a send would skip every route configured for its class
- **THEN** the response is HTTP 422 under its own `error` key, and no message row is created

### Requirement: Evidence about the modem is gathered only from messages offered to the modem

Evidence that the modem needs recovery SHALL be counted only over messages the ladder
offered to the modem rung. A period in which no message was offered to it SHALL NOT be
read as a period of modem failure, and stall evidence SHALL NOT persist across such a
period.

The stall detector was calibrated on the assumption that the modem sees all outbound
traffic — one message exhausting its budget is enough, because this gateway carries a
dozen messages a day. The ladder removes that assumption: successes that would clear the
evidence now happen elsewhere, while the rare message that does reach the modem can drive
the recovery ladder to its hard rung, which calls `os._exit(1)`
(app/modem/manager.py:1197) and takes both authenticated messenger sessions down with it.

[unbacked · the evidence is gathered at app/modem/manager.py today with no route predicate]

#### Scenario: The messengers carry a week of traffic
- **WHEN** no message has been offered to the modem for a week and then one exhausts its budget
- **THEN** that message alone is not sufficient evidence of a stall, and no recovery is triggered by it

### Requirement: Delivery evidence that suppresses a blacklist count is modem evidence

Only a delivery reported by the network SHALL suppress a permanent failure's count toward
a destination's blacklist threshold. A delivery inferred from a non-modem route SHALL NOT.

`has_delivered_to` asks `SELECT 1 FROM messages WHERE phone = ? AND status = 'delivered'`
with no route predicate (app/db/queries.py:424-430), and `record_permanent_fail` returns
early when it is true. Once a messenger route can write `delivered`, a number whose SIM is
dead but whose Telegram is alive would never reach the threshold, and the gateway would
retry SMS to it for ever.

This requirement is `descriptive` about the existing suppression, which no live
specification states, and `normative` about the new distinction.

[unbacked · app/db/queries.py:424-437]

#### Scenario: A number reachable in Telegram with a dead SIM
- **WHEN** a number has a messenger-inferred `delivered` message and then accumulates permanent SMS failures
- **THEN** those failures count toward the blacklist threshold as if no delivery had been recorded
