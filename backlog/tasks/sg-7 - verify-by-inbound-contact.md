---
id: SG-7
title: verify-by-inbound-contact
status: To Do
assignee: []
created_date: '2026-09-25 11:59'
labels:
  - migrated
dependencies: []
references:
  - openspec/changes/verify-by-inbound-contact
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Why

Verifying that a person holds a phone number is one job, and this gateway spent a week
designing it as though it were the job of *sending an SMS*. That framing is what made the
outage of 06.09.2026 look like an emergency: МегаФон stopped accepting this gateway's
outbound traffic — of 55 messages sent between 06.09 and 08.09, 49 failed and 6 arrived,
roughly one in nine — and with one route, a filter on that route is a total outage.

**The gateway now has more than one way to reach a person, and they differ enormously in
price.** Two of them are free. One of those two did not exist as far as anyone knew until
18.09.2026.

🔴 **The premise this change was first written on is withdrawn.** Its earlier text said
*"The modem in service cannot supply the second — verified 07.09.2026, a call to its SIM is
silence and disconnect"*. That is false. The live `EP06-E` (`EP06ELAR03A08M4G`) had IMS
switched off; the setting was invisible because nothing in the gateway reads it. After
`AT+QCFG="ims",1` and `AT+CFUN=1,1` it read `+QCFG: "ims",1,1` — the second digit is the
network's answer, so Билайн admits this module — and a call to the SIM landed as fifteen
`RING` / `+CLIP` pairs in sixteen seconds, carrying the caller's number.

Three days of work concluded "this module has no voice path" from a single `AT+CIREG?` →
`ERROR`. Quectel confirmed in writing on 18.09.2026 that the command is absent from this
build and that IMS state is read with `AT+QCFG="ims"`. **`ERROR` on an AT command is a
statement about the firmware's dictionary, not about the module's capability** — an empty
reading, not a negative one.

## 🔴 The author's second error, and why this change was rebuilt

**This change was first written as a new capability, `inbound-verification`, owning
`POST /verifications` and its neighbours.** It could not be, and the reason was already
written down: `route-sends-by-operator` authors the capability `phone-verification` and
states normatively that it *"SHALL remain the single owner of `POST /verifications`,
`POST /verifications/{id}/check` and `GET /verifications/{id}`, a method being a variant
within it rather than a capability of its own"*. Two capabilities under one door is how one
of them silently stops being consulted. Both critics reached this independently; the author
had not opened the neighbouring change at all.

**On the owner's decision of 18.09.2026 the routes are rungs inside `phone-verification`.**
This change is now a delta to it: four `MODIFIED` requirements, one `REMOVED` and replaced,
ten `ADDED`. Seven findings the critics raised are **not carried here** because
`phone-verification` already answers them — ownership by `app_id`, expiry with notification,
normalisation and the blacklist at the door, the per-number rate limits including uCaller's
ten-hour block, spend visibility and the balance floor, atomic confirmation by one
conditional update, and retention.

The price of the decision is named rather than hidden: one of the new norms — that the
caller-ID subscription is the gateway's own recorded state rather than something it reads
back from the modem — is a serial-link concern sitting inside a verification capability.
It is here because the owner put it here and because it is load-bearing for exactly one
rung. A later reader who wants it in `modem-link` is not wrong; they are reading a decision,
not an oversight.

## What Changes

**This capability stops being "send a code and hope" and becomes a chooser over a priced
ladder of routes.** A verification request names a number; the gateway answers with the
routes that can actually carry it right now, cheapest first.

- **The order and membership of the ladder are configuration, not code.** Prices move,
  vendors change, an operator unblocks. Compiling the ladder in would make a price change a
  deployment.
- **A route is offered only when its precondition is proven** — not when it is merely
  configured, and not on evidence older than a configured maximum. This is the load-bearing
  norm of the change.
- **The answer carries the available routes; the consumer selects one.** The application may
  take the first silently or put the list in front of the person. Selection is a second call,
  because "or the person" means a round trip.
- **The gateway never moves to another route by itself.** The owner's standing prohibition on
  silent switching survives the ladder: a list to choose from is not a licence to hop.
- **A confirmation names the method that proved it**, because the methods are not equally
  strong and the consumer is entitled to refuse the weak one.
- **Two rungs are added here**: `call_in` — the subscriber calls the gateway's own SIM,
  free to both sides — and `sms_in` — the subscriber texts the code back, last on the
  ladder because it is the only route the subscriber pays for.

Not in this change: `/sms/send` keeps working unchanged for messages that are not
verifications. The rungs `sms_out`, `flash_call` and `tg_gateway` are specified by
`route-sends-by-operator` and are not re-specified here.

## The load-bearing norm: a route must prove itself, or it is not offered

An incoming call reaches the modem **only while IMS is on**. If IMS goes off — a reset, a
firmware reload, a change at the carrier — `RING` simply stops arriving. There is no error
anywhere. Every call verification would hang until it expired and then report "expired",
which is indistinguishable from "the person never called".

With the call as the first rung, that is a **silent total outage of verification**, and it is
the single most dangerous property of this design. The remedy is not a better handler. It is
that the chooser may not hand out a route it cannot prove is working: no proof of IMS, no
call rung — the ladder starts one step lower and the person verifies another way without ever
knowing there was a problem.

**The critics found the norm disarmed by its own scenario, and the fix is in.** The earlier
draft required an anonymous `RING` to be treated as an ordinary outcome — the subscriber
withheld their number — which meant a lost `AT+CLIP=1` subscription was indistinguishable
from a polite caller. And `soft_recover` (`app/modem/at_commands.py:669-681`) re-issues
`CNMI` and **not** `CLIP`, on a docstring whose own argument — "losing it is silent and
total" — applies to both. So after an ordinary recovery IMS still reads `1,1`, the rung is
still offered, and every `RING` arrives anonymous.

The other half of that fork looked worse still: the precondition cannot be read back, because
`AT+CLIP?` does not answer on this modem — given eight seconds it spent all eight
(`app/modem/manager.py:125-147`). By the norm "an unreadable precondition is unavailable",
the first rung would switch itself off forever.

**Neither branch is taken.** The subscription is not a thing the gateway reads; it is a thing
the gateway *does*, and therefore a fact it can record: whether `AT+CLIP=1` was last issued
successfully on the link generation now in service. With the record held, an anonymous call
is a withheld number and nothing is wrong. With the record lost, the rung was never offered.
`AT+CLIP=1` is re-issued wherever `AT+CNMI` is. The one residual — a firmware that drops the
subscription without a `CFUN` cycle — is made visible by counting calls that carry no number,
so it shows up as a rate change instead of as nothing.

⚠️ **Two rungs depend on egress, and egress is not stable.** `flash_call` and `tg_gateway`
are calls to `api.ucaller.ru` and `gatewayapi.telegram.org`. Telegram is blocked on this
host's backup uplink — measured, not supposed — and reaches it today only through a relay
that `carry-telegram-on-any-uplink` records as working but nowhere normalises. The moment the
gateway fails over is the moment two paid rungs may become unreachable, and it is also the
moment things are already degraded.

⚠️ **This change does not build the IMS reading; it consumes it.** `watch-the-voice-route`
puts `AT+QCFG="ims"` into the read-only sweep and is required to report when the voice route
was last successfully measured. This change is the consumer of that time and supplies the one
thing it lacks — **a maximum age**, without which "current evidence" is not defined and the
norm above decides nothing. This change SHALL NOT touch `_DIAG_QUERIES`.

## The second boundary: proof decays between the offer and the confirmation

The norm above stands at the **offer**. The critics found the gap after it, and it is not
small. A verification's default lifetime is five minutes; one recovery of this modem is
bounded at `_RECOVERY_TIMEOUT = 300.0` seconds of gate-closed time plus a thirty-second
settle (`app/modem/manager.py:55,58`), and the hard rung of the escalation calls `os._exit(1)`
(`app/modem/manager.py:1236`). A recovery can consume a verification's entire window.

So an open verification whose route has lost its precondition now **ends with that reason**
rather than expiring silently. "Expired", told to a person who did call, on time, from the
right number, is the gateway reporting the one thing that did not happen.

🔴 **And a call has no buffer.** Inbound SMS survives an outage: messages accumulate in modem
memory and are reconciled by `scan_inbox` when the link returns (`app/modem/manager.py:452`).
A caller during those three minutes exists nowhere — not in the modem, not in the log. The
asymmetry is a property of the bearer and cannot be engineered away; what the spec forbids is
concealing it.

## What an inbound call proves, and what it does not

**It proves possession of the number exactly as well as the network's caller ID can be
trusted, and no better.** `+CLIP` is spoofable. That is stated in the spec rather than buried,
because this rung is first and will carry most verifications.

🔴 **The earlier rationale for the four-digit code was wrong, and the correction matters.** It
read: an attacker "must additionally produce a code displayed only on the subscriber's
screen". The flow refutes it — the application displays the code to whoever started the
verification, so an attacker who enters someone else's number reads the code on their own
screen. **The code is an attribution tag, not a second factor.** The real defence on every
route is the same one: the event must originate from the number being verified.

