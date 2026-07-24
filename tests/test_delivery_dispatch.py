"""Delivery dispatch: the outbound counterpart of inbound dispatch.

Routes key off `messages.app_id` (the app that sent the message), so unlike inbound
there is no prefix to parse — but the same transport, retry ladder and failure alert.
"""
import asyncio
import json
from datetime import datetime

import pytest

import app.alerting as alerting
import app.modem.delivery_dispatch as dd
from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from conftest import FakeResponse, fake_webhook_client


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def maybe_send(self, text, dedup_sig=None, phone=None):
        self.calls.append((text, dedup_sig, phone))


ROUTE = {"app_id": "app1", "webhook_url": "https://x.test/delivery", "bearer": "tok"}


@pytest.fixture
def env(monkeypatch):
    """One configured route for app `app1`, alerts on, no retry ladder."""
    fake = FakeNotifier()
    monkeypatch.setattr(alerting, "_notifier", fake)
    monkeypatch.setitem(store._cache, "notify_dispatch_errors", "true")
    monkeypatch.setitem(store._cache, "inbound_dispatch_retries", "1")
    monkeypatch.setitem(store._cache, "delivery_dispatch", json.dumps([ROUTE]))
    return fake


def _with_db(coro):
    async def run():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        return await coro()
    try:
        return asyncio.run(run())
    finally:
        asyncio.run(close_db())


def test_body_carries_id_status_error_and_occurred_at(monkeypatch, env):
    posted = fake_webhook_client(monkeypatch, lambda *a: FakeResponse(200))

    async def body():
        mid = await queries.create_message("app1", "+79991234567", "hi")
        assert await dd.dispatch_delivery(mid, "delivered") is True
        return mid, posted

    mid, posted = _with_db(body)
    url, payload, _ = posted[0]
    assert url == "https://x.test/delivery"
    assert payload["id"] == mid
    assert payload["status"] == "delivered"
    assert payload["error"] is None
    # parses as an aware UTC timestamp
    parsed = datetime.fromisoformat(payload["occurred_at"].replace("Z", "+00:00"))
    assert parsed.utcoffset().total_seconds() == 0


def test_error_text_is_passed_through(monkeypatch, env):
    posted = fake_webhook_client(monkeypatch, lambda *a: FakeResponse(200))

    async def body():
        mid = await queries.create_message("app1", "+7985", "hi")
        await dd.dispatch_delivery(mid, "failed", "service rejected (temporary, st=99)")

    _with_db(body)
    assert posted[0][1]["status"] == "failed"
    assert posted[0][1]["error"] == "service rejected (temporary, st=99)"


def test_api_created_message_has_no_resent_from(monkeypatch, env):
    posted = fake_webhook_client(monkeypatch, lambda *a: FakeResponse(200))

    async def body():
        mid = await queries.create_message("app1", "+7985", "hi")
        await dd.dispatch_delivery(mid, "sent")

    _with_db(body)
    assert "resent_from" not in posted[0][1]


def test_resent_message_carries_resent_from(monkeypatch, env):
    posted = fake_webhook_client(monkeypatch, lambda *a: FakeResponse(200))

    async def body():
        original = await queries.create_message("app1", "+7985", "hi")
        copy = await queries.create_message("app1", "+7985", "hi", resent_from=original)
        await dd.dispatch_delivery(copy, "delivered")
        return original, copy

    original, copy = _with_db(body)
    assert posted[0][1]["id"] == copy
    assert posted[0][1]["resent_from"] == original


def test_bearer_header_is_sent(monkeypatch, env):
    posted = fake_webhook_client(monkeypatch, lambda *a: FakeResponse(204))

    async def body():
        mid = await queries.create_message("app1", "+7985", "hi")
        await dd.dispatch_delivery(mid, "sent")

    _with_db(body)
    assert posted[0][2]["Authorization"] == "Bearer tok"


def test_app_without_a_route_is_silent(monkeypatch, env):
    """An unconfigured app is not a gateway fault — no POST, no alert."""
    posted = fake_webhook_client(monkeypatch, lambda *a: FakeResponse(200))

    async def body():
        await queries.create_app("turbo", "token-turbo")
        mid = await queries.create_message("turbo", "+7985", "hi")
        return await dd.dispatch_delivery(mid, "delivered")

    assert _with_db(body) is False
    assert posted == []
    assert env.calls == []


def test_successful_dispatch_is_silent(monkeypatch, env):
    fake_webhook_client(monkeypatch, lambda *a: FakeResponse(200))

    async def body():
        mid = await queries.create_message("app1", "+7985", "hi")
        return await dd.dispatch_delivery(mid, "delivered")

    assert _with_db(body) is True
    assert env.calls == []


def test_failed_dispatch_alerts_the_operator(monkeypatch, env):
    fake_webhook_client(monkeypatch, lambda *a: FakeResponse(401, "unauthorized"))

    async def body():
        mid = await queries.create_message("app1", "+7985", "hi")
        return await dd.dispatch_delivery(mid, "delivered"), mid

    (ok, mid) = _with_db(body)
    assert ok is False
    assert len(env.calls) == 1
    text, dedup_sig, _ = env.calls[0]
    assert "app1" in text and str(mid) in text and "delivered" in text and "401" in text
    assert dedup_sig == ("dispatch_error", "https://x.test/delivery")


def test_a_dead_endpoint_alerts_once_per_window(monkeypatch, env):
    """Dedup is on the url, so a burst of messages does not become a burst of alerts."""
    fake_webhook_client(monkeypatch, lambda *a: FakeResponse(500))
    sigs = []

    class DedupingNotifier(FakeNotifier):
        def maybe_send(self, text, dedup_sig=None, phone=None):
            if dedup_sig in sigs:
                return
            sigs.append(dedup_sig)
            super().maybe_send(text, dedup_sig, phone)

    fake = DedupingNotifier()
    monkeypatch.setattr(alerting, "_notifier", fake)

    async def body():
        for _ in range(5):
            mid = await queries.create_message("app1", "+7985", "hi")
            await dd.dispatch_delivery(mid, "failed", "boom")

    _with_db(body)
    assert len(fake.calls) == 1


def test_delivered_is_not_queued_behind_a_slow_sent(monkeypatch, env):
    """Notifications are independent tasks (design D6): a delivery report must not wait
    out a `sent` that is stuck retrying. Here `sent` blocks on an event that only the
    `delivered` POST releases — so if they were serialized this would deadlock."""
    gate = asyncio.Event()
    order = []

    async def handler(url, payload, headers):
        status = payload["status"]
        if status == "sent":
            await gate.wait()          # sent cannot finish until delivered has run
        order.append(status)
        if status == "delivered":
            gate.set()
        return FakeResponse(200)

    fake_webhook_client(monkeypatch, handler)

    async def body():
        mid = await queries.create_message("app1", "+7985", "hi")
        await asyncio.wait_for(
            asyncio.gather(
                dd.dispatch_delivery(mid, "sent"),
                dd.dispatch_delivery(mid, "delivered"),
            ),
            timeout=2.0,
        )

    _with_db(body)
    assert order == ["delivered", "sent"], "delivered was blocked behind sent"


def test_unknown_message_is_a_noop(monkeypatch, env):
    posted = fake_webhook_client(monkeypatch, lambda *a: FakeResponse(200))

    async def body():
        return await dd.dispatch_delivery(999_999, "delivered")

    assert _with_db(body) is False
    assert posted == []
    assert env.calls == []
