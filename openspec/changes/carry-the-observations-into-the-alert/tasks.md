Nothing here needs the hardware. The observations this change carries are already collected
on every load of `/admin/modem`; the work is delivery, not gathering.

## 1. Decide the shape before writing it

- [x] 1.1 **Chosen: `sim`, `cs_reg`, `signal`, `operator`.** Renders as `SIM=READY reg=searching signal=-71dBm operator=?` — 96 chars against a 500 budget, and it lets a reader rule out the antenna without opening anything else
- [x] 1.2 **Answered by the architecture rather than chosen.** `TelegramAlertHandler._signature` (`app/alerting.py:307`) dedups on `record.msg` — the template — while `format_alert` delivers `record.getMessage()`. The snapshot rides as a `%s` argument: the text varies, the signature does not, suppression is untouched
- [x] 1.3 `observations unavailable: <error>`, reusing the short-circuit `collect_diagnostics()` already returns from its `AT` liveness pre-check

## 2. Critique

- [x] 2.1 **Closed as non-essential — owner's call, 2026-09-06.** The critic layer was not run. The reasoning accepted: the change is text-only, the ladder's behaviour is pinned by an explicit regression test (3.5), and both new guards were mutation-tested (§6). Recorded as a decision so that a later reader does not mistake it for an oversight — if this change is ever widened beyond alert text, the critic layer is owed

## 3. Implement

- [x] 3.1 Test: an alert raised while the modem answers AT carries the chosen readings
- [x] 3.2 Test: the alert does not contain `check antenna/operator` when the readings do not support it
- [x] 3.3 Test: when the snapshot cannot be collected, the alert says so and names no cause
- [x] 3.4 Test: repeated escalations with unchanged observations do not produce a full snapshot every 3.5 minutes — the rule chosen in 1.2, asserted
- [x] 3.5 Test (regression): the ladder's decisions are unchanged. Same rungs, same order, same timing — this change touches text only, and that must be provable
- [x] 3.6 Implement at the `COOLDOWN` and `HARD` rungs (`app/modem/manager.py:1094-1109`)

## 4. Land it

- [x] 4.1 **700 passed, 4 failed** — the four are `tests/test_alert_send_sh.py`, pre-existing on macOS and in a file this diff does not touch. **No lint or typecheck was run because the project has neither**: no ruff/mypy/flake8 in `requirements-dev.txt`, no `pyproject.toml`, no `setup.cfg`
- [x] 4.2 Nine AT queries, collected before the remedy and behind `_alert_observations()`, which never raises — an alert must not be lost because its evidence failed to gather
- [x] 4.3 **Deployed 2026-09-06 19:39 MSK, rev `5f6688f`.** Target established from the box, not guessed: `/opt/sms-gate.git` has `HEAD -> refs/heads/master`, and its `post-receive` runs `checkout -f` then `systemctl restart sms-gate` (`main` in that bare repo is a stale branch and deploys nothing). Verified: service active from 19:39:11, both ports reopened, link restored, no errors. Re-checked after a five-minute pause, per the Ops rule that a parallel deploy can overwrite a green result minutes later

## 5. Afterwards — a note, deliberately not a task

This change owns no work here, so this is prose rather than a checkbox: a task belonging to
a future change would block this one's archive for ever.

When the next modem escalation happens, read the alert. It reports what `AT+CPIN?` answers
during a real fault, which is the single fact blocking the SIM-cause change — the one that
would stop the ladder spending soft recoveries on a card it cannot re-read. Open that change
then, against the "Findings carried forward" section of `design.md`, which holds the three
things already paid for on 2026-09-06.

## 6. Mutation evidence (the guards were bitten, 2026-09-06)

Per the verify gate, a new guard is proved by breaking what it guards. The script ran in a
session scratchpad and is gone; it is not needed, because both mutations are one edit each
to `app/modem/manager.py` and are named below. Two mechanics that are easy to get wrong and
were not: the file was restored **by copying it back**, never `git checkout --` (which would
have reverted the uncommitted change itself and made the guard bite empty air), and
`app/modem/__pycache__` was cleared before every run (a mutation that only reorders lines
leaves the file size unchanged, and Python judges a `.pyc` by size and mtime-to-the-second).

```
[BASELINE]                             11 passed
[MUT1 antenna text restored]           1 failed, 10 passed
[MUT2 snapshot interpolated inline]    1 failed, 10 passed
[RESTORED]                             11 passed
```

MUT2 is the one worth keeping: interpolating the snapshot into the template instead of
passing it as an argument is the natural way to write this, it looks identical in the
delivered message, and it silently destroys duplicate suppression.
