## Why

Confirmation codes reach a subscriber only if the operator lets us send. Since 06.09.2026
МегаФон mostly does not: 50 reports of `0x63` across the gateway's history, 35 of them in
the 30 hours from that evening, every one bound for a МегаФон subscriber while every other
operator delivered normally in the same minutes. A probe of six messages differing in
wording, in alphabet and in whether they carried a code at all was rejected identically, so
nothing inside a message changes the outcome. This SIM has also been blocked outright before.

**"Mostly" is measured, and it corrects this proposal's first draft.** Of 55 messages sent to
МегаФон between 06.09.2026 18:30 and 08.09.2026, 49 failed and 6 were genuinely delivered —
live `+CDS` reports, not inferred — so roughly one in nine arrives. A channel that drops
eight codes out of nine cannot carry a login, and the conclusion does not change. But "not a
single one gets through" was a small sample stated as a fact, and a later reader comparing it
to the live database would have found it false.

Every remedy considered so far buys a different way to **send**: a commercial SMS provider,
or a voice channel. The modem in service cannot supply the second — verified 07.09.2026, a
call to its SIM is silence and disconnect while SMS to the same SIM arrives — but a vendor's
flash call supplies it without the modem, and that is the route the owner chose as primary on
08.09.2026.

🔴 **The price argument this was first written with was wrong, and it is withdrawn.** It read
"≈530 ₽/month for the МегаФон share, and a monthly sender-name fee that dwarfs it". Both
halves rest on a count that missed half of МегаФон: `upper()` and `LIKE` in sqlite are
ASCII-only and do not touch Cyrillic, and `number_operators` carries both `МЕГАФОН` and
`МегаФон`. Re-measured against the live database on 08.09.2026: the flash-call vendor charges
0,80 ₽ per verification, ≈52 ₽/month at the three-month average of 65 `sp_app` verifications
to МегаФон, against ≈190 ₽/month for the same traffic at an SMS provider's 2,92 ₽. **Neither
is a sum worth reversing a protocol over,** and what this change is worth is stated under
Cost instead.

**Reversing the direction removes the obstacle; paying only moves it.** What is
being filtered is our outbound A2P traffic to one operator. A message from the subscriber to
us is ordinary P2P between two consumer numbers and is not subject to it. The gateway already
receives, stores and indexes inbound messages — `+CMTI` → `inbound_loop` →
`inbound_messages(phone, text, received_at)` — and that path was confirmed working on
07.09.2026 while the outbound path to МегаФон was refusing everything.

It is also the only option that survives the event that keeps recurring: if the SIM is
blocked for sending again, in whole or in part, inbound still arrives.

## What Changes

- **A new capability owns phone verification**, and owns the choice of how it is done. The
  application asks for a phone to be verified; it does not ask for an SMS to be sent and it
  is not told which route was used.
- **When the gateway cannot deliver to an operator, it says so in the same answer** and
  returns the fallback instruction — the code to display and the number to text — rather
  than accepting the send and failing it later.
- **The gateway generates the code**, because the two halves of the check must have one
  owner: a four-digit code is safe only because it is matched together with the sender's
  number, and splitting the secret from its matcher is what makes short codes unsafe.
- **Inbound messages become consumable by the owning application**, which today they are
  not: the public API is `/sms/send` and `/sms/{id}` only, and inbound is visible in the
  admin UI alone (`app/admin/router.py:351`).

Not in this change: `/sms/send` keeps working unchanged for messages that are not
verifications — `mprz_bot` and the admin console send through it and are not affected.

## Why four digits is enough

Owner's decision, 07.09.2026. It holds because the match is on the **pair** — sender number
and code — not on the code alone. An attacker must send from the subscriber's own SIM, which
is the possession factor the outbound code was standing in for anyway, and additionally
produce a code shown only on the subscriber's screen. Guessing is 1 in 10 000 per attempt
from a number that already has to be the victim's.

Four also reduces the failure mode that actually fires: a person in a car retyping digits at
a barrier.

The requirement below states the pair-match as normative precisely because a later reader
who sees "four digits" alone will reasonably think it is too short, and shorten the wrong
thing — or lengthen it and think the problem solved.

## Cost

Nothing per verification, for us. The subscriber pays for one SMS at their own tariff. That
is a real cost moved onto the customer, and it is the honest objection to this design.

It is **not** defended by being cheaper. At ≈52 ₽/month the paid route is not a cost anyone
needs saving from, and a design that moves a charge onto the customer to save that would be
indefensible. What this buys is independence: no vendor account, no prepaid balance, no API
key, nothing outside the gateway that can run out in the middle of a login. That is concrete
and not hypothetical — as of 12.09.2026 the primary route has been stopped since 08.09.2026
on exactly those three things, and no МегаФон subscriber has gained anything in those days.

## Capabilities

### New Capabilities

- `inbound-verification`: verifying possession of a phone number, and the fallback used when
  the gateway cannot deliver to it.

## Open questions

1. **How the application learns the code arrived** — a webhook on the `delivery-dispatch`
   pattern, or polling a status endpoint. Both are specified as acceptable below; the choice
   is the parking developer's and depends on whether that app can receive callbacks.
2. **Whether the SIM's inbox can fill.** Inbound lands on the SIM and is read-then-deleted.
   Sustained verification traffic is a different load than today's occasional inbound, and
   the SIM holds only a few dozen messages. Task 3.7.

## Status

**Authored 07.09.2026. Frozen 08.09.2026 as the fallback route, unfrozen 12.09.2026 — both
the owner's decision. Not critiqued.** The `system-architect` / `gap-finder` round has not
been run; the authoring session was barred from spawning subagents, and the round is still
owed.

The numbers in "Why" were re-measured on 08.09.2026 against the live database and the price
argument withdrawn on 12.09.2026. The integration contract was handed to the parking
developer before any of that, and five things in it have since diverged from what the
neighbouring change normalises — tasks 1.1 to 1.5 carry them, and amending the contract is
the owner's to do, not ours.
