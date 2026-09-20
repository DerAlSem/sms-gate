import json
from typing import Any
import aiosqlite
from app import periods
from app.db.connection import get_db

# Statuses that owe nothing further. `expired` is deliberately absent: a report can
# still arrive for it and correct it to `delivered` while the part it names is inside
# `delivery_report_max_age_hours` (see `parts_matching_ref` and
# `app.modem.attribution`), which is one of the two reasons it is not deletable either.
TERMINAL_STATUSES = ("delivered", "failed")


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
    """Record a segment the modem accepted, under its own identity.

    A plain INSERT, not `INSERT OR REPLACE`. The old form was keyed on `modem_ref` — one
    octet the modem reuses every 256 sends — so a wrap did not add a row, it took the row
    of whichever message held that reference before, and that message lost every trace of
    what it put on the wire.

    On the new key a conflict is a fault, not a collision to resolve: the same segment of
    the same message cannot legitimately be accepted twice. It is raised rather than
    swallowed, and the caller decides — `is_retryable(..., already_sent=…)` refuses a
    retry once any part has been accepted, so this can only fire after the network already
    took the segment.

    `sent_at` is the segment's own submit time. The message's `sent_at` dates the message,
    which is set once on the first part; a later segment is not that time, and attribution
    measures a part's age against its own clock.
    """
    db = await get_db()
    await db.execute(
        "INSERT INTO message_parts (message_id, seq, modem_ref, total, sent_at) "
        "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
        (message_id, seq, modem_ref, total),
    )
    await db.commit()


