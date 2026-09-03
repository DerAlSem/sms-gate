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
The classifier that would have prevented all of this was already written and already
correct; nothing consulted it at the point where the decision was made.

This is a **live defect**, not a consequence of `attribute-late-delivery-reports`. That
change named it as a non-goal, carried the requirement forward verbatim, and neither fixed
nor worsened it.

## What is NOT measured

**How often this fires here is unknown.** Before this change is designed, the ledger
`attribute-late-delivery-reports` introduces should be read: `delivery_reports` records
`status_code` for every report, so `SELECT status_code, COUNT(*) FROM delivery_reports
GROUP BY status_code` answers it directly for everything received after that deploy. The
`messages.error` column carries the decoded string for older ones —
`WHERE error LIKE '%temporary%'` — but only for reports that were attributed at all, and
only while the message row survives.

The fix is not conditional on the count: a report that says "still trying" must not be
recorded as a failure at any frequency. The count decides **priority**, and it decides
whether the answer is "hold the message" or "hold it and re-arm the timeout".

## What Changes

- **A temporary TP-status stops being a failure.** The message stays in a status the real
  verdict can still be applied to, and the part stays outstanding.
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

**Authored, not critiqued.** Whoever picks this up runs the `system-architect` /
`gap-finder` layer before implementing: it has not been run, and the open questions in
"What Changes" are the reason it must be.
