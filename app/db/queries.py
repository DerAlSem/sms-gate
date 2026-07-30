from typing import Any
import aiosqlite
from app.db.connection import get_db


async def add_notify_ref(message_id: int, phone: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO notify_refs (message_id, phone) VALUES (?, ?)",
        (message_id, phone),
    )
    await db.commit()


async def find_notify_ref(message_id: int) -> str | None:
    db = await get_db()
    async with db.execute(
        "SELECT phone FROM notify_refs WHERE message_id = ?", (message_id,)
    ) as cursor:
        row = await cursor.fetchone()
        return row["phone"] if row else None


async def get_app_by_token(token: str) -> aiosqlite.Row | None:
    db = await get_db()
    async with db.execute(
        "SELECT id, is_active FROM apps WHERE token = ?", (token,)
    ) as cursor:
        return await cursor.fetchone()


async def create_message(
    app_id: str, phone: str, text: str, resent_from: int | None = None
) -> int:
    db = await get_db()
    async with db.execute(
        # `next_attempt_at` is set here, a minute out, so a message the in-memory queue
        # loses to a restart is still recoverable. In the normal path the sender claims
        # it long before then and clears the time.
        """
        INSERT INTO messages (app_id, phone, text, resent_from, next_attempt_at)
        VALUES (?, ?, ?, ?, datetime('now', '+60 seconds'))
        """,
        (app_id, phone, text, resent_from),
    ) as cursor:
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def get_message(message_id: int, app_id: str) -> aiosqlite.Row | None:
    db = await get_db()
    async with db.execute(
        """
        SELECT id, phone, text, status, created_at, sent_at, delivered_at, error,
               attempts, delivery_inferred
        FROM messages
        WHERE id = ? AND app_id = ?
        """,
        (message_id, app_id),
    ) as cursor:
        return await cursor.fetchone()


async def get_message_any(message_id: int) -> aiosqlite.Row | None:
    """Message by id without the app_id scope — for the admin UI, which is not
    bound to a single application (unlike the public API's get_message)."""
    db = await get_db()
    async with db.execute(
        "SELECT id, app_id, phone, text, status FROM messages WHERE id = ?",
        (message_id,),
    ) as cursor:
        return await cursor.fetchone()


async def get_message_delivery_context(message_id: int) -> aiosqlite.Row | None:
    """What the delivery webhook needs about a message: who owns it, and whether it
    replaces an earlier one."""
    db = await get_db()
    async with db.execute(
        "SELECT id, app_id, resent_from FROM messages WHERE id = ?",
        (message_id,),
    ) as cursor:
        return await cursor.fetchone()


