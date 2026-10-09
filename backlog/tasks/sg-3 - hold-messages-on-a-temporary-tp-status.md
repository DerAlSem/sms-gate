---
id: SG-3
title: hold-messages-on-a-temporary-tp-status
status: To Do
assignee: []
created_date: '2026-09-25 11:58'
labels:
  - migrated
dependencies: []
references:
  - openspec/changes/hold-messages-on-a-temporary-tp-status
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Why

`parse_cds` calls a report delivered when `st` is zero and failed otherwise
(`app/modem/parser.py:213`). GSM 03.40 §9.2.3.15 does not divide the status that way, and
this gateway's own code knows it does not: `_tp_status_class` (`app/modem/parser.py:171`)
sorts the same byte into three classes, and names `0x20–0x3F` **temporary** — "congestion",
"recipient busy", "no response from recipient", "service rejected". The service centre is
saying it is *still trying*, not that it has stopped.

The gateway answers that by moving the message to `failed`. Three consequences follow, and
the third is the one that cannot be undone by a later report:

- the owning application is told the message failed, over a webhook it acts on — in this
  estate a failure webhook is answered by messaging a person;
- an operator alert fires naming a delivery failure that has not happened;
- **`failed` is not an eligible status.** `attribute` considers only parts whose message is
  `sent` or `expired` (`app/modem/attribution.py:23`), so when the network *does* reach its
  verdict — the delivery, or the permanent failure — that report is recorded `superseded`
  and changes nothing. The gateway has closed the case on the network's "wait" and can never
  reopen it.

The blacklist is not affected: `_is_permanent_status` already checks `0x40–0x5F`
(`app/modem/manager.py:40`), so a temporary status is not counted against the destination.

The classifier that would have prevented this was already written, but it is **not** by
itself sufficient, and the first draft of this change was misled by trusting it. GSM 03.40
§9.2.3.15 has four ranges; `_tp_status_class` returns three labels, spending the single word
"temporary" on both `0x20–0x3F` (still trying) and `0x60–0x7F` (stopped trying). Those two
call for opposite handling, so the decision point needs the range and not the word.

This is a **live defect**, not a consequence of `attribute-late-delivery-reports`. That
change named it as a non-goal, carried the requirement forward verbatim, and neither fixed
nor worsened it.

## Measured, 07.09.2026 — and it inverts the change

The ledger and `messages.error` were read as this section previously asked. The counts do
not merely set priority; they show the change was aimed at the wrong range.

| TP-status | Range | Reports | Span |
|---|---|---|---|
| `0x63` service rejected | temporary, **abandoned** | **50** | 27.04 → 07.09.2026 |
| `0x46` validity period expired | permanent | 21 | 29.04 → 23.08.2026 |
| `0x40` remote procedure error | permanent | 1 | 01.09.2026 |
| anything in `0x20–0x3F` | temporary, **still trying** | **0** | never |

Ledger alone (`delivery_reports`, complete since 03.09.2026): 115 × `0`, 35 × `99`, one
report whose status could not be read. `messages.error` supplies the rest of the history
and undercounts by construction — it holds only reports that were attributed at all, and
only while the message row survives.

**The band this change exists to hold has never once arrived.** The band that does arrive
is `0x60–0x7F`, where the service centre has *stopped* trying — and the delta as first
written classified it as "still trying" and would have held it. That is not a missing
improvement, it is a regression against working code: `app/modem/manager.py` already fails
these at once and already keeps them off the blacklist.

The correction is in the delta. What remains genuinely open is the `0x20–0x3F` branch,
which stays worth building — a report that says "still trying" must not be recorded as a
failure at any frequency, including zero — but it is now a change against a case that has
never fired, and should be priced that way.

**Live context for the 50.** They are not spread evenly: 35 of them fall in the 30 hours
from 06.09.2026 18:30 MSK, every one bound for a МегаФон subscriber, while every other
operator delivered normally. A probe on 07.09.2026 sent six messages differing in wording,
alphabet and whether they carried a code at all; all six were rejected identically, so the
cause is the sender's route to that operator and not anything in the message. That incident
is not this change's to fix — but it is why the range is no longer hypothetical.

## What Changes

- **A still-trying TP-status (`0x20–0x3F`) stops being a failure.** The message stays in a
  status the real verdict can still be applied to, and the part stays outstanding.
