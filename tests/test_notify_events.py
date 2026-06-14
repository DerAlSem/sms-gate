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
