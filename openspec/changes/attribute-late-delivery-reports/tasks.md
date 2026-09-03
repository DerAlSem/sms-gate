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

- [ ] 2.1 Test: an attributed report leaves a record naming message, segment and how it was chosen, and raises no notification
- [ ] 2.2 Test: an unplaced report leaves a record carrying reference, address and reason, and raises one operator notification
- [ ] 2.3 Test: a superseded report — one whose reference matches a part of an already `delivered` message — is recorded and raises **no** notification
- [ ] 2.4 Test: several unplaced reports with the same reference inside the dedup window raise one notification
- [ ] 2.5 Test: a `+CDS` line that does not parse still leaves a record holding the raw line and the arrival time
- [ ] 2.6 Test: the record names **every** part whose reference matched, each with its own outcome — not only the winner
- [ ] 2.6a Test: a report bounded out by the window records the part it bounded out, not "nothing matched"; a superseded report names the part it was superseded by. Collect the reference matches BEFORE applying the window and status filters — a `WHERE` clause that filters first cannot name what it discarded, and makes every superseded report look unplaced and alert
- [ ] 2.6b Test: an unparsable line is recorded under its own outcome and logged at **error** level — it is the one class of event that must not reach nobody, because our parser failing on a live line is either a wire-format change or the group-renumbering fault
- [ ] 2.7 Test: the record carries the window and switch values in force at the time
- [ ] 2.8 Test: a failing record write leaves the attribution standing and logs
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

- [ ] 4.1 Test: one qualifying, uncontradicted candidate **is** updated — the positive obligation, without which attributing nothing satisfies every other rule
- [ ] 4.2 Test: two candidates, one chosen by the rules → that one **is** updated. Choosing is not applying, and a chain that selects and writes nothing satisfies every "SHALL prefer"
- [ ] 4.3 Test: a part with no recorded submit time qualifies, rather than being excluded as too old
- [ ] 4.4 Test: an empty address, an address of six digits, or a stored number of fewer than ten digits eliminates nothing
- [ ] 4.5 Test: `89031680015` does not eliminate a candidate addressed to `+79031680015`
- [ ] 4.6 Test: a submit timestamp hours from the candidate's own does not stop the update
- [ ] 4.7 Test: two candidates → nearest submit time wins, every candidate recorded
- [ ] 4.8 Test: no usable report timestamp → most recent wins, record says recency
- [ ] 4.9 Test: two candidates nothing separates, permanent status → most recent wins and the destination's failure count is **not** incremented
- [ ] 4.9a Test: the same carve-out holds on the late-negative path — an `expired` message moved to `failed` by a recency-chosen report does not increment the blacklist. Blocking a destination 422s every later send to it and unblocking does not reset the count
- [ ] 4.10 Test: an already-reported part does not shadow an unreported candidate sharing the reference
- [ ] 4.11 Test: a second report for an already-reported part, no other match → status stands, outcome superseded
- [ ] 4.12 Test: the only matching part is past the window → nothing changes, recorded unplaced
- [ ] 4.13 Test: `delivery_report_max_age_hours` saved as `0` or negative is refused; a stored value that cannot be read falls back to the default rather than discarding every report
- [ ] 4.14 Rewrite the lookup as the chain, returning a **decision** — part, outcome, and how it was chosen — not a row
- [ ] 4.15 Wire the decision through `_handle_cds`: the ledger writes all of it, the alert fires on unplaced alone, and `record_permanent_fail` is skipped when the choice was recency. Without this task 4.9 has a test and no mechanism
- [ ] 4.16 Add `delivery_report_max_age_hours` (positive int, refused at zero or below, re-read per report, default per design)
- [ ] 4.17 Change `set_part_delivered` / `set_part_failed` to address `(message_id, seq)`
- [ ] 4.18 Test: a report attributed to one part leaves another message's part with the same reference untouched
- [ ] 4.19 Test: `message_parts_all_delivered` reports parts outstanding for a message with no part rows
- [ ] 4.20 Test: a message no report was ever attributed to does not become `delivered` at the timeout, by inference or otherwise
- [ ] 4.21 Test: a late negative report inside the window moves an `expired` message to `failed`, notifies after the `expired` notification, and counts toward the blacklist
- [ ] 4.22 Close both vacuous truths — the zero-row answer and the inferred delivery
- [ ] 4.23 Test: the status write commits before the record is written

