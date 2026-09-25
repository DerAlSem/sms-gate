---
id: SG-1
title: attribute-late-delivery-reports
status: To Do
assignee: []
created_date: '2026-09-25 11:58'
labels:
  - migrated
dependencies: []
references:
  - openspec/changes/attribute-late-delivery-reports
ordinal: 1000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Why

A delivery report is attributed to a message by the modem's message reference alone, and
that reference is one octet. It counts 0…255 and starts again, and the gateway has been
round that loop eight times.

`message_parts` is keyed on it — `modem_ref INTEGER PRIMARY KEY` — and parts are written
with `INSERT OR REPLACE`. So a send that reuses a reference does not add a row: it
**overwrites** the row of the message that used that reference before, taking its part
record away. The older message keeps its row in `messages` and loses every trace of what it
put on the wire. By construction the whole table can never hold more than 256 rows.

`find_message_by_part_ref` then matches on the reference alone, against any message still
`sent` or `expired`, with **no upper bound on age**. A message expires five minutes after
it is sent and stays eligible for a delivery report for ever.

Put together, a report that arrives late — the normal case for a permanent failure, because
the network retries until the validity period runs out and only then gives its verdict — is
applied to whichever message happens to hold that reference *now*:

- the wrong message changes status, and the operator alert names the wrong id and the wrong
  phone number;
- `delivery-dispatch` POSTs that wrong id to the owning application, which is told a
  message failed that was delivered;
- `record_permanent_fail` counts the failure against the **recipient of the wrong
  message**, moving an uninvolved number toward the blacklist threshold, where unblocking
  deliberately does not reset the count;
- worst, and least visible: a misattributed **positive** report marks one part of an
  unrelated multipart message delivered, and at the timeout
  `complete_partly_reported_messages` promotes that message to `delivered` with
  `delivery_inferred = 1`. A message no report ever named becomes a delivery, and the record
  states that the gateway concluded it;
- and the message the report was actually about can never be corrected: its part row is
  gone.

The report carries what would settle it. Text-mode `+CDS` is `fo,mr,ra,tora,scts,dt,st` —
the recipient address and the service centre's timestamp of the original submit are in
every line, in fields the parser's own regex already steps over. It keeps `mr` and `st` and
throws the rest away.

## What is measured

Measured on the live database, 2026-09-02 (1765 messages, `derserver:/opt/sms-gate/data/sms.db`).

**The table is saturated: `message_parts` holds exactly 256 rows.** The structural cap is
not a worst case, it is the steady state.

**131 messages are `sent` or `expired` — eligible for a late report under today's rule,
which has no upper bound on age. Exactly one of them still has its part records.** Of the
other 130, twenty-five were created after per-part tracking landed (0.2.0, 2026-06-14) and
therefore *lost* records they once had; the remaining 105 predate the feature and never had
any. Since that release the gateway has expired 26 messages, and 25 of them have had their
part record taken.

**130 of those messages carry a stored `modem_ref` that `message_parts` now attributes to a
different message.** If the network speaks about any one of them, the report is applied to
somebody else: wrong id in the alert, wrong number, wrong webhook to the owning app, and a
permanent status counted against an uninvolved destination.

**Eleven messages carry `delivery_inferred = 1`** — deliveries the gateway concluded rather
than was told. When the rule that produces them shipped, production held one. A
misattributed positive report is one of the ways that number grows, and nothing distinguishes
the two causes after the fact.

### The alert that prompted this was attributed correctly

Message 1749 was created 2026-09-01 12:37:01 and sent a second later; it holds reference 75,
still owns both of its part records, and reached `failed` when the report arrived on
2026-09-02 at 15:37 — **twenty-seven hours** after submission. It was in the journal the
whole time, on its own creation date, which is why it was not at the top of a list ordered by
creation. Nothing was misattributed here. The defect below is the one the path it travelled
makes possible, not the one it demonstrates.

### The window default is measured, not guessed

