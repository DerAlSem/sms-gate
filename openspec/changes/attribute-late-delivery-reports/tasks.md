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

- [ ] 8.1 Back up `data/sms-gate.db`, deploy, confirm the migration ran and the part-row count matches 7.9
- [ ] 8.2 Rehearse the back-out once: restore the backup into a scratch copy and confirm the service starts on it. "Restore" is the whole rollback plan and it has never been executed
- [ ] 8.3 Live: send a message and confirm it reaches `delivered` through the new lookup — the path is not proven by tests that build their own reports
- [x] 8.4 Changelog entry saying plainly that a delivery report could land on a message it was not about, and that a positive one could manufacture a delivery; bump the version in `app/__init__.py`
- [x] 8.5 Replace the file-only evidence tags in the spec deltas with the shipped line spans
- [ ] 8.6 Archive through `openspec archive`, once every task above is checked

## 9. After the ledger has evidence

- [ ] 9.1 A week after deploy, read the ledger: how many reports were contradicted, how many unplaced, how many decided by recency, how many superseded. Turn `delivery_report_strict_attribution` on only if the contradictions are real misattributions and not our own formatting
- [ ] 9.2 After the flip, verify both directions on the live gateway: a contradicting report is refused **and** ordinary deliveries still complete. Write down the condition that turns it back off
- [ ] 9.3 Open a separate change for the intermediate-status defect: a temporary `st` in the 0x20–0x3F band moves a message to `failed`, which is not an eligible status, so the real verdict can never be applied afterwards. Named as a non-goal here, and it is a live bug either way

- [x] 9.4 `AGENTS.md` says the database is `data/sms-gate.db`; on the host it is `data/sms.db`. One of them is wrong and it is the one an operator would follow
