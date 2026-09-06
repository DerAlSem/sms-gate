## Context

The alert text is a constant at the `COOLDOWN` and `HARD` rungs of the watchdog
(`app/modem/manager.py:1094-1109`). The observations it should carry already exist:
`collect_diagnostics()` runs `_DIAG_QUERIES` (`app/modem/manager.py:118`) — `AT+CPIN?`,
`AT+CREG?`, `AT+CEREG?`, `AT+CGREG?`, `AT+CSQ`, `AT+COPS?`, `AT+CSCA?`, `AT+QNWINFO`,
`AT+QCSQ` — is read-only, takes the existing serial lock, short-circuits on a wedged modem
and never raises. The console renders it. Nothing carries it into an alert.

## Goals / Non-Goals

**Goals:**

- An alert that is actionable on its own, without opening the console or the journal.
- No claim in the text that the observations do not support.

**Non-Goals:**

- The ladder's causes, thresholds, remedies and timing. Untouched.
- Any new AT query. This change spends no new round-trips that the diagnostics page does
  not already spend.

## Decisions

**Reuse `collect_diagnostics()` rather than a narrower probe.** It already has the
properties an alert path needs — never raises, one failing query does not break the sweep,
liveness pre-check — and writing a second, smaller collector would mean two things that can
disagree about the modem. The cost is nine AT queries on the alert path; during an
escalation sending is suspended anyway (`Sending suspended while the modem is recovered`),
so the serial lock is not contended at exactly the moment this runs.

**The text must not become a diagnosis.** The alert reports readings; it does not conclude.
`check antenna/operator` was wrong not because it was the wrong guess but because it was a
guess presented as a finding. A signal reading and an operator reading let the reader
conclude, and on 2026-09-06 they would have been enough: a modem with signal and no
registered operator is not an antenna fault.

**Suppression is part of the design, not a follow-up.** The alert fires roughly every 3.5
minutes for as long as the fault lasts — 2026-09-06 produced 30+ of them, already collapsed
by duplicate suppression into "(N duplicates suppressed in window)". A text that varies
with the snapshot may stop being a duplicate and turn one alert every 3.5 minutes into a
wall of full snapshots. Either the suppression key stays the constant part of the message,
or the snapshot is attached only to the first alert of a run. The third scenario in the
delta exists to force this decision rather than discover it in production.

## Findings carried forward for the SIM-cause follow-up

Both were paid for on 2026-09-06 and neither is obvious from the code. They are recorded
here so the follow-up change does not re-derive them.

**A soft recovery cannot fix an unusable SIM, and a reseat cannot either.** Soft recovery is
`CFUN=4→1` plus `COPS=0` (`app/modem/at_commands.py:657`) — a radio cycle that leaves card
state untouched. The operator reseated the SIM at roughly 18:05; the kernel logged no USB
event, the card state did not change, and `AT+CNMI` began returning `ERROR` where it had
succeeded minutes earlier. What cleared it was the scheduled hard reset at 18:29:11, which
re-enumerates the device. The gateway recovered by the arithmetic of a cooldown, not by
diagnosis.

**A stop condition counting hard resets cannot hold its counter in memory.** The `HARD`
rung sleeps `_WD_HARD_RESET_SETTLE` and then calls `os._exit(1)`
(`app/modem/manager.py:1174-1175`) — a hard reset ends the process. An in-memory counter is
zeroed by the very event it counts, so a bound of two could never be reached. The count
belongs on disk beside `_hard_reset_marker` (`app/modem/manager.py:97`), for the same
reason the cooldown is there. That in turn means re-arming cannot be a side effect inside
`decide()`, which is pure by its own docstring: it has to be an explicit write by the
caller when it observes a usable card, and the first healthy poll after startup has to
perform it too, or an operator who changes the card and restarts the service finds the
ladder still stopped.

**The probe cannot fire inside the settle window.** The settle is followed by the process
exit, and `watchdog_loop` awaits `_wait_for_tick()` before its first step
(`app/modem/manager.py:1145`), so the successor's first poll is a tick away, not immediate.
The residual case is startup against a modem that was already booting, where `_wait_for_tick`
can return early on a waiter.

**What is still unknown, and how it arrives without staging an outage.** Which AT query
names an unusable SIM. Observed: `invalid-sim-state` over QMI (not a path this gateway
uses) and `AT+CNMI` failing during port init (an init failure, not a probe — a modem still
waking after a reset fails it too). Never captured: what `AT+CPIN?` answered while the
fault was live, which is the query the diagnostics already runs. Once this change ships,
the next occurrence answers it from the alert text itself.

## Risks / Trade-offs

**A longer alert is a less-read alert.** Thirty lines of AT output in Telegram is a worse
alert than one wrong sentence. The snapshot has to be a handful of named readings, not a
dump.

**Nine AT queries on the alert path.** Bounded by `collect_diagnostics()`'s own guarantees
and issued while sending is suspended, but it is the one new cost this change introduces
and belongs in the verification.
