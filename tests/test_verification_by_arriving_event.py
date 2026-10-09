"""A call and a message confirm a verification, and each does it once.

These are the two rungs this change bears, and they share a property nothing else in this
capability has: the confirming event arrives **from the person**, on its own, through no
door of ours. Nothing about it passes through `POST /verifications/{id}/check`, so every
guarantee written for that door has to be restated for these — single use, the deadline,
and the atomic decision — or it holds for the rungs the gateway sends and lapses for the
rungs it receives.
"""

import asyncio

import pytest

import app.modem.manager as manager_mod
from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.modem.manager import ModemManager
from app.settings_store import store
from app.verification.routes import CALL_IN, SMS_IN

CALLER = "+79261234888"
CLIP = f'+CLIP: "{CALLER}",145,,,,0'
STRANGER = "+79031680015"


class ScriptedPort:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.in_service = True
        self.usable = True

    async def read_urc(self, timeout=1.0):
        if self._chunks:
            return self._chunks.pop(0)
        await asyncio.sleep(0.002)
        raise asyncio.TimeoutError


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


def _manager(monkeypatch):
    m = ModemManager("/dev/null", "/dev/null")
    monkeypatch.setattr(manager_mod, "spawn_delivery_dispatch", lambda *a, **kw: None)
    return m


async def _drive(m, chunks, *, settle=0.05):
    m._reader_link = ScriptedPort(chunks)
    task = asyncio.get_event_loop().create_task(m.reader_loop())
    await asyncio.sleep(settle)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _open(route, phone=CALLER, code="1234", ttl=300):
    vid = await queries.create_verification("app1", phone, code=code, ttl_seconds=ttl)
    await queries.select_route(vid, "app1", route=route)
    return vid


async def _status(vid):
    row = await queries.get_verification(vid, "app1")
    return row["status"], row["confirmed_by"]


# --- 8.1 — the call ----------------------------------------------------------------------

def test_a_call_from_the_number_being_verified_confirms_it(monkeypatch):
    async def body():
        vid = await _open(CALL_IN)
        await _drive(_manager(monkeypatch), [b"\r\nRING\r\n", (CLIP + "\r\n").encode()])
        return await _status(vid)

    assert _run(body) == ("confirmed", CALL_IN)


def test_the_call_that_confirmed_is_recorded_as_having_done_so(monkeypatch):
    """"Who called us" has an answer, and so does "what did that call do"."""
    async def body():
        vid = await _open(CALL_IN)
        await _drive(_manager(monkeypatch), [b"\r\nRING\r\n", (CLIP + "\r\n").encode()])
        db = await get_db()
        async with db.execute(
            "SELECT outcome, verification_id FROM inbound_calls"
        ) as cur:
            return [tuple(r) for r in await cur.fetchall()], vid

    rows, vid = _run(body)
    assert rows == [("confirmed", vid)]


def test_fifteen_repetitions_confirm_once_and_change_nothing_after(monkeypatch):
    """Repetition is not an edge case here: the modem reports one call fifteen times."""
    async def body():
        vid = await _open(CALL_IN)
        chunks = [b"\r\nRING\r\n", (CLIP + "\r\n").encode()] * 15
        await _drive(_manager(monkeypatch), chunks)
        db = await get_db()
        async with db.execute("SELECT COUNT(*) FROM inbound_calls") as cur:
            calls = (await cur.fetchone())[0]
        return await _status(vid), calls

    assert _run(body) == (("confirmed", CALL_IN), 1)


def test_a_call_from_a_stranger_confirms_nothing_and_is_recorded_unattributed(monkeypatch):
    async def body():
        vid = await _open(CALL_IN, phone=STRANGER)
        await _drive(_manager(monkeypatch), [b"\r\nRING\r\n", (CLIP + "\r\n").encode()])
        db = await get_db()
        async with db.execute("SELECT outcome FROM inbound_calls") as cur:
            outcome = (await cur.fetchone())[0]
        return await _status(vid), outcome

    assert _run(body) == (("pending", None), "unattributed")


def test_a_call_after_the_deadline_does_not_revive_a_verification(monkeypatch):
    async def body():
        vid = await _open(CALL_IN, ttl=-1)
        await _drive(_manager(monkeypatch), [b"\r\nRING\r\n", (CLIP + "\r\n").encode()])
        return await _status(vid)

    assert _run(body) == ("pending", None), "an expired window must not confirm"