**One asymmetry survives.** A person is easy to persuade to dial a number and nearly
impossible to persuade to text four specific digits. An attacker can open a verification on a
victim's number and, in the same minute, give the victim a reason to call us. Mitigations: one
open call-verification per number, the per-number rate limits `phone-verification` already
requires, and a window configurable **shorter for this rung than for the ladder**. It does not
reduce to zero, and an application whose stakes do not tolerate it should read the returned
method and refuse it.

## What this is actually for, which bounds nearly everything below

**The owner's answer of 18.09.2026: a person verifies a number ONCE, at onboarding, and is then
let into the project; from there the application authenticates them by email.** This is not a
login factor that fires on every session.

Three things follow, and they are why the numbers in this change are the size they are.

- **Volume is one per user, not one per login.** A paid rung at ≈0,80 ₽ is a one-off cost of
  acquiring a customer, not a running cost of serving one. That is a very different thing to
  weigh a ladder against.
- **Which makes the one rung the subscriber pays for harder to justify, not easier.** `sms_in`
  exists to be reached when everything cheaper failed to prove itself. If the whole event
  happens once in a customer's life, spending 0,80 ₽ of ours rather than a message of theirs is
  a small price for not asking a new customer to text a robot. The ladder keeps `sms_in` last
  because the owner ordered it so; it is worth knowing it may be worth dropping entirely.
- **It sets what the residual risk buys an attacker**: not a session, but a project account
  bound to someone else's number — after which email takes over and the phone stops being the
  key. Whether that is tolerable is task 1.4, and the answer is now a narrower question than it
  looked while this was thought to be an authentication factor.

## Cost

| Rung | Ours | Subscriber's | Precondition that must be proven |
|---|---|---|---|
| `call_in` | 0 | **0, once the call is ended before voicemail** | `AT+CLIP=1` recorded as held, IMS registered, evidence fresh |
| `sms_out` (`sms_out`) | ≈0 (flat ~100 ₽/мес) | 0 | operator not on the undeliverable list |
| `flash_call` | 0,80 ₽ | 0 | balance; vendor reachable on the current uplink |
| `tg_gateway` | $0.01 ≈ 0,80 ₽ | 0 | balance; vendor reachable; Telegram can reach the number |
| `sms_in` | 0 | **1 SMS at their tariff** | the modem receives |

**The first rung is free to the subscriber because the gateway hangs up.** The owner decided
this on 18.09.2026, and it is what closes the hole the draft left open: the gateway neither
answers the call — answering costs the caller money and needs an audio path this module does
not have — nor lets it ring on into the carrier's voicemail, which is a connection somebody
pays for. The number is read from the first `+CLIP` and the call is ended there.

🔴 **Every step of that is still an assertion.** That `ATH` ends an unanswered incoming call
on this firmware is not measured; neither is taking the command port from the sender to do it,
nor what the carrier does with a rejected call. So the spec separates the two: **confirmation
rests on the number, which is already in hand, and never on the hang-up succeeding** — a failed
hang-up is recorded, not fatal, and it may not delay a send. The cost claim stays unpublished to
consumers until the sequence is seen end to end on the live modem; task 1.2 carries it.

**Owner's decision, 18.09.2026: uCaller ranks above Telegram Gateway.** Recorded as a
decision, not a measurement. The counter-argument was raised and declined: Telegram Gateway
refunds undelivered codes automatically, so a failed attempt there costs nothing, which would
otherwise make it the cheaper of two routes priced the same.

The honest objection to the old design — that it moved a charge onto the customer — is
answered by the ladder rather than defended: `sms_in` is now the last resort, reached
only when every cheaper rung failed to prove itself.

## Capabilities

### Modified Capabilities

- `phone-verification`: gains the two rungs the gateway itself bears (`call_in`,
  `sms_in`), the norm that a rung is offered only on fresh proof, the consumer's
  selection and the prohibition on silent switching, and the two boundaries the critics
  found — the caller-ID subscription as recorded state, and the end of a verification whose
  route died under it.

**No new capability.** That was the error this rebuild corrects.

## 🔴 Archiving order, and the guard that holds it

This change's `MODIFIED` and `REMOVED` blocks address five requirements that exist **only in
`route-sends-by-operator`'s delta** — `phone-verification` is not in `openspec/specs/` yet.
`openspec validate --strict` is green on this change and proves nothing: it does not check
that a modified requirement exists. Archive this one first and five blocks merge into
nothing, silently, including the `REMOVED` that retires the requirement the owner's decision
overturned.

The guard is machine-checkable, not a memo:
`openspec/changes/verify-by-inbound-contact/check-base.sh` greps the living spec for all five
headings and exits 1 while any is missing; registry row `sms-gate/20260918-04` runs it as its
probe. Both were verified in both directions on 18.09.2026.

The delta repeats `phone-verification`'s `## Purpose` **verbatim**, so that whichever change
archives first writes the same text and no drift can appear.

## Renaming, and the neighbours' references

**This change replaces `verify-by-inbound-code`**, renamed on 18.09.2026 because the rungs it
now carries are not all codes. Normative references to the old name have been repointed in
`route-sends-by-operator` (`proposal.md`, `specs/phone-verification/spec.md`).

⚠️ **`watch-the-voice-route` declares editing `verify-by-inbound-code/proposal.md` as its own
Impact.** That item is discharged here and that change should drop it; its files are owned by
a sibling session and are deliberately untouched.

✅ **The method vocabulary is settled by the owner, 18.09.2026: one flat field, names
disambiguated.** `sms_out` (our SIM sends), `sms_in` (the subscriber texts us), `call_in` (the
subscriber calls us), `flash_call` (uCaller dials, *"our modem does not participate at all"*),
`tg_gateway`, `tg_user`, `max_user`, `app_bot`. The name `call` is retired outright, because it
meant two different mechanisms in two changes and that is how an implementer builds the wrong
one. `modem` is retired in favour of `sms_out`, which says the direction the old name left to
be inferred.

The decision is applied here and in `route-sends-by-operator`, whose `outbound-routing` spec
posed the contest and deferred it. It is **not** applied inside `reach-people-in-messengers` —
its files belong to a sibling session; its task 1.1 records the decision so that session can
apply `modem` → `sms_out` in its own deltas. Its other three values are adopted unchanged.

⚠️ **The flat form buys simplicity and pays for it with a convention.** Nothing structural
stops a later change re-introducing `call`; only the fact that this paragraph exists does.

⚠️ **`route-sends-by-operator` tasks 3.1–3.2 rest on a premise the owner withdrew**: they
speak of a contract "already in the parking developer's hands" and of a sent artifact. The
owner said on 18.09.2026 that the contract was never sent. Not repaired here — it is that
change's task list and its owner's call — but it is named so the next reader does not spend a
day reconciling with a party that does not exist.

## Open questions

1. **What the Telegram bot rung actually is.** Recorded as the author's reading of the owner's
   words on 18.09.2026 — a bot that requests the contact, Telegram vouching for the
   number-to-account binding — and not confirmed. **It is deliberately absent from the spec.**
   The critic's structural objection stands: its precondition cannot be proven before the list
   is issued, so it does not obey the load-bearing norm. Task 1.1 settles whether it exists.
2. ~~**Whether the gateway hangs up.**~~ **Settled by the owner 18.09.2026: it does**, as soon
   as the number is read, so the call never reaches voicemail. What remains is not a decision
   but a measurement — that `ATH` works from a contended command port on this firmware, and
   what the carrier does with a rejected call. Task 1.2.
3. ~~**Whether the subscriber pays for the unanswered call.**~~ Dissolved by the answer above:
   there is no unanswered call to pay for once the gateway ends it. Contingent on 2.
4. **Whether the SIM's inbox can fill** under sustained `sms_in` traffic. Less urgent than
   before, since that rung is now last.

## Status

**Authored 07.09.2026 as an inbound-SMS fallback. Reframed 18.09.2026 as a priced ladder after
the modem was found to accept calls. Rebuilt 18.09.2026 as a delta to `phone-verification`
after the critic round found a competing capability under the same door.**

The `system-architect` / `gap-finder` round has been run, on the redaction that preceded this
one; this redaction **is** its reconciliation. Three findings were real and are carried in:
the disarmed precondition norm, the boundary between offer and confirmation, and the broken
name references. Seven were already answered by `phone-verification` and are not duplicated.

🔴 **A statement in the earlier text is corrected on the owner's word: the integration
contract was never handed to the parking developer.** Tasks that existed to reconcile a
divergence with an external party are removed; there is no external party yet. The owner's
plan is to migrate their own projects onto this gradually, which is why every existing route
stays live rather than being retired on cutover.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
# Tasks

## 1. Settled by the owner, and what each answer left behind

- [x] 1.1 **Method vocabulary — decided 18.09.2026: one flat field, names disambiguated.**
      `sms_out`, `sms_in`, `call_in`, `flash_call`, `tg_gateway`, `tg_user`, `max_user`,
      `app_bot`. `call` is retired (it meant two mechanisms in two changes); `modem` is retired
      in favour of `sms_out`. Applied in this change and in `route-sends-by-operator`.
