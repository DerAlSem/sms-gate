## Purpose

Which way out the gateway reaches a subscriber. There are three — the local modem, which
carries arbitrary text; Telegram's Gateway API, which carries a verification code to a
subscriber reachable in Telegram; and a vendor flash call, which carries four digits as the
last digits of a calling number. This capability owns the choice between them, the rule that
expresses it, the order in which the paid ones are tried, what a route is capable of carrying,
and what happens when the choice cannot be honoured. It exists because the modem route has
been withdrawn by operators before, at whole-estate scale, and the replacement must be
reachable by configuration rather than by deploying code during an outage.

## ADDED Requirements

### Requirement: Every outbound attempt is assigned exactly one route before it leaves

A message or a verification SHALL be assigned a route — `sms_out`, `tg_gateway` or `flash_call` —
before any transmission is attempted, and that assignment SHALL be recorded against it. It
SHALL NOT be carried by a route other than the one recorded, and SHALL NOT be carried by two
at once.

Where a ladder advances a verification from one paid rung to the next, each rung SHALL be a
recorded attempt of its own, carrying its own route, its own vendor identifiers and its own
cost. The verification SHALL name the route that actually carried the code it is matching
against. A ladder written as one attempt whose route changes underneath it cannot answer what
the second rung cost or why the first was abandoned, and both questions are asked the first
time a bill looks wrong.

The recorded route SHALL be readable afterwards, because the cost, the outcome vocabulary and
the meaning of success all differ by route, and none of them can be reconstructed afterwards
from the message alone. It SHALL be a field of the item it belongs to — of the message for a
send, of the verification for a verification — and SHALL stay readable for that item's whole
life.

The route names the way out. The method an application is told about SHALL be derived from the
route by a mapping this capability owns and states, and no other capability SHALL define a
second vocabulary for the same decision. Two words for one choice agree while there are
exactly two routes and disagree on the day there is a third.

**That day arrived on 18.09.2026**, and the disagreement it predicted was real rather than
hypothetical: the messenger ladder proposed on 12.09.2026 named the same ways out on a second
axis separate from a direction of `outbound`/`inbound`, while a third change named the
subscriber's own incoming call `call` as well — two mechanisms, one word, in which the modem
either does everything or does not participate at all.