Over 1544 reported deliveries the mean report arrives 93 seconds after submission, eleven
took more than an hour, the slowest took **13 hours, and none took more than a day**. The
negative verdict above took 27 hours, which is what a permanent failure costs: the network
exhausts its retries first. `delivery_report_max_age_hours` at **168** is six times the worst
verdict this gateway has ever seen.

### What is *not* measured, and one hypothesis that failed

The reference counter was suspected of restarting on `AT+CFUN=1,1`, which would make
references repeat minutes apart rather than hundreds of sends apart. **The data does not
support it.** Across the whole history the reference decreases eight times: seven are exactly
`255 -> 0`, and the eighth, `225 -> 12` on 2026-08-28, is what a wrap looks like when about
forty references are consumed without producing a message row. The service restarted two
minutes *after* that send, and no `CFUN` appears in the log around it. The counter wraps; it
was not observed to restart. The fix is unaffected — it rests on the report's own contents,
not on why references repeat — but the claim does not go into the design as a fact.

Sizing queries, for repetition:

```sql
SELECT COUNT(*) FROM message_parts;                      -- 256, by construction
SELECT COUNT(*) FROM messages m
 WHERE m.status IN ('sent','expired')
   AND m.modem_ref IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM message_parts p  WHERE p.message_id = m.id)
   AND EXISTS     (SELECT 1 FROM message_parts p2 WHERE p2.modem_ref = m.modem_ref
                                                    AND p2.message_id <> m.id);
```

## What Changes

Three layers, deliberately separable, and only the third can refuse a delivery.

**1. Identity — nothing can get worse.**

- **A part is identified by its message and segment**, not by the number the network handed
  back. `modem_ref` becomes an ordinary, indexed, repeating attribute; part history stops
  being overwritten.
- **The status writes address the part**, by message and segment, instead of updating every
  part that shares a reference.
- **A message reaches `delivered` only on evidence about itself** — closing both the
  vacuous `True` that `message_parts_all_delivered` returns for a message with no parts, and
  the inferred delivery that a single misattributed report can manufacture.

**2. Evidence — recorded before it is trusted.**

- **Every `+CDS` is written down**: its fields, its raw line, which part it was attributed
  to, and which candidates were considered. A report that cannot be placed is *kept*, not
  discarded, and an operator is told rather than left to find a rotated log line.
- **The recipient address and submit timestamp are parsed** and used to order candidates.
- **Eligibility for a late report is bounded** by `delivery_report_max_age_hours` — the
  window stops an ancient message sitting in the candidate set for ever; it does not
  adjudicate, and what it bounds out is recorded rather than lost.

**3. Refusal — behind a switch, off on arrival.**

- **A report whose recipient contradicts the only candidate is refused**, under
  `delivery_report_strict_attribution`. Off, the contradiction is recorded and the report is
  attributed as before; on, it is refused. The switch is flipped as a separate decision,
  against the ledger's own evidence, because this is the one rule that can turn a real
  delivery into an expiry.

**Absent evidence never closes a door.** An empty or short `ra`, an `scts` that will not
parse, a part whose submit time is unknown — each leaves attribution exactly where it is
today. The new fields may eliminate a candidate they contradict or order candidates they
can separate; they may never be required before an attribution is made. A rule that turned
deliveries into expiries on a formatting difference would be worse than the defect it
replaces.

## Capabilities

### New Capabilities

None. The report ledger is storage for an existing capability, not a capability of its own.

### Modified Capabilities

- `outbound-send`: the rule that records a part against the reference the modem returned,
  and the rule that turns a `+CDS` into a message status. Both are true of a counter that
  does not repeat, and this one repeats.
- `delivery-dispatch`: the scenario promising that an `expired` message "can still correct
  itself" when a late report arrives. True without qualification today, because eligibility
  never ends; the window gives it a bound, and an unqualified promise the code no longer
  keeps is worse than a qualified one.
- `admin-sms-console`: the rule refusing to delete an `expired` message, which is justified
  by that same never-ending eligibility. The rule stays and needs a second reason to stand
  on past the window — an `expired` message is one whose outcome the gateway never learned,
  and the record of an unanswered question is not routine tidying. That is a new premise, and
  it is stated here rather than decided quietly inside a delta. The same rule also has to say
  what deletion does to the recorded reports, which name the message and outlive it.

