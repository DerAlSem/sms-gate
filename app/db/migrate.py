from app.db.connection import get_db


async def _add_column_if_missing(db, table: str, column: str, decl: str) -> None:
    """ALTER TABLE ADD COLUMN, skipped when the column is already there — SQLite has no
    `ADD COLUMN IF NOT EXISTS`, and run_migrations() runs on every start."""
    async with db.execute(f"PRAGMA table_info({table})") as cursor:
        existing = {row[1] async for row in cursor}
    if column not in existing:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


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

        CREATE TABLE IF NOT EXISTS message_parts (
            modem_ref   INTEGER PRIMARY KEY,
            message_id  INTEGER NOT NULL REFERENCES messages(id),
            seq         INTEGER NOT NULL,
            total       INTEGER NOT NULL,
            status      TEXT NOT NULL DEFAULT 'sent'
        );

        CREATE INDEX IF NOT EXISTS idx_message_parts_message ON message_parts(message_id);

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
