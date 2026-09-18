# Tasks

## 1. Settle what only the owner can settle

- [ ] 1.1 **The method vocabulary, across three changes at once.** `route-sends-by-operator`
      calls uCaller's flash call `call`; this change's rung is `inbound_call` and must never
      be `call`, because in the vendor's rung *"our modem does not participate at all"*.
      `reach-people-in-messengers` task 1.1 defers to this decision and holds its own deltas
      provisional until it lands. Two axes, not one flat list: direction
      (`outbound`/`inbound`) and bearer (`modem`, `ucaller`, `tg_gateway`, `app_bot`,
      `tg_user`, `max_user`). These are normative values exposed to consumers.
- [ ] 1.2 **Does the subscriber pay for the unanswered call?** The gateway does not answer,
      so the call runs to the carrier's voicemail, and voicemail is a connection. The whole
      ladder is ordered by cost and this is its first rung: if the answer is "yes", the
      ordering premise is wrong where it matters most. Measurable from a real subscriber's
      itemised bill or the carrier's own tariff, not from this gateway.
- [ ] 1.3 **Does the `telegram_bot` rung exist at all?** Recorded as the author's reading of
      the owner's words on 18.09.2026 and deliberately kept out of the spec: the critic's
      objection is structural — its precondition cannot be proven before the list is issued,
      so it does not obey the load-bearing norm. Either it is dropped or the norm needs an
      exception written for it, and the second needs the owner.
- [ ] 1.4 **Is the residual risk acceptable per consuming application?** An attacker opens a
      verification on a victim's number and, inside the window, gives the victim a reason to
      call. Mitigated by one open call-verification per number, the rate limits and a shorter
      window for this rung; it does not reduce to zero. The spec returns the method so an
      application may refuse it — somebody has to decide which will.
- [ ] 1.5 **The window for `inbound_call`.** `phone-verification` ships five minutes for the
      ladder by the owner's decision of 18.09.2026. Two minutes was proposed here on the
      grounds that the person is standing at a barrier, and never measured. The spec makes
      the rung's window separately configurable and no longer than the default; what it
      should actually be is a decision, and 1.4 is the reason it is a short one.

## 2. Hold the archiving order, because the validator will not

- [x] 2.1 `check-base.sh` greps the living spec for every heading this change modifies or
      removes and exits 1 while any is missing. Verified in both directions on 18.09.2026:
      it refuses today, and the same five headings exist verbatim in
      `route-sends-by-operator`'s delta, so it will pass once that change archives.
- [x] 2.2 Registry row `sms-gate/20260918-04` runs that script as its probe, so the order is
      a thing that asks rather than a thing somebody must remember.
- [ ] 2.3 **Before archiving**, run `check-base.sh` by hand and require "можно". If the
      neighbour has archived and the probe still refuses, the headings have diverged — read
      them line by line, do not force.

## 3. Depend on the IMS reading rather than building it

- [ ] 3.1 Wait for `watch-the-voice-route` to land the `AT+QCFG="ims"` row. This change SHALL
      NOT touch `_DIAG_QUERIES`; two changes editing one sweep is how one of them silently
      loses.
- [ ] 3.2 Consume the reading **with its age**. That change is required to report when the
      voice route was last successfully measured; this one supplies the maximum age and
      refuses the rung on stale evidence. Unreadable and stale both count as unavailable —
      the failing direction, not the passing one.

## 4. Caller ID becomes something the gateway knows it holds

- [ ] 4.1 Re-issue `CLIP_SUBSCRIBE` wherever `CNMI_SUBSCRIBE` is re-issued —
      `soft_recover` (`app/modem/at_commands.py:669-681`) does the second and not the first,
      on a docstring whose own argument covers both. Test first, and it must fail first.
- [ ] 4.2 Record the subscription's state per link generation: issued and acknowledged, or
      not. `AT+CLIP=1` at init is already allowed to fail with only a warning
      (`app/modem/at_commands.py:706-715`) — that warning becomes a recorded fact.
- [ ] 4.3 Make that record, and nothing read back from the modem, the rung's precondition on
      caller ID. `AT+CLIP?` does not answer on this device and `AT+CLIP=?` answers a
      different question.
- [ ] 4.4 Count calls arriving with no usable caller number and expose the count to an
      operator. This is the only detector for a subscription dropped without a `CFUN` cycle,
      which the record in 4.2 cannot see.

## 5. The reader learns that a call happened

- [ ] 5.1 Parse `RING` and `+CLIP` in `reader_loop` (`app/modem/manager.py:746-762`),
      alongside the existing `+CDS` and `+CMTI` branches. Today both fall to the `else`
      branch and are logged as `Unhandled URC` — the code comment there already names this
      as the case it was left for.