## Impact

- `app/db/migrate.py` — `message_parts` rebuilt under an explicit transaction; the base DDL
  replaced so a fresh install does not create the old shape; `delivery_reports` added.
- `app/db/queries.py` — part insert, the attribution lookup, both part status writers, the
  vacuous-truth guard, the inferred-delivery sweep, ledger insert and prune.
- `app/modem/parser.py` — `DeliveryReport` gains the two fields the line already carries.
  **The capture groups are positional and renumbering them silently inverts every
  delivery**; see design.
- `app/modem/manager.py` — `_handle_cds`, and the reader loop that calls it, which today
  catches no exception a malformed report could raise.
- `app/settings_store.py` — the window and the strict-attribution switch.
- `app/alerting.py` — an operator event for a report that could not be placed.
- `docs/api.md` — **both language versions**, at `:121` and `:305`, promise applications
  without qualification that a late `+CDS` arriving after a message was marked `expired`
  will still update it. That is the promise the window bounds, and it is the only document
  here addressed to the consumer of the contract.
- `docs/database.md`, `docs/modem.md`, `docs/implementation-notes.md` — all three describe
  the old part schema or the old lookup.
- `app/admin/router.py` — the resend docstring, which explains itself by saying delivery
  reports key off `modem_ref`. After this they do not.
- The webhook body is unchanged. Applications keep receiving the same statuses for the same
  ids; the ids start being the right ones, and the *distribution* shifts — a report that
  used to produce a `failed` for the wrong message can now produce an `expired` for the
  right one.

## Depends on

Nothing. The wire contract is recorded in `docs/modem.md` with a captured sample, and the
pattern is known to match live lines of both outcomes.
<!-- SECTION:DESCRIPTION:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Phases are ordered so that nothing risky ships before the evidence to judge it exists.
Phase 5 is the only one that can refuse a delivery, and it arrives switched off.

## 1. The report stops hiding what it carries

- [x] 1.1 Test: `parse_cds` on the captured sample in `docs/modem.md:103` returns reference **42** and status **0** — written and passing BEFORE 1.5, and still passing after
      <!-- The trap: `_CDS_PATTERN` groups are positional. Capturing `ra` and `scts`
           renumbers them, `status_code` starts reading a timestamp, and every delivery in
           the system silently becomes a failure while every hand-built test still passes. -->
- [x] 1.2 Test: the same on a failure line — reference and `st=64` come back from a report shaped like the one that prompted this change
- [x] 1.3 Test: an empty recipient address (`""`) parses, and the address is reported absent rather than as an empty number
- [x] 1.4 Test: a submit timestamp the parser cannot read leaves the report usable — the field is absent, the report is not rejected
- [x] 1.5 Extend `DeliveryReport` and `_CDS_PATTERN`; re-index every group reference in `parse_cds`
- [x] 1.6 Test: `"26/04/17,12:00:01+12"` reads as 12:00:01 at UTC+03:00 — quarter-hours, not hours — and `YY` as 20YY
- [x] 1.7 Parse the submit timestamp to an absolute time; unparsable is absent, never epoch zero

## 2. Every report is written down

