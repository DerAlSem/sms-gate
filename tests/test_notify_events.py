import app.alerting as alerting
from app.alerting import notify
from app.settings_store import store


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def maybe_send(self, text, dedup_sig=None):
        self.calls.append((text, dedup_sig))


def _install(monkeypatch, **toggles):
    fake = FakeNotifier()
    monkeypatch.setattr(alerting, "_notifier", fake)
    for key, val in toggles.items():
        monkeypatch.setitem(store._cache, key, "true" if val else "false")
    return fake


def test_notify_noop_when_no_notifier(monkeypatch):
    monkeypatch.setattr(alerting, "_notifier", None)
    notify("inbound", "hi")   # must not raise


def test_notify_respects_toggle_off(monkeypatch):
    fake = _install(monkeypatch, notify_send_errors=False)
    notify("send_error", "boom", dedup_extra="x")
    assert fake.calls == []


def test_notify_send_error_dedups_on_event_and_extra(monkeypatch):
    fake = _install(monkeypatch, notify_send_errors=True)
    notify("send_error", "boom", dedup_extra="+CMS ERROR 305")
    assert len(fake.calls) == 1
    text, sig = fake.calls[0]
    assert "boom" in text
    assert sig == ("send_error", "+CMS ERROR 305")


def test_notify_inbound_has_no_dedup(monkeypatch):
    fake = _install(monkeypatch, notify_inbound=True)
    notify("inbound", "msg one")
    notify("inbound", "msg one")
    assert len(fake.calls) == 2
    assert all(sig is None for _, sig in fake.calls)


def test_notify_delivery_error_dedup_sig(monkeypatch):
    fake = _install(monkeypatch, notify_delivery_errors=True)
    notify("delivery_error", "fail", dedup_extra=65)
    assert fake.calls[0][1] == ("delivery_error", 65)


# --- manager call sites ---
import asyncio

import app.modem.manager as manager_mod
from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries
from app.modem.manager import ModemManager
from app.modem.parser import DeliveryReport
from app.modem.at_commands import ATCommandError


def _record_notify(monkeypatch):
    calls = []
    monkeypatch.setattr(manager_mod, "notify", lambda *a, **k: calls.append((a, k)))
    return calls


def test_send_failure_notifies_send_error(monkeypatch):
    calls = _record_notify(monkeypatch)

    async def run():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "tok1", "t")
        mid = await queries.create_message("app1", "+79991234567", "hi")
        m = ModemManager("/dev/null", "/dev/null")

        async def boom(parts, on_part_sent, timeout=30.0):
            raise ATCommandError("+CMS ERROR 305 (invalid text mode parameter)")
        monkeypatch.setattr(m._sender, "send_sms_pdu", boom)

        await m.enqueue(mid, "+79991234567", "hi", "app1")
        task = asyncio.create_task(m.sender_loop())
        await m._queue.join()
        task.cancel()
        await close_db()

    asyncio.run(run())
    types = [a[0] for a, k in calls]
    assert "send_error" in types


def test_delivery_failure_notifies(monkeypatch):
    calls = _record_notify(monkeypatch)

    async def run():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "tok1", "t")
        mid = await queries.create_message("app1", "+79991234567", "hi")
        await queries.set_message_sent(mid, 200)
        await queries.add_message_part(mid, 200, 1, 1)
        m = ModemManager("/dev/null", "/dev/null")
        await m._handle_cds(DeliveryReport(modem_ref=200, delivered=False, status_code=0x41))
        await close_db()

    asyncio.run(run())
    types = [a[0] for a, k in calls]
    assert "delivery_error" in types


def test_inbound_notifies(monkeypatch):
    calls = _record_notify(monkeypatch)
    monkeypatch.setattr(manager_mod, "dispatch_inbound",
                        lambda *a, **k: asyncio.sleep(0))

    async def run():
        m = ModemManager("/dev/null", "/dev/null")
        m._spawn_dispatch("+79991234567", "hello")
        await asyncio.sleep(0)

    asyncio.run(run())
    types = [a[0] for a, k in calls]
    assert "inbound" in types


def test_notify_inbound_html_format(monkeypatch):
    fake = _install(monkeypatch, notify_inbound=True)
    monkeypatch.setitem(store._cache, "instance_name", "sms.deralsem.ru")
    notify("inbound", "+79261234567: Привет")
    text, sig = fake.calls[0]
    assert text.startswith("<b>📨 Inbound · sms.deralsem.ru</b>\n")
    assert text.endswith("+79261234567: Привет")
    assert sig is None


def test_notify_escapes_html_in_body(monkeypatch):
    fake = _install(monkeypatch, notify_inbound=True)
    notify("inbound", "a <b> & c")
    text, _ = fake.calls[0]
    assert "a &lt;b&gt; &amp; c" in text


def test_notify_send_error_title(monkeypatch):
    fake = _install(monkeypatch, notify_send_errors=True)
    notify("send_error", "+7999 (id 5): boom", dedup_extra="boom")
    text, _ = fake.calls[0]
    assert text.startswith("<b>🔴 Send failed · ")
