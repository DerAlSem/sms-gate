import asyncio

import app.telegram_poll as tp
from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries


class FakeModem:
    def __init__(self):
        self.enqueued = []

    async def enqueue(self, message_id, phone, text, app_id=""):
        self.enqueued.append((message_id, phone, text, app_id))


def _reply_update(update_id, chat_id, reply_to_id, text):
    return {
        "update_id": update_id,
        "channel_post": {
            "chat": {"id": chat_id},
            "text": text,
            "reply_to_message": {"message_id": reply_to_id},
        },
    }


def test_known_reply_enqueues_sms():
    async def run():
        await init_db(":memory:")
        await run_migrations()
        await queries.add_notify_ref(100, "+79991234567")
        modem = FakeModem()
        await tp._handle_update(_reply_update(1, -100123, 100, "ответ абоненту"), -100123, modem)
        await close_db()
        return modem.enqueued
    enq = asyncio.run(run())
    assert len(enq) == 1
    _mid, phone, text, app_id = enq[0]
    assert phone == "+79991234567"
    assert text == "ответ абоненту"
    assert app_id == "telegram"


def test_wrong_chat_ignored():
    async def run():
        await init_db(":memory:")
        await run_migrations()
        await queries.add_notify_ref(100, "+79991234567")
        modem = FakeModem()
        await tp._handle_update(_reply_update(1, -999, 100, "x"), -100123, modem)
        await close_db()
        return modem.enqueued
    assert asyncio.run(run()) == []


def test_no_reply_ignored():
    async def run():
        await init_db(":memory:")
        await run_migrations()
        modem = FakeModem()
        upd = {"update_id": 1, "channel_post": {"chat": {"id": -100123}, "text": "hi"}}
        await tp._handle_update(upd, -100123, modem)
        await close_db()
        return modem.enqueued
    assert asyncio.run(run()) == []


def test_unknown_ref_no_enqueue():
    async def run():
        await init_db(":memory:")
        await run_migrations()
        modem = FakeModem()
        await tp._handle_update(_reply_update(1, -100123, 777, "x"), -100123, modem)
        await close_db()
        return modem.enqueued
    assert asyncio.run(run()) == []


def test_empty_text_ignored():
    async def run():
        await init_db(":memory:")
        await run_migrations()
        await queries.add_notify_ref(100, "+79991234567")
        modem = FakeModem()
        await tp._handle_update(_reply_update(1, -100123, 100, ""), -100123, modem)
        await close_db()
        return modem.enqueued
    assert asyncio.run(run()) == []


def test_drain_backlog_returns_last_plus_one(monkeypatch):
    async def fake_get_updates(token, offset, timeout):
        return [{"update_id": 7}, {"update_id": 8}]
    monkeypatch.setattr(tp, "_get_updates", fake_get_updates)
    assert asyncio.run(tp._drain_backlog("tok")) == 9


def test_drain_backlog_empty_returns_zero(monkeypatch):
    async def fake_get_updates(token, offset, timeout):
        return []
    monkeypatch.setattr(tp, "_get_updates", fake_get_updates)
    assert asyncio.run(tp._drain_backlog("tok")) == 0
