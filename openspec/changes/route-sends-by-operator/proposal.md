## Why

The gateway has exactly one way to reach a subscriber: the modem. That was never a design
decision, it was the absence of one — and the assumption underneath it is that the SIM will
keep being allowed to carry this traffic. It has already been withdrawn once: this SIM has
been blocked before, and on 06.09.2026 at about 18:30 MSK messages bound for a МегаФон
subscriber began coming back `0x63` (service rejected) while every other operator delivered
normally in the same minutes.

A probe that day sent six messages to one operator-confirmed МегаФон number, differing in
wording, in alphabet, and in whether they carried a code at all. All six were rejected
identically. The cause is the sender's route to that operator. Nothing in the message and
nothing in this codebase can change it.

**The recurring event is not "МегаФон is refusing".** It is "the modem route stopped working
for some part of the estate", and its blast radius has been total before. A branch that
names МегаФон would encode the shape of one symptom; the next withdrawal would need code
again, during an outage, which is the worst moment to be writing any.

**Owner's decision, 08.09.2026:** the second route is not a second way to send SMS. It is
https://developer.ucaller.ru — a flash call, where the code is the last four digits of the
calling number. Our modem does not participate at all; the vendor's infrastructure calls the
subscriber's phone. It is therefore a way to deliver a *verification code*, and only that.

## What Changes

- **A verification stops being an SMS the application composes.** The application asks the
  gateway to verify a number; the gateway generates the code, chooses how to deliver it, and
  answers whether a code the person typed is the right one. This is the contract already
  drafted for `verify-by-inbound-code` and already sent to the parking developer — the same
  door, with a third method behind it.
- **A send acquires a route.** The modem stops being the only way out and becomes one route
  of two, the second being uCaller's flash call.
- **Route selection is a configured rule keyed on the recipient's operator**, not a branch.
  Today it carries one entry — МегаФон to the call route — set without deploying code.
- **A message that its operator's route cannot carry is failed at once**, not attempted and
  not silently rerouted. A flash call carries four digits and nothing else; free text,
  a link, or a multipart notice cannot travel it.

Explicitly **not** in this change, by the owner's decisions of 07–08.09.2026:

- **no automatic failover.** A route that starts failing does not reroute itself. Automatic
  escalation into a paid channel needs a spend ceiling to be safe, and that is a second
  change, not a corner of this one.
- **no migration of the other operators.** The modem keeps МТС, Билайн, Теле2 and the rest.
- **`verify-by-inbound-code` stays frozen.** It remains the reserve path — not discarded,
  not implemented, and not edited by this change.

## Measured, not quoted

From the gateway's own ledger on the production host, read on 08.09.2026. Two figures
carried in the first draft of this proposal were wrong and are corrected here.

⚠️ **`upper()` and `LIKE` in SQLite are ASCII-only.** `number_operators` holds МегаФон under
two spellings — `МЕГАФОН` (120 numbers) and `МегаФон` (57) — and a case-insensitive match
silently counts only one of them. Every figure below matches both spellings explicitly. The
first attempt at this table did not, and undercounted МегаФон by half.

Messages per month, by originating application:

| App | Jun | Jul | Aug | 01–08.09 |
|---|---|---|---|---|
| `sp_app` (parking) — total | 314 | 276 | 265 | 183 |
| `sp_app` → МегаФон | 55 | 94 | 46 | 77 |
| `gmp_app` — total | 29 | 178 | **297** | 71 |
| `gmp_app` → МегаФон | 6 | 36 | **63** | 18 |
| `mprz_bot` → МегаФон | 0 | 0 | 2 | 6 |
| `turbo_route_bot` → МегаФон | 12 | 4 | 0 | 1 |

**Half the МегаФон traffic is not the parking app.** In August — the last full month —
МегаФон received 111 messages, of which 46 came from `sp_app` and 63 from `gmp_app`, which
is growing (6 → 36 → 63). This is the fact that shapes the change: a flash call can serve
`sp_app` completely and `gmp_app` not at all.

**What each application sends** (448 `sp_app` and 368 `gmp_app` messages since 01.08):

| | `sp_app` | `gmp_app` |
|---|---|---|
| carries a four-digit run | 446 of 448 | 325 of 368 |
| carries a five-digit-or-longer run | **0** | 237 |
| carries a link | **0** | 19 |
| text length | 8–26 chars | 11–472 chars |

`sp_app` is one template, `SokolParking: ####`, and nothing else. `gmp_app` is free text.