- [ ] 1.2 **The hang-up sequence, measured end to end on the live modem.** The owner decided
      18.09.2026 that the gateway ends the call as soon as the number is read, which is what
      makes this rung free to the subscriber. Every step is still an assertion: that `ATH` ends
      an *unanswered incoming* call on this firmware; that the command port can be taken from
      the sender to do it without displacing a send; and what the carrier does with a rejected
      call. 🔴 The cost claim stays unpublished to consumers until all three are observed.
      Confirmation does not depend on any of them — that is already normative.
- [x] 1.3 **`telegram_bot` — not in this change.** Recorded as the author's reading of the
      owner's words and kept out of the spec: the critic's objection is structural — its
      precondition cannot be proven before the list is issued, so it does not obey the
      load-bearing norm. It returns as its own proposal or not at all.
- [ ] 1.4 **Is the residual risk acceptable per consuming application?** An attacker opens a
      verification on a victim's number and, inside the window, gives the victim a reason to
      call. Narrower than it looked: verification happens **once, at onboarding**, after which
      the application authenticates by email — so what the attack buys is a project account
      bound to someone else's number, not a session. Mitigated by one open `call_in`
      verification per number, the rate limits, and a shorter window for this rung. It does not
      reduce to zero; the spec returns the method so an application may refuse it.
- [ ] 1.5 **The window for `call_in`.** `phone-verification` ships five minutes for the ladder
      by the owner's decision of 18.09.2026. Two minutes was proposed here and never measured.
      The spec makes the rung's window separately configurable and no longer than the default;
      1.4 is the reason it should be a short one.
- [ ] 1.6 **Is `sms_in` worth keeping at all?** Raised by the onboarding answer, not yet put to
      the owner. It is the only rung the subscriber pays for, and it exists to be reached when
      everything cheaper failed. If the event happens once in a customer's life, spending
      0,80 ₽ of ours beats asking a new customer to text a robot. The ladder keeps it last
      because the owner ordered it so; dropping it is a decision, not a cleanup.

## 2. Hold the archiving order, because the validator will not

- [x] 2.1 `check-base.sh` greps the living spec for every heading this change modifies or
      removes and exits 1 while any is missing. Verified in both directions on 18.09.2026:
      it refuses today, and the same five headings exist verbatim in
      `route-sends-by-operator`'s delta, so it will pass once that change archives.
- [x] 2.2 Registry row `sms-gate/20260918-04` runs that script as its probe, so the order is
      a thing that asks rather than a thing somebody must remember.
- [ ] 2.3 **Before archiving**, run `check-base.sh` by hand and require "можно". If the
      neighbour has archived and the probe still refuses, the headings have diverged — read
      them line by line, do not force.

## 3. Depend on the IMS reading rather than building it

- [ ] 3.1 Wait for `watch-the-voice-route` to land the `AT+QCFG="ims"` row. This change SHALL
      NOT touch `_DIAG_QUERIES`; two changes editing one sweep is how one of them silently
      loses.
- [ ] 3.2 Consume the reading **with its age**. That change is required to report when the
      voice route was last successfully measured; this one supplies the maximum age and
      refuses the rung on stale evidence. Unreadable and stale both count as unavailable —
      the failing direction, not the passing one.

## 4. Caller ID becomes something the gateway knows it holds

- [x] 4.1 Re-issue `CLIP_SUBSCRIBE` wherever `CNMI_SUBSCRIBE` is re-issued —
      `soft_recover` (`app/modem/at_commands.py:669-681`) does the second and not the first,
      on a docstring whose own argument covers both. Test first, and it must fail first.
- [x] 4.2 Record the subscription's state per link generation: issued and acknowledged, or
      not. `AT+CLIP=1` at init is already allowed to fail with only a warning
      (`app/modem/at_commands.py:706-715`) — that warning becomes a recorded fact.
- [x] 4.3 Make that record, and nothing read back from the modem, the rung's precondition on
      caller ID. `AT+CLIP?` does not answer on this device and `AT+CLIP=?` answers a
      different question.
- [x] 4.4 Count calls arriving with no usable caller number and expose the count to an
      operator. This is the only detector for a subscription dropped without a `CFUN` cycle,
      which the record in 4.2 cannot see.

## 5. The reader learns that a call happened

- [x] 5.1 Parse `RING` and `+CLIP` in `reader_loop` (`app/modem/manager.py:746-762`),
      alongside the existing `+CDS` and `+CMTI` branches. Today both fall to the `else`
      branch and are logged as `Unhandled URC` — the code comment there already names this
      as the case it was left for.
- [x] 5.2 Canonicalize the caller number through `phonenumbers` before matching, per
      AGENTS.md — canonicalize before storage, never after.
- [x] 5.3 Collapse one call's repetitions into one event. Measured 18.09.2026: fifteen
      `RING` / `+CLIP` pairs in sixteen seconds for a single call. Test first, failing first.
- [x] 5.4 Record every call in its own store, including those that confirmed nothing and
      those that carried no number — not in `inbound_messages`.
- [x] 5.5 Do not answer the call. `ATH` stays out: it needs the command port the sender holds,
      and that it rejects an unanswered incoming call on this firmware is an assertion about
      the device rather than a measurement.

## 6. The chooser

🔴 **Blocked on the base capability existing, verified in code on 19.09.2026, against
the previous handoff's claim that this section was free to start.** There is no
`verifications` table, no `POST /verifications`, no `/check` and no
`GET /verifications/{id}`: the public API is `/sms/send` and `/sms/{id}` and nothing
else. The selection door below is `POST /verifications/{id}/route`, and `{id}` has no
source. Those norms live in `route-sends-by-operator`'s delta, which is at 9/89 with
every code task open, and task 7.1 here forbids inventing a second store. Who builds
the base — that change or this one — is the owner's call, because a sister session
runs the other one and two sessions building one door is the collision task 3.1
exists to avoid.

- [x] 6.1 Route registry with a precondition probe per rung; the ladder's order and membership
      read from configuration.
- [x] 6.2 Bound the probe set **as a whole**, not probe by probe, and count an unanswered
      probe as unproven.
- [x] 6.3 The invariant on the boundary: a rung with an unproven or stale precondition is not
      offered. Guard on the offering, not a walk over the callers.
- [x] 6.4 The selection door — `POST /verifications/{id}/route`. Nothing is placed, composed
      or charged before a selection; selecting a rung that was not offered, or one whose
      precondition has since lapsed, is refused with that reason.
- [x] 6.5 No silent hop. A failed rung fails the verification with its reason and re-offers
      what is left; moving on is the consumer's act. **The ambiguity this carried is settled
      by the owner, 19.09.2026: failure is terminal, and "select again" means a new
      verification.** What the failed one owes is the list, not a second turn — without it a
      consumer would have to open a verification merely to discover what is left. Built:
      the poll on a `failed` verification carries the remaining ladder with its instructions,
      asked of the registry **at read time** (a rung's precondition decays, and a list
      composed at the ending is the stale evidence this change refuses everywhere else) and
      **without the rung that failed, by name** (it may still prove itself — `sms_in` burns
      its attempts on a mistyped code without becoming unavailable — and handing it back is
      the hop this norm forbids, arriving by the other door). Selecting on a verification
      that ended is refused as `verification_<status>` rather than `already_selected`: the
      latter is an answer about the route and would send a consumer looking for a way to
      release it.
- [x] 6.6 One open `call_in` verification per number; a second request for that number is
      answered without that rung.
- [x] 6.7 Refuse the verification when no rung can prove itself, in the same answer, rather
      than opening one that can only expire.

## 7. What the verification stores and says

- [x] 7.1 Reuse `phone-verification`'s storage requirement — per rung attempted, its vendor
      identifiers, cost and refund. Add: the rung selected, and the method that confirmed.
      Do not invent a second store.
- [x] 7.2 A verification whose selected rung loses its precondition ends with that reason and
      notifies, rather than reaching its deadline. Every writer of a terminal state notifies.
- [x] 7.3 The `call_in` window, configurable separately and defaulting to no longer than
      the ladder's.
- [x] 7.4 Return the code to the owning application **only** on `sms_in`, and never in an
      operator notification or a log line on any rung.
- [x] 7.5 The confirmation names the method, in the push and in the poll.

## 8. The two rungs this change bears

- [x] 8.1 `call_in` — confirmed by the caller's number alone, within one open window.
- [x] 8.2 `sms_in` — confirmed only by the pair of originating number and code; last on
      the ladder, and not offered when a cheaper rung proved itself.
- [x] 8.3 Inbound traffic that confirms nothing stays stored and visible exactly as today
      (`app/admin/router.py:351`) — verification neither deletes, hides nor reclassifies it.
      🔴 **Named and deliberately left, by the owner's decision of 19.09.2026:** an inbound
      message still reaches an application through `inbound_dispatch`, which routes by the
      first word and may therefore hand it to an application other than the one that opened
      the verification — carrying the code along with the text if the person typed one. That
      is today's behaviour and this task is what forbids changing it here; the path belongs
      to inbound routing, not to verification, and fixing it is its own change. The operator
      notification was cleaned of the code; this was not.

