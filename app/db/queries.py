from typing import Any
import aiosqlite
from app.db.connection import get_db


async def get_app_by_token(token: str) -> aiosqlite.Row | None:
    db = await get_db()
    async with db.execute(
        "SELECT id, is_active FROM apps WHERE token = ?", (token,)
    ) as cursor:
        return await cursor.fetchone()


async def create_message(app_id: str, phone: str, text: str) -> int:
    db = await get_db()
    async with db.execute(
        "INSERT INTO messages (app_id, phone, text) VALUES (?, ?, ?)",
        (app_id, phone, text),
    ) as cursor:
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def get_message(message_id: int, app_id: str) -> aiosqlite.Row | None:
    db = await get_db()
    async with db.execute(
        """
        SELECT id, phone, text, status, created_at, sent_at, delivered_at, error
        FROM messages
        WHERE id = ? AND app_id = ?
        """,
        (message_id, app_id),
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


async def find_message_by_modem_ref(modem_ref: int) -> aiosqlite.Row | None:
    """Most recent message for modem_ref still awaiting/expired (eligible for late report)."""
    db = await get_db()
    async with db.execute(
        """
        SELECT id, status, phone FROM messages
        WHERE modem_ref = ? AND status IN ('sent', 'expired')
        ORDER BY sent_at DESC
        LIMIT 1
        """,
        (modem_ref,),
    ) as cursor:
        return await cursor.fetchone()


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


async def expire_stale_messages(timeout_seconds: int) -> None:
    db = await get_db()
    await db.execute(
        """
        UPDATE messages
        SET status = 'expired'
        WHERE status = 'sent'
          AND sent_at < datetime('now', ? || ' seconds')
        """,
        (f"-{timeout_seconds}",),
    )
    await db.commit()


async def save_inbound(phone: str, text: str) -> int:
    db = await get_db()
    async with db.execute(
        "INSERT INTO inbound_messages (phone, text) VALUES (?, ?)",
        (phone, text),
    ) as cursor:
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


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