- [x] 2.1 Test: an attributed report leaves a record naming message, segment and how it was chosen, and raises no notification
- [x] 2.2 Test: an unplaced report leaves a record carrying reference, address and reason, and raises one operator notification
- [x] 2.3 Test: a superseded report — one whose reference matches a part of an already `delivered` message — is recorded and raises **no** notification
- [x] 2.4 Test: several unplaced reports with the same reference inside the dedup window raise one notification
- [x] 2.5 Test: a `+CDS` line that does not parse still leaves a record holding the raw line and the arrival time
- [x] 2.6 Test: the record names **every** part whose reference matched, each with its own outcome — not only the winner
- [x] 2.6a Test: a report bounded out by the window records the part it bounded out, not "nothing matched"; a superseded report names the part it was superseded by. Collect the reference matches BEFORE applying the window and status filters — a `WHERE` clause that filters first cannot name what it discarded, and makes every superseded report look unplaced and alert
- [x] 2.6b Test: an unparsable line is recorded under its own outcome and logged at **error** level — it is the one class of event that must not reach nobody, because our parser failing on a live line is either a wire-format change or the group-renumbering fault
- [x] 2.7 Test: the record carries the window and switch values in force at the time
- [x] 2.8 Test: a failing record write leaves the attribution standing and logs
- [x] 2.9 Test: pruning removes records past the retention and nothing newer
- [x] 2.10 Add the `delivery_reports` table and its indexes, the insert, and a named retention constant with a 30-day default
- [x] 2.11 Call the prune from the expiry sweep, not from `scan_inbox` — a gateway that never loses its link would otherwise never prune
- [x] 2.11a Test: pruning happens on a recurring tick, not only at startup — a boot-only prune satisfies "does not depend on link recovery" and still never runs on a long-lived gateway
- [x] 2.12 Add the alert type with **its own toggle defaulting to on** (`notify_delivery_errors` defaults to off and would leave the guarantee empty on every existing install) and dedup keyed on the reference

## 3. A part record stops being the network's to overwrite

- [x] 3.1 Test: recording a part under a reference another message already used leaves both records, each against its own message, and the earlier one keeps its status
- [x] 3.2 Test: recording part 2 does not disturb part 1 of the same message
- [x] 3.3 Test: part 2's recorded time is when part 2 was accepted, not the message's `sent_at`
- [x] 3.4 Test: the migration carries existing part rows over with status intact and backfills submit time from the message
- [x] 3.5 Test: the migration is idempotent, and the guard reads the **primary key shape** from `sqlite_master`, not the presence of a column
- [x] 3.6 Test: **fresh install** — an empty database gets the new shape from the base DDL and the rebuild does not run, on the first start or the second. Without this, a base statement the guard cannot match rebuilds the table on every boot, invisibly
- [x] 3.7 Test: legacy rows duplicating `(message_id, seq)` do not abort the migration, **and a duplicated pair holding `delivered` and `sent` survives as `delivered`** — a column-wise `MAX()` picks `sent` and silently downgrades a confirmed part, which then expires and tells the app a delivery failed
- [x] 3.7a Test: a duplicate insert on the new key raises, is logged, and does **not** fail the message — it can only fire after a segment the network already accepted, and failing there invites a resend and a second delivery
- [x] 3.8 Test: a database left holding `message_parts_v2` from a crashed run migrates cleanly instead of crash-looping
- [x] 3.9 Test: both indexes exist after the rebuild — `DROP TABLE` takes them, and the base script that created one has already run
- [x] 3.10 Rebuild `message_parts` in its own explicit transaction, outside `executescript`, with `foreign_keys` off around it
- [x] 3.11 Replace the base DDL at `app/db/migrate.py:90` so a fresh install creates the new shape and satisfies the guard
- [x] 3.12 Record each part's own submit time, and stop using `INSERT OR REPLACE`

## 4. Attribution, failing open

