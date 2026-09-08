## Why

The gateway has exactly one way to send: the modem. That was never a design decision, it
was the absence of one — and the assumption underneath it is that the SIM will keep being
allowed to carry this traffic. It has already been withdrawn once: this SIM has been blocked
before, and on 06.09.2026 at about 18:30 MSK every message bound for a МегаФон subscriber
began coming back `0x63` (service rejected) while every other operator delivered normally.
By 07.09.2026 the МегаФон direction was 0 of 16.

A probe that day sent six messages to one operator-confirmed МегаФон number, differing in
wording, in alphabet, and in whether they carried a code at all. All six were rejected
identically, and unrelated production traffic to Билайн, Теле2 and Т2 delivered in the same
minutes. The cause is the sender's route to that operator. Nothing in the message and
nothing in this codebase can change it.

**The recurring event is not "МегаФон is refusing".** It is "the modem route stopped working
for some part of the estate", and its blast radius has been total before. A branch that
names МегаФон would encode the shape of one symptom; the next withdrawal would need code
again, during an outage, which is the worst moment to be writing any.

## What Changes

- **A send acquires a route.** The modem stops being the only way out and becomes one route
  of two, the second being a commercial SMS provider reached over HTTP.
- **Route selection is a configured rule keyed on the recipient's operator**, not a branch.
  Today it carries one entry — МегаФон to the provider — set without deploying code.
- **The application's contract does not move.** `delivery-dispatch` keeps promising the same
  statuses on the same webhook. Which route carried a message is an operational fact, not a
  product one, and the owning app SHALL NOT have to know.

Explicitly **not** in this change, by the owner's decision of 07.09.2026:

- **no automatic failover.** A route that starts failing does not reroute itself. Priced and
  declined together: automatic escalation into a paid channel needs a spend ceiling to be
  safe, and that is a second change, not a corner of this one.
- **no migration of the other operators.** The modem keeps МТС, Билайн, Теле2 and the rest.

## Cost, measured rather than quoted

Volume over the 30 days to 07.09.2026, from the gateway's own ledger:

| Scope | Recipients | Messages / month |
|---|---|---|
| МегаФон only | 78 | 180 |
| whole estate | 357 | 712 |

At a published digital-sender rate of 2,92 ₽ per SMS, the МегаФон share costs ≈ **530 ₽ per
month** against the ≈ 100 ₽ flat the SIM costs today; the whole estate would be ≈ 2 080 ₽.

⚠️ **This is a price-list estimate and not a quote.** МегаФон tariffs A2P traffic in
per-recipient monthly packages, so the per-message arithmetic above is an upper bound on a
shape the provider prices differently. It has not been confirmed against this traffic
profile, and confirming it is task 1.1 — before any adapter is written.

## Capabilities

### New Capabilities

- `outbound-routing`: which way out a message takes, and what happens when that cannot be
  decided.

### Modified Capabilities

- `outbound-send`: the requirement that a message becomes `sent` when the **modem** accepts
  its first part. True of one route out of two.

## Open questions — design, not implementation

These are not rhetorical; each one changes what gets built.

1. **Which provider, and can it be dropped later.** P1SMS is the researched candidate
   (free shared sender name, digital sender at 2,92 ₽). The adapter is specified
   provider-agnostically so this stays a procurement decision, but the delivery-report
   mechanism differs sharply between vendors and may not survive a swap.
2. **How the provider reports delivery.** The `+CDS` machinery — references, attribution
   windows, `delivery_reports` — is a property of the modem route and does not apply. A
   provider reports over a webhook we must expose, or by polling we must schedule. This is
   the largest unknown in the change and the one most likely to change its size.
3. **What an unknown operator does.** `record_operator` is pure enrichment and never blocks
   a send (`app/lookup/operator.py:23-26`); a failed lookup leaves no row at all. So the
   routing key is genuinely absent sometimes, and the rule must say so rather than assume.

## Status

**Authored 07.09.2026. Not critiqued.** The `system-architect` / `gap-finder` round has not
been run — the session that authored this was barred from spawning subagents. Whoever picks
it up owes that round, and open question 2 is why.
