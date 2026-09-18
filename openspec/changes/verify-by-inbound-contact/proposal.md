## Why

Verifying that a person holds a phone number is one job, and this gateway has been
designing it as though it were the job of *sending an SMS*. That framing is what made the
outage of 06.09.2026 look like an emergency: МегаФон stopped accepting this gateway's
outbound traffic — of 55 messages sent between 06.09 and 08.09, 49 failed and 6 arrived,
roughly one in nine — and with one route, a filter on that route is a total outage.

**The gateway now has more than one way to reach a person, and they differ enormously in
price.** Two of them are free. One of those two did not exist as far as anyone knew until
2026-09-18.

🔴 **The premise this change was first written on is withdrawn.** Its earlier text said
*"The modem in service cannot supply the second — verified 07.09.2026, a call to its SIM is
silence and disconnect"*. That is false. The live `EP06-E` (`EP06ELAR03A08M4G`) had IMS
switched off; the setting was invisible because nothing in the gateway reads it. After
`AT+QCFG="ims",1` and `AT+CFUN=1,1` it read `+QCFG: "ims",1,1` — the second digit is the
network's answer, so Билайн admits this module — and a call to the SIM landed as fifteen
`RING` / `+CLIP` pairs in sixteen seconds, carrying the caller's number. The same call to
the same modem had previously left not one line anywhere.

Three days of work concluded "this module has no voice path" from a single `AT+CIREG?` →
`ERROR`. Quectel confirmed in writing on 2026-09-18 that the command is absent from this
build and that IMS state is read with `AT+QCFG="ims"`. **`ERROR` on an AT command is a
statement about the firmware's dictionary, not about the module's capability** — an empty
reading, not a negative one.

## What Changes

**This capability stops being "send a code and hope" and becomes a chooser over a priced
ladder of routes.** A verification request names a number; the gateway answers with the
routes that can actually carry it right now, cheapest first.

- **Six routes, ordered by cost.** An inbound call to the modem and a Telegram bot contact
  are free to both sides. Our own outbound SMS is effectively free to us (flat ~100 ₽/мес)
  and free to the subscriber. uCaller and Telegram Gateway cost ≈0,80 ₽ each. An inbound
  SMS from the subscriber costs *them* one message at their tariff, which is why it is
  last and not first.
- **The order is configuration, not code.** Prices move, vendors change, an operator
  unblocks. Compiling the ladder into the gateway would make a price change a deployment.
- **A route is offered only when its precondition is proven** — not when it is merely
  configured. This is the load-bearing norm of the change; see below.
- **The response carries the available routes, not a single choice.** The consuming
  application may take the first silently or present them to the person. Either way it
  never looks up an operator and never holds a table of which networks work.
- **The method that confirmed a verification is recorded and returned**, because the
  methods are not equally strong and the consumer is entitled to know which one it got.
- **Inbound messages become consumable by the owning application**, which today they are
  not: the public API is `/sms/send` and `/sms/{id}` only, and inbound is visible in the
  admin UI alone (`app/admin/router.py:351`).

Not in this change: `/sms/send` keeps working unchanged for messages that are not
verifications.

## The load-bearing norm: a route must prove itself, or it is not offered

An incoming call reaches the modem **only while IMS is on**. If IMS goes off — a modem
reset, a firmware reload, an operator change — `RING` simply stops arriving. There is no
error anywhere. Every call verification would hang until it expired and then report
"expired", which is indistinguishable from "the person never called".

With the call as the first rung, that is a **silent total outage of verification**, and it
is the single most dangerous property of this design. The remedy is not a better handler.
It is that the chooser may not hand out a route it cannot prove is working: no proof of
IMS, no call rung — the ladder simply starts one step lower, and the person verifies by
another route without ever knowing there was a problem.

The same shape applies to every rung: a vendor with an exhausted balance, an operator on
the undeliverable list, a Telegram account that cannot be reached. **A rung that cannot
prove its precondition is skipped, never attempted-and-failed.**

⚠️ **Two rungs depend on egress, and egress is not stable.** `ucaller` and
`telegram_gateway` are calls to `api.ucaller.ru` and `gatewayapi.telegram.org`. Telegram is
blocked on this host's backup uplink — measured, not supposed — and reaches it today only
through a relay that the sibling change `carry-telegram-on-any-uplink` records as working
but nowhere normalised. So the moment the gateway fails over is the moment two paid rungs
may become unreachable, and it is also the moment things are already degraded. Their
preconditions SHALL therefore be reachability now, not configuration; the general norm
above covers it, and it is named here because this one is history rather than foresight.