- [ ] 5.2 Canonicalize the caller number through `phonenumbers` before matching, per
      AGENTS.md — canonicalize before storage, never after.
- [ ] 5.3 Collapse one call's repetitions into one event. Measured 18.09.2026: fifteen
      `RING` / `+CLIP` pairs in sixteen seconds for a single call. Test first, failing first.
- [ ] 5.4 Record every call in its own store, including those that confirmed nothing and
      those that carried no number — not in `inbound_messages`.
- [ ] 5.5 Do not answer the call. `ATH` stays out: it needs the command port the sender holds,
      and that it rejects an unanswered incoming call on this firmware is an assertion about
      the device rather than a measurement.

## 6. The chooser

- [ ] 6.1 Route registry with a precondition probe per rung; the ladder's order and membership
      read from configuration.
- [ ] 6.2 Bound the probe set **as a whole**, not probe by probe, and count an unanswered
      probe as unproven.
- [ ] 6.3 The invariant on the boundary: a rung with an unproven or stale precondition is not
      offered. Guard on the offering, not a walk over the callers.
- [ ] 6.4 The selection door — `POST /verifications/{id}/route`. Nothing is placed, composed
      or charged before a selection; selecting a rung that was not offered, or one whose
      precondition has since lapsed, is refused with that reason.
- [ ] 6.5 No silent hop. A failed rung fails the verification with its reason and re-offers
      what is left; moving on is the consumer's act.
- [ ] 6.6 One open `inbound_call` verification per number; a second request for that number is
      answered without that rung.
- [ ] 6.7 Refuse the verification when no rung can prove itself, in the same answer, rather
      than opening one that can only expire.

## 7. What the verification stores and says

- [ ] 7.1 Reuse `phone-verification`'s storage requirement — per rung attempted, its vendor
      identifiers, cost and refund. Add: the rung selected, and the method that confirmed.
      Do not invent a second store.
- [ ] 7.2 A verification whose selected rung loses its precondition ends with that reason and
      notifies, rather than reaching its deadline. Every writer of a terminal state notifies.
- [ ] 7.3 The `inbound_call` window, configurable separately and defaulting to no longer than
      the ladder's.
- [ ] 7.4 Return the code to the owning application **only** on `inbound_sms`, and never in an
      operator notification or a log line on any rung.
- [ ] 7.5 The confirmation names the method, in the push and in the poll.

## 8. The two rungs this change bears

- [ ] 8.1 `inbound_call` — confirmed by the caller's number alone, within one open window.
- [ ] 8.2 `inbound_sms` — confirmed only by the pair of originating number and code; last on
      the ladder, and not offered when a cheaper rung proved itself.
- [ ] 8.3 Inbound traffic that confirms nothing stays stored and visible exactly as today
      (`app/admin/router.py:351`) — verification neither deletes, hides nor reclassifies it.

## 9. Guards that must bite, not merely pass

- [ ] 9.1 Each new guard is checked by mutation: break the guarded thing and confirm it goes
      red. A guard that never bit is not a guard.
- [ ] 9.2 The silent-death guard specifically: with the IMS precondition unmet, assert the
      call rung is absent from the answer — **and assert the positive control**, that it is
      present when the precondition holds. A negative guard without its positive control has
      executed nothing.
- [ ] 9.3 The same pair for the caller-ID record: rung absent when `AT+CLIP=1` failed, present
      when it succeeded, and an anonymous call is *not* a fault while the record holds.
- [ ] 9.4 A test that `soft_recover` re-issues `CLIP` — it is a one-line omission today and
      will be a one-line omission again after the next edit to that function.
- [ ] 9.5 Assert the ladder cannot be reordered into offering a rung without its precondition,
      and that stale evidence is refused as firmly as absent evidence.

## 10. Verify against the real thing

- [ ] 10.1 Full suite. Six failures are inherited and unrelated — `test_alert_send_sh.py` (4)
      and `test_cds_attribution.py` (2) — verified by substitution against the unmodified tree
      on 14.09.2026. Do not report them as this change's.
- [ ] 10.2 A live inbound call to the production number confirming a real verification.
      🔴 Production carries live customer traffic — codes and passwords to real people every
      30–90 minutes. Pick a quiet window, check the queue first, and get the owner's sanction
      for the restart.
- [ ] 10.3 A live call **across a recovery**: confirm the verification ends naming the outage
      rather than reporting "expired". This is the boundary the critics found and the one no
      unit test can prove.
- [ ] 10.4 A live inbound SMS still lands and is still visible in the admin console — the
      regression that matters most, because it is the path that works today.