## 9. Guards that must bite, not merely pass

- [ ] 9.1 Each new guard is checked by mutation: break the guarded thing and confirm it goes
      red. A guard that never bit is not a guard.
- [x] 9.2 The silent-death guard specifically: with the IMS precondition unmet, assert the
      call rung is absent from the answer — **and assert the positive control**, that it is
      present when the precondition holds. A negative guard without its positive control has
      executed nothing.
- [x] 9.3 The same pair for the caller-ID record: rung absent when `AT+CLIP=1` failed, present
      when it succeeded, and an anonymous call is *not* a fault while the record holds.
- [x] 9.4 A test that `soft_recover` re-issues `CLIP` — it is a one-line omission today and
      will be a one-line omission again after the next edit to that function.
- [x] 9.5 Assert the ladder cannot be reordered into offering a rung without its precondition,
      and that stale evidence is refused as firmly as absent evidence.

## 10. Verify against the real thing

- [ ] 10.1 Full suite. Six failures are inherited and unrelated — `test_alert_send_sh.py` (4)
      and `test_cds_attribution.py` (2) — verified by substitution against the unmodified tree
      on 14.09.2026. Do not report them as this change's.
- [ ] 10.2 A live inbound call to the production number confirming a real verification.
      🔴 Production carries live customer traffic — codes and passwords to real people every
      30–90 minutes. Pick a quiet window, check the queue first, and get the owner's sanction
      for the restart.
- [ ] 10.3 A live call **across a recovery**: confirm the verification ends naming the outage
      rather than reporting "expired". This is the boundary the critics found and the one no
      unit test can prove.
- [ ] 10.4 A live inbound SMS still lands and is still visible in the admin console — the
      regression that matters most, because it is the path that works today.

## Хендофф

ветка: worktree-verify-by-inbound-contact
имя: S·обратный-код

# Хендофф — доставка кодов подтверждения мимо блокировки МегаФона

> ## 🔴 19.09.2026, ночь — ЗДЕСЬ И СЕЙЧАС. Читать эту главу; ниже — история.
>
> **32 из 44. Три вопроса владельцу закрыты, и 6.5 вместе с ними.**
> Одиннадцать коммитов, `f22283e`..`6f7577f`. Набор: **831 зелёный, 6 падений — ровно
> унаследованные** `test_alert_send_sh` (4) и `test_cds_attribution` (2).
> `openspec validate --strict` — зелёный. Отметка круга перевыставлена.
>
> ### 🟢 Решения владельца 19.09.2026 — все три записаны в спеку и задачи
>
> 1. **Провал рунга ТЕРМИНАЛЕН для проверки; «выбрать снова» значит новую.** Это
>    снимает двусмысленность, которую 6.5 несла с момента появления лестницы.
> 2. **Спека правится под механизм: код отдаётся на ВЫБОРЕ рунга, не на создании.**
>    На создании рунга нет, а норма самой спеки — «исключение следует РУНГУ, а не
>    приложению» — рассудила её же текст.
> 3. **Путь утечки через `inbound_dispatch` не трогаем.** Назван в 8.3 как
>    осознанно оставленный: он принадлежит inbound-маршрутизации, а не проверке.
>
> ### Что построено этой сессией
>
> | Где | Что |
> |---|---|
> | `app/verification/routes.py` | `Registry.offer(phone, *, without=...)` — рунги снимаются ДО опроса |
> | `app/api/schemas.py` | `VerificationStatusResponse.routes` — пусто везде, кроме `failed` |
> | `app/api/router.py` | опрос проваленной проверки зовёт реестр и снимает её рунг по имени; выбор на кончившейся проверке отказывает `verification_<status>` |
> | `specs/phone-verification/spec.md` | момент выдачи кода; терминальность провала; +6 сценариев (49 → 55) |
>
> Три решения внутри, все вынуждены нормами заявки, а не вкусом:
>
> 1. **Список спрашивается на ЧТЕНИИ, не пишется в момент конца.** Предусловие рунга
>    протухает; запечённый при провале список — ровно то несвежее доказательство,
>    которое заявка отвергает во всех прочих местах. По той же причине его нет в
>    пуше: пуш читают минутами позже.
> 2. **`without` — параметр `offer`, а не фильтр над результатом.** Правило «платный
>    рунг снимается, если что-то дешевле себя доказало» читает СОСТАВ лестницы.
>    Отфильтруй `call_in` постфактум — получишь пустоту там, где остался ровно
>    `sms_in`, снятый за дороговизну относительно рунга, которого на лестнице уже нет.
> 3. **Провалившийся рунг снимается по имени, а не оставляется своей пробе:** он
>    вполне может доказать себя — `sms_in` сжигает попытки на опечатке в коде, не
>    становясь недоступным, — и вернуть его значит сделать ту же перепрыжку другой
>    дверью.
>
> Укус (все три мутации красят): снять отсев `without` — 4 красных; предлагать
> лестницу на любом статусе — 2; не исключать провалившийся рунг — 2.
>
> ### 🟡 Одно мелкое, что осталось владельцу
>
> **`CallWatch.open_call`** — публичное свойство, заведённое этой заявкой, с нулём
> читателей в `app/` и `tests/`. Свип по каждому новому публичному имени (38 имён)
> нашёл ровно его; остальные четыре «без вызова» зовёт фреймворк — хендлеры FastAPI
> и валидаторы pydantic. Снести или оставить швом под чузер.
>
> ### Что осталось и почему
>
> - **Владелец:** 1.2 (замер трёх шагов отбоя), 1.4 (остаточный риск), 1.5 (окно
>   `call_in` — сейчас по умолчанию равно ладдерному), 1.6 (держать ли `sms_in`).
> - **Сосед `watch-the-voice-route`:** 3.1/3.2 — ряд `AT+QCFG="ims"`. Шов ждёт:
>   `ModemManager.ims_proof` — `callable`, возвращающий `Proof(holds, measured_at)`;
>   сейчас его НЕТ, и потому `call_in` не предлагается вовсе. Это верное направление
>   отказа, а не поломка. 🔴 Эта заявка НЕ трогает `_DIAG_QUERIES`.
> - **9.1** — покусано мутациями всё, включая сегодняшние; отметка последней.
> - **10.1** — прогон делается каждый раз; отметка последней.
> - **10.2–10.4** — живой прод, боевой трафик каждые 30–90 минут: тихое окно, очередь
>   проверить, санкция владельца на рестарт. 🔴 До этого выставить `gateway_msisdn`:
>   пока он пуст, НИ ОДИН рунг не предлагается.
> - **2.3** — `check-base.sh` перед архивацией, ждать «можно». Архивировать раньше
>   `route-sends-by-operator` нельзя.
>
> ### Оплаченный урок этой сессии
>
> **«Заблокировано на владельце» — утверждение о задаче ЦЕЛИКОМ, и оно почти всегда
> шире правды.** 6.5 стояла запертой на двусмысленности, у которой обе ветви
> прочтения требовали одного и того же куска работы: списка остатка лестницы. Без
> него «выбрать снова» нечем сделать при ЛЮБОМ толковании. Проверка дешёвая —
> выписать обе ветви и спросить, что у них ОБЩЕЕ; общее строится не дожидаясь
> ответа, и к моменту ответа остаётся развилка в одну дверь, а не задача.
>
> 🔴 Репозиторий работается параллельно; ворктри вырезан. Венв в ворктри нет:
> `/Users/deralsem/dev/sms-gate/venv/bin/python -m pytest`.

