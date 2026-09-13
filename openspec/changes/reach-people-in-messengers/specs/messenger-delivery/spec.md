# messenger-delivery Specification

## Purpose

The gateway's pool of messenger sender accounts and the rules that bind them: which
application may send under which brand, how a recipient is found from a phone number
alone, what an attempt may conclude, how fast one account may write to people who did not
ask to hear from it, and what is recorded so that a person who asks can be answered.
`outbound-send` owns the ladder that picks a route; this seam owns the routes that reach
into a messenger and the identity they send under.

## ADDED Requirements

### Requirement: A messenger route addresses a recipient by phone number alone and leaves no contact behind

A messenger route SHALL resolve the recipient from the phone number carried by the send
request, and SHALL NOT require any stored association between that number and a chat,
account or prior conversation.

Resolution SHALL leave no durable contact entry on the sender account once the send has
concluded. Adding the recipient as a contact SHALL be used only where resolution is
impossible without it, and SHALL be undone afterwards.

Left alone, the account accumulates a complete list of the service's customers' phone
numbers, held on the vendor's servers under an account whose session file sits on this
host; mass contact import is itself a signal the vendors act on; and the recipient may see
themselves added as somebody's contact.

[unbacked · Telethon resolves a number through contact import; PyMax exposes
`search_by_phone` at src/pymax/infra/user.py:55 and `add_contact` at :75]

#### Scenario: A person who has never met us in the messenger is reached
- **WHEN** a send is routed to `tg_user` for a number with no prior contact with any of our accounts
- **THEN** the route resolves the number and delivers, without any linking step having occurred

#### Scenario: The send concludes
- **WHEN** resolution required adding a contact and the send has concluded either way
- **THEN** the contact entry no longer exists on the sender account

#### Scenario: No account exists on that number
- **WHEN** the resolution finds no account for the number
- **THEN** the route reports a miss, the message is not failed, and the ladder continues

### Requirement: An attempt concludes in one of four outcomes, and an indeterminate attempt stops the ladder

Every route SHALL report exactly one of four outcomes: **accepted**, **miss** (this
recipient cannot be reached by this route), **unavailable** (this route cannot be used
right now), or **indeterminate** (the send may already have happened).

A failure that occurs after the request has left this process SHALL be indeterminate
unless the library gives a positive statement that nothing was sent. A rung that exceeds
its deadline SHALL be indeterminate.

An indeterminate outcome SHALL stop the ladder: the message SHALL NOT be offered to any
lower rung, and the outcome SHALL be recorded. A miss and an unavailability SHALL both let
the ladder continue, and neither SHALL be surfaced to the calling application as a
delivery failure of the message.

Three outcomes are not enough, and the missing one is the expensive one. A connection lost
after the frame was written, classified as unavailable, sends the same verification code
again down the next rung: the person receives two different codes and neither works. This
gateway has already decided for the modem that a possibly-transmitted message is never
re-offered; the messenger routes SHALL NOT be given the opposite default.

[unbacked]

#### Scenario: The connection drops after the message was written
- **WHEN** a client raises after the request left the process, with no statement that nothing was sent
- **THEN** the outcome is indeterminate, the ladder stops, and the modem is not offered the message

#### Scenario: The recipient hides from lookup by phone
- **WHEN** the recipient's privacy settings prevent resolution by phone number
- **THEN** the route reports a miss and the ladder continues, and the application sees no error

### Requirement: Each outcome is recognised by a named vendor error or a captured sample

The mapping from a library's failure to `miss`, `unavailable` or `indeterminate` SHALL be
written against a named vendor error or a captured live sample, and the mapping SHALL cite
it. A verdict recognised by a string match invented by us SHALL NOT be written.

This gateway has paid for this rule once: the modem's failure classification enumerates
`+CMS` and `+CME` codes by number, and 96 was filed as permanent when it is not. The
messenger routes carry the same risk in a worse place — a transient network error read as
"the account is limited" disables a working route, and a limited account read as an
ordinary error leaves it enabled and reported to nobody.

[unbacked · no captured sample exists yet for any messenger outcome]

#### Scenario: A verdict has no cited evidence
- **WHEN** a failure mapping cites neither a named vendor error nor a captured sample
- **THEN** it is not written, and the outcome defaults to indeterminate

### Requirement: The sender identity is derived from the caller's credential

The permitted set of sender brands SHALL be derived from the authenticated `app_id`. A
brand key carried in a request SHALL be accepted only after it is confirmed to be a member
of that application's permitted set; otherwise the gateway SHALL refuse the request with
HTTP 422 under its own `error` key, and SHALL NOT send under any brand.