**The refusal is heavy, not total.** Between 06.09 18:30 MSK and 08.09, 55 messages went to
МегаФон numbers: 49 failed and **6 were genuinely delivered** — real `+CDS` reports, with
`delivery_inferred = 0`, so not the sweep's inference. Roughly one in nine still gets
through, spread across both days rather than clustered before the block bit. That does not
save the channel — a confirmation code that arrives 11% of the time is unusable — but
"0 of 16" from the earlier note was a small sample, and the true shape is a filter, not a
wall.

**Cost.** uCaller charges 0,80 ₽ per verification (the landing page offers "from 0,4" at
volume; the docs' worked example shows `cost: 0.3`). At the three-month mean of 65 `sp_app`
verifications to МегаФон per month, that is **≈ 52 ₽/month**, against 2,92 ₽ per SMS at
P1SMS — the provider the first draft of this change was written around — which would have
been ≈ 190 ₽/month for the same traffic. The vendor's two free repeats per verification are
not charged.

## The single unverified link

**We have never proved that a flash call reaches a МегаФон subscriber.** The whole change
stands on it. Voice availability is not SMS availability: a busy line, a diversion, a
call-blocker app or a hidden-number filter each break a call where an SMS would have
arrived, and none of them show up until tried.

It costs one call to `+79851600019` (an operator-confirmed МегаФон number the owner has
released for probes) once an API key exists. **Task 1.1, before anything else is built.**

## Capabilities

### New Capabilities

- `outbound-routing`: which way out a message or a verification takes, what the rule is, and
  what happens when the chosen route cannot carry what it was handed.
- `phone-verification`: verifying that a person holds a phone number — the request, the
  code, the choice of method, and the answer to "is this the right code".

### Modified Capabilities

- `outbound-send`: a message may now be refused before the modem is touched, because its
  operator's route cannot carry text.
- `delivery-dispatch`: the same per-application routes now carry verification outcomes as well
  as message statuses, and the two must not be mistakable for each other. The live capability
  fixes both the body and the rule that every status writer notifies, so carrying a second kind
  of thing over it changes it and cannot be left undeclared.

## What this costs the other applications

`gmp_app`, `mprz_bot` and `turbo_route_bot` do not send codes and cannot use the call route.
Their МегаФон traffic — about 70 messages a month and growing — will be **failed at accept
time** with a named reason instead of failing after the retry ladder. Owner's decision of
08.09.2026, taken with this consequence stated: the outcome is the same failure either way,
delivered sooner and with a reason a human can act on.

Two hazards follow, and both are tasks rather than prose:

1. **If МегаФон recovers and the rule is left set, those applications stay broken silently.**
   The refusal must be countable per operator, so the rule's cost is visible.
2. **The parking app must adopt the new endpoint before any of this helps a single person.**
   Until it does, МегаФон users get nothing new. The gateway side can be finished and
   verified independently, but the outcome for a customer waits on the parking developer.

## Open questions — design, not implementation

1. **How long a verification stays open, and how many code attempts it allows.** The person
   is standing at a barrier; too short is a support call, too long is a wider guessing
   window. Not decided here.
2. **Whether the SMS method's text is a per-application template setting or is composed by
   the gateway.** With the gateway generating the code, the application can no longer supply
   finished text, and `SokolParking: ####` has to come from somewhere.
3. **Where the routing rule lives** — `settings` (changeable from the admin console, no
   restart) or `.env` (a restart, which drops sending sessions). Both satisfy "no deploy";
   they differ in who can change it and how fast.

## Status

**Rewritten 08.09.2026** from the P1SMS draft of 07.09.2026, on the owner's decision to use
uCaller. **Critiqued 11.09.2026** — one round, both critics, seeded with the mechanical pass;
32 findings deduplicated to 20 and checked against the code before being accepted. Three were
corrected by that check: the unknown-operator hole is narrower than reported, because
`record_operator` is awaited before a message is created and resolves a first-time number
synchronously; what it did confirm is that the requirement claiming nothing is delayed cited
that same code as its evidence. The round added 22 scenarios and one capability delta
(`delivery-dispatch`), and it is closed — the ceiling is one round.

Two of its findings are left for the owner rather than written as norms: an entitlement
deciding which applications may spend on a paid route (today any active token can), and the
rewriting of tasks 5.2 and 5.3, which as written prove the change on live customer traffic.

The vendor contract below was taken from uCaller's official reference on 08.09.2026, which
satisfies the external-contract gate for `initCall`, `getInfo` and `initRepeat`. **No live
sample has been captured.** The `inboundCallWaiting` webhook is deliberately absent from this
change: its payload fields are not in the documentation, and a parser for it may not be
written from guesses.