def test_a_call_does_not_confirm_a_verification_carried_by_another_rung(monkeypatch):
    """The rung is part of what the event confirms. A person who chose to be texted has
    not agreed to be identified by a call they may not have made."""
    async def body():
        vid = await _open(SMS_IN)
        await _drive(_manager(monkeypatch), [b"\r\nRING\r\n", (CLIP + "\r\n").encode()])
        return await _status(vid)

    assert _run(body) == ("pending", None)


# --- 8.2 — the message -------------------------------------------------------------------

def test_the_right_code_from_the_right_number_confirms():
    async def body():
        vid = await _open(SMS_IN)
        got = await queries.confirm_by_inbound_message(
            CALLER, code="1234", method=SMS_IN)
        return got, vid, await _status(vid)

    got, vid, status = _run(body)
    assert got == vid
    assert status == ("confirmed", SMS_IN)


def test_the_right_code_from_another_number_confirms_nothing_and_consumes_nothing():
    async def body():
        vid = await _open(SMS_IN)
        got = await queries.confirm_by_inbound_message(
            STRANGER, code="1234", method=SMS_IN)
        row = await queries.get_verification(vid, "app1")
        return got, row["status"], row["attempts"]

    assert _run(body) == (None, "pending", 0)


def test_the_wrong_code_from_the_right_number_leaves_it_pending_and_spends_no_attempt():
    """Deliberately different from the check door. There the attempt limit exists because
    a caller can walk a four-digit space; here the guess must also originate from the
    number being verified, so the only party who can spend the attempts is the person
    themselves, mistyping — and counting those locks a real person out."""
    async def body():
        vid = await _open(SMS_IN)
        got = await queries.confirm_by_inbound_message(
            CALLER, code="9999", method=SMS_IN)
        row = await queries.get_verification(vid, "app1")
        return got, row["status"], row["attempts"]

    assert _run(body) == (None, "pending", 0)


# --- 7.4 — the code must not leave the matcher by the operator's door -------------------

def _inbound(monkeypatch, phone, text):
    """Drive the inbound path the way a decoded SMS reaches it, capturing the alert."""
    alerts = []
    monkeypatch.setattr(manager_mod, "notify",
                        lambda kind, message, **kw: alerts.append(message))
    monkeypatch.setattr(manager_mod, "dispatch_inbound",
                        lambda *a, **kw: asyncio.sleep(0))
    m = _manager(monkeypatch)

    async def body():
        vid = await _open(SMS_IN, phone=phone)
        await m.handle_inbound_text(phone, text)
        return vid, await _status(vid), list(alerts)

    return _run(body)


def test_a_texted_code_from_the_right_number_confirms(monkeypatch):
    vid, status, _ = _inbound(monkeypatch, CALLER, "1234")
    assert status == ("confirmed", SMS_IN)


def test_the_code_a_person_texted_is_not_relayed_to_the_operator(monkeypatch):
    """Notifications relay message text to Telegram. A live code riding out on that path
    leaves the matcher by a door nobody thought of as a door."""
    _, _, alerts = _inbound(monkeypatch, CALLER, "Мой код 1234, спасибо")
    assert alerts, "the inbound notification must still happen"
    # The body only: the alert names the sender, and this caller's own number happens to
    # contain the digits — asserting on the whole line would pass or fail on that.
    body = alerts[0].split(": ", 1)[1]
    assert "1234" not in body, body
    assert "спасибо" in body, "only the code is redacted, not the message"


def test_an_ordinary_message_is_relayed_unchanged(monkeypatch):
    """The positive control. Redaction that eats every message has hidden a feature
    rather than protected a secret — and four digits are an ordinary thing to write."""
    _, _, alerts = _inbound(monkeypatch, CALLER, "Приеду в 1500, ждите")
    assert "1500" in alerts[0], alerts[0]


def test_a_message_that_confirms_nothing_is_still_stored_and_visible(monkeypatch):
    """8.3 — the gateway receives ordinary messages from people, and a person replying to
    a verification with a question must still be visible in the console."""
    alerts = []
    monkeypatch.setattr(manager_mod, "notify",
                        lambda kind, message, **kw: alerts.append(message))
    captured = []

    def fake_dispatch(phone, text):
        captured.append((phone, text))
        return asyncio.sleep(0)

    monkeypatch.setattr(manager_mod, "dispatch_inbound", fake_dispatch)
    m = _manager(monkeypatch)

    async def body():
        await _open(SMS_IN)
        await m.handle_inbound_text(CALLER, "а это вообще что такое?")
        return captured

    assert _run(body) == [(CALLER, "а это вообще что такое?")]
