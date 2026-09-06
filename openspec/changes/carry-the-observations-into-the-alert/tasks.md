Nothing here needs the hardware. The observations this change carries are already collected
on every load of `/admin/modem`; the work is delivery, not gathering.

## 1. Decide the shape before writing it

- [x] 1.1 **Chosen: `sim`, `cs_reg`, `signal`, `operator`.** Renders as `SIM=READY reg=searching signal=-71dBm operator=?` — 96 chars against a 500 budget, and it lets a reader rule out the antenna without opening anything else
- [x] 1.2 **Answered by the architecture rather than chosen.** `TelegramAlertHandler._signature` (`app/alerting.py:307`) dedups on `record.msg` — the template — while `format_alert` delivers `record.getMessage()`. The snapshot rides as a `%s` argument: the text varies, the signature does not, suppression is untouched
- [x] 1.3 `observations unavailable: <error>`, reusing the short-circuit `collect_diagnostics()` already returns from its `AT` liveness pre-check

## 2. Critique

- [ ] 2.1 Run `system-architect` and `gap-finder` on the delta once 1.1–1.3 are settled. The gap categories `AGENTS.md` names as thin here — modem-state, AT-timeout — are the ones that apply

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
- [ ] 4.3 Deploy. No hardware verification is possible without staging a fault, and staging one was declined — the first real escalation is the verification, and it is also the evidence the SIM-cause follow-up is waiting on

## 5. Afterwards — not part of this change

- [ ] 5.1 When the next modem escalation happens, read the alert. It answers what `AT+CPIN?` reports during a real fault, which is the one fact blocking the SIM-cause change. Open that change then, against `design.md`'s "Findings carried forward"

## 6. Mutation evidence (the guards were bitten, 2026-09-06)

Per the verify gate, a new guard is proved by breaking what it guards. Script kept at
`scratchpad/bite.sh`; the file was restored by copy, not `git checkout`, and
`__pycache__` was cleared before each run.

```
[BASELINE]                             11 passed
[MUT1 antenna text restored]           1 failed, 10 passed
[MUT2 snapshot interpolated inline]    1 failed, 10 passed
[RESTORED]                             11 passed
```

MUT2 is the one worth keeping: interpolating the snapshot into the template instead of
passing it as an argument is the natural way to write this, it looks identical in the
delivered message, and it silently destroys duplicate suppression.
