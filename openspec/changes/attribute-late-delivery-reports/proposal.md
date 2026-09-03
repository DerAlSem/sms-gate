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
