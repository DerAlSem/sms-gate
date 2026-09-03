The measurement comes first here, because it decides the shape of the answer and not just
its priority.

## 1. Find out how often the network says "still trying"

- [ ] 1.1 Read the ledger: `SELECT status_code, COUNT(*) FROM delivery_reports GROUP BY status_code`, and separately the `0x20–0x3F` band alone
- [ ] 1.2 Read `messages.error LIKE '%temporary%'` for the period before the ledger existed, and say plainly that it undercounts — it holds only reports that were attributed, and only while the message row survives

## 2. Design, with the critic layer run

- [ ] 2.1 Decide what the owning application hears when a report says "still trying": nothing, or a status of its own. A receiver told nothing does not know either
- [ ] 2.2 Decide what a held message does at `delivery_timeout_seconds` — expire, or re-arm the timeout once the network has said it is still trying
- [ ] 2.3 Run `system-architect` and `gap-finder` on the delta; this change has not been through the critic layer

## 3. Implement

- [ ] 3.1 Test: a report with `st=0x21` (recipient busy) leaves the message in a status a later report can still be applied to
- [ ] 3.2 Test: the definitive report that follows it **is** applied — the case the current behaviour makes impossible
- [ ] 3.3 Test (positive control): a report with `st=0x41` still fails the message and still counts toward the blacklist
- [ ] 3.4 Test: a message held on a temporary status and never resolved reaches a terminal state rather than staying outstanding for ever
- [ ] 3.5 Carry the decision from 2.1 into the `delivery-dispatch` contract if it changes what the application hears
- [ ] 3.6 Implement, and update `docs/modem.md`'s status table, which lists `32` as "Still trying (temporary)" while the code treats it as a failure
