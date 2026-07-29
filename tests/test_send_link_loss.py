"""The send path meeting a lost link.

This is where the incident would have done real damage. A transport failure reached
`sender_loop`'s broad `except Exception` and the message was failed at `attempt=0` with
"internal error while sending" — no retry, and a `failed` webhook, which GM+ answers by
SMS-ing an operator. The whole retry ladder built in 0.9.0–0.11.0 was bypassed because
the exception was of the wrong class. Nothing was lost on 2026-07-29 only because no
send was attempted during the five hours.

The opposite mistake is worse, so it is pinned here too: holding a message that *was*
already written puts a second copy on someone's handset.
"""

import asyncio

import pytest

import app.modem.manager as manager_mod
from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.modem.at_commands import ATCommandError, ModemTransportError
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
        "SELECT status, attempts, error, last_attempt_error, next_attempt_at "
        "FROM messages WHERE id = ?", (message_id,),
    ) as cur:
        return dict(await cur.fetchone())


def _manager(monkeypatch, *, registration=True, send_impl=None):
    m = ModemManager("/dev/null", "/dev/null")
    dispatched = []

    async def probe():
        if callable(registration):
            return registration()
        return registration

    async def send(parts, on_part_sent, **kw):
        await on_part_sent(1, 42)
        return [42]

    m._sender.registration_state = probe
    m._sender.send_sms_pdu = send_impl or send
    monkeypatch.setattr(
        manager_mod, "spawn_delivery_dispatch",
        lambda mid, status, error=None: dispatched.append((mid, status)),
    )
    monkeypatch.setattr(manager_mod, "notify", lambda *a, **kw: None)
    return m, dispatched


# --- before anything is written ------------------------------------------------


def test_a_link_lost_before_the_probe_holds_the_message(monkeypatch):
    """The incident's real cost, had a send been due: failed at zero attempts with a
    `failed` webhook, instead of waiting for a link that comes back."""

    def gone():
        raise ModemTransportError("link to /dev/ttyUSB2 lost: gone")

    async def body():
        m, dispatched = _manager(monkeypatch, registration=gone)
        mid = await queries.create_message("app1", PHONE, "hi")
        await m._send_one(OutgoingMessage(mid, PHONE, "hi", "app1"))
        return await _state(mid), dispatched

    state, dispatched = _run(body)
    assert state["status"] == "pending"
    assert state["attempts"] == 0, "a message never offered to the modem spent a chance"
    assert state["error"] is None, "a message still on its way must not report an error"
    assert state["next_attempt_at"] is not None, "held and then stranded — invisible to the scheduler"
    assert dispatched == [], "the owning app was told the message failed"


def test_a_link_lost_after_the_claim_gives_the_attempt_back(monkeypatch):
    """`begin_message_attempt` counts the attempt and clears the schedule before a byte
    goes out. A hold decided after that must give both back, or the message carries a
    spent attempt and no schedule — declined and then stranded until its deadline."""

    async def dies(parts, on_part_sent, **kw):
        raise ModemTransportError("link to /dev/ttyUSB2 lost: gone")

    async def body():
        m, dispatched = _manager(monkeypatch, registration=True, send_impl=dies)
        mid = await queries.create_message("app1", PHONE, "hi")
        await m._send_one(OutgoingMessage(mid, PHONE, "hi", "app1"))
        return await _state(mid), dispatched

    state, dispatched = _run(body)
    assert state["status"] == "pending"
    assert state["attempts"] == 0, "the claimed attempt was not returned"
    assert state["next_attempt_at"] is not None, "the message has no schedule to come back on"
    assert dispatched == []


# --- once something has been written -------------------------------------------


def test_a_link_lost_after_the_pdu_fails_the_message(monkeypatch):
    """The SMSC may already hold it. Retrying would put a second copy on the handset."""

    async def dies_after_write(parts, on_part_sent, **kw):
        raise ModemTransportError("link lost", pdu_submitted=True)

    async def body():
        m, dispatched = _manager(monkeypatch, registration=True, send_impl=dies_after_write)
        mid = await queries.create_message("app1", PHONE, "hi")
        await m._send_one(OutgoingMessage(mid, PHONE, "hi", "app1"))
        return await _state(mid), dispatched

    state, dispatched = _run(body)
    assert state["status"] == "failed"
    assert state["next_attempt_at"] is None, "a transmitted message was scheduled to go again"
    assert ("failed" in [s for _, s in dispatched])


def test_a_link_lost_between_the_parts_of_a_multipart_fails_it(monkeypatch):
    """Part 1 is already at the SMSC under a concatenation reference. Holding would
    schedule a retry that transmits it a second time under the same reference."""

    async def dies_after_first_part(parts, on_part_sent, **kw):
        await on_part_sent(1, 42)          # part 1 accepted
        raise ModemTransportError("link lost")   # no PDU flag: part 2 never went out

    async def body():
        m, dispatched = _manager(monkeypatch, registration=True, send_impl=dies_after_first_part)
        mid = await queries.create_message("app1", PHONE, "hi")
        await m._send_one(OutgoingMessage(mid, PHONE, "hi", "app1"))
        return await _state(mid), dispatched

    state, dispatched = _run(body)
    assert state["status"] == "failed", "a message with a part already accepted was held"
    assert state["next_attempt_at"] is None


# --- the distinction the send path must keep ------------------------------------


def test_an_at_failure_of_the_probe_still_attempts_the_message(monkeypatch):
    """Not knowing is not a refusal: a gateway that stops sending whenever it cannot ask
    a question is worse than one that tries and reports a real failure."""

    def cannot_tell():
        return None

    async def body():
        m, dispatched = _manager(monkeypatch, registration=cannot_tell)
        mid = await queries.create_message("app1", PHONE, "hi")
        await m._send_one(OutgoingMessage(mid, PHONE, "hi", "app1"))
        return await _state(mid), dispatched

    state, dispatched = _run(body)
    assert state["status"] == "sent", "an unanswerable probe stopped a send it should have tried"


def test_a_hold_for_a_lost_link_still_ends_at_the_pending_deadline(monkeypatch):
    """Declining must not become indefinite retention. A message the gateway keeps
    refusing to attempt still reaches a terminal status, and its application is still
    told — otherwise an outage silently swallows it."""

    def gone():
        raise ModemTransportError("link to /dev/ttyUSB2 lost: gone")

    async def body():
        m, dispatched = _manager(monkeypatch, registration=gone)
        mid = await queries.create_message("app1", PHONE, "hi")
        msg = OutgoingMessage(mid, PHONE, "hi", "app1")
        for _ in range(5):
            await m._send_one(msg)
        db = await get_db()
        await db.execute(
            "UPDATE messages SET created_at = datetime('now', '-9000 seconds') "
            "WHERE id = ?", (mid,))
        await db.commit()
        await m._retry_step()
        return await _state(mid), dispatched

    state, dispatched = _run(body)
    assert state["status"] == "failed", "a message held for a lost link was kept for ever"
    assert "failed" in [s for _, s in dispatched], "its application was never told"