- **An abandoned-temporary TP-status (`0x60–0x7F`) stays an immediate failure**, and stays
  off the blacklist. This is what the code already does; the change's job here is to write
  the rule down so the next reader of the word "temporary" does not undo it.
- **The owning application is not told a failure that has not happened.** What it *is* told
  — nothing, or something new — is the open design question, since a receiver that has heard
  nothing for a while is also a receiver that does not know.
- **What happens if the verdict never comes** is settled rather than left to the expiry
  sweep by accident. A message held on "still trying" past `delivery_timeout_seconds` has to
  reach some terminal state, and `expired` is the honest one: the gateway never learned the
  outcome.

## Capabilities

### Modified Capabilities

- `outbound-send`: the rule that turns a negative `+CDS` into a message status. It is true
  of a status byte with two meanings and this one has three.

## Depends on

**`attribute-late-delivery-reports` must be archived first.** Its delta rewrites the same
requirement, and the `MODIFIED` block below is written against the text *it* installs — an
archive in the other order would drop one of the two rewrites silently.

Its ledger is also where the measurement above comes from.

## Status

**Corrected by measurement 07.09.2026. The `system-architect` / `gap-finder` layer has
still not been run** — the correction above came from reading the ledger and the standard,
not from the critic layer, and the session that made it was barred from spawning subagents.
Whoever picks this up still owes that round before implementing; the open questions under
"What Changes" are unchanged and are the reason it is owed.

What the measurement already settled, so the round need not re-derive it: the `0x60–0x7F`
range is not held, and the `0x20–0x3F` branch has never had a live input.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
The measurement comes first here, because it decides the shape of the answer and not just
its priority.

## 1. Find out how often the network says "still trying"

- [x] 1.1 Read the ledger: `SELECT status_code, COUNT(*) FROM delivery_reports GROUP BY status_code`, and separately the `0x20–0x3F` band alone — done 07.09.2026: 115 × `0`, 35 × `99`, one unreadable, and **zero** in `0x20–0x3F`
- [x] 1.2 Read `messages.error LIKE '%temporary%'` for the period before the ledger existed, and say plainly that it undercounts — done 07.09.2026: whole history is 50 × `0x63`, 21 × `0x46`, 1 × `0x40`, still zero in `0x20–0x3F`. The undercount caveat is stated in `proposal.md`
- [x] 1.3 Record the result where it governs: the range this change was written to hold has never arrived, and the range its first draft misclassified is the gateway's most common failure. In `proposal.md` and in the delta's evidence line

## 2. Design, with the critic layer run

- [ ] 2.1 Decide what the owning application hears when a report says "still trying": nothing, or a status of its own. A receiver told nothing does not know either
- [ ] 2.2 Decide what a held message does at `delivery_timeout_seconds` — expire, or re-arm the timeout once the network has said it is still trying
- [ ] 2.3 Run `system-architect` and `gap-finder` on the delta; this change has not been through the critic layer

## 3. Implement

- [ ] 3.1 Test: a report with `st=0x21` (recipient busy) leaves the message in a status a later report can still be applied to
- [ ] 3.2 Test: the definitive report that follows it **is** applied — the case the current behaviour makes impossible
- [ ] 3.3 Test (positive control): a report with `st=0x41` still fails the message and still counts toward the blacklist
- [ ] 3.4 Test (negative control, guards the defect this change nearly introduced): a report with `st=0x63` fails the message **at once** — not held — and does **not** count toward the blacklist
- [ ] 3.5 Test: a message held on a temporary status and never resolved reaches a terminal state rather than staying outstanding for ever
- [ ] 3.6 Split the label, not just the branch: `_tp_status_class` returns "temporary" for both `0x20–0x3F` and `0x60–0x7F`, and that single word is what misled this change's own first draft. Give the two ranges distinguishable names, and check every caller and every operator-facing string that consumes them
- [ ] 3.7 Carry the decision from 2.1 into the `delivery-dispatch` contract if it changes what the application hears
- [x] 3.8 `docs/modem.md`'s status table — corrected 07.09.2026 ahead of implementation, because it was actively wrong rather than merely stale: it called `96` a permanent "incompatible destination" (it is `0x60`, temporary-abandoned congestion; `incompatible destination` is `65`) and omitted `99` entirely. Coding from that table would have counted network congestion against the recipient's blacklist
<!-- SECTION:NOTES:END -->
