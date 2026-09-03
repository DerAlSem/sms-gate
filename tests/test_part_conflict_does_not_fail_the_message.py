"""A part record that conflicts is a fault, and a fault that must not fail the message.

`add_message_part` stopped using `INSERT OR REPLACE`, so recording the same segment of
the same message twice now raises instead of silently discarding a reference. That is the
point — but it can only fire *after* the network already accepted the segment. Failing
the message there would invite an operator resend and a second delivery to the recipient,
which is exactly what the change exists to stop happening by accident.
"""
import asyncio
import logging

import pytest

import app.modem.manager as manager_mod
from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.modem.manager import ModemManager, OutgoingMessage
from app.settings_store import store

PHONE = "+79990000001"


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        return await body()
    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


async def _state(message_id: int) -> dict:
    db = await get_db()
    async with db.execute(
        "SELECT status, error, last_attempt_error FROM messages WHERE id = ?",
        (message_id,),
    ) as cur:
        return dict(await cur.fetchone())


async def _parts(message_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT seq, modem_ref, status FROM message_parts WHERE message_id = ? ORDER BY seq",
        (message_id,),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


def test_a_conflicting_part_record_is_logged_and_the_message_still_sends(
    monkeypatch, caplog
):
    """Task 3.7a — raised, logged, and not turned into a failed message."""
    refs = iter([42, 200])

    async def send_one_segment(parts, on_part_sent, **kw):
        ref = next(refs)
        await on_part_sent(1, ref)
        return [ref]

    async def body():
        m = ModemManager("/dev/null", "/dev/null")
        dispatched = []

        async def registered():
            return True

        m._sender.registration_state = registered
        m._sender.send_sms_pdu = send_one_segment
        monkeypatch.setattr(
            manager_mod, "spawn_delivery_dispatch",
            lambda mid, status, error=None: dispatched.append((mid, status)),
        )
        monkeypatch.setattr(manager_mod, "notify", lambda *a, **kw: None)

        mid = await queries.create_message("app1", PHONE, "hi")
        out = OutgoingMessage(mid, PHONE, "hi", "app1")
        with caplog.at_level(logging.ERROR, logger="app.modem.manager"):
            await m._send_one(out)
            # A second attempt at a message whose first segment the network already took.
            # `is_retryable(..., already_sent=…)` refuses this, which is why the conflict
            # is a fault rather than a case to resolve — but the fault must not be paid
            # for by the recipient.
            await m._send_one(out)
        return mid, await _state(mid), await _parts(mid), dispatched

    with caplog.at_level(logging.ERROR, logger="app.modem.manager"):
        mid, state, parts, dispatched = _run(body)

    assert state["status"] == "sent", (
        "the network took the segment; failing the message here invites a resend and a "
        "second delivery"
    )
    assert state["error"] is None
    assert all(status == "sent" for _, status in dispatched), (
        "no failure webhook for a message that went out: %r" % (dispatched,)
    )
    assert len(parts) == 1 and parts[0]["modem_ref"] == 42, "the first record stands"
    assert any("part" in r.getMessage().lower() for r in caplog.records
               if r.levelno >= logging.ERROR), "the fault reached the log"
