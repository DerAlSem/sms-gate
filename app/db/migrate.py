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
