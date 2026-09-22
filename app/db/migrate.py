import logging

from app.db.connection import get_db

logger = logging.getLogger(__name__)


async def _add_column_if_missing(db, table: str, column: str, decl: str) -> None:
    """ALTER TABLE ADD COLUMN, skipped when the column is already there — SQLite has no
    `ADD COLUMN IF NOT EXISTS`, and run_migrations() runs on every start."""
    async with db.execute(f"PRAGMA table_info({table})") as cursor:
        existing = {row[1] async for row in cursor}
    if column not in existing:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


# The fact the rebuild is idempotent on: the *shape of the primary key*, read back from
# the DDL SQLite stored. Deliberately not the presence of `sent_at` — a column anybody
# can add with `_add_column_if_missing`, after which the guard would lie for ever.
_PARTS_PAIR_KEY = "primary key (message_id, seq)"


async def _parts_keyed_on_the_pair(db) -> bool:
    async with db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='message_parts'"
    ) as cursor:
        row = await cursor.fetchone()
    if row is None or row[0] is None:
        return False
    return _PARTS_PAIR_KEY in " ".join(row[0].split()).lower()


async def _rebuild_message_parts(db) -> None:
    """Move `message_parts` off `modem_ref INTEGER PRIMARY KEY` onto `(message_id, seq)`.

    SQLite cannot replace a primary key in place, so the table is rebuilt — and the naive
    script is unsafe here in three separate ways.

    **Atomic.** `run_migrations` uses `executescript`, which commits implicitly and would
    leave these steps unprotected: a kill between `DROP` and `RENAME` leaves no
    `message_parts` at all, the base `CREATE TABLE IF NOT EXISTS` recreates the *old*
    shape empty on the next boot, the rebuild runs again, hits the `message_parts_v2`
    left behind, and the service crash-loops with the part records gone. So this runs as
    its own explicit transaction, driven by hand.

    **One whole row per pair, never a blend.** The old key never constrained
    `(message_id, seq)`, so the pair can repeat in legacy data. A column-wise `GROUP BY`
    with `MAX()` assembles a row that never existed — `MAX(status)` under BINARY
    collation orders `'delivered' < 'sent'` and downgrades a confirmed part to
    outstanding, which then feeds the expiry sweep and tells the owning app a delivery
    failed. Taking the latest row by `rowid` loses it just as surely, because the report
    that confirmed a segment arrived against the *earlier* transmission of it. The
    surviving row is therefore chosen whole, preferring the one a report actually
    reached, latest first within that.

    **Orphans are dropped** by the `JOIN`: a part whose message is gone is unattributable
    by definition, and carrying it forward would feed it back into the candidate set.
    """
    if await _parts_keyed_on_the_pair(db):
        return

    logger.info("Rebuilding message_parts onto (message_id, seq)")

    # `PRAGMA foreign_keys` is a no-op inside a transaction, so it is set with none open,
    # as the documented SQLite table-rebuild procedure requires. The transaction is then
    # driven by explicit statements rather than by the connection's implicit handling —
    # `BEGIN IMMEDIATE` leaves autocommit off, so the driver adds no `BEGIN` of its own,
    # and the whole rebuild commits or rolls back as one.
    await db.commit()
    await db.execute("PRAGMA foreign_keys = OFF")
    try:
        await db.execute("BEGIN IMMEDIATE")
        try:
            # A previous crashed run leaves this behind; without the DROP the rebuild
            # cannot make progress and every start fails the same way.
            await db.execute("DROP TABLE IF EXISTS message_parts_v2")
            await db.execute(f"""
                CREATE TABLE message_parts_v2 (
                    message_id  INTEGER NOT NULL REFERENCES messages(id),
                    seq         INTEGER NOT NULL,
                    modem_ref   INTEGER NOT NULL,
                    total       INTEGER NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'sent',
                    sent_at     TIMESTAMP,
                    PRIMARY KEY (message_id, seq)
                )
            """)
            await db.execute("""
                INSERT INTO message_parts_v2
                       (message_id, seq, modem_ref, total, status, sent_at)
                SELECT p.message_id, p.seq, p.modem_ref, p.total, p.status, m.sent_at
                  FROM message_parts p
                  JOIN messages m ON m.id = p.message_id
                 WHERE p.rowid = (
                        SELECT p2.rowid FROM message_parts p2
                         WHERE p2.message_id = p.message_id
                           AND p2.seq        = p.seq
                         ORDER BY (p2.status = 'sent') ASC, p2.rowid DESC
                         LIMIT 1)
            """)
            await db.execute("DROP TABLE message_parts")     # takes its indexes with it
            await db.execute("ALTER TABLE message_parts_v2 RENAME TO message_parts")
            # Recreated *inside* the rebuild. The base script's index has already run by
            # this point and the DROP above took it; nothing would put it back until the
            # next start.
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_message_parts_message "
                "ON message_parts(message_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_message_parts_ref "
                "ON message_parts(modem_ref)"
            )
            await db.execute("COMMIT")
        except Exception:
            await db.execute("ROLLBACK")
            raise
    finally:
        await db.execute("PRAGMA foreign_keys = ON")


