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