## 5. Refusal, behind the switch

- [ ] 5.1 Test: strict on, the only candidate addressed elsewhere → nothing changes, both numbers recorded, operator notified
- [ ] 5.2 Test (positive control for 5.1): strict on, the same report against a candidate whose digits agree → the part **is** updated. Without this, 5.1 passes against a lookup that finds nothing at all
- [ ] 5.3 Test: strict off, that same contradicting report → attributed as before, contradiction recorded
- [ ] 5.4 Test: the switch is read per report — changing it takes effect without a restart
- [ ] 5.5 Add `delivery_report_strict_attribution`, default off
- [ ] 5.6 Mutation check: revert the lookup to matching on reference alone and confirm 4.1, 4.18 and 5.1 go red. A guard nobody has bitten is an unchecked box

## 6. The loop survives what the network sends

- [ ] 6.1 Test: a report whose address field cannot be interpreted is recorded and abandoned, and the next `+CDS` on the port is still processed
- [ ] 6.2 Test: an unexpected error inside report handling is logged, the reader loop continues, and a later `+CMTI` is still handled
- [ ] 6.3 Wrap `+CDS` handling in `reader_loop` as `inbound_loop` and `retry_loop` already are — today it is the only bare path, and this change is what starts feeding it network-chosen text

## 7. Nothing left unwired, nothing left unmeasured

- [ ] 7.1 Mini conformance sweep: every normative SHALL added or reworded by this change, matched to the test that would fail without it. Name the ones with no test
- [ ] 7.2 `grep -rn` every function this change adds or renames; each must have a caller outside its own definition and its tests
- [ ] 7.3 Confirm `_handle_cds` passes the new fields through — the boundary unit tests do not cross, since they build `DeliveryReport` themselves
- [ ] 7.4 Test: no `delivered`/`failed` webhook is sent for a report that was not attributed
- [ ] 7.5 Test: an `expired` message past the window still cannot be deleted, and deleting an eligible message leaves its ledger rows
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
- [ ] 7.9 Rehearse the migration on a **copy of the production database**, recording the part-row count before and after. The precedent in this repo rehearsed an `ADD COLUMN`; this one drops a table
- [ ] 7.10 Full test suite green
- [ ] 7.11 Update `docs/api.md` (**both language versions**, `:121` and `:305` — the only document addressed to the consumer of the contract), `docs/database.md`, `docs/modem.md`, `docs/implementation-notes.md`, and the resend docstring at `app/admin/router.py:212`, which explains itself by saying delivery reports key off `modem_ref`

## 8. Ship

- [ ] 8.1 Back up `data/sms-gate.db`, deploy, confirm the migration ran and the part-row count matches 7.9
- [ ] 8.2 Rehearse the back-out once: restore the backup into a scratch copy and confirm the service starts on it. "Restore" is the whole rollback plan and it has never been executed
- [ ] 8.3 Live: send a message and confirm it reaches `delivered` through the new lookup — the path is not proven by tests that build their own reports
- [ ] 8.4 Changelog entry saying plainly that a delivery report could land on a message it was not about, and that a positive one could manufacture a delivery; bump the version in `app/__init__.py`
- [ ] 8.5 Replace the file-only evidence tags in the spec deltas with the shipped line spans
- [ ] 8.6 Archive through `openspec archive`, once every task above is checked

## 9. After the ledger has evidence

- [ ] 9.1 A week after deploy, read the ledger: how many reports were contradicted, how many unplaced, how many decided by recency, how many superseded. Turn `delivery_report_strict_attribution` on only if the contradictions are real misattributions and not our own formatting
- [ ] 9.2 After the flip, verify both directions on the live gateway: a contradicting report is refused **and** ordinary deliveries still complete. Write down the condition that turns it back off
- [ ] 9.3 Open a separate change for the intermediate-status defect: a temporary `st` in the 0x20–0x3F band moves a message to `failed`, which is not an eligible status, so the real verdict can never be applied afterwards. Named as a non-goal here, and it is a live bug either way

- [ ] 9.4 `AGENTS.md` says the database is `data/sms-gate.db`; on the host it is `data/sms.db`. One of them is wrong and it is the one an operator would follow