- [x] 4.1 Test: one qualifying, uncontradicted candidate **is** updated — the positive obligation, without which attributing nothing satisfies every other rule
- [x] 4.2 Test: two candidates, one chosen by the rules → that one **is** updated. Choosing is not applying, and a chain that selects and writes nothing satisfies every "SHALL prefer"
- [x] 4.3 Test: a part with no recorded submit time qualifies, rather than being excluded as too old
- [x] 4.4 Test: an empty address, an address of six digits, or a stored number of fewer than ten digits eliminates nothing
- [x] 4.5 Test: `89031680015` does not eliminate a candidate addressed to `+79031680015`
- [x] 4.6 Test: a submit timestamp hours from the candidate's own does not stop the update
- [x] 4.7 Test: two candidates → nearest submit time wins, every candidate recorded
- [x] 4.8 Test: no usable report timestamp → most recent wins, record says recency
- [x] 4.9 Test: two candidates nothing separates, permanent status → most recent wins and the destination's failure count is **not** incremented
- [x] 4.9a Test: the same carve-out holds on the late-negative path — an `expired` message moved to `failed` by a recency-chosen report does not increment the blacklist. Blocking a destination 422s every later send to it and unblocking does not reset the count
- [x] 4.10 Test: an already-reported part does not shadow an unreported candidate sharing the reference
- [x] 4.11 Test: a second report for an already-reported part, no other match → status stands, outcome superseded
- [x] 4.12 Test: the only matching part is past the window → nothing changes, recorded unplaced
- [x] 4.13 Test: `delivery_report_max_age_hours` saved as `0` or negative is refused; a stored value that cannot be read falls back to the default rather than discarding every report
- [x] 4.14 Rewrite the lookup as the chain, returning a **decision** — part, outcome, and how it was chosen — not a row
- [x] 4.15 Wire the decision through `_handle_cds`: the ledger writes all of it, the alert fires on unplaced alone, and `record_permanent_fail` is skipped when the choice was recency. Without this task 4.9 has a test and no mechanism
- [x] 4.16 Add `delivery_report_max_age_hours` (positive int, refused at zero or below, re-read per report, default per design)
- [x] 4.17 Change `set_part_delivered` / `set_part_failed` to address `(message_id, seq)`
- [x] 4.18 Test: a report attributed to one part leaves another message's part with the same reference untouched
- [x] 4.19 Test: `message_parts_all_delivered` reports parts outstanding for a message with no part rows
- [x] 4.20 Test: a message no report was ever attributed to does not become `delivered` at the timeout, by inference or otherwise
- [x] 4.21 Test: a late negative report inside the window moves an `expired` message to `failed`, notifies after the `expired` notification, and counts toward the blacklist
- [x] 4.22 Close both vacuous truths — the zero-row answer and the inferred delivery
- [x] 4.23 Test: the status write commits before the record is written

## 5. Refusal, behind the switch

- [x] 5.1 Test: strict on, the only candidate addressed elsewhere → nothing changes, both numbers recorded, operator notified
- [x] 5.2 Test (positive control for 5.1): strict on, the same report against a candidate whose digits agree → the part **is** updated. Without this, 5.1 passes against a lookup that finds nothing at all
- [x] 5.3 Test: strict off, that same contradicting report → attributed as before, contradiction recorded
- [x] 5.4 Test: the switch is read per report — changing it takes effect without a restart
- [x] 5.5 Add `delivery_report_strict_attribution`, default off
- [x] 5.6 Mutation check: revert the lookup to matching on reference alone and confirm 4.1, 4.18 and 5.1 go red. A guard nobody has bitten is an unchecked box
      <!-- Done, and the task's own single mutation turned out not to bite all three: the
           three guards protect three different mechanisms, so each was bitten separately.
           (a) chain matches on the reference alone — 8 red, including 5.1, the superseded
           outcome and the window bound; 4.1 and 4.18 stay green, correctly, because one
           uncontradicted candidate is still found and the WRITE is still addressed.
           (b) set_part_delivered addressed by modem_ref again — 4.18 red, and 4.20 with
           it: that is the inferred-delivery manufacture reappearing.
           (c) attribution selects but applies nothing — 4.1 red, with four others.
           A single mutation reported as covering all three would have been a green tick
           over two unbitten guards. -->

## 6. The loop survives what the network sends

- [x] 6.1 Test: a report whose address field cannot be interpreted is recorded and abandoned, and the next `+CDS` on the port is still processed
- [x] 6.2 Test: an unexpected error inside report handling is logged, the reader loop continues, and a later `+CMTI` is still handled
- [x] 6.3 Wrap `+CDS` handling in `reader_loop` as `inbound_loop` and `retry_loop` already are — today it is the only bare path, and this change is what starts feeding it network-chosen text

## 7. Nothing left unwired, nothing left unmeasured

