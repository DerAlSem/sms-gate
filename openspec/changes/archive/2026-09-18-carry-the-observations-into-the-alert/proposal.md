## Why

On 2026-09-06 the gateway sent nothing between 15:32 and 18:29. Seventeen messages
(1869–1885) reached `failed` after 930s pending each, and every application that had asked
for one was told over its webhook that delivery had failed.

Every alert raised during those two hours said the same thing:

> `Modem still unhealthy; hard reset on cooldown — check antenna/operator`

The antenna was fine. The operator was fine. The text named the two things that were
working and said nothing about the one that was not, and it was **acted on** — the operator
went and checked them. The fault was only found by reading the journal of `wwan-backup`,
the other consumer of the same modem, which was being refused with `[cm] invalid-sim-state`
24 times over against 8 `no-service`, starting one minute before the gateway's first
`Modem unhealthy`.

The gateway was not short of information. `_DIAG_QUERIES` (`app/modem/manager.py:118`)
already reads SIM, both registration states, signal, operator, SMSC and network info; the
whole snapshot is rendered on `/admin/modem` and was available on every one of those two
hours. The alert simply does not carry it. An operator who is woken by an alert is sent to
a second surface to learn what the first one already knew — and on 2026-09-06 nobody went,
because the alert sounded like it had already made the diagnosis.

The text is a constant (`app/modem/manager.py:1094-1099`). It names a cause the gateway
never observed, and it says it identically whether the signal is full or absent, whether an
operator is registered or not, and whether the SIM is readable or not.

## What Changes

- **The alert carries the observations the gateway already has.** SIM, signal, operator,
  registration — the snapshot the diagnostics page renders, in the message that wakes
  someone up.
- **The alert stops naming a cause it did not observe.** `check antenna/operator` survives
  only where the observations support it, and is not the default text for every escalation.

## Capabilities

### Modified Capabilities

- `outbound-send`: the alert raised by the recovery ladder. What the ladder *does* is
  unchanged by this change; what it *says* is not.

## Non-goals — and one of them is a decision, not an oversight

- **Making an unusable SIM its own cause in the recovery ladder.** This is the other half of
  the incident and it is deliberately not here. The ladder spent five soft recoveries on a
  fault a soft recovery cannot touch (`CFUN=4→1` does not make a modem re-read its card),
  and a fourth cause would fix that. It requires knowing which AT query names the fault,
  and **that is not known**: `invalid-sim-state` was observed over QMI, a path this
  gateway does not use, and what `AT+CPIN?` answered at the time was never captured.

  Establishing it means pulling the SIM on the production modem — a deliberate outage on a
  live gateway. **The owner declined that on 2026-09-06, and the decision stands recorded
  here rather than left as an open task nobody explains.** The evidence is not worth a
  second outage on the same day as the first.

  This change is what makes that evidence arrive for free: once the alert carries the
  snapshot, the *next* occurrence answers the question from the alert text itself, with no
  SIM pulled and no outage staged. The follow-up change should be opened then, against real
  observations, and `design.md` here carries the two findings already paid for so they are
  not re-derived.

- **Hot-swap detection (`AT+QSIMDET`).** Quectel-specific, separate evidence, separate
  change.
- **Reading the backup uplink's QMI state.** `backup-uplink` deliberately keeps the two
  consumers independent — *"neither SHALL assume the other has dealt with it"*.

## Impact

- `app/modem/manager.py` — the alert text at the `COOLDOWN` and `HARD` rungs, and the call
  that gathers the snapshot for it.
- Alert volume: this alert fires on a ~3.5-minute cadence during an outage and produced 30+
  near-identical messages on 2026-09-06. A text that now varies with the snapshot interacts
  with duplicate suppression, which is why that is a task rather than an afterthought.
- No change to the ladder, its causes, its thresholds or its timing.

## Status

**Authored, not critiqued.** The `system-architect` / `gap-finder` layer has not been run.