> ## 19.09.2026, поздно — состояние на 31 из 44 (история; актуальную главу см. выше).
>
> **31 из 44. Реализовано всё, что не заперто на владельце, соседе или проде.**
> Восемь коммитов на ветке `worktree-verify-by-inbound-contact`, `f22283e`..`fe32854`.
> Набор: **821 зелёный, 6 падений — ровно унаследованные** `test_alert_send_sh` (4) и
> `test_cds_attribution` (2).
>
> ### 🟢 Решение владельца 19.09: базу `phone-verification` строит ЭТА заявка
>
> Граница проведена и записана в `route-sends-by-operator/tasks.md` (раздел 4), чтобы
> сестринская сессия не построила то же самое: **ядро здесь, вендорское — там.** У соседа
> остаются адаптеры uCaller и Telegram Gateway, подпись коллбэка, шаблон `sms_out`,
> вендорская половина учёта денег и само правило маршрутизации по оператору. Они и так
> заперты на аккаунтах и балансах (его задачи 1.1, 1.7).
>
> ### Что стоит в коде
>
> | Где | Что |
> |---|---|
> | `app/modem/at_commands.py` | `CLIP` переподаётся в `soft_recover`; `caller_id_subscribed` — запись, а не опрос |
> | `app/modem/parser.py` | `parse_clip` по захваченному контракту, с CLI validity |
> | `app/modem/calls.py` | схлопывание повторов: правило о времени, зазор 10 с |
> | `app/modem/manager.py` | `RING`/`+CLIP` в ридере, журнал звонков, редакция кода в оповещении, `verification_step` |
> | `app/db/migrate.py` | `inbound_calls`, `verifications`, `verification_rungs` |
> | `app/db/queries.py` | приём, выбор, проверка, подтверждение событием, свип, удержание |
> | `app/verification/routes.py` | реестр: порядок из конфига, проба на рунг, бюджет на НАБОР, возраст доказательства |
> | `app/verification/probes.py` | пробы `call_in` и `sms_in` |
> | `app/verification/dispatch.py` | единственный оглашатель конца проверки |
> | `app/api/router.py` | `POST /verifications`, `/route`, `/check`, `GET /verifications/{id}` |
>
> Настройки: `verification_ttl_seconds`, `verification_max_attempts`,
> `verification_retention_days`, `verification_route_order`, `verification_probe_timeout`,
> `verification_proof_max_age_seconds`, `verification_call_in_ttl_seconds`,
> `gateway_msisdn`. 🔴 **`gateway_msisdn` пуст по умолчанию, и пока он пуст, НИ ОДИН из
> двух рунгов не предлагается** — человеку нечего сказать, куда звонить. Это верно, но на
> проде это первое, что надо выставить.
>
> ### 🔴 Три вещи для владельца, которых я не решал
>
> 1. **Спека противоречит собственному механизму.** Она говорит «код отдаётся в ответе на
>    СОЗДАНИЕ» (`sms_in`), но эта же заявка вводит выбор маршрута ПОСЛЕ создания — на
>    создании рунга ещё нет, и отдать код приложению, которое потом выберет `call_in`,
>    значит отдать секрет задаром. Реализовано на ВЫБОРЕ `sms_in`. Правка спеки закрывает
>    отметку круга (`.critique` хранит хеш `specs/`), поэтому это решение, а не уборка.
> 2. **Задача 6.5 не закрыта из-за двусмысленности.** «Провалившийся рунг проваливает
>    проверку… и потребитель выбирает снова» — но выбрать снова на проваленной проверке
>    нельзя по определению. Либо «снова» значит новую проверку, либо провал не терминален.
>    Запрет тихой перепрыжки реализован целиком; неясна именно вторая половина.
> 3. **Путь утечки кода, который я НЕ трогал.** Входящая SMS уходит приложению по
>    `inbound_dispatch` — маршрутизация по первому слову, то есть возможно НЕ тому
>    приложению, которое завело проверку. Если человек напишет код, этот код уедет туда
>    вместе с текстом. Это сегодняшнее поведение, и задача 8.3 прямо велит его не менять;
>    оповещение оператору я вычистил, а это — нет. Решать владельцу.
>
> ### Реестр: строка `20260918-03` снята 19.09.2026
>
> Владелец распорядился снять. Проба сработала 18.09 в 16:42 — первая входящая SMS ПОСЛЕ
> включения IMS дошла, доставка не ушла с CS. 🔴 **Остаток строки не наш и не сделан:**
> задачу 1.3 заявки `watch-the-voice-route` и снятие с неё статуса главного риска делает
> та сессия, что ведёт заявку. Строка снята, напоминать больше некому — если сосед об
> этом не узнает, оно потеряется.
>
> ### Что осталось и почему
>
> - **Владелец:** 1.2 (замер трёх шагов отбоя), 1.4 (остаточный риск), 1.5 (окно `call_in`
>   — сейчас по умолчанию равно ладдерному), 1.6 (держать ли `sms_in`), плюс три пункта выше.
> - **Сосед `watch-the-voice-route`:** 3.1/3.2 — ряд `AT+QCFG="ims"`. Шов готов и ждёт:
>   `ModemManager.ims_proof` — это `callable`, возвращающий `Proof(holds, measured_at)`;
>   сейчас его НЕТ, и потому рунг `call_in` не предлагается вовсе. Это верное направление
>   отказа, а не поломка. 🔴 Эта заявка НЕ трогает `_DIAG_QUERIES`.
> - **9.1** — покусано мутациями всё, что написано (14 мутаций по пяти семействам
>   сторожей); отметка ставится последней, когда код перестанет расти.
> - **10.1** — прогон делается каждый раз; отметка тоже последней.
> - **10.2–10.4** — живой прод. Боевой трафик каждые 30–90 минут: тихое окно, очередь
>   проверить, санкция владельца на рестарт. 🔴 До этого выставить `gateway_msisdn`.
> - **2.3** — `check-base.sh` перед архивацией, ждать «можно».
>
> ### Оплаченные уроки этой сессии
>
> - **Позитивный контроль поймал то, что негативный сторож пропустил бы зелёным:**
>   перепроверяя рунг под открытой проверкой, проба натыкалась на её же окно, и каждая
>   проверка умирала через минуту после выбора. Отсюда `excluding`.
> - **Отметка, поставленная по наличию функции, а не по вызову:** 7.2 была отмечена, когда
>   существовал только писатель. Греп по каждому новому публичному имени вскрыл три таких
>   места. Правило простое: `grep -rn '<имя>' app/ | grep -v 'def '` перед отметкой.
> - **Дублёры `ATSerial` в чужих тестах не знают о новых свойствах** — семь тестов упали не
>   от продукта, а от ручных заглушек. Заглушка обязана стоять за то, что подменяет.
>
> 🔴 Репозиторий работается параллельно; ворктри вырезан. Венв в ворктри нет:
> `/Users/deralsem/dev/sms-gate/venv/bin/python -m pytest`.

> ## 19.09.2026, утро — разделы 4 и 5 (история; актуальную главу см. выше).
>
> **Реализация началась. Разделы 4 и 5 закрыты кодом, 13 из 44 задач. Раздел 6
> ЗАБЛОКИРОВАН — посылка прошлого хендоффа о нём не подтвердилась.**
>
> Ворктри `.claude/worktrees/verify-by-inbound-contact`, ветка
> `worktree-verify-by-inbound-contact`, два коммита: `f22283e` и `9eab2d5`.
>
> ### Что отгружено
>
> - **4.1, 4.2, 9.4 — подписка на номер звонящего.** `soft_recover` теперь переподаёт
>   `CLIP_SUBSCRIBE` за `CNMI_SUBSCRIBE` (`app/modem/at_commands.py`), отказ не валит
>   восстановление, но ЗАПИСЫВАЕТСЯ. Свойство `ATSerial.caller_id_subscribed` — запись, а
>   не опрос: гаснет вместе с поколением линка, ничего не спрашивает у модема.
>   `tests/test_caller_id_record.py`, восемь сторожей.
> - **4.4, 5.1–5.5 — ридер узнаёт о звонке.** `parse_clip` в `app/modem/parser.py` по
>   захваченному контракту (последнее поле — CLI validity). Схлопывание повторов —
>   `app/modem/calls.py`, правило о ВРЕМЕНИ (зазор 10 с), проверяемое без модема. Строка
>   пишется на первом `RING` в свою таблицу `inbound_calls`, номер пристёгивается первым
>   `+CLIP`; канонизация `phonenumbers` ДО записи, сырая форма рядом. `ATH` не выдаётся —
>   сторож на «ридер не говорит модему ничего». Оператору: `caller_id` в снимке здоровья,
>   `calls_total`/`calls_without_number` на странице диагностики.
>   `tests/test_inbound_calls.py`, девятнадцать сторожей.
> - Обработчики звонка обёрнуты так же, как `+CDS`: падение записи не уносит `reader_loop`
>   (проверено сторожем — `+CMTI` за упавшим звонком доезжает).
> - Покусано мутациями: снятие переподачи `CLIP` роняет 4 теста, «запись всегда держится» —
>   3, снятие схлопывания — 9, снятие канонизации — 2, игнор validity — 1.
> - Набор: **735 зелёных, 6 падений — ровно унаследованные** `test_alert_send_sh` (4) и
>   `test_cds_attribution` (2). Семь тестов-соседей поправлены: их ручные дублёры `ATSerial`
>   не знали про `caller_id_subscribed`, а свип диагностики получил ряд `calls`.
>
> ### 🔴 Раздел 6 начинать НЕЛЬЗЯ, и прошлый хендофф тут ошибался
>
> Он писал «6.1–6.7 можно делать прямо сейчас, ничего не ждёт». Проверено кодом:
>
> - `grep -ril verification app/` — до этой сессии НОЛЬ совпадений;
> - публичный API это `/sms/send` и `/sms/{id}`, больше ничего;
> - таблицы `verifications` не существует, `POST /verifications` не существует,
>   `/check` и `GET /verifications/{id}` не существуют.
>
> **У двери `POST /verifications/{id}/route` нет источника `{id}`.** База capability
> `phone-verification` — чужая: её нормы лежат в дельте `route-sends-by-operator`, а та на
> 9/89 и все её кодовые задачи (4.1–4.8) не закрыты. Наша задача 7.1 прямо велит
> «переиспользовать хранилище `phone-verification`, второго не заводить» — переиспользовать
> нечего.
>
> Разделы 6, 7, 8 и сторожа 9.2/9.3/9.5 стоят на этом же. Задача 4.3 («запись — это и есть
> предусловие рунга») не закрыта по той же причине: рунга нет.
>
> ### 🟡 Вопрос владельцу — он один и он отпирает больше всего
>
> **Кто строит базу `phone-verification` — эта заявка или `route-sends-by-operator`?**
> Соседнюю ведёт сестринская сессия, и две сессии, строящие одну дверь, — та самая
> коллизия, ради которой заявка НЕ трогает `_DIAG_QUERIES`. Сам построить базу здесь
> нельзя без этого решения: строки будут одни и те же.
>
> ### Что осталось, по причинам
>
> - **Владелец:** 1.2 (замер трёх шагов отбоя), 1.4 (остаточный риск), 1.5 (окно `call_in`),
>   1.6 (держать ли `sms_in` вообще).
> - **Сосед `watch-the-voice-route`:** 3.1/3.2 — ряд `AT+QCFG="ims"`. Эта заявка НЕ трогает
>   `_DIAG_QUERIES`.
> - **База `phone-verification`:** 4.3, 6.1–6.7, 7.1–7.5, 8.1–8.2, 9.2, 9.3, 9.5.
> - **8.3 — половина сделана:** звонок не попадает в `inbound_messages`, сторож есть.
>   Вторая половина (проверка ничего не прячет и не переклассифицирует) ждёт базы.
> - **10.1** не отмечена сознательно: это финальная сверка, а код ещё пишется.
> - **10.2–10.4** — живой прод. Боевой трафик каждые 30–90 минут: тихое окно, очередь
>   проверить, санкция владельца на рестарт.
>
> 🔴 **Архивировать эту заявку РАНЬШЕ `route-sends-by-operator` нельзя.** Перед архивацией —
> `./openspec/changes/verify-by-inbound-contact/check-base.sh`, ждать «можно».
>
> 🔴 Репозиторий работается параллельно; ворктри вырезан — работать в нём. Венв в ворктри
> нет, прогонять набор основным: `/Users/deralsem/dev/sms-gate/venv/bin/python -m pytest`.

