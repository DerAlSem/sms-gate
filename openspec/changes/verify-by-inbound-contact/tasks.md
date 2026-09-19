# Tasks

## 1. Settled by the owner, and what each answer left behind

- [x] 1.1 **Method vocabulary — decided 18.09.2026: one flat field, names disambiguated.**
      `sms_out`, `sms_in`, `call_in`, `flash_call`, `tg_gateway`, `tg_user`, `max_user`,
      `app_bot`. `call` is retired (it meant two mechanisms in two changes); `modem` is retired
      in favour of `sms_out`. Applied in this change and in `route-sends-by-operator`.
- [ ] 1.2 **The hang-up sequence, measured end to end on the live modem.** The owner decided
      18.09.2026 that the gateway ends the call as soon as the number is read, which is what
      makes this rung free to the subscriber. Every step is still an assertion: that `ATH` ends
      an *unanswered incoming* call on this firmware; that the command port can be taken from
      the sender to do it without displacing a send; and what the carrier does with a rejected
      call. 🔴 The cost claim stays unpublished to consumers until all three are observed.
      Confirmation does not depend on any of them — that is already normative.
- [x] 1.3 **`telegram_bot` — not in this change.** Recorded as the author's reading of the
      owner's words and kept out of the spec: the critic's objection is structural — its
      precondition cannot be proven before the list is issued, so it does not obey the
      load-bearing norm. It returns as its own proposal or not at all.
- [ ] 1.4 **Is the residual risk acceptable per consuming application?** An attacker opens a
      verification on a victim's number and, inside the window, gives the victim a reason to
      call. Narrower than it looked: verification happens **once, at onboarding**, after which
      the application authenticates by email — so what the attack buys is a project account
      bound to someone else's number, not a session. Mitigated by one open `call_in`
      verification per number, the rate limits, and a shorter window for this rung. It does not
      reduce to zero; the spec returns the method so an application may refuse it.
- [ ] 1.5 **The window for `call_in`.** `phone-verification` ships five minutes for the ladder
      by the owner's decision of 18.09.2026. Two minutes was proposed here and never measured.
      The spec makes the rung's window separately configurable and no longer than the default;
      1.4 is the reason it should be a short one.
- [ ] 1.6 **Is `sms_in` worth keeping at all?** Raised by the onboarding answer, not yet put to
      the owner. It is the only rung the subscriber pays for, and it exists to be reached when
      everything cheaper failed. If the event happens once in a customer's life, spending
      0,80 ₽ of ours beats asking a new customer to text a robot. The ladder keeps it last
      because the owner ordered it so; dropping it is a decision, not a cleanup.

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

- [x] 4.1 Re-issue `CLIP_SUBSCRIBE` wherever `CNMI_SUBSCRIBE` is re-issued —
      `soft_recover` (`app/modem/at_commands.py:669-681`) does the second and not the first,
      on a docstring whose own argument covers both. Test first, and it must fail first.
- [x] 4.2 Record the subscription's state per link generation: issued and acknowledged, or
      not. `AT+CLIP=1` at init is already allowed to fail with only a warning
      (`app/modem/at_commands.py:706-715`) — that warning becomes a recorded fact.
- [x] 4.3 Make that record, and nothing read back from the modem, the rung's precondition on
      caller ID. `AT+CLIP?` does not answer on this device and `AT+CLIP=?` answers a
      different question.
- [x] 4.4 Count calls arriving with no usable caller number and expose the count to an
      operator. This is the only detector for a subscription dropped without a `CFUN` cycle,
      which the record in 4.2 cannot see.

## 5. The reader learns that a call happened

- [x] 5.1 Parse `RING` and `+CLIP` in `reader_loop` (`app/modem/manager.py:746-762`),
      alongside the existing `+CDS` and `+CMTI` branches. Today both fall to the `else`
      branch and are logged as `Unhandled URC` — the code comment there already names this
      as the case it was left for.
- [x] 5.2 Canonicalize the caller number through `phonenumbers` before matching, per
      AGENTS.md — canonicalize before storage, never after.
- [x] 5.3 Collapse one call's repetitions into one event. Measured 18.09.2026: fifteen
      `RING` / `+CLIP` pairs in sixteen seconds for a single call. Test first, failing first.
- [x] 5.4 Record every call in its own store, including those that confirmed nothing and
      those that carried no number — not in `inbound_messages`.
- [x] 5.5 Do not answer the call. `ATH` stays out: it needs the command port the sender holds,
      and that it rejects an unanswered incoming call on this firmware is an assertion about
      the device rather than a measurement.

## 6. The chooser