- [x] 7.1 Mini conformance sweep: every normative SHALL added or reworded by this change, matched to the test that would fail without it. Name the ones with no test
      <!-- 73 SHALLs across the three deltas (58 outbound-send, 6 delivery-dispatch,
           9 admin-sms-console). Every one is matched to a test EXCEPT the four found
           bare, which have since been closed:
           (1) "SHALL NOT be compared by canonicalizing" — a NEGATIVE structural claim.
               Task 4.5 (89031680015 vs +79031680015) passes against a canonicalizing
               implementation too: validate_and_normalize("8903…", "RU") resolves to the
               same number. The distinguishing case is a valid FOREIGN address, which
               raises under restrict_region=True. Closed by
               test_a_foreign_address_the_canonicalizer_would_reject_eliminates_nothing,
               which demonstrates the raise and then shows the digit comparison both
               agreeing and eliminating.
           (2) "delivery_report_max_age_hours ... SHALL be re-read for each report" —
               the strict switch had this test (5.4) and the window did not. Closed by
               test_the_window_is_read_for_each_report.
           (3) delivery-dispatch, "SHALL NOT notify a status change arising from a report
               it did not attribute", the WINDOW case specifically — 7.4 covered a
               reference nothing carries, not a match bounded out. Closed by
               test_a_report_bounded_out_by_the_window_sends_no_second_notification.
           (4) task 4.9a — the recency carve-out reached through `expired` rather than
               `sent`. Same function, so covered by construction, which is exactly the
               reasoning that should not be trusted. Closed by
               test_the_recency_carve_out_holds_on_the_late_negative_path. -->
- [x] 7.2 `grep -rn` every function this change adds or renames; each must have a caller outside its own definition and its tests
      <!-- 21 names checked (parse_scts, attribute, significant_digits,
           AttributionDecision, record_delivery_report, prune_delivery_reports,
           parts_matching_ref, set_part_delivered, set_part_failed,
           _rebuild_message_parts, _parts_keyed_on_the_pair, _on_cds_line,
           _record_report, _apply_report, _as_stored_time,
           _DELIVERY_REPORT_RETENTION, notify_unplaced_reports,
           delivery_report_max_age_hours, delivery_report_strict_attribution,
           the "delivery_unplaced" event, the "posint" setting type).
           Every one has at least one caller in `app/` outside its own definition. -->
- [x] 7.3 Confirm `_handle_cds` passes the new fields through — the boundary unit tests do not cross, since they build `DeliveryReport` themselves
      <!-- test_every_parsed_field_crosses_the_boundary_into_the_record drives a real
           line through _on_cds_line and asserts every parsed field in the stored row,
           including the quarter-hour conversion (11:00:01+12 -> 08:00:01 UTC). Bitten:
           dropping submitted_at in _handle_cds reddens that test and NOTHING else — 40
           other tests across the parser and chain suites stay green, which is the gap
           this task exists for. -->
- [x] 7.4 Test: no `delivered`/`failed` webhook is sent for a report that was not attributed
- [x] 7.5 Test: an `expired` message past the window still cannot be deleted, and deleting an eligible message leaves its ledger rows
- [x] 7.6 Settle the reference-counter question — does `AT+CFUN=1,1` restart TP-MR?
      <!-- Measured on live data instead of a vendor doc, which answers it better: eight
           reference decreases in 1765 messages, seven exactly 255->0, the eighth (225->12,
           2026-08-28) a wrap crossing the boundary with ~43 refs consumed without a message
           row; no CFUN in the log, and the service restart was two minutes later. NOT
           supported. Design corrected; it had been written as a hypothesis, not a fact. -->
- [x] 7.7 Live, read-only: part-table size and messages that lost their records
      <!-- message_parts = exactly 256 rows, saturated. 131 messages sent/expired, ONE still
           has part rows. 25 lost theirs since 0.2.0 (2026-06-14); 105 predate the feature.
           130 carry a modem_ref that message_parts now attributes to another message. -->
- [x] 7.8 Live, read-only: message 1749, and the report-latency distribution
      <!-- 1749: created 2026-09-01 12:37:01, sent 12:37:02, now failed; holds ref 75 and
           BOTH its part rows, so that attribution was correct. Verdict took 27h. Delivered
           messages (n=1544): mean 93s, max 13.0h, eleven over 1h, none over 24h.
           168h default stands — six times the worst verdict observed. -->