> ## 18.09.2026 ~19:30 — авторинг закрыт (история; актуальную главу см. выше).
>
> **Заявка ПЕРЕСОБРАНА дельтой к `phone-verification`. Авторинг закрыт, кода ноль.**
> Ворктри `.claude/worktrees/verify-by-inbound-contact`, ветка
> `worktree-verify-by-inbound-contact`. 15 блоков (4 `MODIFIED`, 1 `REMOVED`, 10 `ADDED`),
> 49 сценариев, `openspec validate --changes --strict` — 7 из 7 зелёные.
> Отметка круга стоит (`.critique`).
>
> ### Что сделано в этой сессии
>
> - Прочитана `route-sends-by-operator/specs/phone-verification/spec.md` целиком — то,
>   с чего следовало начать. Своя capability `inbound-verification` снята; каталог
>   `specs/inbound-verification` переименован в `specs/phone-verification`.
> - **Три находки круга внесены**, семь чужих требований НЕ дублированы.
> - **Ссылки по имени починены**: `route-sends-by-operator/proposal.md` (2 места),
>   его же `specs/phone-verification/spec.md` (2 места),
>   `reach-people-in-messengers/tasks.md:3` (это была ЧЕТВЁРТАЯ, в хендоффе не названная),
>   `entry:` строки реестра `20260912-01` (пятая, вела на мёртвый путь).
> - **Сторож порядка архивации заведён** — `check-base.sh` + строка реестра
>   `sms-gate/20260918-04`. Проверен в обе стороны. ⚠️ `waiting.py new` положил строку в
>   ОСНОВНОЕ дерево (оно на `master` и общее) — перенёс в ворктри и вернул основное как
>   было. Следствие: строка видна из этой ветки и НЕ видна с `master`, пока ветка не
>   влита. Это верно — заявка, которую она сторожит, там тоже не существует.
>
> ### 🟢 Развилка находки 1 решена третьей ветвью — ни «читать», ни «считать неисправностью»
>
> Хендофф прошлой сессии считал обе ветки плохими. Третья: **подписка `AT+CLIP=1` — это не
> то, что шлюз ЧИТАЕТ, а то, что он ДЕЛАЕТ, значит факт, который он может ЗАПИСАТЬ.**
> Предусловие — собственная запись «выдана ли команда успешно на нынешнем поколении
> линка», а не опрос модема. При держащейся записи анонимный `RING` = абонент скрыл номер
> (штатно); при потерянной — рунг вообще не предлагался. Остаток (прошивка теряет подписку
> без цикла `CFUN`) закрыт СЧЁТОМ звонков без номера: он превращает невидимое в скорость.
>
> Дерево, кстати, уехало с прошлой сессии: `CLIP_SUBSCRIBE` уже в коде
> (`at_commands.py:38`, коммит `3026351` от 14.09), и `clip`/`clip_caps` уже в
> `_DIAG_QUERIES`. Чего НЕТ — переподачи в `soft_recover` (`at_commands.py:669-681`).
>
> ### 🟢 Закрыто без владельца
>
> - **Окно 2 минуты** — снято. `phone-verification` уже несёт пять минут решением
>   владельца 18.09; спека делает окно рунга отдельно настраиваемым и не длиннее
>   ладдерного, а конкретную цифру отдаёт задаче 1.5.
> - **Шов возраста IMS** — сосед `watch-the-voice-route` ОБЯЗАН отдавать время последнего
>   успешного замера (требование «A voice route that stopped being measured…»). Нехватало
>   предельного возраста — он теперь наш и записан нормой.
> - **`telegram_bot`** — из спеки выкинут. Довод критика структурный и проверен: его
>   предусловие недоказуемо до выдачи списка. Живёт задачей 1.3, не нормой.
>
> ### ✅ Три ответа владельца 18.09 ~20:00 — внесены
>
> 1. **Кладём трубку, как только номер определён** (первый `+CLIP`). Звонок не доезжает до
>    голосовой почты — это и делает рунг бесплатным абоненту, а не «предположительно
>    бесплатным». 🔴 Но механизм весь непроверен: `ATH` с командного порта, который держит
>    отправитель; что он вообще гасит НЕОТВЕЧЕННЫЙ входящий на этой прошивке; что делает
>    оператор с отбитым звонком. Поэтому нормой записано: **подтверждение стоит на номере,
>    который уже в руках, и НИКОГДА на успехе отбоя** — неудавшийся отбой пишется в журнал,
>    не валит проверку и не задерживает отправку. Задача 1.2 — замерить всё три.
> 2. **Словарь решён: плоский список, имена разведены.** `sms_out`, `sms_in`, `call_in`,
>    `flash_call`, `tg_gateway`, `tg_user`, `max_user`, `app_bot`. `call` изъят вовсе (значил
>    два механизма в двух заявках), `modem` → `sms_out`. Применён здесь и в
>    `route-sends-by-operator` (34 значения в трёх спеках, плюс абзац, который ставил вопрос,
>    теперь записывает решение). В `reach-people-in-messengers` НЕ применён — её файлы ведёт
>    сестринская сессия; решение записано в её задачу 1.1, менять там надо только `modem`.
> 3. **Контракт отдадим, когда поймём, что и как по итогу.** Посылка соседа исправлена:
>    `route-sends-by-operator` задачи 3.1/3.2a/3.2 и абзац спеки больше не говорят об
>    «уже отданном» контракте и о «четырёх расхождениях в руках разработчика».
>
> ### ⚠️ Что из ответа про «один раз» стоит взвесить отдельно
>
> Проверка происходит **однажды, при заводе клиента**, дальше авторизация по почте. Значит
> платный рунг — разовая цена привлечения, а не текущая. Отсюда новая задача **1.6**: стоит
> ли вообще держать `sms_in` — единственный рунг, за который платит АБОНЕНТ. Если событие
> раз в жизни клиента, 0,80 ₽ наших дешевле, чем просить нового клиента писать роботу.
> Владельцу не задавалось; лестницу не менял.
>
> ### 🔴 Открытое — и что из этого требует владельца
>
> 1. **Задачи 1.2, 1.4, 1.5, 1.6 — владельцу.** 1.2 не решение, а замер (три шага отбоя).
>    1.4 — приемлемость остаточного риска, теперь уже, чем казалось: атака покупает не
>    сессию, а аккаунт в проекте, привязанный к чужому номеру. 1.5 — окно для `call_in`.
>    1.6 — держать ли `sms_in` вообще (см. выше).
> 2. **`AGENTS.md` не в гите вовсе** — untracked и игнорируется. Конвенции проекта
>    (канонизация номеров через `phonenumbers` и прочее) живут в файле, которого в свежем
>    клоне не будет. На эту заявку не влияет; кому-то надо решить.
> 3. **`watch-the-voice-route` объявила правку `verify-by-inbound-code/proposal.md` своим
>    Impact** — пункт погашен здесь, соседу его надо снять. Её файлы не трогал: untracked
>    в основном дереве, ведёт сестринская сессия.
> 4. **`reach-people-in-messengers` ждёт применения словаря** — только `modem` → `sms_out`,
>    решение записано в её задачу 1.1. Её спеки не трогал по той же причине.
>
> ### Первый ход следующей сессии — РЕАЛИЗАЦИЯ, и часть её не заблокирована
>
> Авторинг закрыт: 15 блоков, 51 сценарий, отметка круга стоит, `validate` 7/7.
> **Начинать с `openspec instructions apply --change verify-by-inbound-contact`**, а не с
> перечитывания истории: всё состояние в `proposal.md` и `tasks.md`.
>
> **Можно делать прямо сейчас, ничего не ждёт:**
>
> - **4.1 — переподача `CLIP_SUBSCRIBE` в `soft_recover`** (`app/modem/at_commands.py:669-681`,
>   рядом со строкой 681, где переподаётся `CNMI_SUBSCRIBE`). Однострочник, но TDD: тест
>   первым и обязан упасть первым. Это же 9.4.
> - **4.2–4.4** — запись состояния подписки по поколению линка, она же предусловие рунга
>   вместо опроса модема; счётчик звонков без номера.
> - **5.1–5.5** — `RING`/`+CLIP` в `reader_loop` (`app/modem/manager.py:746-762`, сейчас обе
>   строки падают в `else` и логируются как `Unhandled URC`), канонизация через
>   `phonenumbers`, схлопывание пятнадцати повторов в одно событие, свой стор звонков,
>   отбой по первому `+CLIP`.
> - **6.1–6.7** — чузер: реестр маршрутов с пробой предусловия, дверь выбора
>   `POST /verifications/{id}/route`, запрет тихой перепрыжки.
>
> **Ждёт и начинать нельзя:**
>
> - **3.1/3.2** — ряд `AT+QCFG="ims"` кладёт `watch-the-voice-route` (сестринская сессия).
>   🔴 Эта заявка НЕ трогает `_DIAG_QUERIES`: две заявки в одном свипе — так одна из них
>   молча теряется.
> - **1.2, 1.4, 1.5, 1.6** — владелец. 1.2 не решение, а замер трёх шагов отбоя.
>
> ⚠️ **10.2/10.3 — живой прогон на проде.** Прод несёт боевой трафик: коды и пароли живым
> людям каждые 30–90 минут. Тихое окно, очередь проверить, санкция владельца на рестарт.
>
> 🔴 **Архивировать эту заявку РАНЬШЕ `route-sends-by-operator` нельзя.** Пять блоков
> адресуют требования, которых в живой спеке нет; `validate` на это молчит. Перед
> архивацией — `./openspec/changes/verify-by-inbound-contact/check-base.sh`, ждать «можно».
>
> 🔴 Репозиторий работается параллельно; ворктри вырезан — работать в нём.