A request that names no brand SHALL use that application's configured default brand. An
application with **no** configured default SHALL be refused with HTTP 422 naming that
cause — it SHALL NOT be defaulted to any account, and the messenger rungs SHALL NOT be
silently skipped for it.

One account SHALL NOT be bound to more than one brand, and a configuration that binds it
twice SHALL be refused at save time. Otherwise the non-substitution rule below is
satisfied and vacuous: a parking code would arrive from the GM+ account with every SHALL
obeyed.

[unbacked · the request carries no brand today, app/api/schemas.py:12-22]

#### Scenario: An application asks for a brand it does not own
- **WHEN** an application whose permitted set is `{gmplus}` requests the brand `sokol`
- **THEN** the response is HTTP 422, no message is created, and no messenger send is attempted

#### Scenario: The brand is omitted
- **WHEN** a permitted application sends without naming a brand and has a configured default
- **THEN** the message is sent under that default brand

#### Scenario: An application has no default brand
- **WHEN** a permitted application sends without naming a brand and has no configured default
- **THEN** the response is HTTP 422 naming that cause, and the messenger rungs are not silently skipped

#### Scenario: One account is bound to two brands
- **WHEN** a configuration binds one account to both `sokol` and `gmplus`
- **THEN** the save is refused

### Requirement: An unavailable sender is never substituted by another brand

When the account for the requested brand cannot send — it is limited, logged out, rate
bound or missing — the gateway SHALL skip that route and continue down the ladder. It
SHALL NOT send the message from an account belonging to a different brand.

#### Scenario: The brand's account is limited
- **WHEN** the `sokol` Telegram account is limited and a `sokol` send is routed to `tg_user`
- **THEN** `tg_user` is skipped and the ladder continues, and no send is made from any other brand's account

### Requirement: A messenger client library is confined behind the route interface

No type, exception or session object of a messenger client library SHALL cross the route
interface, and every call into one SHALL be bounded by a configured deadline. A failure
inside such a library — including a protocol change on the vendor's side — SHALL be
contained as an outcome of that one route, and SHALL NOT prevent any other route from
carrying the message nor block the send path for other messages.

This is required because `max_user` speaks an unofficial internal API that its own author
warns may change without notice.

[unbacked]

#### Scenario: The MAX client raises on a changed protocol
- **WHEN** the MAX client raises before the request leaves the process
- **THEN** `max_user` is unavailable, the ladder continues, and the modem carries the message

#### Scenario: The MAX client never returns
- **WHEN** a call into the client does not return
- **THEN** it is abandoned at its deadline and no other message waits behind it

### Requirement: A sender account is rate bound durably, atomically, and per recipient

Each sender account SHALL have a configured maximum number of sends per rolling hour and
per rolling day, counted from **durable** records that survive a restart, and an allowance
SHALL be consumed by a claim that cannot be granted twice for the same send.

A bound SHALL also apply **per recipient across every account**: one person SHALL NOT
receive messages from two brands' accounts within a configured window.

The configured maxima SHALL start conservatively and SHALL be raised deliberately; no
vendor publishes the threshold at which an account is limited, and the penalty on the
second occurrence is permanent.

Exceeding any bound SHALL make the route unavailable; the send SHALL NOT be queued behind
the bound. A limit rule that cannot be parsed SHALL raise an alert and SHALL NOT be read
as absent or as zero, and SHALL be refused at save time with the offending part named.

An in-memory window satisfies a rolling-window requirement and is wrong here: this process
exits by design — the modem's hard recovery rung calls `os._exit(1)`, and every push to
`master` restarts the service — and each restart would hand the account a fresh allowance
inside the same hour. Retry state in this gateway is persisted for exactly this reason.

[unbacked · app/db/migrate.py:304-312 records the persisted-retry precedent]

#### Scenario: The hourly limit is reached
- **WHEN** an account has already sent its hourly maximum and another send is routed to it
- **THEN** the route is unavailable, the ladder continues, and nothing waits for the hour to roll

#### Scenario: The limit rule is malformed
- **WHEN** the stored limit rule does not parse
- **THEN** an alert is raised and the rule is not treated as "no limit"

#### Scenario: The service restarts inside the hour
- **WHEN** an account has consumed its hourly allowance and the service restarts
- **THEN** the allowance is still consumed, and the route is unavailable until the window rolls

#### Scenario: Two sends race on one account
- **WHEN** two sends read the same remaining allowance of one concurrently
- **THEN** exactly one claim is granted and the other finds the route unavailable

#### Scenario: Two brands address one person at once
- **WHEN** two applications send to the same number under two brands within the window
- **THEN** the second is not carried by a messenger route

### Requirement: Every rung offered a message leaves a durable record

