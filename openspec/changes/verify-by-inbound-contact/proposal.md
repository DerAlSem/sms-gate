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
- **Two rungs are added here**: `inbound_call` — the subscriber calls the gateway's own SIM,
  free to both sides — and `inbound_sms` — the subscriber texts the code back, last on the
  ladder because it is the only route the subscriber pays for.

Not in this change: `/sms/send` keeps working unchanged for messages that are not
verifications. The rungs `modem`, `ucaller` and `tg_gateway` are specified by
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

⚠️ **Two rungs depend on egress, and egress is not stable.** `ucaller` and `telegram_gateway`
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

## Cost

| Rung | Ours | Subscriber's | Precondition that must be proven |
|---|---|---|---|
| `inbound_call` | 0 | **0 — unproven, see below** | `AT+CLIP=1` recorded as held, IMS registered, evidence fresh |
| `outbound_sms` (`modem`) | ≈0 (flat ~100 ₽/мес) | 0 | operator not on the undeliverable list |
| `ucaller` | 0,80 ₽ | 0 | balance; vendor reachable on the current uplink |
| `telegram_gateway` | $0.01 ≈ 0,80 ₽ | 0 | balance; vendor reachable; Telegram can reach the number |
| `inbound_sms` | 0 | **1 SMS at their tariff** | the modem receives |

🔴 **The first rung's "0 to the subscriber" is not established.** The gateway does not answer
the call — answering costs the caller money and needs an audio path this module does not
have — so the call runs to the carrier's voicemail, and voicemail is a connection. Whether
the subscriber is charged for it is unmeasured. If they are, the premise that puts this rung
first is wrong for the rung it puts first. The spec forbids publishing the cost claim to
consumers until it is measured; task 1.2 carries the measurement.

**Owner's decision, 18.09.2026: uCaller ranks above Telegram Gateway.** Recorded as a
decision, not a measurement. The counter-argument was raised and declined: Telegram Gateway
refunds undelivered codes automatically, so a failed attempt there costs nothing, which would
otherwise make it the cheaper of two routes priced the same.

The honest objection to the old design — that it moved a charge onto the customer — is
answered by the ladder rather than defended: `inbound_sms` is now the last resort, reached
only when every cheaper rung failed to prove itself.

## Capabilities

### Modified Capabilities

- `phone-verification`: gains the two rungs the gateway itself bears (`inbound_call`,
  `inbound_sms`), the norm that a rung is offered only on fresh proof, the consumer's
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

⚠️ **`reach-people-in-messengers` task 1.1 defers the method vocabulary to this change.** It
now points at task 1.1 below. The vocabulary is genuinely cross-cutting — `call` in
`route-sends-by-operator` is uCaller's flash call, in which *"our modem does not participate
at all"*, so this change's rung is `inbound_call` and never `call`.

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
2. **Whether the subscriber pays for the unanswered call.** See Cost. Task 1.2.
3. **Whether the gateway hangs up.** `ATH` needs the command port, which the sender holds, and
   that it rejects an unanswered incoming call on this firmware is an assertion about the
   device, not a measurement. Left outside this change by the spec.
4. **Whether the SIM's inbox can fill** under sustained `inbound_sms` traffic. Less urgent than
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
