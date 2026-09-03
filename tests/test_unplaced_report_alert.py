"""The alert for a report about nothing, and its own switch.

Reusing `notify_delivery_errors` would inherit its `False` default, and the guarantee
"an unplaced report notifies an operator" would be empty on every existing install —
which is every install that has the defect.
"""
import app.alerting as alerting
from app.alerting import notify
from app.settings_store import SPEC_BY_KEY, store


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def maybe_send(self, text, dedup_sig=None, phone=None):
        self.calls.append((text, dedup_sig))


def _install(monkeypatch, **toggles):
    fake = FakeNotifier()
    monkeypatch.setattr(alerting, "_notifier", fake)
    for key, val in toggles.items():
        monkeypatch.setitem(store._cache, key, "true" if val else "false")
    return fake


def test_the_unplaced_toggle_defaults_to_on():
    spec = SPEC_BY_KEY["notify_unplaced_reports"]
    assert spec.type == "bool"
    assert spec.default is True, (
        "an install that never touched settings must still be told about a report the "
        "gateway could not place"
    )


def test_it_is_not_the_delivery_error_toggle():
    """The one it would naturally have been folded into defaults to off."""
    assert SPEC_BY_KEY["notify_delivery_errors"].default is False
    assert "notify_unplaced_reports" != "notify_delivery_errors"


def test_an_unplaced_report_notifies_when_delivery_errors_are_off(monkeypatch):
    fake = _install(monkeypatch, notify_unplaced_reports=True, notify_delivery_errors=False)
    notify("delivery_unplaced", "ref 42, +79991234567: nothing matched", dedup_extra=42)
    assert len(fake.calls) == 1
    text, sig = fake.calls[0]
    assert "nothing matched" in text
    assert sig == ("delivery_unplaced", 42), "deduped on the report's reference"


def test_it_respects_its_own_switch(monkeypatch):
    fake = _install(monkeypatch, notify_unplaced_reports=False)
    notify("delivery_unplaced", "ref 42: nothing matched", dedup_extra=42)
    assert fake.calls == []


def test_a_wrapped_counter_cannot_turn_one_fault_into_a_storm(monkeypatch):
    """Task 2.4 — through the real notifier, so the window is really exercised.

    A reference is one octet. If a counter wrap makes several reports unplaceable in a
    row, the operator gets told once, not once per report.
    """
    sent = []
    notifier = alerting.TelegramNotifier(
        "tok", "chat", dedup_window=300.0, sender=lambda *a, **kw: sent.append(a),
        start_worker=False, time_fn=lambda: 0.0,
    )
    monkeypatch.setattr(alerting, "_notifier", notifier)
    monkeypatch.setitem(store._cache, "notify_unplaced_reports", "true")

    notify("delivery_unplaced", "ref 42 (1st): nothing matched", dedup_extra=42)
    notify("delivery_unplaced", "ref 42 (2nd): nothing matched", dedup_extra=42)
    notify("delivery_unplaced", "ref 42 (3rd): nothing matched", dedup_extra=42)
    queued = [notifier._queue.get_nowait() for _ in range(notifier._queue.qsize())]
    assert len(queued) == 1, f"one notification for one reference, got {len(queued)}"

    notify("delivery_unplaced", "ref 43: nothing matched", dedup_extra=43)
    assert notifier._queue.qsize() == 1, "a different reference is a different fault"