async def set_message_sent(message_id: int, modem_ref: int) -> None:
    db = await get_db()
    await db.execute(
        """
        UPDATE messages
        SET status = 'sent', modem_ref = ?, sent_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (modem_ref, message_id),
    )
    await db.commit()


async def set_message_failed(message_id: int, error: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE messages SET status = 'failed', error = ? WHERE id = ?",
        (error, message_id),
    )
    await db.commit()


async def begin_message_attempt(message_id: int) -> int:
    """Claim a message for transmission and return its attempt number.

    Runs before a single byte reaches the modem. Clearing `next_attempt_at` is what
    makes a half-finished attempt safe: a process killed between here and the modem's
    acknowledgement leaves the message with no schedule, so nothing ever re-sends it.
    Only a clean decision to try later puts a time back.
    """
    db = await get_db()
    await db.execute(
        """
        UPDATE messages
        SET attempts = attempts + 1, next_attempt_at = NULL
        WHERE id = ?
        """,
        (message_id,),
    )
    await db.commit()
    async with db.execute(
        "SELECT attempts FROM messages WHERE id = ?", (message_id,)
    ) as cursor:
        row = await cursor.fetchone()
    return row["attempts"] if row else 0


async def schedule_message_retry(
    message_id: int, delay_seconds: int, error: str
) -> None:
    """Put a message back on the clock instead of failing it.

    Status stays `pending`, and the reason goes to `last_attempt_error` rather than
    `error` — the message is still on its way, so a consumer reading `error` must not
    be told it failed.
    """
    db = await get_db()
    await db.execute(
        """
        UPDATE messages
        SET last_attempt_error = ?,
            next_attempt_at = datetime('now', ? || ' seconds')
        WHERE id = ?
        """,
        (error, f"{int(delay_seconds):+d}", message_id),
    )
    await db.commit()


async def hold_message_after_attempt(
    message_id: int, delay_seconds: int, error: str
) -> None:
    """Undo a claimed attempt and put the message back on the clock.

    `begin_message_attempt` counts the attempt and clears the schedule before a single
    byte goes out, deliberately: a message with no schedule is never re-queued, which is
    what makes a half-finished attempt safe. That leaves no way to decline *after* the
    claim without both spending a chance and stranding the message — an attempt counted
    against it and no `next_attempt_at` for the scheduler to find, so it sits `pending`
    until its deadline having never been offered to the modem again.

    This is the narrow exit for the one case that needs it: the link was found gone after
    the claim and before any byte was written. Holding costs a message time, never
    chances.
    """
    db = await get_db()
    await db.execute(
        """
        UPDATE messages
        SET attempts = MAX(attempts - 1, 0),
            last_attempt_error = ?,
            next_attempt_at = datetime('now', ? || ' seconds')
        WHERE id = ?
        """,
        (error, f"{int(delay_seconds):+d}", message_id),
    )
    await db.commit()


async def due_pending_messages(
    max_age_seconds: int, limit: int = 20
) -> list[aiosqlite.Row]:
    """Scheduled `pending` messages whose time has come.

    Bounded twice on purpose. `max_age_seconds` stops the gateway ever resurrecting an
    old message — a payment link sent out days late is worse than one never sent — and
    `limit` stops a single tick stuffing the queue ahead of live traffic.

    A message currently being transmitted has no `next_attempt_at`, so it cannot be
    selected here however long the modem takes.
    """
    db = await get_db()
    async with db.execute(
        """
        SELECT id, app_id, phone, text, attempts
        FROM messages
        WHERE status = 'pending'
          AND next_attempt_at IS NOT NULL
          AND next_attempt_at <= datetime('now')
          AND created_at > datetime('now', ? || ' seconds')
        ORDER BY next_attempt_at
        LIMIT ?
        """,
        (f"-{int(max_age_seconds)}", int(limit)),
    ) as cursor:
        return await cursor.fetchall()


async def stale_pending_messages(max_age_seconds: int) -> list[aiosqlite.Row]:
    """`pending` messages too old to still be on their way.

    Nothing else sweeps `pending`: `expire_stale_messages` only covers `sent`. Without
    this a message whose attempt died mid-flight — or one the scheduler declines to
    resurrect — would sit `pending` forever, and the app polling it would never see a
    terminal status.
    """
    db = await get_db()
    async with db.execute(
        """
        SELECT id, phone, last_attempt_error
        FROM messages
        WHERE status = 'pending'
          AND created_at <= datetime('now', ? || ' seconds')
        ORDER BY id
        """,
        (f"-{int(max_age_seconds)}",),
    ) as cursor:
        return await cursor.fetchall()


async def add_message_part(message_id: int, modem_ref: int, seq: int, total: int) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO message_parts (modem_ref, message_id, seq, total) "
        "VALUES (?, ?, ?, ?)",
        (modem_ref, message_id, seq, total),
    )
    await db.commit()


async def find_message_by_part_ref(modem_ref: int) -> aiosqlite.Row | None:
    """Part + owning message for a +CDS ref, only while the message is still
    awaiting/expired (eligible for a delivery report)."""
    db = await get_db()
    async with db.execute(
        """
        SELECT p.message_id, p.seq, m.status AS msg_status, m.phone
        FROM message_parts p
        JOIN messages m ON m.id = p.message_id
        WHERE p.modem_ref = ? AND m.status IN ('sent', 'expired')
        """,
        (modem_ref,),
    ) as cursor:
        return await cursor.fetchone()


async def set_part_delivered(modem_ref: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE message_parts SET status = 'delivered' WHERE modem_ref = ?",
        (modem_ref,),
    )
    await db.commit()


async def set_part_failed(modem_ref: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE message_parts SET status = 'failed' WHERE modem_ref = ?",
        (modem_ref,),
    )
    await db.commit()


async def message_parts_all_delivered(message_id: int) -> bool:
    db = await get_db()
    async with db.execute(
        "SELECT 1 FROM message_parts WHERE message_id = ? AND status != 'delivered' LIMIT 1",
        (message_id,),
    ) as cursor:
        return await cursor.fetchone() is None


async def set_message_delivered(message_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE messages SET status = 'delivered', delivered_at = CURRENT_TIMESTAMP WHERE id = ?",
        (message_id,),
    )
    await db.commit()


async def set_message_delivery_failed(message_id: int, error: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE messages SET status = 'failed', error = ? WHERE id = ?",
        (error, message_id),
    )
    await db.commit()


async def has_delivered_to(phone: str) -> bool:
    db = await get_db()
    async with db.execute(
        "SELECT 1 FROM messages WHERE phone = ? AND status = 'delivered' LIMIT 1",
        (phone,),
    ) as cursor:
        return await cursor.fetchone() is not None


async def record_permanent_fail(phone: str, error: str, threshold: int) -> None:
    """Increment permanent-fail counter; block when count crosses threshold.
    No-op if phone has any successful delivery on record."""
    if await has_delivered_to(phone):
        return
    db = await get_db()
    await db.execute(
        """
        INSERT INTO bad_numbers (phone, fail_count, last_error, last_fail_at)
        VALUES (?, 1, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(phone) DO UPDATE SET
            fail_count = fail_count + 1,
            last_error = excluded.last_error,
            last_fail_at = CURRENT_TIMESTAMP
        """,
        (phone, error),
    )
    await db.execute(
        """
        UPDATE bad_numbers
        SET blocked_at = CURRENT_TIMESTAMP
        WHERE phone = ? AND blocked_at IS NULL AND fail_count >= ?
        """,
        (phone, threshold),
    )
    await db.commit()


async def is_phone_blocked(phone: str) -> bool:
    db = await get_db()
    async with db.execute(
        "SELECT 1 FROM bad_numbers WHERE phone = ? AND blocked_at IS NOT NULL LIMIT 1",
        (phone,),
    ) as cursor:
        return await cursor.fetchone() is not None


async def list_bad_numbers() -> list[aiosqlite.Row]:
    db = await get_db()
    async with db.execute(
        """
        SELECT phone, fail_count, blocked_at, last_error, last_fail_at, created_at
        FROM bad_numbers
        ORDER BY blocked_at IS NULL, blocked_at DESC, last_fail_at DESC
        """
    ) as cursor:
        return list(await cursor.fetchall())


async def unblock_phone(phone: str) -> None:
    db = await get_db()
    await db.execute("DELETE FROM bad_numbers WHERE phone = ?", (phone,))
    await db.commit()


async def list_messages(
    status: str | None,
    phone: str | None,
    limit: int,
    offset: int,
) -> list[aiosqlite.Row]:
    where: list[str] = []
    params: list[Any] = []
    if status:
        where.append("m.status = ?")
        params.append(status)
    if phone:
        where.append("m.phone LIKE ?")
        params.append(f"%{phone}%")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.extend([limit, offset])
    db = await get_db()
    async with db.execute(
        f"""
        SELECT m.id, m.app_id, m.phone, m.text, m.status, m.modem_ref,
               m.created_at, m.sent_at, m.delivered_at, m.error,
               m.attempts, m.last_attempt_error, m.next_attempt_at,
               o.operator, o.region
        FROM messages m
        LEFT JOIN number_operators o ON o.phone = m.phone
        {where_sql}
        ORDER BY m.id DESC
        LIMIT ? OFFSET ?
        """,
        params,
    ) as cursor:
        return list(await cursor.fetchall())


async def count_messages(status: str | None, phone: str | None) -> int:
    where: list[str] = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status)
    if phone:
        where.append("phone LIKE ?")
        params.append(f"%{phone}%")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    db = await get_db()
    async with db.execute(
        f"SELECT COUNT(*) FROM messages {where_sql}", params
    ) as cursor:
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def status_counts() -> dict[str, int]:
    db = await get_db()
    async with db.execute(
        "SELECT status, COUNT(*) FROM messages GROUP BY status"
    ) as cursor:
        return {row[0]: int(row[1]) for row in await cursor.fetchall()}


async def daily_counts(days: int) -> list[aiosqlite.Row]:
    db = await get_db()
    async with db.execute(
        """
        SELECT DATE(created_at, '+3 hours') AS day, status, COUNT(*) AS n
        FROM messages
        WHERE created_at > datetime('now', ? || ' days')
        GROUP BY day, status
        ORDER BY day DESC
        """,
        (f"-{days}",),
    ) as cursor:
        return list(await cursor.fetchall())


async def complete_partly_reported_messages(timeout_seconds: int) -> list[int]:
    """Complete timed-out messages the network partly confirmed; return the ids affected.

    Runs *before* the expiry sweep, and that ordering is the whole mechanism: this moves
    them out of `sent`, so the sweep below never sees them and needs no change of its own.

    The condition is deliberately narrow. At least one part reported delivered, and no part
    reported failed. A message with nothing confirmed is not touched — silence about
    everything is absence of evidence, and turning it into a delivery would trade a wrong
    `expired` for a wrong `delivered`, which is the worse direction. A message with a failed
    part is not touched either; that path already has an answer and is not a timeout
    question.

    What justifies it is the asymmetry between the two silences. A network that reported one
    segment took the message and handed part of it over. Saying nothing about the rest is
    what this network does about the rest — a failure it would report. So the timeout is
    evidence that the remaining reports are not coming, not evidence that the message was
    not delivered.
    """
    db = await get_db()
    async with db.execute(
        """
        UPDATE messages
        SET status = 'delivered',
            delivered_at = CURRENT_TIMESTAMP,
            delivery_inferred = 1
        WHERE status = 'sent'
          AND sent_at < datetime('now', ? || ' seconds')
          AND EXISTS (
                SELECT 1 FROM message_parts p
                WHERE p.message_id = messages.id AND p.status = 'delivered'
          )
          AND NOT EXISTS (
                SELECT 1 FROM message_parts p
                WHERE p.message_id = messages.id AND p.status = 'failed'
          )
        RETURNING id
        """,
        (f"-{timeout_seconds}",),
    ) as cursor:
        ids = [row[0] for row in await cursor.fetchall()]
    await db.commit()
    return ids


async def expire_stale_messages(timeout_seconds: int) -> list[int]:
    """Sweep timed-out messages to 'expired'; return the ids affected.

    RETURNING rather than a bare UPDATE: this is the one bulk status writer, and the
    delivery webhook needs a row per message. Without the ids the whole batch would
    change status silently.
    """
    db = await get_db()
    async with db.execute(
        """
        UPDATE messages
        SET status = 'expired'
        WHERE status = 'sent'
          AND sent_at < datetime('now', ? || ' seconds')
        RETURNING id
        """,
        (f"-{timeout_seconds}",),
    ) as cursor:
        ids = [row[0] for row in await cursor.fetchall()]
    await db.commit()
    return ids


async def save_inbound(phone: str, text: str) -> int:
    db = await get_db()
    async with db.execute(
        "INSERT INTO inbound_messages (phone, text) VALUES (?, ?)",
        (phone, text),
    ) as cursor:
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def inbound_pdu_seen(pdu_key: str) -> bool:
    """Whether this stored message has already been persisted by an earlier read."""
    db = await get_db()
    async with db.execute(
        "SELECT 1 FROM inbound_seen WHERE pdu_key = ?", (pdu_key,)
    ) as cursor:
        return await cursor.fetchone() is not None


async def mark_inbound_pdu_seen(pdu_key: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO inbound_seen (pdu_key) VALUES (?)", (pdu_key,)
    )
    await db.commit()


async def prune_inbound_seen(max_age_seconds: int) -> int:
    """Drop keys older than `max_age_seconds`, and report how many went.

    The key guards against re-reading a copy still in modem memory, and that copy is
    deleted by the first scan that recognises the key — so a row that has outlived the
    retention has nothing left to guard.
    """
    db = await get_db()
    async with db.execute(
        "DELETE FROM inbound_seen WHERE received_at < datetime('now', ?) RETURNING pdu_key",
        (f"-{max_age_seconds} seconds",),
    ) as cursor:
        gone = len(await cursor.fetchall())
    await db.commit()
    return gone


async def list_inbound(
    phone: str | None, limit: int, offset: int
) -> list[aiosqlite.Row]:
    where: list[str] = []
    params: list[Any] = []
    if phone:
        where.append("phone LIKE ?")
        params.append(f"%{phone}%")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.extend([limit, offset])
    db = await get_db()
    async with db.execute(
        f"""
        SELECT id, phone, text, received_at FROM inbound_messages
        {where_sql}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        params,
    ) as cursor:
        return list(await cursor.fetchall())


async def count_inbound(phone: str | None) -> int:
    where_sql = "WHERE phone LIKE ?" if phone else ""
    params = [f"%{phone}%"] if phone else []
    db = await get_db()
    async with db.execute(
        f"SELECT COUNT(*) FROM inbound_messages {where_sql}", params
    ) as cursor:
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def delete_inbound(message_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM inbound_messages WHERE id = ?", (message_id,))
    await db.commit()


async def dialog_phones(limit: int = 100) -> list[aiosqlite.Row]:
    """List of phones with last activity (in or out), sorted by recency."""
    db = await get_db()
    async with db.execute(
        """
        SELECT phone, MAX(ts) AS last_ts, SUM(in_n) AS in_n, SUM(out_n) AS out_n FROM (
            SELECT phone, COALESCE(received_at, '') AS ts, 1 AS in_n, 0 AS out_n
              FROM inbound_messages
            UNION ALL
            SELECT phone, COALESCE(sent_at, created_at) AS ts, 0 AS in_n, 1 AS out_n
              FROM messages
        ) GROUP BY phone
        ORDER BY last_ts DESC
        LIMIT ?
        """,
        (limit,),
    ) as cursor:
        return list(await cursor.fetchall())


async def get_number_operator(phone: str) -> aiosqlite.Row | None:
    db = await get_db()
    async with db.execute(
        "SELECT phone, operator, region, checked_at "
        "FROM number_operators WHERE phone = ?",
        (phone,),
    ) as cursor:
        return await cursor.fetchone()


async def list_unresolved_numbers() -> list[aiosqlite.Row]:
    """Distinct phone numbers that have no number_operators row, oldest message
    first (FIFO). msisdn10 is substr(phone,3,10), used to drive the lookup."""
    db = await get_db()
    async with db.execute(
        """
        SELECT m.phone AS phone,
               substr(m.phone, 3, 10) AS msisdn10,
               MIN(m.id) AS first_id
        FROM messages m
        WHERE m.phone LIKE '+7%'
          AND NOT EXISTS (
            SELECT 1 FROM number_operators o WHERE o.phone = m.phone
        )
        GROUP BY m.phone
        ORDER BY first_id ASC
        """
    ) as cursor:
        return list(await cursor.fetchall())


async def save_number_operator(
    phone: str,
    operator: str | None,
    region: str | None,
) -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO number_operators (phone, operator, region, checked_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(phone) DO UPDATE SET
            operator = excluded.operator,
            region = excluded.region,
            checked_at = CURRENT_TIMESTAMP
        """,
        (phone, operator, region),
    )
    await db.commit()


async def list_number_operators() -> list[aiosqlite.Row]:
    db = await get_db()
    async with db.execute(
        """
        SELECT phone, operator, region, checked_at
        FROM number_operators
        ORDER BY checked_at DESC
        """
    ) as cursor:
        return list(await cursor.fetchall())


async def dialog_for(phone: str) -> list[aiosqlite.Row]:
    """Combined timeline of inbound + outbound for a phone, oldest first."""
    db = await get_db()
    async with db.execute(
        """
        SELECT 'in' AS direction, id, text, received_at AS ts,
               NULL AS status, NULL AS error
          FROM inbound_messages WHERE phone = ?
        UNION ALL
        SELECT 'out' AS direction, id, text, COALESCE(sent_at, created_at) AS ts,
               status, error
          FROM messages WHERE phone = ?
        ORDER BY ts ASC, id ASC
        """,
        (phone, phone),
    ) as cursor:
        return list(await cursor.fetchall())


async def save_inbound_part(
    phone: str, ref: int, total: int, seq: int, text: str
) -> None:
    """Save a multipart-SMS part. Duplicate (re-delivery) — ignored."""
    db = await get_db()
    await db.execute(
        """
        INSERT INTO inbound_parts (phone, ref, total, seq, text)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(phone, ref, total, seq) DO NOTHING
        """,
        (phone, ref, total, seq, text),
    )
    await db.commit()


async def get_inbound_parts(phone: str, ref: int, total: int) -> list[aiosqlite.Row]:
    db = await get_db()
    async with db.execute(
        """
        SELECT seq, text FROM inbound_parts
        WHERE phone = ? AND ref = ? AND total = ?
        ORDER BY seq
        """,
        (phone, ref, total),
    ) as cursor:
        return list(await cursor.fetchall())


async def delete_inbound_parts(phone: str, ref: int, total: int) -> int:
    """Delete a group of parts. Returns the number of deleted rows — this is the «claim»:
    only the caller whose DELETE actually deleted rows may save the assembled message."""
    db = await get_db()
    async with db.execute(
        "DELETE FROM inbound_parts WHERE phone = ? AND ref = ? AND total = ?",
        (phone, ref, total),
    ) as cursor:
        deleted = cursor.rowcount
    await db.commit()
    return deleted


async def stale_part_groups(max_age_seconds: int) -> list[aiosqlite.Row]:
    """Part groups that have not received any new piece for a long time (incomplete assemblies)."""
    db = await get_db()
    async with db.execute(
        """
        SELECT phone, ref, total FROM inbound_parts
        GROUP BY phone, ref, total
        HAVING MAX(received_at) < datetime('now', ? || ' seconds')
        """,
        (f"-{max_age_seconds}",),
    ) as cursor:
        return list(await cursor.fetchall())


async def list_apps() -> list[aiosqlite.Row]:
    db = await get_db()
    async with db.execute(
        "SELECT id, token, description, is_active, created_at FROM apps ORDER BY created_at DESC, id"
    ) as cursor:
        return list(await cursor.fetchall())


async def create_app(app_id: str, token: str, description: str = "") -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO apps (id, token, description, is_active) VALUES (?, ?, ?, 1)",
        (app_id, token, description),
    )
    await db.commit()


async def set_app_active(app_id: str, active: bool) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE apps SET is_active = ? WHERE id = ?", (1 if active else 0, app_id)
    )
    await db.commit()


async def app_message_count(app_id: str) -> int:
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM messages WHERE app_id = ?", (app_id,)
    ) as cursor:
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def delete_app(app_id: str) -> None:
    db = await get_db()
    await db.execute("DELETE FROM apps WHERE id = ?", (app_id,))
    await db.commit()
