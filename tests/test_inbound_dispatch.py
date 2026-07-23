"""Inbound dispatch: delivery outcome and the operator alert on failure.

A failed webhook used to be visible only as three WARNING lines in journalctl —
the gateway looked healthy while the receiving app never learned about the SMS.
"""
import asyncio
import json

import httpx
import pytest

import app.alerting as alerting
import app.modem.dispatch as dispatch
from app.settings_store import store


class FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def maybe_send(self, text, dedup_sig=None, phone=None):
        self.calls.append((text, dedup_sig, phone))


def _route(**over):
    route = {"prefix": "GMP", "webhook_url": "https://x.test/hook", "bearer": "tok"}
    route.update(over)
    return route


@pytest.fixture
def env(monkeypatch):
    """One configured GMP route, alerts on, no retry ladder (keeps tests instant)."""
    fake = FakeNotifier()
    monkeypatch.setattr(alerting, "_notifier", fake)
    monkeypatch.setitem(store._cache, "notify_dispatch_errors", "true")
    monkeypatch.setitem(store._cache, "inbound_dispatch_retries", "1")
    monkeypatch.setitem(store._cache, "inbound_dispatch", json.dumps([_route()]))
    return fake


def _fake_client(monkeypatch, handler):
    """Patch httpx.AsyncClient so `handler(url, json, headers)` decides the outcome."""
    posted = []

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            posted.append((url, json, headers))
            return handler(url, json, headers)

    monkeypatch.setattr(dispatch.httpx, "AsyncClient", FakeClient)
    return posted


def test_deliver_reports_success_with_no_error(monkeypatch, env):
    _fake_client(monkeypatch, lambda *a: FakeResponse(200))
    ok, err = asyncio.run(dispatch.deliver(_route(), {"phone": "+7", "text": "GMP 1"}))
    assert ok is True
    assert err is None


def test_deliver_reports_the_status_on_non_2xx(monkeypatch, env):
    _fake_client(monkeypatch, lambda *a: FakeResponse(401, "unauthorized"))
    ok, err = asyncio.run(dispatch.deliver(_route(), {}))
    assert ok is False
    assert "401" in err


def test_deliver_reports_the_exception_on_transport_error(monkeypatch, env):
    def boom(*a):
        raise httpx.ConnectError("nope")

    _fake_client(monkeypatch, boom)
    ok, err = asyncio.run(dispatch.deliver(_route(), {}))
    assert ok is False
    assert "ConnectError" in err


def test_deliver_sends_bearer_and_payload(monkeypatch, env):
    posted = _fake_client(monkeypatch, lambda *a: FakeResponse(204))
    asyncio.run(dispatch.deliver(_route(), {"phone": "+79851600019", "text": "GMP 8U5Z6G"}))
    url, payload, headers = posted[0]
    assert url == "https://x.test/hook"
    assert payload == {"phone": "+79851600019", "text": "GMP 8U5Z6G"}
    assert headers["Authorization"] == "Bearer tok"


def test_failed_dispatch_alerts_the_operator(monkeypatch, env):
    _fake_client(monkeypatch, lambda *a: FakeResponse(401, "unauthorized"))
    ok = asyncio.run(dispatch.dispatch_inbound("+79851600019", "GMP 8U5Z6G"))
    assert ok is False
    assert len(env.calls) == 1, "a matched route that failed to deliver must alert"
    text, dedup_sig, phone = env.calls[0]
    assert "GMP" in text and "https://x.test/hook" in text and "401" in text
    assert phone == "+79851600019"
    assert dedup_sig == ("dispatch_error", "https://x.test/hook")


def test_successful_dispatch_is_silent(monkeypatch, env):
    _fake_client(monkeypatch, lambda *a: FakeResponse(200))
    assert asyncio.run(dispatch.dispatch_inbound("+79851600019", "GMP 8U5Z6G")) is True
    assert env.calls == []


def test_unrouted_sms_is_silent(monkeypatch, env):
    """Ordinary SMS with no matching prefix are not a gateway fault — no alert."""
    _fake_client(monkeypatch, lambda *a: FakeResponse(200))
    assert asyncio.run(dispatch.dispatch_inbound("+79851600019", "привет как дела")) is False
    assert env.calls == []


def test_alert_can_be_switched_off(monkeypatch, env):
    monkeypatch.setitem(store._cache, "notify_dispatch_errors", "false")
    _fake_client(monkeypatch, lambda *a: FakeResponse(500))
    asyncio.run(dispatch.dispatch_inbound("+79851600019", "GMP 8U5Z6G"))
    assert env.calls == []