The gateway SHALL record, for every rung offered a message, the message, the route, the
account, the outcome and its reason, append-only. This record SHALL be the source of the
rate windows, of the alerting below, and of the answer to a person who asks how their
number was used.

Without it, the two states with opposite remedies — *our account is dead* and *these
recipients have no messenger account* — are indistinguishable, because both appear only as
an absence of acceptances. This gateway already keeps such an account where the stakes are
evidentiary: `delivery_reports` is append-only, records the raw line before anything is
decided, and keeps even the candidates it rejected.

[unbacked · app/db/migrate.py:223-264 and app/db/queries.py:271-297 record the precedent]

#### Scenario: A rung misses
- **WHEN** `tg_user` reports a miss
- **THEN** the record carries the message, route, account, outcome and reason, and is not overwritten later

### Requirement: A route that stops working is alerted on the aggregate, not on the vendor's goodwill

The gateway SHALL alert when a route stops accepting: after a configured number of
consecutive non-acceptances on one route, or when a route's share of acceptances over a
window reaches zero while messages are still being offered to it. It SHALL also alert when
a route observes that its account has been limited or logged out, naming the brand and the
messenger.

The aggregate alert is the load-bearing one. An alert conditioned only on recognising
"limited" is satisfied by an implementation that never recognises it, while the silent
degradation continues: every send falls through to the modem, which is refusing МегаФон,
and nobody is told until logins stop.

[unbacked · app/alerting.py carries the alert surface]

#### Scenario: The vendor changes a payload
- **WHEN** every send to a route has missed for the configured run, with no "limited" signal
- **THEN** an alert is raised naming the route

#### Scenario: Telegram limits an account
- **WHEN** a send fails in a way that indicates the account is limited
- **THEN** an alert naming the brand and the messenger is raised

### Requirement: A sender session is a credential

The session material of a sender account SHALL be treated as equal to the account itself:
marked secret, excluded from backups and from version control, and replaceable. Possession
of it is possession of every private conversation the brand account has had and the ability
to write as the brand.

A code needed to re-authenticate a sender account SHALL NOT be dispatched to any
application's webhook and SHALL NOT be posted to the operator alert channel. Where such a
code arrives by SMS on a SIM this gateway reads, the inbound path SHALL withhold it from
both: today an inbound message is persisted, dispatched to a configured application by
prefix and, with `notify_inbound` on, posted in full to the operator channel
(app/modem/manager.py:914-948), which would publish the login code of our own account to
third parties by design.

[unbacked · the precedent for marking a credential is `alert_bot_token` with
`is_secret=True`, app/settings_store.py:31]

#### Scenario: A re-login code arrives on the gateway's own SIM
- **WHEN** a messenger login code is received as an inbound SMS
- **THEN** it is neither dispatched to an application nor posted to the alert channel

### Requirement: A recipient can tell the sender is us, and a refusal suppresses the route

Each brand's account SHALL have a recorded presentation — display name, username, photo
and a description naming the service — and the first message to a recipient SHALL identify
who is writing and why.

A recipient's reply SHALL reach the operator by the same path an inbound SMS does, and a
recipient's refusal SHALL suppress messenger routes for that number **without**
blacklisting it out of SMS.

A personal account writing a payment link to a stranger who cannot verify it is us is
correctly read as fraud on the evidence available to them, and the only action the design
otherwise leaves them is the report that costs the brand its account permanently. Being
answerable is the cheapest reduction of that risk.

[unbacked · the inbound path exists for SMS at app/modem/manager.py:945-948; no messenger
route reads replies today]

#### Scenario: A recipient asks whether it is really us
- **WHEN** a recipient replies to a brand account
- **THEN** the reply reaches the operator as an inbound message does

#### Scenario: A recipient says to stop writing
- **WHEN** a recipient refuses further messages
- **THEN** messenger routes are suppressed for that number, and SMS to it is unaffected

### Requirement: A number offered to a messenger route is recorded as disclosed, and may be withheld

A number offered to a messenger route SHALL be recorded as disclosed to that vendor, with
the brand account and the time, whatever the outcome. Resolution sends the number to the
vendor **before** any verdict, so a miss is a disclosure too.

A number MAY be withheld from messenger lookup entirely, without being blacklisted out of
SMS.

The record of the route that *accepted* is exactly the set of disclosures that is not the
interesting one. A person asking how their number reached a MAX contact search is owed an
answer the ledger can give.

[unbacked]

#### Scenario: A messenger rung misses and the modem carries the message
- **WHEN** `max_user` resolves a number, misses, and the modem delivers
- **THEN** the disclosure to MAX is recorded even though MAX carried nothing

#### Scenario: A number is withheld
- **WHEN** a number is marked withheld from messenger lookup
- **THEN** no messenger route resolves it, and SMS to it is unaffected