async def record_delivery_report(
    *,
    raw_line: str,
    outcome: str,
    reason: str | None = None,
    modem_ref: int | None = None,
    recipient: str | None = None,
    submitted_at: str | None = None,
    discharged_at: str | None = None,
    status_code: int | None = None,
    decided_by: str | None = None,
    message_id: int | None = None,
    seq: int | None = None,
    candidates: list | None = None,
    window_hours: int | None = None,
    strict: bool | None = None,
) -> int:
    """Write down one `+CDS`, whatever became of it.

    Only the raw line and the outcome are required: a line the parser cannot read has
    nothing else, and it is precisely the line that must not become the one event leaving
    no trace.

    `candidates` records **every** part whose reference matched, each with its own
    outcome — not only the winner. "How many reports did we contradict" is unanswerable
    from a table that stores the choice and forgets the alternatives.
    """
    db = await get_db()
    async with db.execute(
        """
        INSERT INTO delivery_reports (
            raw_line, outcome, reason, modem_ref, recipient, submitted_at,
            discharged_at, status_code, decided_by, message_id, seq, candidates,
            window_hours, strict
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            raw_line, outcome, reason, modem_ref, recipient, submitted_at,
            discharged_at, status_code, decided_by, message_id, seq,
            json.dumps(candidates, ensure_ascii=False) if candidates is not None else None,
            window_hours,
            None if strict is None else int(strict),
        ),
    ) as cursor:
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def prune_delivery_reports(max_age_seconds: int) -> int:
    """Drop records past the retention, and report how many went.

    Called from the expiry sweep rather than from `scan_inbox`, where `prune_inbound_seen`
    is called: that one fires at startup and on link recovery, so a gateway that never
    loses its link would not prune this table for months.
    """
    db = await get_db()
    async with db.execute(
        "DELETE FROM delivery_reports WHERE received_at < datetime('now', ?) RETURNING id",
        (f"-{int(max_age_seconds)} seconds",),
    ) as cursor:
        gone = len(await cursor.fetchall())
    await db.commit()
    return gone


async def parts_matching_ref(modem_ref: int) -> list[aiosqlite.Row]:
    """**Every** part carrying this reference, with its message's status and number.

    Deliberately unfiltered. The window and the message-status test are applied by
    `app.modem.attribution` and recorded as per-candidate outcomes, because a `WHERE`
    clause that discards the rows cannot name what it excluded: the record would answer
    "nothing matched" where the truth was "one match, too old", the evidence the strict
    switch is flipped on would not exist, and a superseded report would be
    indistinguishable from a report about nothing — which would start waking an operator
    on ordinary traffic.
    """
    db = await get_db()
    async with db.execute(
        """
        SELECT p.message_id, p.seq, p.status AS part_status, p.sent_at,
               m.status AS msg_status, m.phone
        FROM message_parts p
        JOIN messages m ON m.id = p.message_id
        WHERE p.modem_ref = ?
        ORDER BY p.message_id, p.seq
        """,
        (modem_ref,),
    ) as cursor:
        return list(await cursor.fetchall())


async def set_part_delivered(message_id: int, seq: int) -> None:
    """Mark the part attribution chose, addressed by its own identity.

    This used to say `WHERE modem_ref = ?` with no `LIMIT`, so the moment the reference
    repeated it rewrote every historical part sharing that octet.
    """
    db = await get_db()
    await db.execute(
        "UPDATE message_parts SET status = 'delivered' "
        "WHERE message_id = ? AND seq = ?",
        (message_id, seq),
    )
    await db.commit()


async def set_part_failed(message_id: int, seq: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE message_parts SET status = 'failed' WHERE message_id = ? AND seq = ?",
        (message_id, seq),
    )
    await db.commit()


async def message_parts_all_delivered(message_id: int) -> bool:
    """Whether every recorded part of this message is delivered.

    A message with no part rows at all answers **False**. "Nothing is outstanding" and
    "nothing is known" are different answers and only the first is a delivery; the
    previous form said `True` vacuously, which is one of the two ways a message no report
    ever named could be recorded as delivered.
    """
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) AS total, "
        "       SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) AS done "
        "FROM message_parts WHERE message_id = ?",
        (message_id,),
    ) as cursor:
        row = await cursor.fetchone()
    total = int(row["total"] or 0)
    return total > 0 and int(row["done"] or 0) == total


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


async def block_phone(phone: str) -> None:
    """Block a number by hand.

    Separate from `record_permanent_fail` on purpose: that one blocks as a side
    effect of counting failures, and a manual block is not a failure. `fail_count`
    is left alone.
    """
    db = await get_db()
    await db.execute(
        """
        INSERT INTO bad_numbers (phone, blocked_at) VALUES (?, CURRENT_TIMESTAMP)
        ON CONFLICT(phone) DO UPDATE SET blocked_at = CURRENT_TIMESTAMP
        """,
        (phone,),
    )
    await db.commit()


async def unblock_phone(phone: str) -> None:
    """Lift a block, keeping the failure history.

    This used to DELETE the row, which was tolerable while unblocking meant a trip to
    its own tab. It is now one click inside any conversation, and deleting the row
    would hand a number that earned its threshold a fresh budget of failures.
    `is_phone_blocked` keys on `blocked_at IS NOT NULL`, so clearing it is a complete
    unblock.
    """
    db = await get_db()
    await db.execute(
        "UPDATE bad_numbers SET blocked_at = NULL WHERE phone = ?", (phone,)
    )
    await db.commit()




# --- the merged two-direction listing -----------------------------------------
#
# Outbound and inbound live in separate tables with separate id sequences, so the
# SMS view unions them into one shape and orders by the message's own timestamp:
# `created_at` for outbound, `received_at` for inbound. That same column is what the
# period bounds, so ordering, filtering and the statistics all agree on when a
# message happened.

_THREAD_OUT = """
    SELECT 'out' AS direction, m.id AS id, m.phone AS phone, m.text AS text,
           m.status AS status, m.created_at AS ts, m.sent_at AS sent_at,
           m.delivered_at AS delivered_at, m.error AS error, m.attempts AS attempts,
           m.last_attempt_error AS last_attempt_error, m.app_id AS app_id,
           o.operator AS operator, o.region AS region
      FROM messages m
      LEFT JOIN number_operators o ON o.phone = m.phone
"""

_THREAD_IN = """
    SELECT 'in' AS direction, i.id AS id, i.phone AS phone, i.text AS text,
           NULL AS status, i.received_at AS ts, NULL AS sent_at,
           NULL AS delivered_at, NULL AS error, NULL AS attempts,
           NULL AS last_attempt_error, NULL AS app_id,
           o.operator AS operator, o.region AS region
      FROM inbound_messages i
      LEFT JOIN number_operators o ON o.phone = i.phone
"""


def normalize_filters(status: str | None, direction: str | None) -> tuple[str, str]:
    """Reconcile the status and direction filters.

    Status belongs to outbound messages only, so an active one forces the outbound
    direction. The rule runs one way only: both controls submit on every request, so
    a server that also let direction clear status could not tell which the operator
    just changed. The control offering the inbound direction drops the status as it
    navigates instead.
    """
    status = status or ""
    direction = direction if direction in ("in", "out") else ""
    if status:
        direction = "out"
    return status, direction


def _thread_query(
    period: str,
    phone: str | None,
    status: str | None,
    direction: str | None,
) -> tuple[str, list[Any]]:
    """(sql, params) for the union of the branches this filter set selects."""
    status, direction = normalize_filters(status, direction)
    lower = periods.bound(period)

    branches: list[str] = []
    params: list[Any] = []

    def branch(sql: str, ts_column: str, status_column: str | None) -> None:
        where: list[str] = []
        if lower is not None:
            where.append(f"{ts_column} > datetime('now', ?)")
            params.append(lower)
        if phone:
            where.append(f"{ts_column.split('.')[0]}.phone LIKE ?")
            params.append(f"%{phone}%")
        if status and status_column:
            where.append(f"{status_column} = ?")
            params.append(status)
        branches.append(sql + (("WHERE " + " AND ".join(where)) if where else ""))

    if direction != "in":
        branch(_THREAD_OUT, "m.created_at", "m.status")
    if direction != "out":
        branch(_THREAD_IN, "i.received_at", None)

    if not branches:                       # unreachable: direction is one of "", in, out
        return "SELECT NULL WHERE 0", []
    return "\nUNION ALL\n".join(branches), params


async def list_thread_page(
    period: str,
    phone: str | None,
    status: str | None,
    direction: str | None,
    limit: int,
    offset: int,
) -> list[aiosqlite.Row]:
    """One page of the merged stream, newest first.

    The tie-break is load-bearing: CURRENT_TIMESTAMP has one-second resolution, and
    multipart bursts, reconcile sweeps and test runs all produce equal timestamps.
    Ordering on `ts` alone under LIMIT/OFFSET lets sqlite return a row on two pages
    or on neither.
    """
    sql, params = _thread_query(period, phone, status, direction)
    db = await get_db()
    async with db.execute(
        f"SELECT * FROM (\n{sql}\n) ORDER BY ts DESC, direction DESC, id DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ) as cursor:
        return list(await cursor.fetchall())


async def count_thread_page(
    period: str,
    phone: str | None,
    status: str | None,
    direction: str | None,
) -> int:
    sql, params = _thread_query(period, phone, status, direction)
    db = await get_db()
    async with db.execute(f"SELECT COUNT(*) FROM (\n{sql}\n)", params) as cursor:
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def get_thread_row(direction: str, row_id: int) -> aiosqlite.Row | None:
    """The counterparty of a single row, for resolving an `open=<direction>-<id>` key.

    Expansion is addressed by the row, not by the number: a number can hold many rows
    in the window, and matching on the number would render its conversation under
    every one of them.
    """
    table = "messages" if direction == "out" else "inbound_messages"
    db = await get_db()
    async with db.execute(
        f"SELECT id, phone FROM {table} WHERE id = ?", (row_id,)
    ) as cursor:
        return await cursor.fetchone()


async def status_counts(period: str = "all") -> dict[str, int]:
    """Outbound counts per status within the period.

    A message belongs to the period by when it was created, and is counted under its
    *current* status — the only definition that stays stable as statuses keep moving
    after the fact, and the one that makes the cards agree with the table about which
    messages exist.
    """
    lower = periods.bound(period)
    where, params = ("WHERE created_at > datetime('now', ?)", [lower]) if lower else ("", [])
    db = await get_db()
    async with db.execute(
        f"SELECT status, COUNT(*) FROM messages {where} GROUP BY status", params
    ) as cursor:
        return {row[0]: int(row[1]) for row in await cursor.fetchall()}


async def inbound_count(period: str = "all") -> int:
    """How many messages arrived in the period. With the Inbound tab gone, nothing
    else reports this."""
    lower = periods.bound(period)
    where, params = ("WHERE received_at > datetime('now', ?)", [lower]) if lower else ("", [])
    db = await get_db()
    async with db.execute(
        f"SELECT COUNT(*) FROM inbound_messages {where}", params
    ) as cursor:
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def period_buckets(period: str) -> list[aiosqlite.Row]:
    """Outbound counts per (time bucket, status) for the statistics breakdown.

    Bucket size follows the period — hourly over a day, daily over a week or month,
    monthly over a year — because a 365-row daily table is not a breakdown anyone
    reads.
    """
    bucket = periods.bucket_expr("created_at", period)
    lower = periods.bound(period)
    where, params = ("WHERE created_at > datetime('now', ?)", [lower]) if lower else ("", [])
    db = await get_db()
    async with db.execute(
        f"""
        SELECT {bucket} AS bucket, status, COUNT(*) AS n
        FROM messages {where}
        GROUP BY bucket, status
        ORDER BY bucket DESC
        """,
        params,
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



async def create_verification(
    app_id: str, phone: str, *, code: str, ttl_seconds: int,
) -> int:
    """Persist a verification before anything is placed on its behalf.

    The deadline is computed by the database rather than by the caller, so that it is
    comparable with `CURRENT_TIMESTAMP` in every conditional update below — the whole
    point of those being single statements is lost if the times they compare were written
    by two different clocks.
    """
    db = await get_db()
    async with db.execute(
        "INSERT INTO verifications (app_id, phone, code, expires_at) "
        "VALUES (?, ?, ?, datetime('now', ? || ' seconds'))",
        # `:+d`, the idiom this module already uses for a signed interval: a plain
        # "+" prefix turns a negative interval into "+-1", which SQLite reads as no date
        # at all and the NOT NULL constraint then reports as a missing deadline.
        (app_id, phone, code, f"{int(ttl_seconds):+d}"),
    ) as cursor:
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def open_codes_for(phone: str) -> set[str]:
    """The codes currently live on this number, so a new one can differ from all of them.

    Two open verifications sharing a code would make an arriving answer attributable to
    neither with certainty, which is the one job a code has on the routes that carry one.
    """
    db = await get_db()
    async with db.execute(
        "SELECT code FROM verifications "
        "WHERE phone = ? AND status = 'pending' AND expires_at > CURRENT_TIMESTAMP "
        "AND code IS NOT NULL",
        (phone,),
    ) as cursor:
        return {row[0] for row in await cursor.fetchall()}


async def select_route(verification_id: int, app_id: str, *, route: str) -> str:
    """Record the consumer's choice of rung. Answers what happened, in one word.

    One of: `selected`, `already_selected`, `expired`, `not_found`. A verification is
    carried by exactly one route at a time and the gateway never moves it to another by
    itself — a list to choose from is not a licence to hop — so this is the single moment
    at which a verification acquires a route, and it is a conditional update for the same
    reason the confirmation is: two selections can arrive together.

    Nothing is placed here. Placement is the caller's act, after this returns `selected`.
    """
    db = await get_db()
    cursor = await db.execute(
        "UPDATE verifications SET route = ? "
        " WHERE id = ? AND app_id = ? AND status = 'pending' AND route IS NULL "
        "   AND expires_at > CURRENT_TIMESTAMP",
        (route, verification_id, app_id),
    )
    await db.commit()
    if cursor.rowcount == 1:
        return "selected"
    row = await get_verification(verification_id, app_id)
    if row is None:
        return "not_found"
    if row["route"] is not None:
        return "already_selected"
    return "expired"


async def shorten_verification_window(verification_id: int, *, ttl_seconds: int) -> None:
    """Bring a verification's deadline in to this rung's own window, never out.

    A rung may hold a shorter window than the capability's default and may not hold a
    longer one: the deadline the application was told at creation is the ceiling, and a
    configuration saying otherwise is clamped rather than obeyed. `MIN` does that in the
    statement itself, so there is no read between the decision and the write.
    """
    db = await get_db()
    await db.execute(
        "UPDATE verifications "
        "   SET expires_at = MIN(expires_at, datetime('now', ? || ' seconds')) "
        " WHERE id = ? AND status = 'pending'",
        (f"{int(ttl_seconds):+d}", verification_id),
    )
    await db.commit()


async def fail_verification(verification_id: int, *, reason: str) -> bool:
    """End an open verification with a named reason, and say whether this call did it.

    Used where a verification stops being carryable for a reason that is not the clock:
    the selected route lost the precondition it was offered on, or the modem went out of
    service under it. "Expired" told to a person who did call, on time, from the right
    number, is the gateway reporting the one thing that did not happen.

    The boolean says whether this call is the one that ended it, which a caller wants for
    its own log line. It is deliberately *not* what makes the announcement exactly-once —
    that is the announcer's own claim — because a writer that both ends and announces is a
    writer that can be added without announcing.
    """
    db = await get_db()
    cursor = await db.execute(
        "UPDATE verifications SET status = 'failed', reason = ?, code = NULL "
        " WHERE id = ? AND status = 'pending'",
        (reason, verification_id),
    )
    await db.commit()
    return cursor.rowcount == 1


async def record_verification_rung(
    verification_id: int, *, route: str, vendor_ref: str | None = None,
    cost: float | None = None, outcome: str | None = None, reason: str | None = None,
) -> int:
    """One rung attempted, with what it cost and what became of it.

    Per rung rather than per verification: a ladder has more than one, and a verification
    that tried Telegram and then placed a call holds two vendor identifiers and two costs
    against one code.
    """
    db = await get_db()
    async with db.execute(
        "INSERT INTO verification_rungs "
        "       (verification_id, route, vendor_ref, cost, outcome, reason) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (verification_id, route, vendor_ref, cost, outcome, reason),
    ) as cursor:
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def verification_seconds_left(verification_id: int) -> int:
    """How much of this verification's life is left, in whole seconds, by the database's
    clock rather than ours.

    The same clock that wrote the deadline, for the same reason every conditional update
    here is a single statement: a lifetime computed against a second clock is a lifetime
    that disagrees with the one the application was promised. Zero for a verification that
    is gone or already past its deadline — a rung asked to carry that is being asked to
    buy nothing.
    """
    db = await get_db()
    async with db.execute(
        "SELECT CAST(strftime('%s', expires_at) - strftime('%s', 'now') AS INTEGER) "
        "  FROM verifications WHERE id = ?",
        (verification_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None or row[0] is None:
        return 0
    return max(0, int(row[0]))


async def set_rung_outcome(
    rung_id: int, *, outcome: str, reason: str | None = None,
    vendor_ref: str | None = None, cost: float | None = None,
) -> None:
    """Finish the row the ladder wrote before it contacted this rung.

    The row is written first and updated here so that the order on disk is the order of
    the money: a crash between a vendor's confirmation and our record would otherwise
    leave a fee attributable to nothing. For the same reason `vendor_ref` and `cost` are
    written only when this call has them — a carrier that already recorded a charge and
    then failed must not have that charge erased by the outcome that follows it.
    """
    db = await get_db()
    await db.execute(
        "UPDATE verification_rungs "
        "   SET outcome = ?, "
        "       reason = COALESCE(?, reason), "
        "       vendor_ref = COALESCE(?, vendor_ref), "
        "       cost = COALESCE(?, cost) "
        " WHERE id = ?",
        (outcome, reason, vendor_ref, cost, rung_id),
    )
    await db.commit()


async def verification_rungs(verification_id: int) -> list[aiosqlite.Row]:
    """Every rung attempted for this verification, oldest first.

    A ladder has more than one, and the question a support call asks — "what did this
    person's login cost" — is answered by the list rather than by a last value.
    """
    db = await get_db()
    async with db.execute(
        "SELECT * FROM verification_rungs WHERE verification_id = ? "
        " ORDER BY started_at, id",
        (verification_id,),
    ) as cursor:
        return list(await cursor.fetchall())


async def record_rung_delivery(
    vendor_ref: str, *, route: str, outcome: str, reason: str | None = None,
    refunded: bool = False,
) -> int | None:
    """Record a vendor's delivery outcome against the rung holding `vendor_ref`.

    Returns the verification the rung belongs to, or None when no rung claims that
    reference — which is not an error and not a rejection: a correctly signed callback
    naming a request we have no record of is the vendor's, and arguing with it is not
    this layer's job.

    Matched on the pair, not on the reference alone. A vendor reference is unique at its
    own vendor and this gateway has more than one; the day a second vendor issues the
    same digits, an unqualified match would move the wrong rung.

    `refunded` is written only when it is True. The column cannot say "the vendor did not
    mention it", so the affirmative is the only thing it is allowed to assert, and what
    the vendor actually said belongs in `reason`.
    """
    db = await get_db()
    async with db.execute(
        "SELECT id, verification_id FROM verification_rungs "
        " WHERE vendor_ref = ? AND route = ? ORDER BY started_at DESC, id DESC LIMIT 1",
        (vendor_ref, route),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    await db.execute(
        "UPDATE verification_rungs SET outcome = ?, reason = ?, "
        "       refunded = CASE WHEN ? THEN 1 ELSE refunded END "
        " WHERE id = ?",
        (outcome, reason, 1 if refunded else 0, row["id"]),
    )
    await db.commit()
    return row["verification_id"]


async def confirm_by_inbound_call(phone: str, *, method: str) -> int | None:
    """Confirm the open `call_in` verification for this caller, at most once.

    Returns the id confirmed, or None when the call confirmed nothing — no open
    verification on that rung for that number, or one that had already closed.

    A single conditional update, like the check door's, and for a sharper reason:
    repetition is not an edge case here. The modem reports one call fifteen times in
    sixteen seconds, so a read-then-write would see "pending" fourteen times after the
    first confirmation and race itself.

    Nothing about the call is required beyond its number, because nothing else is
    carried. Attribution rests on the number and the single open window, which is why
    the rung is separately forbidden from having two windows open on one number.
    """
    db = await get_db()
    cursor = await db.execute(
        "UPDATE verifications SET status = 'confirmed', "
        "       confirmed_at = CURRENT_TIMESTAMP, confirmed_by = ?, code = NULL, "
        "       notified = 0 "
        " WHERE id = (SELECT id FROM verifications "
        "              WHERE phone = ? AND route = 'call_in' AND status = 'pending' "
        "                AND expires_at > CURRENT_TIMESTAMP "
        "              ORDER BY id LIMIT 1)",
        (method, phone),
    )
    await db.commit()
    if cursor.rowcount != 1:
        return None
    async with db.execute(
        "SELECT id FROM verifications "
        " WHERE phone = ? AND route = 'call_in' AND status = 'confirmed' "
        " ORDER BY confirmed_at DESC, id DESC LIMIT 1",
        (phone,),
    ) as c:
        row = await c.fetchone()
    return row[0] if row else None


async def confirm_by_inbound_message(phone: str, *, code: str, method: str) -> int | None:
    """Confirm on the pair of originating number **and** code. Neither half alone.

    The code binds the arriving message to one open verification; the originating number
    is what binds the person to the number. A message carrying a valid open code from
    another number confirms nothing and consumes nothing, and a wrong code from the right
    number leaves the verification pending — deliberately without spending an attempt,
    because on this rung the only party who can spend them is the person themselves,
    mistyping, and counting those locks a real person out of a barrier they are at.
    """
    db = await get_db()
    cursor = await db.execute(
        "UPDATE verifications SET status = 'confirmed', "
        "       confirmed_at = CURRENT_TIMESTAMP, confirmed_by = ?, code = NULL, "
        "       notified = 0 "
        " WHERE id = (SELECT id FROM verifications "
        "              WHERE phone = ? AND code = ? AND route = 'sms_in' "
        "                AND status = 'pending' AND expires_at > CURRENT_TIMESTAMP "
        "              ORDER BY id LIMIT 1)",
        (method, phone, code),
    )
    await db.commit()
    if cursor.rowcount != 1:
        return None
    async with db.execute(
        "SELECT id FROM verifications "
        " WHERE phone = ? AND route = 'sms_in' AND status = 'confirmed' "
        " ORDER BY confirmed_at DESC, id DESC LIMIT 1",
        (phone,),
    ) as c:
        row = await c.fetchone()
    return row[0] if row else None


async def unnotified_terminal_verifications() -> list[aiosqlite.Row]:
    """Verifications that reached a terminal state and have not been announced yet.

    Every writer of a terminal state leaves `notified` at 0 for this to pick up, so that
    "who tells the application" has one answer rather than one per writer — including the
    expiry sweep, which has no privilege here despite holding its own list. A writer that
    announced its own would be a writer somebody could add without announcing, and the
    guard in `tests/test_verification_outcome_reaches_the_app.py` enforces exactly that.
    """
    db = await get_db()
    async with db.execute(
        "SELECT id, app_id, status, confirmed_by, reason FROM verifications "
        " WHERE status != 'pending' AND notified = 0 ORDER BY id"
    ) as cursor:
        return list(await cursor.fetchall())


async def mark_verification_notified(verification_id: int) -> bool:
    """Claim the right to announce this one. True only for the caller that won it."""
    db = await get_db()
    cursor = await db.execute(
        "UPDATE verifications SET notified = 1 WHERE id = ? AND notified = 0",
        (verification_id,),
    )
    await db.commit()
    return cursor.rowcount == 1


async def has_open_verification(
    phone: str, *, route: str, excluding: int | None = None,
) -> bool:
    """Whether this number already has a live verification on this rung.

    Asked by the `call_in` rung, which carries no code: attribution there rests entirely
    on the calling number and a single open window, so a second window on one number
    would leave an arriving call belonging to neither with certainty.

    `excluding` is for re-proving a rung *under* an open verification. Without it the
    question answers itself — the verification being checked is the open window — and the
    sweep that watches for dead routes would end every call verification a minute after
    it was selected. The positive control in
    `tests/test_verification_outcome_reaches_the_app.py` is what caught that.
    """
    db = await get_db()
    async with db.execute(
        "SELECT 1 FROM verifications "
        " WHERE phone = ? AND route = ? AND status = 'pending' "
        "   AND expires_at > CURRENT_TIMESTAMP AND id IS NOT ? LIMIT 1",
        (phone, route, excluding),
    ) as cursor:
        return await cursor.fetchone() is not None


async def get_verification(verification_id: int, app_id: str) -> aiosqlite.Row | None:
    """Scoped to the owning application, and indistinguishable from missing to any other.

    Unscoped reads exist elsewhere in this module for the admin console; this door is not
    one of them. An application walking another's verifications by id does worse than
    read them — it spends their attempts.
    """
    db = await get_db()
    async with db.execute(
        "SELECT * FROM verifications WHERE id = ? AND app_id = ?",
        (verification_id, app_id),
    ) as cursor:
        return await cursor.fetchone()


async def open_verifications_with_a_route() -> list[aiosqlite.Row]:
    """Open verifications that are being carried by a rung right now.

    Asked once a minute so that a rung which has died under one of them is noticed while
    the person is still waiting, rather than at the deadline — where the only word the
    gateway has left is "expired", which is the one thing that did not happen.
    """
    db = await get_db()
    async with db.execute(
        "SELECT id, app_id, phone, route FROM verifications "
        " WHERE status = 'pending' AND route IS NOT NULL "
        "   AND expires_at > CURRENT_TIMESTAMP"
    ) as cursor:
        return list(await cursor.fetchall())


async def check_verification(
    verification_id: int, app_id: str, *, code: str, max_attempts: int,
) -> str:
    """Answer whether `code` is this verification's, and say what happened.

    One of: `confirmed`, `wrong_code`, `already_confirmed`, `expired`, `no_attempts_left`,
    `not_found`. A bare no is not an answer — the caller is a barrier with a person
    standing at it, and "expired" and "wrong" mean different things to them.

    `max_attempts` is required rather than defaulted on purpose. It is a setting, this
    layer does not read settings, and a default here would be a quiet hole: a new call
    site that forgot it would pass, silently bounded by somebody else's number.

    Both the confirmation and the spent attempt are single conditional updates, decided on
    the rows they changed. Reading the state and writing it back loses the race that
    actually happens: a person double-taps Confirm, and both reads see a pending
    verification with attempts to spare.
    """
    db = await get_db()
    limit = int(max_attempts)
    cursor = await db.execute(
        "UPDATE verifications SET status = 'confirmed', "
        "       confirmed_at = CURRENT_TIMESTAMP, confirmed_by = 'check', code = NULL "
        " WHERE id = ? AND app_id = ? AND status = 'pending' "
        "   AND expires_at > CURRENT_TIMESTAMP AND attempts < ? AND code = ?",
        (verification_id, app_id, limit, code),
    )
    await db.commit()
    if cursor.rowcount == 1:
        return "confirmed"

    # It was not confirmed. Spend an attempt under the same conditions, so that a wrong
    # code costs one and a code offered to something already finished costs nothing.
    cursor = await db.execute(
        "UPDATE verifications SET attempts = attempts + 1 "
        " WHERE id = ? AND app_id = ? AND status = 'pending' "
        "   AND expires_at > CURRENT_TIMESTAMP AND attempts < ?",
        (verification_id, app_id, limit),
    )
    await db.commit()
    spent = cursor.rowcount == 1
    if spent:
        # The attempt that reaches the limit finishes the verification, and a finished
        # verification stops holding a usable secret.
        await db.execute(
            "UPDATE verifications SET status = 'failed', reason = 'no_attempts_left', "
            "       code = NULL "
            " WHERE id = ? AND status = 'pending' AND attempts >= ?",
            (verification_id, limit),
        )
        await db.commit()
        return "wrong_code"

    # Nothing changed, so why is a read — used to explain, never to decide.
    row = await get_verification(verification_id, app_id)
    if row is None:
        return "not_found"
    if row["status"] == "confirmed":
        return "already_confirmed"
    if row["status"] == "expired":
        return "expired"
    if row["status"] == "failed":
        return "no_attempts_left"
    return "expired"          # pending, but past its deadline: the sweep has not run yet


async def expire_due_verifications() -> list[int]:
    """Move open verifications past their deadline to expired, and hand back which.

    The rows are left **unannounced** — `notified` stays 0 — because who tells the
    application is one answer for the whole capability and not one per writer: the
    announcer claims each row with a conditional update of its own, which is what makes
    the telling exactly-once whichever writer ended it.

    An expiry computed only when somebody next asks never fires for the case that matters.
    The person who never got the call has no reason to come back with a code, so nothing
    triggers a lazy check and the application waits for an answer that is never computed.
    """
    db = await get_db()
    async with db.execute(
        "SELECT id FROM verifications "
        " WHERE status = 'pending' AND expires_at <= CURRENT_TIMESTAMP"
    ) as cursor:
        ids = [row[0] for row in await cursor.fetchall()]
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    await db.execute(
        f"UPDATE verifications SET status = 'expired', reason = 'expired', code = NULL "
        f" WHERE id IN ({marks}) AND status = 'pending'",
        ids,
    )
    await db.commit()
    return ids


async def prune_verifications(max_age_days: int) -> int:
    """Delete finished verifications past their retention, and report how many went.

    Finished, not merely old: an open verification past the window is a person still
    waiting, and deleting it answers their barrier with a 404.
    """
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM verifications "
        " WHERE status != 'pending' "
        "   AND created_at < datetime('now', ? || ' days')",
        (f"-{int(max_age_days)}",),
    )
    await db.commit()
    return cursor.rowcount


async def record_inbound_call(
    *, phone: str | None = None, raw_number: str | None = None, outcome: str,
    reason: str | None = None,
) -> int:
    """Write down one incoming call, whatever became of it.

    Written on the first `RING`, before anything is known about who is calling: the event
    is the call, and the number is a fact that may or may not follow it. A call recorded
    only once its number arrived would lose exactly the calls this store exists to make
    visible — the nameless ones.
    """
    db = await get_db()
    async with db.execute(
        "INSERT INTO inbound_calls (phone, raw_number, outcome, reason) "
        "VALUES (?, ?, ?, ?)",
        (phone, raw_number, outcome, reason),
    ) as cursor:
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def attach_inbound_call_number(
    call_id: int, *, phone: str | None, raw_number: str, outcome: str,
    verification_id: int | None = None,
) -> None:
    """The first `+CLIP` of a call, joined to the row its `RING` opened.

    `phone` stays None when what arrived is not a number we can match against; the raw
    form is recorded regardless, so "who called us" has an answer even where "which
    verification was this" does not.
    """
    db = await get_db()
    await db.execute(
        "UPDATE inbound_calls SET phone = ?, raw_number = ?, outcome = ?, "
        "       verification_id = ? WHERE id = ?",
        (phone, raw_number, outcome, verification_id, call_id),
    )
    await db.commit()


async def count_inbound_calls() -> int:
    db = await get_db()
    async with db.execute("SELECT COUNT(*) FROM inbound_calls") as cursor:
        return (await cursor.fetchone())[0]


async def count_calls_without_number() -> int:
    """How many calls arrived that nothing can be attributed by.

    The only detector for a caller-ID subscription dropped without a `CFUN` cycle: the
    gateway's record of its own `AT+CLIP=1` cannot see that happen, and a rate of
    nameless calls can.
    """
    db = await get_db()
    async with db.execute(
        "SELECT COUNT(*) FROM inbound_calls WHERE phone IS NULL"
    ) as cursor:
        return (await cursor.fetchone())[0]


async def delete_inbound(message_id: int) -> None:
    db = await get_db()
    await db.execute("DELETE FROM inbound_messages WHERE id = ?", (message_id,))
    await db.commit()


# How long a delivered/failed message stays undeletable. `GET /sms/{id}` is the
# authoritative status source an application polls to recover a dropped webhook, and
# a deleted row answers 404 — indistinguishable from "no such message". A day is
# comfortably past the webhook retry ladder and any plausible poll interval.
DELETE_MIN_AGE = "-1 day"


async def delete_outbound(message_id: int) -> str | None:
    """Delete an outbound message. Returns None on success, else a refusal reason.

    Three conditions, all necessary, and each one protects a promise made elsewhere:

    - status is `delivered` or `failed` — an `expired` message still accepts a late
      delivery report that corrects it to `delivered` while the part it names is inside
      `delivery_report_max_age_hours` (`parts_matching_ref` collects `expired` messages
      for exactly that reason). Past that window the refusal stands on a second reason:
      an `expired` message is one whose outcome the gateway never learned, and the record
      of an unanswered question is not the operator's routine tidying;
    - no re-sent copy is still in flight — `resent_from` is read at notification
      time, so clearing it under a live copy would strip the field the consumer uses
      to attribute the outcome;
    - the message is at least a day old (see DELETE_MIN_AGE).

    The status and age gates are applied *inside* the DELETE and decided on rowcount,
    not by a separate SELECT: a concurrent delivery report can move the status
    between a check and a write. A refusal rolls back, so the part records survive it.
    """
    db = await get_db()

    async with db.execute(
        f"""
        SELECT COUNT(*) FROM messages
        WHERE resent_from = ?
          AND status NOT IN ({','.join('?' * len(TERMINAL_STATUSES))})
        """,
        (message_id, *TERMINAL_STATUSES),
    ) as cursor:
        row = await cursor.fetchone()
        if row and int(row[0]):
            return "resend_in_flight"

    try:
        await db.execute(
            "DELETE FROM message_parts WHERE message_id = ?", (message_id,)
        )
        await db.execute(
            "UPDATE messages SET resent_from = NULL WHERE resent_from = ?",
            (message_id,),
        )
        cursor = await db.execute(
            f"""
            DELETE FROM messages
            WHERE id = ?
              AND status IN ({','.join('?' * len(TERMINAL_STATUSES))})
              AND created_at <= datetime('now', ?)
            """,
            (message_id, *TERMINAL_STATUSES, DELETE_MIN_AGE),
        )
        if cursor.rowcount != 1:
            await db.rollback()
            return await _delete_refusal_reason(message_id)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return None


async def _delete_refusal_reason(message_id: int) -> str:
    """Why the gated DELETE matched nothing — so the operator is told, not just
    refused."""
    db = await get_db()
    async with db.execute(
        "SELECT status, created_at <= datetime('now', ?) AS old_enough "
        "FROM messages WHERE id = ?",
        (DELETE_MIN_AGE, message_id),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return "not_found"
    if row["status"] not in TERMINAL_STATUSES:
        return "not_terminal"
    if not row["old_enough"]:
        return "too_young"
    return "refused"



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


_DIALOG_UNION = """
    SELECT 'in' AS direction, id, text, received_at AS ts,
           NULL AS status, NULL AS error
      FROM inbound_messages WHERE phone = ?
    UNION ALL
    SELECT 'out' AS direction, id, text, created_at AS ts,
           status, error
      FROM messages WHERE phone = ?
"""


async def dialog_for(phone: str, limit: int = 100) -> list[aiosqlite.Row]:
    """Combined timeline of inbound + outbound for a phone, oldest first.

    Outbound is ordered by `created_at`, not `COALESCE(sent_at, created_at)` as it
    once was, so the panel and the table directly above it order the same two
    messages the same way.

    Capped: the panel is rendered inside the list page and re-rendered after every
    action, so a number on the receiving end of a daily notification would otherwise
    make every redirect more expensive. The newest `limit` are kept, then flipped
    back into reading order.
    """
    db = await get_db()
    async with db.execute(
        f"""
        SELECT * FROM (
            SELECT * FROM ({_DIALOG_UNION})
            ORDER BY ts DESC, direction DESC, id DESC
            LIMIT ?
        ) ORDER BY ts ASC, direction ASC, id ASC
        """,
        (phone, phone, limit),
    ) as cursor:
        return list(await cursor.fetchall())


async def dialog_total(phone: str) -> int:
    """How many messages the conversation holds, so a capped panel can say so."""
    db = await get_db()
    async with db.execute(
        f"SELECT COUNT(*) FROM ({_DIALOG_UNION})", (phone, phone)
    ) as cursor:
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


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
