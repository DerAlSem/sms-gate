# Tasks

## 1. Settle what only the owner can settle

- [ ] 1.1 Confirm what the Telegram bot rung is. The spec records the author's reading —
      a bot that requests the contact, Telegram vouching for the number-to-account
      binding. If that is not what was meant, the rung changes and nothing else does.
- [ ] 1.2 Confirm the window. Two minutes is proposed on the grounds that the person is
      standing at a barrier; it is not measured.
- [ ] 1.3 Decide whether the residual risk is acceptable for each consuming application:
      an attacker opens a verification on a victim's number and gives the victim a reason
      to call us inside the window. It does not reduce to zero.

## 2. Design, with the critic layer run

- [ ] 2.1 Mechanics before the circle: `python3 ~/.claude/scripts/check.py .` and the
      scenario count, both handed to the critics as established facts.
- [ ] 2.2 One narrow circle, `system-architect` + `gap-finder`, on the new norms and on
      the neighbouring modules by name: `app/modem/manager.py` (URC reader),
      `app/modem/diag.py`, `app/config.py`, and the sibling change
      `watch-the-voice-route`. The circle is closed by count, not by feeling.
- [ ] 2.3 Reconcile findings to SHALLs by reading `spec.md` — a reviewer saying "closed"
      does not close anything, and prose in a design document does not bind.
- [ ] 2.4 Mechanics after reconciliation: scenario-name diff against the base,
      `git diff --stat`, `check.py`. Record the circle with
      `hooks/openspec-critique-record.sh verify-by-inbound-contact`.

## 3. Depend on the IMS reading rather than building it

- [ ] 3.1 Wait for `watch-the-voice-route` to land the `AT+QCFG="ims"` row. This change
      SHALL NOT touch `_DIAG_QUERIES`; two changes editing one sweep is how one of them
      silently loses.
- [ ] 3.2 Consume the IMS reading as the call route's precondition, with a guard that an
      unreadable precondition counts as unavailable — the failing direction, not the
      passing one.

## 4. The reader learns that a call happened

- [ ] 4.1 Parse `RING` and `+CLIP` in `reader_loop` (`app/modem/manager.py`), alongside
      the existing `+CDS` and `+CMTI` branches. Today both fall to the `else` branch and
      are logged as `Unhandled URC`.
- [ ] 4.2 Canonicalize the caller number through `phonenumbers` before matching, per
      AGENTS.md — canonicalize before storage, never after.
- [ ] 4.3 Collapse one call's repetitions into one event. Measured on 2026-09-18: fifteen
      `RING` / `+CLIP` pairs in sixteen seconds for a single call. Test written before the
      code and failing first.
- [ ] 4.4 Record every call, including those that confirm nothing, in its own store — not
      in `inbound_messages`.
- [ ] 4.5 Handle a withheld or unparseable caller number as an ordinary non-confirmation.

## 5. The chooser

- [ ] 5.1 Route registry with a precondition probe per route, and the ladder's order and
      membership read from configuration.
- [ ] 5.2 The invariant on the boundary: a route with an unproven precondition is not
      offered. Guard on the offering, not a walk over the callers.
- [ ] 5.3 One open call verification per number; a second request for the same number is
      answered with a different route.
- [ ] 5.4 Refuse a verification when no route can prove itself, in the same answer, rather
      than opening one that can only expire.

## 6. The verification itself

- [ ] 6.1 Storage: verification, its number, its route, its code where the route has one,
      its expiry, its outcome and the method that proved it.
- [ ] 6.2 Expiry, single use, and no revival after expiry.
- [ ] 6.3 Two verifications open for one number are distinguishable — never sharing a code
      and never sharing a route that cannot tell them apart.
- [ ] 6.4 Rate limit on opening verifications per number.
- [ ] 6.5 Public API: create, read state, and a push carrying the method that confirmed.

## 7. Routes, added one at a time

- [ ] 7.1 `inbound_call` — first rung, free to both sides.
- [ ] 7.2 `outbound_sms` — the existing path, precondition being that the operator is not
      on the undeliverable list.
- [ ] 7.3 `inbound_sms` — last rung; the only one that charges the subscriber.
- [ ] 7.4 `ucaller` — owner ranks it above Telegram Gateway. External-contract gate: the
      vendor reference or a captured sample before the parser.
- [ ] 7.5 `telegram_gateway` — same gate. Note its automatic refund for undelivered codes.
- [ ] 7.6 `telegram_bot` — after task 1.1 settles what it is.

## 8. Guards that must bite, not merely pass

- [ ] 8.1 Each new guard is checked by mutation: break the guarded thing and confirm it
      goes red. A guard that never bit is not a guard.
- [ ] 8.2 The silent-death guard specifically: with the IMS precondition unmet, assert the
      call route is absent from the answer — and assert the positive control too, that it
      is present when the precondition holds. A negative guard without its positive
      control has executed nothing.
- [ ] 8.3 Assert the ladder cannot be reordered into offering a route without its
      precondition.

## 9. Verify against the real thing

- [ ] 9.1 Full suite. Six failures are inherited and unrelated — `test_alert_send_sh.py`
      (4) and `test_cds_attribution.py` (2) — verified by substitution against the
      unmodified tree on 2026-09-14. Do not report them as this change's.
- [ ] 9.2 A live inbound call to the production number confirming a real verification.
      🔴 Production carries live customer traffic — codes and passwords to real people
      every 30–90 minutes. Pick a quiet window, check the queue first, and get the owner's
      sanction for the restart.
- [ ] 9.3 A live inbound SMS still lands and is still visible in the admin console —
      the regression that matters most, because it is the path that works today.