✅ **The owner settled it on 18.09.2026: one flat field, names disambiguated.** The values are
`sms_out` (the gateway's SIM sends), `sms_in` (the subscriber texts the gateway), `call_in`
(the subscriber calls the gateway's SIM), `flash_call` (the vendor dials), `tg_gateway`,
`tg_user`, `max_user` and `app_bot`. **`call` is retired outright** and `modem` is retired in
favour of `sms_out`, which states the direction the old name left to be inferred. The gateway
SHALL hold exactly this vocabulary, and SHALL NOT carry a second one for the same choice.

[unbacked · no route concept exists in the code today]

#### Scenario: A route is decided and recorded before transmission
- **WHEN** a send or a verification is accepted
- **THEN** its route is decided and stored before any transmission is attempted

#### Scenario: The recorded route is the one used
- **WHEN** an item carries a recorded route of `flash_call`
- **THEN** the modem sender does not pick it up, and the reverse for `sms_out`

### Requirement: The route is chosen by a configured rule keyed on the recipient's operator

Route selection SHALL be expressed as configuration read at send time, keyed on the
recipient's operator as recorded in `number_operators`. Adding, changing or removing an
operator's route SHALL NOT require a code change or a deploy.

An entry's value SHALL be an **ordered list** of routes rather than a single one, and the
gateway SHALL try them in the order written. A single-route entry is the list of length one,
so the modem's own entries are unaffected. The order is the thing being configured: which
paid way out is attempted first is a money decision, it changes as vendors' prices and
reachability change, and it is precisely the decision that must not need a deploy.

No operator name SHALL appear in a branch in the sending path. The rule's initial content —
МегаФон to `[tg_gateway, flash_call]`, everything else to `[sms_out]` — is data, and the change that
introduces it is not permitted to hard-code it, because the event this capability exists for
is the next withdrawal rather than this one. Nor SHALL the ladder's order be hard-coded: an
implementation that tries Telegram first because the code says so, rather than because the
entry says so, satisfies the letter of this requirement and defeats it.

The rule SHALL NOT be keyed on the originating application. An `app_id` in the rule is the
same hard-coding moved into configuration, and it would route by who is asking rather than by
what is reachable. Who is allowed to spend on a paid route is a separate question from which
route reaches a subscriber, and it is answered below rather than by the rule.

The rule SHALL be held in `settings` as a typed setting of its own, validated when it is
saved: each entry SHALL name an operator and a non-empty ordered list of routes drawn from the
known routes, entries SHALL be stripped of surrounding whitespace on write as well as on read,
and an entry naming an unknown route, or naming the same route twice, SHALL be refused at save
time rather than discovered at send time. It SHALL NOT be carried by the existing
dispatch-route setting, which requires a webhook URL on every entry and would reject this rule
outright.

**`settings` rather than `.env`, by the owner's decision of 18.09.2026**, and the code had
already shown why: `seed_from_env()` copies an environment variable into `settings` only for a
key that has no row yet, so `.env` is a one-time seed and never the place a value lives. A
rule kept in `.env` would also need a restart to change, and a restart drops sending sessions
— which is the deploy this requirement exists to avoid, merely spelled differently.

A stored rule that cannot be parsed SHALL raise an operator alert and SHALL NOT be treated as
an empty rule. Read as empty, a broken rule sends the whole of an operator's traffic back to
the route that is rejecting it, and does so without a single line in the log — the one failure
mode of this capability that is both total and silent.

The default route SHALL be an entry of the same rule, changeable by the same means. A default
compiled into the sending path is the hard-coding this requirement forbids, merely spelled
differently.

Two entries name no operator and are spelled with characters an operator name cannot contain,
so that neither can ever be shadowed by a real network. `*` answers for an operator the rule
does not mention. `?` answers for an operator that could not be resolved at all, and it is
separate from `*` on purpose: the numbers most likely to lack an operator row are the ones
never messaged before, and a first-time recipient is exactly who a confirmation code is usually
for, so the unknown case is one the owner configures rather than one arrived at by accident.

A third reserved word, `refuse`, is not a way out but the absence of one, and it is expressible
for the reason the rule is configuration at all: refusing is sometimes the correct answer and
must not need a deploy either. It SHALL stand alone in an entry — a ladder that continues past
a refusal is not a refusal.

A rule that is readable but cannot answer for this operator — no entry, no `*`, no `?` — SHALL
refuse rather than fall back to a route of the implementation's choosing. A default arrived at
by accident is the silent failover this capability refuses by name elsewhere, and it would be
arrived at exactly when the rule is half-configured.

Two entries whose operator names normalise to the same thing SHALL be refused at save time.
Which of the two wins would otherwise be decided by the order of the list, invisibly, and the
data already holds one operator under two spellings.

[backed · `app/verification/rule.py`, guarded by `tests/test_routing_rule.py`; eight mutations
in `bite-rule.sh` — exact-string matching, a hard-coded ladder order, an accepted unknown
route, a broken rule read as empty, an unanswerable rule guessing the modem, an accepted
`app_id`, two spellings of one operator, and a `refuse` continuing into a ladder — each turn a
guard red]

#### Scenario: An operator with a configured route
- **WHEN** the rule routes МегаФон to `[tg_gateway, flash_call]` and a verification is requested for a МегаФон number
- **THEN** the verification is routed `tg_gateway` first, and `flash_call` only if that rung declines it

#### Scenario: The ladder's order is data, not code
- **WHEN** the entry for an operator is rewritten as `[flash_call, tg_gateway]` while the service is running
- **THEN** subsequent verifications for that operator try `flash_call` first, with no restart and no code change

#### Scenario: An operator with no entry in the rule
- **WHEN** an item is addressed to an operator the rule does not mention
- **THEN** it is routed `sms_out`, the configured default

#### Scenario: An entry naming a route that does not exist
- **WHEN** a rule entry naming an unknown route is saved
- **THEN** the save is refused with that reason, and the rule in force is unchanged

#### Scenario: The rule changes without a deploy
- **WHEN** a second operator is added to the rule while the service is running
- **THEN** subsequent items for that operator take the new route, with no restart and no code change

#### Scenario: An operator that could not be resolved at all
- **WHEN** a verification is requested for a number whose operator the lookup could not resolve
- **THEN** it takes the rule's `?` entry rather than its `*` entry, and either may be set to `refuse`

#### Scenario: A rule that cannot answer for this operator
- **WHEN** the rule holds neither an entry for the operator nor a `*` entry
- **THEN** the item is refused rather than routed to a way out the implementation chose

### Requirement: A route's credentials live in `settings`, marked secret, and never in the environment

A route that needs credentials SHALL read them from `settings`, and each SHALL be its own
setting marked secret. The admin console SHALL be able to say whether a credential is
configured and SHALL NOT render its value; changing one SHALL NOT require a restart. The
gateway already holds a secret on exactly these terms — `alert_bot_token` — and this is that
precedent, not a new mechanism.

**`.env` is not where such a value lives, and this is a fact about the code rather than a
preference.** `seed_from_env()` copies an environment variable into `settings` only for a key
that has no row yet: placed before the first run it is copied once and lives in `settings`
afterwards, and placed after, it is read by nobody. The gateway SHALL NOT read a vendor
credential from the environment at send time. Owner's decision of 18.09.2026, confirming what
the code had already shown on 11.09.2026.

There are two vendors behind the ladder and therefore two credentials: uCaller's, a single
bearer string carrying both an API key and a service id, and Telegram Gateway's bearer token.
They SHALL be separate settings. A route whose credential is absent SHALL NOT be attempted and
SHALL NOT be called unauthenticated to find out.

A rung skipped for a missing credential SHALL raise an operator alert on the configuration the
gateway ships with, and the ladder SHALL then advance past it as it would past a decline. This
is deliberately the lesser of two bad outcomes: refusing an operator's traffic outright because
the *cheap* rung is unconfigured means nobody on that network logs in, while advancing means
paying more than intended — bounded by the spend ceiling, and loudly. It is the one place in
this capability where a configuration gap costs money rather than traffic, and it is written
down so that it is a decision rather than a discovery.

**A ladder every one of whose rungs was skipped SHALL fail the verification with a reason
naming the missing credentials, and SHALL NOT fall back to `sms_out`.** Advancing past the last
rung leaves nothing to advance to, and the quiet answer — sending it over the modem — is the
silent fallback this capability forbids everywhere else, reached here by exhausting a list
rather than by deciding anything.

[unbacked · `is_secret` precedent and `seed_from_env()`: app/settings_store.py]

#### Scenario: A credential placed in the environment after the first run
- **WHEN** a vendor credential is written to `.env` for a key that already has a row in `settings`
- **THEN** the running gateway does not use it, and the value in `settings` remains the one in force

#### Scenario: A secret is not rendered
- **WHEN** an operator opens the settings page
- **THEN** it says whether each vendor credential is configured, and shows neither value

#### Scenario: A rung with no credential
- **WHEN** the first rung of a ladder has no credential configured
- **THEN** it is not attempted, the operator is alerted on stock settings, and the ladder advances to the next rung

#### Scenario: A ladder with no credential anywhere
- **WHEN** no rung of an operator's ladder has a credential configured
- **THEN** the verification fails with a reason naming them, and nothing is sent over the modem instead

### Requirement: Operator names are matched normalised, never by exact string

An operator name in the rule SHALL be compared against the stored operator case-insensitively
over Cyrillic and after trimming surrounding whitespace. An exact-string comparison SHALL NOT
be used.

This is normative because the data already breaks it: `number_operators` holds МегаФон under
two spellings — `МЕГАФОН` and `МегаФон` — written by the same lookup at different times, and
on 08.09.2026 they covered 120 and 57 numbers respectively. A rule matching one spelling
would route a third of МегаФон subscribers correctly and the rest to a route that has been
rejecting them, and it would do so silently.

The comparison SHALL NOT be built on SQLite's `upper()`, `lower()` or `LIKE`, all of which
are ASCII-only in the shipped build and leave Cyrillic untouched. A measurement taken with
`upper()` on 08.09.2026 undercounted МегаФон traffic by half before the mistake was caught.

[unbacked · evidence for the two spellings: production `number_operators`, read 08.09.2026]

#### Scenario: The other spelling routes identically
- **WHEN** the rule names `МегаФон` and a number's stored operator is `МЕГАФОН`
- **THEN** it takes the same route as a number stored as `МегаФон`

#### Scenario: A stored name with surrounding whitespace
- **WHEN** a stored operator name differs from the rule's only by surrounding whitespace
- **THEN** the rule still matches it

### Requirement: An unknown operator does not block, delay or fail the attempt

The operator lookup is enrichment and SHALL remain so. Nothing SHALL be delayed, held or
failed because the recipient's operator is unknown, unresolved or stale: `record_operator`
never fails a send today, and routing SHALL NOT be the thing that makes it blocking.

When the operator is not known at routing time, the item SHALL take the route the rule
configures for the unknown-operator case and SHALL be recorded as having been routed without a
known operator, so that the case is countable rather than invisible. That route SHALL be part
of the rule's data and SHALL be settable to a refusal, because an unknown operator on a
network being refused is a coin toss with a person's login on it.

A **verification**, whose answer must name the method in the same response, SHALL resolve the
operator synchronously within a bounded time before answering, and SHALL NOT silently answer
with the default route when it could not.

This matters more than it looks: the numbers most likely to lack an operator row are the ones
never messaged before, and a first-time recipient is exactly who a confirmation code is
usually for. Today a send resolves such a number synchronously — `record_operator` is awaited
before the message is created and waits on the lookup up to its timeout — so what is unknown
at routing time is not "every new number" but every number whose lookup failed, and for those
the default route is a guess.

[normative · evidence: app/lookup/operator.py:23-45 (awaited before create_message at app/api/router.py:26, and waits on a cache miss) · conf: high]

#### Scenario: A first-time number whose lookup has not resolved
- **WHEN** a message is addressed to a number with no row in `number_operators`
- **THEN** it goes over the unknown-operator route without being failed for it, and the absence of the operator is recorded

#### Scenario: A verification for a number whose operator will not resolve
- **WHEN** a verification is requested and the operator cannot be resolved within the bound
- **THEN** it takes the configured unknown-operator route, which may be a refusal, and the answer says which method was chosen

#### Scenario: The lookup service is unreachable
- **WHEN** the operator lookup fails for every number for an hour
- **THEN** sending continues over the default route throughout, and nothing is failed for want of an operator

### Requirement: A route carries only what it is capable of carrying

Each route SHALL declare what it can carry. The `sms_out` route carries arbitrary text. The
`flash_call` route carries a verification code and nothing else: the code is the last four digits of
the calling number, so there is no field in which words, a link or a second sentence could
travel. The `tg_gateway` route carries a verification code and nothing else either, for a
different reason — `sendVerificationMessage` accepts a `code` and a `code_length` and no
message body at all, the wording being Telegram's rather than ours.

**Adding the third route therefore does nothing for the applications that are not sending
codes.** `gmp_app`, which sent 63 of August's 111 МегаФон messages and is growing, sends free
text with links, and neither paid route has a field to put it in. The ladder widens how a
*code* reaches a МегаФон subscriber; it does not narrow what this change costs the other
applications, and that cost is stated in the proposal unchanged.

An item whose assigned route cannot carry it SHALL NOT be handed to that route, SHALL NOT be
rerouted to another, and SHALL NOT be attempted. It SHALL be refused with a reason naming the
route and what it cannot carry.

The alternative — quietly sending such a message over the modem instead — is the automatic
failover this change refuses, arrived at by accident rather than by decision.

[unbacked]

#### Scenario: Free text addressed to an operator routed to the call route
- **WHEN** an application sends arbitrary text to a number whose operator is routed `flash_call`
- **THEN** the message is refused with a reason naming the route, and no AT command is issued

#### Scenario: A verification addressed to an operator routed to the modem
- **WHEN** a verification is requested for a number whose operator is routed `sms_out`
- **THEN** it is carried as an SMS, because the modem route can carry a code

### Requirement: A paid ladder tries its rungs in order, and nothing is bought before every gate that could refuse has been passed

An operator's entry may name more than one route. The gateway SHALL attempt them in the order
written, SHALL attempt each rung of a verification's ladder at most once, and SHALL advance to
the next rung only when the current one **declines to carry** the verification — not when it
carries it and then fails.

That makes three classes of outcome rather than two, and the third is the expensive one: a rung
that **carried and then failed** SHALL stop the ladder and fail the verification with that rung
named. Advancing there would buy the same code at the second vendor while the first vendor's
fee cannot be refunded until its `ttl` runs out — paying twice for one login, which is the
single most expensive mistake this ladder can make.

A rung that cannot carry **this particular item** SHALL be recorded as such and SHALL NOT be
counted as a decline. The case that exists today is a verification with less life left than the
vendor's `ttl` floor of thirty seconds: inflating the `ttl` to reach the floor would hand the
vendor a message outliving the verification it belongs to, while the automatic refund on
non-delivery is tied to that same `ttl`. A decline is a statement about the **subscriber**, and
a rung that appears to decline everyone is a rung that will be taken out of the rule for the
wrong reason.

Each rung's attempt SHALL be recorded **before** its vendor is contacted, and completed
afterwards. The ordering is the money's: a process that dies between a vendor's confirmation
and our record leaves a fee that belongs to nothing, and the only symptom of that is a balance
that drifts.

A route named by the rule that nothing is configured to carry SHALL NOT be attempted, SHALL
raise an operator alert, and the ladder SHALL advance past it. This is the one configuration
gap that costs money rather than traffic — every verification still completes, by the dearer
rung — and it is therefore the one that must be loud on stock settings.

On `tg_gateway`, declining is `checkSendAbility` reporting that the subscriber cannot be
reached, or not answering within the acceptance bound. On `flash_call`, there is no declining rung
below it; a ladder SHALL end in a route that either carries or fails.

🔴 **`checkSendAbility` is not a free probe, and the design must not be built as though it
were.** The vendor's reference is explicit: *"If the ability to send is confirmed, a fee will
apply according to the pricing plan."* What is free is the **second** call — *"Within the scope
of a `request_id`, only one fee can be charged. Calling `sendVerificationMessage` once with the
returned `request_id` will be free of charge, while repeated calls will result in an error"* —
and what is returned is an undelivered message: *"If a message is not delivered within the
specified `ttl`, the request fee will be refunded automatically."*

So the ladder is cheap for exactly two reasons, and neither is "the check is free": an
**unreachable** subscriber costs nothing, and a **confirmed but undelivered** one is refunded.
Against that, the `flash_call` rung is charged for a call that was *placed*, whether or not anyone
read the digits.

Two consequences follow, and both are normative:

1. **Every gate that can refuse a verification SHALL be evaluated before the first rung is
   contacted** — the blacklist, the number's normalisation, the per-number limits, the
   application's entitlement to spend and the spend ceiling. A gate evaluated after a confirmed
   ability check refuses something already paid for, and no refund path exists for a fee whose
   message was never sent: the refund is tied to non-delivery within a `ttl`, and a `ttl` only
   starts when a message is sent.
2. **A confirmed ability check SHALL be followed by exactly one `sendVerificationMessage`
   carrying its `request_id`.** It SHALL NOT be abandoned, and SHALL NOT be repeated with the
   same `request_id`, which the vendor answers with an error rather than a second message.

An ability check that does not answer within the bound SHALL be recorded as **possibly
charged** and counted separately from both outcomes. A confirmation we never saw is a fee that
cannot be spent and cannot be refunded, and without a count an unexplained fall in the vendor's
reported balance has no name to look for.

🟢 **The decline this whole ladder is built on is spelled `PHONE_NUMBER_NOT_AVAILABLE`, and
that spelling comes from a captured refusal rather than from any document.** The vendor's
reference names exactly one error string — `ACCESS_TOKEN_INVALID` — and for "this subscriber
is not in Telegram" says only that "an appropriate error will be returned". Task 1.7, run
20.09.2026 against a real working number whose owner has no Telegram, is what closed the gap:
`{"ok": false, "error": "PHONE_NUMBER_NOT_AVAILABLE"}`, on HTTP 200, charged nothing. The
gateway SHALL recognise it as a decline of the **subscriber**.

⚠️ **One capture fixes the spelling and does not bound the meaning.** Whether the vendor
answers the same string for a number that is malformed, unallocated or merely unroutable is
not established, and SHALL NOT be assumed in either direction. Nothing turns on it while both
readings send the ladder the same way; what will turn on it is the decline count, because a
rung that appears to decline everyone is a rung taken out of the rule for the wrong reason.

An `ok: false` the gateway still cannot place SHALL be treated as **unclassified**: the ladder
SHALL advance past it as it would past a decline, **and** the operator SHALL be alerted. Both,
because the two ways of guessing fail in opposite directions and each is invisible. Read as a
decline, a rotated token would advance every verification to the dearer rung and tell nobody —
the bill would be the only symptom. Read as a failure, an ordinary unreachable subscriber
would raise an alert per verification and the noise would bury the real one. Advancing and
alerting is wrong in neither direction; it is merely loud, and with the ordinary decline now
named it is no longer loud about the ordinary case.

An error string the gateway *can* place — today only `ACCESS_TOKEN_INVALID` — SHALL be
recorded as a refusal of **us** rather than of the subscriber, and SHALL NOT be counted as a
decline against the rung: a rung that appears to decline every subscriber is a rung that will
be taken out of the rule for the wrong reason.

**Whether a message the Gateway accepted and then failed to deliver within its `ttl` escalates
to the `flash_call` rung is not decided by this change.** Until the owner decides it, such a
verification SHALL fail with that reason and SHALL NOT be escalated. The safe default is the
one that cannot spend money on a decision nobody has taken; the argument for the other is that
the fee is refunded anyway, and it is a real argument, which is why this is an open question
and not an omission.

[backed · live samples captured 20.09.2026 by task 1.7 and kept in `captures/`: `probe-1.7-check-declined.json` (the decline, free), `probe-1.7-check-able.json` (the confirmation, `request_cost: 0.01`, `remaining_balance: 99.99`) and `probe-1.7-send.json` (the send carrying the returned `request_id`). Guarded by `tests/test_tg_gateway_adapter.py`. Two halves remain on the vendor reference and are marked where they are asserted: that a second call with the same `request_id` is refused rather than billed, and that an undelivered message is refunded at the end of its `ttl` — no sample shows either, and `is_refunded` has now been absent from ten captures running. The driver itself —
`app/verification/ladder.py` and `app/verification/tg_carrier.py` — is guarded by
`tests/test_ladder_walk.py` and `tests/test_tg_gateway_carrier.py`; seventeen mutations in
`bite-ladder.sh` and `bite-carrier.sh` each turn a guard red, among them gates that do not run
first, silence recorded as a decline, a bound handed to each rung again, a hard-coded order,
a fee recorded only after the send, and a failed send advancing the ladder]

#### Scenario: The subscriber is not reachable in Telegram
- **WHEN** `checkSendAbility` answers `ok: false` with `PHONE_NUMBER_NOT_AVAILABLE`
- **THEN** nothing is charged for it, the ladder advances to `flash_call`, and the decline is recorded against the `tg_gateway` rung

#### Scenario: The vendor refuses with an error string the gateway cannot place
- **WHEN** `checkSendAbility` answers `ok: false` with an error the gateway does not recognise
- **THEN** the ladder advances to `flash_call` as it would past a decline, and the operator is alerted

#### Scenario: The vendor refuses us rather than the subscriber
- **WHEN** `checkSendAbility` answers `ok: false` with `ACCESS_TOKEN_INVALID`
- **THEN** it is recorded as a refusal of the gateway, is not counted as a decline against the rung, and the operator is alerted

#### Scenario: The subscriber is reachable in Telegram
- **WHEN** `checkSendAbility` confirms the subscriber
- **THEN** the code is sent with that `request_id`, no call is placed, and the one fee already incurred is recorded against the verification

#### Scenario: The ability check does not answer in time
- **WHEN** `checkSendAbility` has not answered within the acceptance bound
- **THEN** the ladder advances to `flash_call` and the check is counted as possibly charged rather than as a decline

#### Scenario: A gate that would refuse is reached after the money
- **WHEN** a verification would be refused by the spend ceiling or by the application's entitlement
- **THEN** it is refused before any rung is contacted, and no ability check is made

#### Scenario: A rung that carried and then failed
- **WHEN** a confirmed ability check is followed by a send the vendor refuses
- **THEN** the ladder stops rather than advancing, the verification fails naming that rung, and the fee already incurred stays recorded

#### Scenario: A rung that cannot carry this verification
- **WHEN** a verification has less life left than the vendor's `ttl` floor
- **THEN** the rung is not bought at all, and the outcome recorded is not a decline

#### Scenario: A route nothing is configured to carry
- **WHEN** the rule names a route for which no carrier is configured
- **THEN** it is not attempted, the operator is alerted on stock settings, and the ladder advances to the next rung

#### Scenario: The Gateway took the message and did not deliver it
- **WHEN** a message the Gateway accepted is not delivered within its `ttl`
- **THEN** the verification fails with that reason, no call is placed, and the refund is reflected in the recorded cost

### Requirement: Spending on a paid route is an entitlement of the application, and it is off by default

Whether an application may have its verifications carried by a paid route SHALL be an
entitlement recorded against that application. An application whose entitlement is absent or
off SHALL be refused, with a reason naming the entitlement.

It SHALL default to off, including for a newly issued token. Today any active token can open a
paid verification, and three of the four applications on this gateway never send codes at all:
`gmp_app`, `mprz_bot` and `turbo_route_bot` between them account for none of the traffic this
route exists to carry. A default of on would mean that the first mistake in any of them is
billed rather than logged.

**The default SHALL also apply to every application that already exists when the entitlement
arrives**, and not only to applications created afterwards. Recorded as a norm because it is
the half a schema change silently gets wrong: a default written to take effect for new rows
leaves the guarantee empty on exactly the installations that have the defect, which are the
ones already running. The change that introduces the entitlement SHALL therefore switch every
existing application off, and SHALL be reversible by deploying the previous code rather than
by removing what an operator has since decided — a column dropped on the way back revokes that
decision silently the next time the newer code is deployed.

**Being active remains the stronger switch.** An application an operator has deactivated SHALL
NOT spend, whatever its entitlement says. The two answer different questions — whether an
application may talk to this gateway at all, and whether it may spend money doing so — and a
deactivated application that went on buying verifications because a second switch was left on
from before would be the deactivation failing to mean anything.

A refusal for want of the entitlement SHALL place no vendor call and make no ability check,
SHALL NOT be reported to the application as a vendor failure, and SHALL NOT be quietly carried
over the `sms_out` route instead — for a МегаФон subscriber that is the route that has been
refusing, so the fallback would read as a delivery and behave as a silence.

The entitlement SHALL NOT be part of the routing rule. The rule answers what reaches a
subscriber and stays keyed on the operator alone; this answers who is allowed to pay for it,
and the two questions have different answers that change at different times. It SHALL be
changeable without a restart, by the same means as the rule.

**Owner's decision of 18.09.2026.** It was raised by the critic round of 11.09.2026 as a
finding left for the owner rather than written as a norm; it is now written as one.

[backed · `apps.may_spend`, added by `app/db/migrate.py` as an `ALTER` so that its default reaches the rows already there; the gate is `gates.entitlement_gate` in `app/verification/gates.py`, read per call so that no restart is needed; operated at `POST /admin/apps/entitlement`. Guarded by `tests/test_paid_entitlement.py` and `tests/test_admin_apps.py`, including a test that builds the table in its pre-change shape, populates it and then migrates. ⚠️ **Implemented is not reachable**: the gate has no production caller, because the door that walks the paid ladder belongs to `verify-by-inbound-contact` and does not exist yet]

#### Scenario: An application without the entitlement
- **WHEN** an application whose entitlement is off requests a verification for an operator routed to a paid ladder
- **THEN** it is refused with a reason naming the entitlement, no vendor is contacted, and nothing is sent over the modem instead

#### Scenario: A newly issued token
- **WHEN** a new application token is created and immediately requests a paid verification
- **THEN** it is refused, because the entitlement defaults to off

#### Scenario: An entitled application
- **WHEN** an application whose entitlement is on requests the same verification
- **THEN** the ladder is attempted normally

#### Scenario: An application that existed before the entitlement did
- **WHEN** the change that introduces the entitlement is deployed onto an installation whose applications predate it
- **THEN** every one of them is switched off, and none of them can open a paid verification until an operator grants it

#### Scenario: A deactivated application that still holds the entitlement
- **WHEN** an application an operator has deactivated requests a paid verification
- **THEN** it is refused, whatever its entitlement says

### Requirement: A route that cannot be used fails loudly and does not silently fall back

If the assigned route cannot carry an item it is capable of carrying — the vendor is
unreachable, unauthenticated, or out of credit — the item SHALL NOT be transmitted over the
other route. It SHALL follow the retry and expiry rules already governing its kind, and the
operator SHALL be alerted.

Automatic failover between routes is deliberately absent. Escalating into a paid channel
without a spend ceiling turns a modem fault into an unbounded bill, and escalating out of one
turns a vendor outage into traffic on a route an operator has already refused.

That argument applies to the paid route itself, not only to escalation into it. A paid route
SHALL have a configured ceiling on how many paid items it may carry per rolling hour and per
rolling day, counted across every number and every application. A request that would exceed it
SHALL be refused with a reason naming the ceiling, no vendor call SHALL be placed, and the
operator SHALL be alerted on the first refusal within the dedup window. A ceiling reached SHALL
NOT be reported to the application as a vendor failure.

The vendor's own limits do not provide this: they are per number — four a minute, thirty a day
— and a loop over five hundred numbers violates none of them while spending four hundred
roubles. A balance floor is not a ceiling either; it reports money already gone.

**The ceiling SHALL count across all paid routes together, not per vendor.** There are two
prepaid accounts behind the ladder now, and a ceiling counted per rung lets a run of
verifications spend twice the intended amount by advancing from one rung to the other — which
is exactly what the ladder does by design. What is being bounded is the bill, and the bill is
one.

**The ceiling SHALL count every attempt on a paid route, including the ones that turn out to
cost nothing.** A ceiling counted over confirmed charges would be blind to exactly the
attempts most likely to have cost money in silence: an ability check that never answered may
have been confirmed and billed at the vendor without our ever learning its `request_id`, which
is the one class of spend this design cannot attribute to anything. Counting attempts also
makes the ceiling decidable before a vendor is contacted, which is what lets it refuse without
spending.

**Its windows SHALL roll rather than reset on a clock**, for the reason the per-number limits
do: this database stores naive UTC and both vendors are Russian, and a calendar window read in
the wrong zone resets early and spends confidently in the gap.

**Its numbers SHALL be settings, and SHALL be set against observed traffic rather than
chosen.** A ceiling below the busiest hour this gateway has really had stops being a guard
against a runaway and becomes a refusal of legitimate work — and that failure is the harder of
the two to attribute, because it presents as a gateway that has quietly stopped verifying
anyone.

Every alert this requirement raises SHALL name **which** vendor it is about. With one paid
route "the vendor is out of credit" was unambiguous; with two it is the question the operator
has to answer before they can act, and answering it by reading a log is the difference between
a two-minute top-up and an outage.

[partly backed · the spend ceiling is `gates.ceiling_gate` in `app/verification/gates.py`, counting `verification_rungs` over `routes.PAID_ROUTES` in rolling windows, with `verification_paid_per_hour` and `verification_paid_per_day` as its settings; guarded by `tests/test_spend_ceiling.py`. 🔴 The shipped numbers are measured rather than chosen — read from this gateway's own live database on 20.09.2026: 2391 messages between 17.04.2026 and 20.09.2026, 601 of them to МегаФон (both spellings matched by hand, since `upper()` is ASCII-only in this build and counts 397 of the 601). The busiest МегаФон hour in five months held 20 messages and the busiest day 47; a verification may consume two paid rungs, so the worst load ever observed is about 40 attempts an hour and 94 a day, and the ceilings of 100 and 300 sit above that with room while stopping a runaway in minutes. The vendor-credential and out-of-credit halves stay unbacked on the uCaller side, which has no adapter (task 4.17, blocked on task 1.1)]

#### Scenario: The vendor rejects our credentials
- **WHEN** a vendor answers with an authentication error
- **THEN** nothing is sent over the modem instead, the operator is alerted with that vendor named, and the existing retry rules apply

#### Scenario: The vendor is out of credit
- **WHEN** a vendor reports insufficient balance
- **THEN** the operator is alerted with that reason and that vendor's name, and nothing is rerouted

#### Scenario: The ceiling counts the ladder, not the rung
- **WHEN** verifications advance from the first rung to the second often enough that the two rungs together reach the configured ceiling
- **THEN** the next request is refused by the ceiling, even though neither rung reached it alone

### Requirement: What the rule costs is countable per operator

The gateway SHALL record, per operator, how many items it refused because the operator's
configured route could not carry them, and that count SHALL be visible to an operator without
reading the database.

A rule set during an outage outlives the outage. When МегаФон starts accepting traffic again,
the rule will still be in force, and the applications that do not send codes will still be
refused — with nothing on any screen to say so. A count is the difference between a rule that
is reviewed and a rule that is forgotten.

[unbacked]

The count SHALL be answerable per application as well as per operator: it decides whether to
call the developer of a particular application or to drop the rule, and "seventy refusals"
answers neither.

The count SHALL NOT be relied upon as evidence that the route has recovered. Once a rule is in
force, the modem route to that operator receives no attempts at all — codes leave by the other
route and text is refused before any AT command — so the one source of proof that the refusal
has ended is the thing the rule switches off. The gateway SHALL therefore retain a way to
observe recovery: either a rate-bounded probe send to that operator over the `sms_out` route,
counted separately, or an alert once a rule entry has been in force longer than a configured
review period.

A refusal SHALL reach the operator on the configuration the gateway ships with. It SHALL NOT
depend on a notification toggle that is off by default — `notify_send_errors` is such a toggle
— and it SHALL be deduplicated on the operator and the route rather than raised once per
refused message, since the measured traffic is about seventy refusals a month and rising.

[unbacked · the default-off toggle: app/settings_store.py, notify_send_errors]

#### Scenario: Refusals accumulate against an operator
- **WHEN** three applications are refused for one operator over a day
- **THEN** the count for that operator shows three, attributable to that operator rather than to the gateway as a whole

#### Scenario: The refusals are attributable to an application
- **WHEN** an operator asks which applications the refusals came from
- **THEN** the count answers per application as well as per operator

#### Scenario: A rule outlives the outage that justified it
- **WHEN** an operator's entry has been in force longer than the configured review period
- **THEN** the operator is alerted that the rule is still in force and has not been reviewed

#### Scenario: The refusal alert arrives on the shipped configuration
- **WHEN** a message is refused for want of a usable route on a gateway whose settings are untouched
- **THEN** the operator is alerted, once per operator and route within the dedup window
