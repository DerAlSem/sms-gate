"""Declining to transmit while the modem is off the network.

The value of this is narrow and worth keeping in view: retries already recover a send
that never reached the modem. What they cannot recover is a multipart whose first part
was accepted before the network went away — and that failure is *created* by starting a
send into a network about to refuse it. So the tests that matter are the ones proving
nothing was transmitted, and that declining costs the message time rather than attempts.
"""

import asyncio

import pytest

import app.modem.manager as manager_mod
from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.modem.at_commands import ATCommandError, ATSerial
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


def _manager(monkeypatch, registration, send_impl=None):
    """`registration` is what the pre-send probe reports: True, False, or None for
    'could not tell'. A callable is used as-is."""
    m = ModemManager("/dev/null", "/dev/null")
    sent = []

    async def send(parts, on_part_sent, **kw):
        sent.append(parts)
        await on_part_sent(1, 42)
        return [42]

    async def probe():
        return registration() if callable(registration) else registration

    m._sender.send_sms_pdu = send_impl or send
    m._sender.registration_state = probe
    monkeypatch.setattr(manager_mod, "spawn_delivery_dispatch",
                        lambda *a, **kw: None)
    monkeypatch.setattr(manager_mod, "notify", lambda *a, **kw: None)
    return m, sent


# ---------------------------------------------------------------- the probe itself


def test_the_probe_separates_a_refusal_from_not_knowing():
    """`registration_ok` folds both into False, which is right for the watchdog and
    wrong here: not knowing must not stop the gateway sending."""
    async def ask(response=None, raises=False):
        s = ATSerial("/dev/null")

        async def command(cmd, timeout=5.0):
            if raises:
                raise ATCommandError("no response from modem (timeout)")
            return response

        s.command = command
        return await s.registration_state()

    assert asyncio.run(ask("+CEREG: 0,1")) is True
    assert asyncio.run(ask("+CEREG: 2,5")) is True
    assert asyncio.run(ask("+CEREG: 0,0")) is False
    assert asyncio.run(ask(raises=True)) is None, "a failed query is not a refusal"
    assert asyncio.run(ask("gibberish")) is None


def test_the_watchdog_still_treats_an_unanswerable_modem_as_unhealthy():
    """Refactoring the probe must not soften the watchdog's own check."""
    async def ask(raises):
        s = ATSerial("/dev/null")

        async def command(cmd, timeout=5.0):
            if raises:
                raise ATCommandError("no response from modem (timeout)")
            return "+CEREG: 0,1"

        s.command = command
        return await s.registration_ok()

    assert asyncio.run(ask(False)) is True
    assert asyncio.run(ask(True)) is False


# ------------------------------------------------------------------- holding back


def test_an_unregistered_modem_holds_the_message_without_spending_an_attempt(monkeypatch):
    async def body():
        m, sent = _manager(monkeypatch, False)
        mid = await queries.create_message("app1", PHONE, "hi")
        await m._send_one(OutgoingMessage(mid, PHONE, "hi", "app1"))
        return sent, await _state(mid)

    sent, state = _run(body)
    assert sent == [], "nothing may reach the modem"
    assert state["status"] == "pending"
    assert state["attempts"] == 0, "a message never offered to the network keeps its budget"
    assert state["next_attempt_at"] is not None
    assert state["error"] is None


def test_a_multipart_is_not_started_during_an_outage(monkeypatch):
    """The one failure retries cannot undo: part 1 accepted, part 2 refused, no resend
    possible. Not starting is the only fix."""
    long_text = "Ы" * 200          # comfortably more than one UCS2 part

    async def body():
        m, sent = _manager(monkeypatch, False)
        mid = await queries.create_message("app1", PHONE, long_text)
        await m._send_one(OutgoingMessage(mid, PHONE, long_text, "app1"))
        return sent, await _state(mid)

    sent, state = _run(body)
    assert sent == []
    assert state["status"] == "pending"


def test_the_message_goes_out_once_the_network_is_back(monkeypatch):
    async def body():
        answers = iter([False, True])
        m, sent = _manager(monkeypatch, lambda: next(answers))
        mid = await queries.create_message("app1", PHONE, "hi")
        msg = OutgoingMessage(mid, PHONE, "hi", "app1")
        await m._send_one(msg)
        held = await _state(mid)
        await m._send_one(msg)
        return held, sent, await _state(mid)

    held, sent, after = _run(body)
    assert held["attempts"] == 0
    assert len(sent) == 1
    assert after["status"] == "sent"
    assert after["attempts"] == 1


def test_a_probe_that_cannot_answer_does_not_hold_the_message(monkeypatch):
    """A gateway that stops sending whenever it cannot ask a question is worse than one
    that tries and reports a real failure."""
    async def body():
        m, sent = _manager(monkeypatch, None)
        mid = await queries.create_message("app1", PHONE, "hi")
        await m._send_one(OutgoingMessage(mid, PHONE, "hi", "app1"))
        return sent, await _state(mid)

    sent, state = _run(body)
    assert len(sent) == 1, "not knowing is not a refusal"
    assert state["attempts"] == 1


def test_a_message_held_through_a_long_outage_still_reaches_a_terminal_status(monkeypatch):
    """Declining must never become silent indefinite retention."""
    async def body():
        m, sent = _manager(monkeypatch, False)
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
        return sent, await _state(mid)

    sent, state = _run(body)
    assert sent == []
    assert state["status"] == "failed", "the pending deadline still terminates it"