Состояние на 12.09.2026, вечер. Ниже по файлу лежат слои 07.09 и 11.09 — датированы,
не переписаны.

> 🟢 **РАЗМОРОЖЕНА 12.09.2026 — решение владельца.** Спрошено прямо: какую из трёх
> ветвей считать живой сейчас — обратный код, uCaller или мессенджеры. Назван
> обратный код. **Это снова основной путь, и входить сюда.**
>
> 🧊 Была заморожена 08.09.2026, тоже решением владельца, в пользу uCaller (flash
> call: звонит вендор, код — последние цифры номера звонящего). Заморозка держалась
> четыре дня; за них uCaller не продвинулся ни на шаг — он упирается в аккаунт,
> оплаченный баланс и четыре нерешённых вопроса, и **ни один абонент МегаФона за
> эти дни не получил ничего.** Сессия `U·uCaller` закрылась, её состояние осталось
> в `.claude/handoff/ucaller.md`.
>
> **Соседи живы, дерево общее.** `M·мессенджеры` ведёт лестницу Telegram/MAX
> (`.claude/handoff/codes-in-messengers.md`), владение файлами разведено: мои —
> `proposal.md`, `tasks.md`, `HANDOFF.md` этой заявки; её — свой хендофф и то, что
> она заведёт в `openspec/changes/`. `route-sends-by-operator/*` и `.claude/waiting/*`
> лежат с незакоммиченными правками мёртвой `U·uCaller` — не трогает никто.
>
> ⚠️ **Контракт у разработчика парковки разошёлся с заявкой по ПЯТИ вещам** — пути,
> словарь способов, форма вебхука, срок 10 минут и ДВЕ заглушки-номера вместо одной.
> Все пять записаны задачами 1.1–1.5 и **ни одна не наша:** правит контракт владелец.

## Что случилось в проде

С 06.09.2026 ~18:30 МСК МегаФон отбивает все наши SMS с TP-статусом `0x63`
(«service rejected»). За всю историю шлюза таких 50; 35 из них — в 30 часов от
того вечера. У остальных операторов в те же минуты доставка 100%.

**Проверено опытом, не догадкой.** 07.09 отправлены шесть сообщений на
подтверждённый мегафоновский номер `+79851600019`: текущий формат, цифры
словами, цифры без бренда, кириллица с цифрами, нейтральный текст без кода
вообще, и контроль в конце. **Отбиты все шесть.** Параллельный боевой трафик на
Билайн, Теле2 и Т2 в те же минуты доставлен. Вывод: режется направление
отправителя, содержимое не влияет ни на что.

**Симку этого шлюза уже блокировали раньше** (со слов владельца). Поэтому
событие считается повторяющимся, а не разовым, и радиус у него бывал полным.

Голосовая ветка проверена и закрыта: звонок на номер симки — тишина и разрыв,
при этом обычная SMS на неё долетает. Значит мёртв именно голос. Модем —
Quectel EG06/EP06/EM06 (`2c7c:0306`), портов `ttyUSB0..3`, шлюз держит USB2 и
USB3. Свободного AT-порта нет; лезть в занятый нельзя — падение линка 06.09 в
18:29 было именно с «multiple access on port?». У владельца есть EM12-G, его
предполагалось проверить отдельно от прода на запасной симке (`AT+CLIP=1`,
ждать `RING` и `+CLIP`). Результата пока нет и на срочный путь он не влияет.

## Сделано 12.09.2026 — после разморозки

Правки по точным якорям, не перезаписью: дерево общее с `M·мессенджеры`.

1. **`proposal.md` — снят ценовой довод, на котором стояло обоснование.** В Why
   значилось «≈530 ₽/month for the МегаФон share, and a monthly sender-name fee that
   dwarfs it» — обе половины из подсчёта, недосчитавшего МегаФона вдвое (`upper()` и
   `LIKE` в sqlite ASCII-only). Замер 08.09 по боевой базе: flash call 0,80 ₽ за
   верификацию ≈ 52 ₽/мес, SMS-провайдер ≈ 190 ₽/мес. **Ни то ни другое не сумма,
   ради которой разворачивают протокол.** Взамен в Cost написано, чем заявка ценна на
   самом деле: ни аккаунта, ни баланса, ни ключа — нечему кончиться посреди входа, и
   это не гипотеза, а ровно то, на чём основной путь стоит с 08.09.
2. **`proposal.md` — «не проходит ни одно» было малой выборкой.** С 06.09 18:30 по
   08.09 на МегаФон ушло 55 сообщений: 49 `failed`, 6 доставлено живыми `+CDS`.
   Примерно каждое девятое. Вывод заявки не меняется, утверждение — меняется.
3. **`proposal.md` — Status несёт обе даты владельца**, заморозку и разморозку, и
   честную строку «круг критики до сих пор не прогнан».
4. **`tasks.md` — пять расхождений контракта приземлены задачами 1.1–1.5**, плюс
   задача 2.2 дописана найденным: соседняя заявка уже нормирует правило как
   **свой типизированный setting** (существующий dispatch-route требует `webhook_url`
   на каждой записи и правило отверг бы), и расхождение с этой заявкой не в
   хранении, а в модели — там оператор отображается в **именованный маршрут**
   (`call`, `modem`), здесь спрашивается булево «configured as undeliverable».
   Булево трёх маршрутов не выражает.

Механика после правок: `openspec validate --strict` зелёный, `check.py` по символам и
путям спеки чист, 13 сценариев как было — сценариев я не трогал.

## Сделано 07.09.2026 — всё НЕЗАКОММИЧЕНО на тот момент

1. **`hold-messages-on-a-temporary-tp-status`** — исправлена неверная
   нормативная строка. Она объявляла `0x60–0x7F` диапазоном «SMSC ещё
   пытается»; на деле там SMSC попытки прекратил. Реализация как было написано
   держала бы сегодняшние отказы до таймаута и гасила в `expired` вместо
   честного немедленного `failed`, то есть ломала бы работающий код.
   Замер, которого заявка просила и не имела, добавлен: `0x63` — 50 случаев,
   `0x46` — 21, `0x40` — 1, диапазон `0x20–0x3F` — **ноль за всю жизнь шлюза**.
   Заявка написана ради ветки, которая ни разу не срабатывала.