async def run_migrations() -> None:
    db = await get_db()

    await db.executescript("""
        CREATE TABLE IF NOT EXISTS apps (
            id          TEXT PRIMARY KEY,
            token       TEXT UNIQUE NOT NULL,
            description TEXT,
            is_active   BOOLEAN DEFAULT 1,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            app_id       TEXT NOT NULL REFERENCES apps(id),
            phone        TEXT NOT NULL,
            text         TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'pending',
            modem_ref    INTEGER,
            sent_at      TIMESTAMP,
            delivered_at TIMESTAMP,
            error        TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_messages_app_id   ON messages(app_id);
        CREATE INDEX IF NOT EXISTS idx_messages_status   ON messages(status);
        CREATE INDEX IF NOT EXISTS idx_messages_modem_ref ON messages(modem_ref);
        CREATE INDEX IF NOT EXISTS idx_messages_phone    ON messages(phone);

        CREATE TABLE IF NOT EXISTS bad_numbers (
            phone        TEXT PRIMARY KEY,
            fail_count   INTEGER NOT NULL DEFAULT 0,
            blocked_at   TIMESTAMP,
            last_error   TEXT,
            last_fail_at TIMESTAMP,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS inbound_messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            phone       TEXT NOT NULL,
            text        TEXT NOT NULL,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_inbound_phone ON inbound_messages(phone);

        -- Incoming calls, in their own right. Deliberately not `inbound_messages`: a
        -- call carries no text, and writing it there would corrupt the record that makes
        -- ordinary inbound traffic visible in the console.
        --
        -- `phone` is the canonical form and is NULL whenever nothing usable arrived —
        -- the caller withheld the number, the network could not supply it, the
        -- subscription was not held, or what came was not a number at all. `raw_number`
        -- keeps what the network actually said, because that is the evidence and our
        -- reading of it is not. A row is written on the first `RING`, before its number
        -- exists; the number is attached when the first `+CLIP` arrives, which is why
        -- `phone` is nullable rather than merely often empty.
        CREATE TABLE IF NOT EXISTS inbound_calls (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            phone      TEXT,
            raw_number TEXT,
            started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            -- no_number    — nothing usable to attribute it by
            -- unattributed — a number arrived and no open verification wanted it
            -- confirmed    — it confirmed a verification
            outcome    TEXT NOT NULL,
            reason     TEXT,
            -- The verification this call confirmed, where it confirmed one. "Who called
            -- us" and "what did that call do" are different questions and the second one
            -- is the one an operator asks after a person says the barrier did not open.
            verification_id INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_inbound_calls_phone ON inbound_calls(phone);
        CREATE INDEX IF NOT EXISTS idx_inbound_calls_at    ON inbound_calls(started_at);

        CREATE TABLE IF NOT EXISTS inbound_parts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            phone       TEXT NOT NULL,
            ref         INTEGER NOT NULL,
            total       INTEGER NOT NULL,
            seq         INTEGER NOT NULL,
            text        TEXT NOT NULL,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(phone, ref, total, seq)
        );

        -- Which stored messages have already been handled. A message is deleted from the
        -- modem only after it has been persisted, so an interruption between the two
        -- leaves it in memory to be found by the next scan. That was rare while scanning
        -- happened once per restart; a link reopened in place scans every time, which
        -- turns a latent duplicate into a likely one.
        --
        -- New and therefore empty on upgrade: a message persisted before this shipped and
        -- still sitting in modem memory can be delivered once more, exactly as it would
        -- have been by the next restart. Pruned by age — the modem's copy is deleted on
        -- the first scan that recognises the key, so a row outlives what it guards by
        -- days.
        CREATE TABLE IF NOT EXISTS inbound_seen (
            pdu_key     TEXT PRIMARY KEY,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_inbound_seen_at ON inbound_seen(received_at);

        -- A part is identified by its message and its segment — the only two facts the
        -- gateway owns at send time. `modem_ref` is one octet the modem picks and reuses
        -- every 256 sends; as a primary key it capped this whole table at 256 rows and
        -- made every wrap overwrite an older message's record.
        --
        -- ⚠️ `_rebuild_message_parts` guards on the primary-key shape it finds in
        -- `sqlite_master`, so this statement has to be written the way that guard reads
        -- it (`_PARTS_PAIR_KEY`). Written otherwise, a fresh install rebuilds the table
        -- on every single start and nothing about it is visible.
        CREATE TABLE IF NOT EXISTS message_parts (
            message_id  INTEGER NOT NULL REFERENCES messages(id),
            seq         INTEGER NOT NULL,
            modem_ref   INTEGER NOT NULL,
            total       INTEGER NOT NULL,
            status      TEXT NOT NULL DEFAULT 'sent',
            sent_at     TIMESTAMP,
            PRIMARY KEY (message_id, seq)
        );

        CREATE INDEX IF NOT EXISTS idx_message_parts_message ON message_parts(message_id);
        -- New and load-bearing: attributing a report is a `modem_ref` scan over a table
        -- this change stops bounding at 256 rows.
        CREATE INDEX IF NOT EXISTS idx_message_parts_ref     ON message_parts(modem_ref);

        -- Every +CDS the gateway reads, recorded before anything is decided on it.
        --
        -- Append-only and evidence, not a queue: there is no operation that applies a
        -- recorded report after the fact. What it buys is that the risky rule can ship
        -- recording but not acting, and be turned on against a week of real evidence
        -- rather than an argument — and that a report the gateway drops is *kept*, so
        -- the complaint this change exists to answer ("the message the report was
        -- actually about can never be corrected") is not reproduced by the fix.
        --
        -- Only `raw_line` and `outcome` are required. Everything the parser produces is
        -- nullable by design, so a line the parser cannot read is recorded too rather
        -- than becoming the one event that leaves no trace.
        --
        -- `message_id` is deliberately NOT a foreign key: `PRAGMA foreign_keys` is ON,
        -- and a declared reference would turn every deletion of a message that has
        -- reports into a refusal — an operator surface breaking on an audit table. This
        -- is the account of what the network said; it outlives the row it names.
        CREATE TABLE IF NOT EXISTS delivery_reports (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            raw_line      TEXT NOT NULL,
            modem_ref     INTEGER,
            recipient     TEXT,
            submitted_at  TIMESTAMP,
            discharged_at TIMESTAMP,
            status_code   INTEGER,
            -- attributed | superseded | unplaced  — the three attribution outcomes;
            -- unparsable  — the parser could not read the line at all;
            -- unprocessable — it parsed, and handling it raised. Kept apart from
            --   unparsable because the two say different things about what broke.
            outcome       TEXT NOT NULL,
            reason        TEXT,            -- why, in words, for the outcomes that need it
            decided_by    TEXT,            -- sole | nearest | recency
            message_id    INTEGER,
            seq           INTEGER,
            candidates    TEXT,            -- JSON: every part whose reference matched
            -- The settings this decision was made under. The flip decision asks "how many
            -- contradictions did we record while the switch was off", and a setting read a
            -- week later cannot answer for a decision made before it changed.
            window_hours  INTEGER,
            strict        INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_delivery_reports_at  ON delivery_reports(received_at);
        CREATE INDEX IF NOT EXISTS idx_delivery_reports_ref ON delivery_reports(modem_ref);

        -- A verification: who asked, which number, the secret, the deadline, the state.
        --
        -- `code` is nullable and is *emptied* the moment the verification stops being
        -- confirmable — confirmed, expired, or out of attempts. The row holds a
        -- subscriber's number next to a live secret, and the window in which that secret
        -- is useful is exactly the window in which the row is pending.
        --
        -- `route` is the rung the consumer selected, and is NULL until it selects one:
        -- nothing is placed, composed or charged before that. `confirmed_by` is the
        -- method that actually proved it, which is not always the route — an application
        -- whose stakes do not tolerate a caller number alone must be able to see what it
        -- got rather than assume the strongest.
        CREATE TABLE IF NOT EXISTS verifications (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            app_id       TEXT NOT NULL,
            phone        TEXT NOT NULL,
            code         TEXT,
            -- pending | confirmed | failed | expired
            status       TEXT NOT NULL DEFAULT 'pending',
            attempts     INTEGER NOT NULL DEFAULT 0,
            route        TEXT,
            confirmed_by TEXT,
            reason       TEXT,
            created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at   TIMESTAMP NOT NULL,
            confirmed_at TIMESTAMP,
            -- Whether the owning application has already been told this verification
            -- reached a terminal state. One notification per verification, and the
            -- sweep must not announce the same expiry on its next pass.
            notified     INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_verifications_phone  ON verifications(phone);
        CREATE INDEX IF NOT EXISTS idx_verifications_status ON verifications(status);

        -- Per rung attempted, not per verification: a ladder has more than one. A
        -- verification that tried Telegram and then placed a call holds two vendor
        -- identifiers and two costs against one code, and a column on the row above
        -- would answer "what did this person's login cost" by overwriting half of it.
        CREATE TABLE IF NOT EXISTS verification_rungs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            verification_id INTEGER NOT NULL,
            route           TEXT NOT NULL,
            vendor_ref      TEXT,
            cost            REAL,
            refunded        INTEGER NOT NULL DEFAULT 0,
            outcome         TEXT,
            reason          TEXT,
            started_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_verification_rungs_v
            ON verification_rungs(verification_id);

        -- What the routing rule costs, one row per item it refused. A rule set during an
        -- outage outlives the outage: when the operator starts accepting traffic again
        -- the rule stays in force, the applications that do not send codes stay refused,
        -- and without this there is nothing on any screen to say so.
        --
        -- A row per refusal rather than a running total, because the question the count
        -- exists to answer is not only "how many" but "how many since this entry came
        -- into force", and a total cannot be asked that afterwards. At the measured rate
        -- — about seventy a month — a row each costs nothing worth saving.
        --
        -- No retention sweep, deliberately, and it is the one table here without one:
        -- the row holds an operator, an application and a route and no subscriber data,
        -- so nothing here expires for privacy. Pruning it for size would answer "this
        -- rule has cost nothing lately" about a rule that has been refusing traffic for
        -- a year, which is the question the table exists to answer correctly.
        --
        -- `operator_key` is the folded spelling (NFKC + casefold, done in Python — the
        -- shipped SQLite's `upper()`/`LIKE` are ASCII-only and leave Cyrillic untouched),
        -- and `operator` is the spelling as it was seen. Grouping happens on the key, so
        -- МегаФон and МЕГАФОН are one operator and not two half-sized counts.
        CREATE TABLE IF NOT EXISTS route_refusals (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            operator_key TEXT NOT NULL,
            operator     TEXT NOT NULL,
            app_id       TEXT NOT NULL,
            route        TEXT NOT NULL,
            refused_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_route_refusals_op
            ON route_refusals(operator_key, refused_at);

        -- Since when each entry of the routing rule has been in force, so that a rule
        -- nobody has revisited can say so. Reconciled against the rule on every review
        -- tick rather than written by a save hook: a rule can change by paths that never
        -- pass through the console — a restored database, a seeded environment, another
        -- process — and a record kept only by the console would date those to never.
        --
        -- `reviewed_at` is when the operator was last told this entry is stale, not when
        -- a human looked at it. Nothing here can know the second one; what it buys is
        -- that a stale rule is reported once per review period instead of once per tick.
        CREATE TABLE IF NOT EXISTS route_rule_entries (
            operator_key   TEXT PRIMARY KEY,
            operator       TEXT NOT NULL,
            routes         TEXT NOT NULL,
            in_force_since TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_at    TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS notify_refs (
            message_id  INTEGER PRIMARY KEY,
            phone       TEXT NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS phone_ranges (
            prefix6      TEXT PRIMARY KEY,
            allocated    INTEGER NOT NULL,
            operator     TEXT,
            region       TEXT,
            operator_inn TEXT,
            checked_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS number_operators (
            phone      TEXT PRIMARY KEY,
            operator   TEXT,
            region     TEXT,
            checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS settings (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Added after `messages` shipped, so it comes as an ALTER rather than a column in
    # the CREATE above. Links an admin re-send to the message it replaces: the delivery
    # webhook fires later, from the modem loops, where the resend handler's context is
    # long gone — the link has to be persisted to survive to that point.
    await _add_column_if_missing(db, "messages", "resent_from", "INTEGER REFERENCES messages(id)")

    # Retry state. Persisted rather than kept on the in-memory queue entry so a pending
    # retry survives a restart — which is also what lets the scheduler pick up messages
    # a restart stranded in `pending`.
    #
    # `next_attempt_at` doubles as the claim marker: it is cleared the moment a message
    # is handed to the modem and only set again by a clean decision to try later. A
    # message whose process died mid-send therefore has no schedule and is never
    # resent — a duplicate on someone's handset is worse than a message an operator
    # has to push manually.
    await _add_column_if_missing(db, "messages", "attempts", "INTEGER NOT NULL DEFAULT 0")
    await _add_column_if_missing(db, "messages", "next_attempt_at", "TIMESTAMP")
    # Kept apart from `error`, which still means "why this message finally failed".
    # Overloading `error` on a message that is still `pending` would make a consumer
    # reading `error != null` see failures that never happened.
    await _add_column_if_missing(db, "messages", "last_attempt_error", "TEXT")

    # Whether `delivered` was reported or concluded. Some networks send a status report for
    # one segment of a multipart message and none for the others, so waiting for every part
    # means waiting for something that never comes — and the expiry sweep then reports a
    # delivery as a failure. The sweep completes those, and this records that it did.
    #
    # Kept apart from the status rather than folded into it: an operator meeting "the
    # customer says they never got it" needs to know whether the network said so or the
    # gateway worked it out. A record that cannot answer that is confidently wrong, which is
    # worse than the `expired` it replaces — nobody trusted `expired`.
    await _add_column_if_missing(db, "messages", "delivery_inferred", "INTEGER NOT NULL DEFAULT 0")

    # What the routing rule answered for this message, and the operator it was answered
    # for. Written by the sender at the moment it decides, which is the only moment both
    # facts are true together: a later lookup fills `number_operators` in, and reading
    # the operator back from there would say this message was routed for МТС when it was
    # routed for nobody.
    #
    # 🔴 **The pair is what makes "routed without a known operator" countable, and the
    # pair is why it is two columns rather than one.** `routed_operator IS NULL` alone
    # cannot tell an unresolved operator from a row that predates this migration or from
    # a message the sender never reached; `routed_route IS NOT NULL AND routed_operator
    # IS NULL` names exactly the case the requirement asks to be able to count. Both
    # NULL for every existing row, which is the truth about them: nothing recorded.
    #
    # Additive and reversible by deploying the old code.
    await _add_column_if_missing(db, "messages", "routed_route", "TEXT")
    await _add_column_if_missing(db, "messages", "routed_operator", "TEXT")

    # Which verification this message carries the code of, and NULL for the ordinary
    # traffic that is all of it today. Three separate mechanisms read it and none of them
    # can be told the fact any other way:
    #
    # - the sender, which otherwise asks the routing rule afresh and refuses anything
    #   whose first rung is not the modem — including a verification the ladder placed on
    #   the modem deliberately, *behind* a paid rung;
    # - the delivery webhook, which otherwise pushes a raw message id to an application
    #   that only ever asked about a verification;
    # - the verification itself, which takes this message's failure as its own.
    #
    # In the row rather than in the queued item on purpose: the restart resume path
    # re-enqueues from these rows, so an ownership carried only in memory would be
    # dropped by the one path that re-sends.
    #
    # Additive, NULL for every existing row — which is the truth about them — and
    # reversible by deploying the old code.
    await _add_column_if_missing(
        db, "messages", "verification_id", "INTEGER REFERENCES verifications(id)")

    # Whether this application may have a verification carried by a **paid** route. An
    # ALTER rather than a column in the CREATE above, and the distinction is the whole
    # guarantee: `DEFAULT 0` on a new column applies to every row that already exists, so
    # the estates that already have the defect — four applications, three of which send
    # no codes at all — come out of the migration switched off rather than entitled.
    #
    # Additive and therefore reversible by deploying the old code: nothing before this
    # change reads the column, and SQLite carries an unread column at no cost. The column
    # is never dropped on the way back, because dropping it would silently revoke an
    # operator's decision the next time the new code is deployed.
    #
    # Separate from `is_active`, which answers whether the application may talk to this
    # gateway at all. This one answers who is allowed to spend, and the two are refused
    # by different people for different reasons.
    await _add_column_if_missing(db, "apps", "may_spend", "INTEGER NOT NULL DEFAULT 0")

    # Which operator this verification's ladder was routed for — or `?`, the rule's own
    # word for one that could not be resolved. Task 6.8: the norm asks for "routed without
    # a known operator" to be **countable rather than invisible**, and on the paid rungs
    # there was nothing to count it with. A verification carried by `tg_gateway` or
    # `flash_call` creates no `messages` row, so the pair on that table
    # (`routed_route`/`routed_operator`) answers only for what the modem sent.
    #
    # A word rather than a NULL for the unknown case, because a NULL cannot tell "routed
    # for nobody" from "written before this column existed" — and the count the rule is
    # reviewed by would then quietly include every row older than the change. NULL keeps
    # exactly that meaning here: not recorded.
    #
    # Additive and therefore reversible by deploying the old code: nothing before this
    # change reads it, and SQLite carries an unread column at no cost.
    await _add_column_if_missing(db, "verifications", "routed_operator", "TEXT")

    # Runs after the base script, which is what makes the index handling above necessary,
    # and outside `executescript`, which is what makes it atomic.
    await _rebuild_message_parts(db)

    await db.execute(
        """
        INSERT OR IGNORE INTO apps (id, token, description, is_active)
        VALUES ('admin', 'admin-internal-' || hex(randomblob(8)), 'Admin UI replies', 0)
        """
    )

    await db.execute(
        """
        INSERT OR IGNORE INTO apps (id, token, description, is_active)
        VALUES ('telegram', 'telegram-internal-' || hex(randomblob(8)), 'Telegram replies', 0)
        """
    )

    await db.commit()