⚠️ **This change does not build the IMS reading; it consumes it.** The sibling change
`watch-the-voice-route` puts `AT+QCFG="ims"` into the read-only sweep and replaces the two
rows that cannot answer on this firmware (`AT+CIREG?`, `AT+QCFG="servicedomain"`). This
change depends on that one and must not touch `_DIAG_QUERIES` itself — two changes editing
the same sweep is how one of them silently loses.

## What an inbound call proves, and what it does not

**It proves possession of the number exactly as well as the network's caller ID can be
trusted, and no better.** `+CLIP` is spoofable. That is stated here rather than buried,
because this route is the first rung and will carry most verifications.

🔴 **The earlier rationale in this document for the four-digit code was wrong, and the
correction matters.** It read: an attacker "must additionally produce a code displayed only
on the subscriber's screen". The flow refutes it — the application displays the code to
whoever started the verification. An attacker who enters someone else's number sees the
code on their own screen. **The code is not a secret from the attacker; it is an
attribution tag**, telling the gateway which open verification an arriving message belongs
to and preventing an unrelated inbound message from confirming anything.

So the real defence in *both* the SMS and the call route is one and the same: the event
must originate from the number being verified. The routes differ in how hard that is to
forge on each bearer, not in the number of factors.

**One asymmetry survives, and it is named because it is real.** A person is easy to
persuade to dial a number and nearly impossible to persuade to send four specific digits.
An attacker can open a verification on a victim's number and, in the same minute, give the
victim a reason to call us. Mitigations: a short window (two minutes — the person is
standing at a barrier), one open call-verification per number, and a rate limit on opening
them. **This does not reduce to zero**, and an application whose stakes do not tolerate it
should read the returned method and refuse it.

## Cost

| Route | Ours | Subscriber's | Precondition that must be proven |
|---|---|---|---|
| `inbound_call` | 0 | **0** | IMS `1,1` and the modem registered |
| `outbound_sms` | ≈0 (flat ~100 ₽/мес) | 0 | operator not on the undeliverable list |
| `telegram_bot` | 0 | **0** | the person reaches the bot and shares the contact |
| `ucaller` | 0,80 ₽ | 0 | account balance |
| `telegram_gateway` | $0.01 ≈ 0,80 ₽ | 0 | balance; Telegram can reach the number |
| `inbound_sms` | 0 | **1 SMS at their tariff** | always available |

**Owner's decision, 2026-09-18: uCaller ranks above Telegram Gateway.** Recorded as a
decision, not as a measurement. The counter-argument was raised and declined: Telegram
Gateway refunds undelivered codes automatically — *"you only pay for successful
verifications"* — so a failed attempt there costs nothing, which would otherwise make it
the cheaper of two routes priced the same. A later reader should know this was weighed.

The honest objection to the old design — that it moved a charge onto the customer — is
answered by the ladder rather than defended: `inbound_sms` is now the last resort, reached
only when five cheaper routes could not prove themselves.

## Capabilities

### New Capabilities

- `inbound-verification`: verifying possession of a phone number, and choosing among the
  routes that can prove it.

## Open questions

1. **What the Telegram bot rung actually is.** Recorded as the author's reading of the
   owner's words on 2026-09-18 — a bot that requests the contact, with Telegram vouching
   for the number-to-account binding — and not yet confirmed by the owner. It is specified
   below as a route with that precondition; if the owner meant something else, the rung
   changes and nothing else does.
2. **Whether the gateway hangs up.** Answering costs the caller money and needs an audio
   path this module does not have. Not hanging up sends the caller to our voicemail.
   `ATH` would end the ringing, but (a) it needs the command port, which the sender holds,
   and (b) that `ATH` rejects an unanswered incoming call on this firmware is an assertion
   about the device, not a measurement — the external-contract gate binds it. Specified
   below as best-effort and explicitly outside the confirmation path.
3. **Whether the SIM's inbox can fill** under sustained `inbound_sms` traffic. Less urgent
   than before, since that route is now last.

## Status

**Authored 2026-09-07 as an inbound-SMS fallback. Reframed 2026-09-18 as a priced ladder,
after the modem was found to accept calls.** The `system-architect` / `gap-finder` round is
owed and has not been run.

🔴 **A statement in the earlier text is corrected on the owner's word: the integration
contract was never handed to the parking developer.** Tasks 1.1–1.5 existed to reconcile a
divergence with an external party and are removed; there is no external party yet. The
owner's plan is to migrate their own projects onto this gradually, which is why every
existing route stays live rather than being retired on cutover.