- [x] 7.9 Rehearse the migration on a **copy of the production database**, recording the part-row count before and after. The precedent in this repo rehearsed an `ADD COLUMN`; this one drops a table
      <!-- Rehearsed 2026-09-03 ON derserver, against `.backup` copies in /tmp — the live
           database was read through `sqlite3 -readonly` and nothing was pulled off the
           host, since it holds message texts and numbers. Copies removed after.

           BEFORE: 256 part rows (saturated, as measured on 2026-09-02), 256 distinct
           (message_id, seq) pairs, zero orphans, zero legacy duplicates; statuses
           250 delivered / 1 failed / 5 sent; 1781 messages; old single-column PK.
           AFTER:  256 part rows, the SAME 250/1/5, `sent_at` backfilled on all 256,
           both indexes present plus the pair PK, `delivery_reports` created empty.
           Second run: byte-identical counts — the guard holds on real stored DDL.
           `PRAGMA integrity_check` = ok, `PRAGMA foreign_key_check` = 0 rows.

           The crash-loop case rehearsed on its own copy: a `message_parts_v2` left
           behind by a killed run (planted with a row in it) migrated cleanly to the same
           256/250/1/5 instead of failing every start.

           Note the live table has no duplicate pairs and no orphans, so the two hardest
           branches of the rebuild ran against nothing here. They are covered by tests
           on constructed data (3.7, orphan-drop), which is the only place they can be. -->
- [x] 7.10 Full test suite green
      <!-- 682 passed. Four failures remain in tests/test_alert_send_sh.py and are
           PRE-EXISTING and unrelated: verified by stashing this branch and running them
           on master, where the same four fail. `encode()` in deploy/alert-send.sh uses
           the GNU sed line-join `-e ':a' -e 'N' -e '$!ba'`, which BSD sed on macOS
           answers with an empty string. A Linux host — which is where the unit runs —
           is unaffected. Not fixed here: it is a different defect in a different file
           and folding it in would hide it. -->
- [x] 7.11 Update `docs/api.md` (**both language versions**, `:121` and `:305` — the only document addressed to the consumer of the contract), `docs/database.md`, `docs/modem.md`, `docs/implementation-notes.md`, and the resend docstring at `app/admin/router.py:212`, which explains itself by saying delivery reports key off `modem_ref`

## 8. Ship

- [x] 8.1 Back up `data/sms.db`, deploy, confirm the migration ran and the part-row count matches 7.9
      <!-- Deployed 2026-09-03 13:42 MSK, 0.17.0 -> 0.18.0, by push-to-deploy to
           `deploy-remote` (the host has no working tree of its own; the post-receive hook
           checks out and restarts). Restart authorised by the owner.
           Backup first: ~/sms-gate-backups/sms-20260903-134159.db, integrity_check ok,
           256 parts / 1784 messages. Path in this task said `sms-gate.db`; the file is
           `sms.db` (task 9.4).
           Queue at restart: 0 pending, 0 sent — nothing was in flight to be dropped.
           Journal: "Rebuilding message_parts onto (message_id, seq)", then every loop
           started, no traceback.
           AFTER, and identical to the rehearsal: 256 parts, 250 delivered / 1 failed /
           5 sent, sent_at on all 256, the pair primary key, both part indexes plus both
           ledger indexes, `delivery_reports` empty, integrity_check ok.
           Settings seeded: delivery_report_max_age_hours=168,
           delivery_report_strict_attribution=FALSE, notify_unplaced_reports=true. -->