🔴 **Blocked on the base capability existing, verified in code on 19.09.2026, against
the previous handoff's claim that this section was free to start.** There is no
`verifications` table, no `POST /verifications`, no `/check` and no
`GET /verifications/{id}`: the public API is `/sms/send` and `/sms/{id}` and nothing
else. The selection door below is `POST /verifications/{id}/route`, and `{id}` has no
source. Those norms live in `route-sends-by-operator`'s delta, which is at 9/89 with
every code task open, and task 7.1 here forbids inventing a second store. Who builds
the base — that change or this one — is the owner's call, because a sister session
runs the other one and two sessions building one door is the collision task 3.1
exists to avoid.


- [x] 6.1 Route registry with a precondition probe per rung; the ladder's order and membership
      read from configuration.
- [x] 6.2 Bound the probe set **as a whole**, not probe by probe, and count an unanswered
      probe as unproven.
- [x] 6.3 The invariant on the boundary: a rung with an unproven or stale precondition is not
      offered. Guard on the offering, not a walk over the callers.
- [x] 6.4 The selection door — `POST /verifications/{id}/route`. Nothing is placed, composed
      or charged before a selection; selecting a rung that was not offered, or one whose
      precondition has since lapsed, is refused with that reason.
- [x] 6.5 No silent hop. A failed rung fails the verification with its reason and re-offers
      what is left; moving on is the consumer's act. **The ambiguity this carried is settled
      by the owner, 19.09.2026: failure is terminal, and "select again" means a new
      verification.** What the failed one owes is the list, not a second turn — without it a
      consumer would have to open a verification merely to discover what is left. Built:
      the poll on a `failed` verification carries the remaining ladder with its instructions,
      asked of the registry **at read time** (a rung's precondition decays, and a list
      composed at the ending is the stale evidence this change refuses everywhere else) and
      **without the rung that failed, by name** (it may still prove itself — `sms_in` burns
      its attempts on a mistyped code without becoming unavailable — and handing it back is
      the hop this norm forbids, arriving by the other door). Selecting on a verification
      that ended is refused as `verification_<status>` rather than `already_selected`: the
      latter is an answer about the route and would send a consumer looking for a way to
      release it.
- [x] 6.6 One open `call_in` verification per number; a second request for that number is
      answered without that rung.
- [x] 6.7 Refuse the verification when no rung can prove itself, in the same answer, rather
      than opening one that can only expire.

## 7. What the verification stores and says

- [x] 7.1 Reuse `phone-verification`'s storage requirement — per rung attempted, its vendor
      identifiers, cost and refund. Add: the rung selected, and the method that confirmed.
      Do not invent a second store.
- [x] 7.2 A verification whose selected rung loses its precondition ends with that reason and
      notifies, rather than reaching its deadline. Every writer of a terminal state notifies.
- [x] 7.3 The `call_in` window, configurable separately and defaulting to no longer than
      the ladder's.
- [x] 7.4 Return the code to the owning application **only** on `sms_in`, and never in an
      operator notification or a log line on any rung.
- [x] 7.5 The confirmation names the method, in the push and in the poll.

## 8. The two rungs this change bears

- [x] 8.1 `call_in` — confirmed by the caller's number alone, within one open window.
- [x] 8.2 `sms_in` — confirmed only by the pair of originating number and code; last on
      the ladder, and not offered when a cheaper rung proved itself.
- [x] 8.3 Inbound traffic that confirms nothing stays stored and visible exactly as today
      (`app/admin/router.py:351`) — verification neither deletes, hides nor reclassifies it.
      🔴 **Named and deliberately left, by the owner's decision of 19.09.2026:** an inbound
      message still reaches an application through `inbound_dispatch`, which routes by the
      first word and may therefore hand it to an application other than the one that opened
      the verification — carrying the code along with the text if the person typed one. That
      is today's behaviour and this task is what forbids changing it here; the path belongs
      to inbound routing, not to verification, and fixing it is its own change. The operator
      notification was cleaned of the code; this was not.

## 9. Guards that must bite, not merely pass

- [ ] 9.1 Each new guard is checked by mutation: break the guarded thing and confirm it goes
      red. A guard that never bit is not a guard.
- [x] 9.2 The silent-death guard specifically: with the IMS precondition unmet, assert the
      call rung is absent from the answer — **and assert the positive control**, that it is
      present when the precondition holds. A negative guard without its positive control has
      executed nothing.
- [x] 9.3 The same pair for the caller-ID record: rung absent when `AT+CLIP=1` failed, present
      when it succeeded, and an anonymous call is *not* a fault while the record holds.
- [x] 9.4 A test that `soft_recover` re-issues `CLIP` — it is a one-line omission today and
      will be a one-line omission again after the next edit to that function.
- [x] 9.5 Assert the ladder cannot be reordered into offering a rung without its precondition,
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