2. **`docs/modem.md`** — таблица статусов была активно неверна: `96` значилось
   постоянной ошибкой «incompatible destination». На деле `96` = `0x60`,
   временный-брошенный, congestion; `incompatible destination` это `65`. Кода
   по той таблице зачёл бы сетевой затор в чёрный список абонента. Исправлено.
3. **`route-sends-by-operator`** — новая заявка: два маршрута (модем и
   коммерческий провайдер), выбор правилом по оператору, без хардкода имени
   оператора в ветке. Без автопереключения — решение владельца. Приоритет
   опущен: при работающем обратном коде нужна только тем, у кого скрыт
   определитель или нет SMS в тарифе.
4. **`verify-by-inbound-code`** — новая заявка. Была основным путём до
   заморозки 08.09, см. шапку. Разворот
   направления: клиент отправляет код нам. Фильтруется наш исходящий A2P;
   сообщение от абонента к нам — обычный P2P и под фильтр не попадает. Приём
   входящих у шлюза работает и проверен.

Все заявки проходят `openspec validate --strict`. `check.py` по символам чист.

## Контракт разработчику парковки — отдан

https://claude.ai/code/artifact/8db0c383-4029-4220-8be9-653fa8e23c26

Опубликован как проект, а не как описание работающего API. В нём три ручки:
`POST /verify`, `POST /verify/{id}/check`, `GET /verify/{id}` плюс вебхук.

🔴 **«Подставить настоящий номер ДО отправки разработчику» — этого не произошло.**
Прежняя редакция писала так, будто отправка ещё впереди; контракт ушёл 07.09 с
заглушкой внутри. Исправлено 12.09: заглушек **две** — `+79001234567` в JSON-примере
и `+7 900 123-45-67` в тексте экрана, и подменить одну без другой значит отдать
контракт, противоречащий себе.

**Что в контракте придумано агентом и уже названо клиенту:** десять минут на код,
опрос раз в две секунды, обе заглушки, словарь способов `outbound`/`inbound`, вебхук
с id верификации в поле `id`.

**Пять расхождений с соседней заявкой — задачи 1.1–1.5.** Правит контракт владелец:
у разработчика лежит документ, который отправил он. Находку про пять вещей (а не про
одно имя пути) принесла сессия `U·uCaller`, прочитав сам артефакт.

## Первый шаг — здесь и сейчас (12.09.2026, вечер)

**Реализация по-прежнему заперта, и не заморозкой, а контрактом.** Разморозка сняла
запрет владельца, но задачи 1.1–1.5 — письмо разработчику парковки и решение владельца
по пяти расхождениям. Ни одну из них агент закрыть не может: документ отправлял
владелец.

🔴 **ПРИОРИТЕТ НЕ РАЗВЕДЁН — слова владельца за один вечер разошлись, и это состояние,
а не недоразумение.** Мне, прямым ответом на прямой вопрос «какую из трёх ветвей считать
живой сейчас»: **разморозить обратный код**. Сессии `M·мессенджеры`, **позже** (хронологию
подтвердила она сама): **мессенджеры — план А, обратный код — план Ц, «даже не Б».**
**РАЗВЕДЕНО в тот же вечер, владельцем:** «я бы начал с мессенджеров, честно; подключаем
юзер-акки, они шлют коды, шлют линки на оплату». План А — лестница
(`openspec/changes/reach-people-in-messengers`, сессия `M·мессенджеры`). Эта заявка **не
заморожена обратно, но и не ведётся**: разморозка в силе, приоритета нет.

Сторожится строкой **`sms-gate-ec2f9e87/20260912-01`** живого реестра
(`python3 ~/.claude/scripts/waiting.py list`). Машинной пробы у неё нет и быть не может:
наблюдаемый признак — доля кодов `sp_app`, ушедших НЕ через модем, а такого поля сегодня нет
ни в одной таблице; оно появится вместе с отчётом «чем отправлено» из самой лестницы.
Созревание прозой: лестница отгружена и измерена на живой парковке — закрыла коды целиком,
и заявка хоронится решением владельца; осталась часть недостижимых — достраивается.

**Что НЕ заперто и чего заявка не имеет — круг критики (задача 2.3).** 🔴 **СНЯТ С
РЕКОМЕНДАЦИИ 12.09 до разведения приоритета:** под план Ц 460k токенов — неверная трата, а
честная строка «не критикована» в Status лучше отметки, купленной не по приоритету.
Разведётся в пользу этой ветки — гнать; останется план Ц — не гнать и строку не трогать. Он не прогонялся
ни разу, и заявка это признаёт в Status с 07.09. Соседняя `route-sends-by-operator`
свой круг прошла 11.09 и выросла с 37 до 70 сценариев — здесь 13, и сравнение честное:
заявки одного размера по замыслу. Дисциплина круга — `derflow/_lane-c.md`: ровно ОДИН
круг, оба критика (`system-architect` + `gap-finder`), мишень узкая, вход засеян
выводом `check.py`. **Цена замерена: ~460k токенов,** и круг требует сабагентов —
поэтому он запрашивается у владельца, а не запускается сам.

Механика перед кругом уже снята 12.09, отдавать критику входом как установленные факты:
`openspec validate --strict` зелёный · `check.py` по символам и путям спеки чист
(две находки в выводе — битые пути в файлах ПАМЯТИ, `CLAUDE.md` и `derflow/_ship.md`
из `deploy-target-is-master-not-main.md`, к заявке не относятся) · **13 сценариев** —
база счёта для сверки после сведения.

**Задача 2.1 (где живёт верификация — своя таблица или статус на существующей) не
решена** и решается внутри круга, а не до него.

## Решения владельца — не пересматривать без него

- четыре цифры в коде, а не шесть;
- код генерирует шлюз; приложение свой прислать не может;
- автопереключения между маршрутами нет;
- остальные операторы остаются на модеме.

## Следующий шаг — незакрытая ветка

Владелец принёс https://runetlex.ru/auth_guide/ и спросил, законна ли
авторизация через Telegram. Разобрано, но **не доведено**:

- по трактовке этой страницы (149-ФЗ ст. 8 ч. 10) **доставка кода** в Telegram —
  аутентификация, разрешена; **бот, запрашивающий телефон как основание входа** —
  кросс-авторизация через иностранный сервис, запрещена. Штраф 500–700 тыс.,
  повторно до 1,4 млн;
- вторая идея владельца («бот просит телефон, человек делится, авторизуем»)
  попадает именно в запрещённый случай;
- **связка, которую надо решить:** чтобы слать код в Telegram, нужен его ID;
  чтобы его получить, человек должен себя назвать; естественный способ назвать —
  тот самый запрещённый. Предложенный выход: первый вход разрешённым способом
  (обратный код по SMS), Telegram привязывается уже авторизованным и работает
  только для повторных входов;
- в репозитории уже есть seam: `telegram_poll.py`, `alerting.py`;
- ⚠️ **это юридический вопрос, а runetlex — коммерческий сайт юруслуг, не закон.**
  Агент не юрист. До постройки нужно заключение человека с лицензией.

## Чего НЕ делать

- не коммитить и не пушить без слова владельца: пуш в `deploy-remote`
  рестартит боевой сервис, а он несёт живой клиентский трафик;
- не слать тестовые SMS на чужие номера; для проб есть `+79851600019`;
- не открывать AT-порт параллельно с работающим шлюзом;
- не начинать реализацию `verify-by-inbound-code` до ответа парковочного
  разработчика по вебхуку и до подстановки настоящего номера в контракт.

## Первый шаг преемника — УСТАРЕЛ, см. дату

🔴 **Этот раздел был верен 07.09 и с тех пор перестал.** Оставлен как история;
порядком шагов не является. Дописано 12.09.2026.

Что с ним стало:

- «у владельца появилась новая идея, и он её ещё не назвал» — **названа**:
  сперва uCaller (08.09), затем доставка кодов через Telegram и MAX (11.09,
  приоритет ушёл туда). Выслушивать нечего, решения записаны;
- «коммит уже сделанного» — **сделан** 11.09, `8647c92`. Не запушено, и это
  сознательно: пуш рестартит боевой сервис, а кода в коммитах нет;
- «юридическая проверка Telegram» — разобрана и отложена, разбор в
  `.claude/handoff/ucaller.md`. Нужно заключение юриста;
- «реализация обратного кода» — ждёт разморозки, которая решение владельца.

🔴 **Числа в прежней редакции этого раздела НЕВЕРНЫ.** «180 сообщений в месяц»,
«78 получателей», «≈530 ₽/мес за мегафоновскую четверть» — замер 08.09 с боевой
базы их опроверг: `upper()` и `LIKE` в sqlite ASCII-only, кириллицу не трогают,
и первый подсчёт недосчитал МегаФона ВДВОЕ. Правда — в таблице по приложениям в
`.claude/handoff/ucaller.md`: МегаФону в августе ушло 111 сообщений, из них
только 46 от парковки. P1SMS как провайдер отменён вместе с прежней редакцией
заявки.

Что верно и проверять заново не надо: формат сообщения ни на что не влияет
(опыт на шести вариантах), голос на этой симке мёртв, симку уже блокировали
целиком.
<!-- SECTION:NOTES:END -->