- [x] 8.2 Rehearse the back-out once: restore the backup into a scratch copy and confirm the service starts on it. "Restore" is the whole rollback plan and it has never been executed
      <!-- Executed. The 0.17.0 tree (9010fdf, from the bare repo) started against the
           restored backup on a scratch port with a modem path that does not exist:
           `/docs` 200, `/admin/` 302 past auth, "Application startup complete", no
           traceback. The old single-column `message_parts` key was intact afterwards with
           256 rows and 1784 messages — the rollback really is "restore the file and put
           the old code back".

           ⚠️ The FIRST attempt reported the same green result and proved nothing: the
           `.env` was written beside the tree rather than inside it, so pydantic-settings
           never read it and the instance came up on a fresh empty database
           (122KB, found by `find`). Caught by asking which file it had actually opened.
           Redone with the values exported into the environment. This is the task's own
           warning arriving a second time: a rollback nobody has executed, and then a
           rehearsal that executed the wrong thing. -->
- [x] 8.3 Live: send a message and confirm it reaches `delivered` through the new lookup — the path is not proven by tests that build their own reports
      <!-- Done on ORGANIC traffic rather than a synthetic send (owner's choice: the live
           database is real customer traffic and a test number would have had to be
           guessed). The first report after deploy exercised the reference collision
           directly.

           `+CDS: 6,112,"+79857566633",145,"26/09/03,14:08:39+12","26/09/03,14:08:41+12",0`

           Reference 112 is carried by TWO messages ten days apart — 1578 (sent
           2026-08-24, to +79266235172) and 1785 (sent today, to +79857566633) — and
           BOTH part rows exist. Under the old schema `add_message_part` would have
           overwritten 1578's row on today's send; that is the whole defect, and it did
           not happen.

           The ledger row: 1578's part graded `superseded` (its message is already
           `delivered`) and recorded `contradicted: true` — the numbers really do differ;
           1785's part `chosen`, `decided_by: sole`. 1785 -> `delivered`,
           `delivery_inferred = 0`. 1578 untouched. No alert, no error in the journal.

           `scts` "26/09/03,14:08:39+12" stored as 2026-09-03 11:08:39 UTC. MSK is UTC+3
           and +12 quarter-hours is +03:00 — the conversion is right on a live line, which
           no hand-built report could have shown.

           Said precisely: this particular report would have been attributed correctly by
           the OLD code too, because 1578 was already `delivered` and therefore ineligible.
           What it proves is the machinery end to end on a real collision — both records
           surviving, the grading, the contradiction recorded while strict is off, the
           timestamp, and the sole choice. -->
- [x] 8.4 Changelog entry saying plainly that a delivery report could land on a message it was not about, and that a positive one could manufacture a delivery; bump the version in `app/__init__.py`
- [x] 8.5 Replace the file-only evidence tags in the spec deltas with the shipped line spans
- [ ] 8.6 Archive through `openspec archive`, once every task above is checked

## 9. After the ledger has evidence

- [ ] 9.1 A week after deploy, read the ledger: how many reports were contradicted, how many unplaced, how many decided by recency, how many superseded. Turn `delivery_report_strict_attribution` on only if the contradictions are real misattributions and not our own formatting
- [ ] 9.2 After the flip, verify both directions on the live gateway: a contradicting report is refused **and** ordinary deliveries still complete. Write down the condition that turns it back off
- [x] 9.3 Open a separate change for the intermediate-status defect: a temporary `st` in the 0x20–0x3F band moves a message to `failed`, which is not an eligible status, so the real verdict can never be applied afterwards. Named as a non-goal here, and it is a live bug either way
      <!-- Opened as `hold-messages-on-a-temporary-tp-status`: proposal, an outbound-send
           MODIFIED delta and tasks, `openspec validate --strict` green. Marked in its own
           proposal as authored-but-NOT-critiqued — the system-architect / gap-finder layer
           is task 2.3 there, and two design questions are deliberately left open (what the
           owning application hears, and what a held message does at the timeout).
           It declares a dependency on THIS change being archived first: both rewrite the
           same requirement, and its MODIFIED block is written against the text this one
           installs. Archiving in the other order would drop one rewrite silently. -->

- [x] 9.4 `AGENTS.md` says the database is `data/sms-gate.db`; on the host it is `data/sms.db`. One of them is wrong and it is the one an operator would follow
<!-- SECTION:NOTES:END -->
