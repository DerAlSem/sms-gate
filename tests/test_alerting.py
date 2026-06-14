import logging
import queue
import sys
from types import SimpleNamespace

from app.alerting import (
    TelegramNotifier,
    TelegramAlertHandler,
    setup_telegram_alerts,
    reconfigure as _reconfigure,
)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make_notifier(clock=None, **kw):
    return TelegramNotifier(
        "tok", "chat", time_fn=clock or FakeClock(), start_worker=False, **kw
    )


def test_first_signature_sends():
    n = make_notifier()
    assert n._should_send(("sig",)) == (True, 0)


def test_duplicate_within_window_suppressed():
    clock = FakeClock()
    n = make_notifier(clock=clock, dedup_window=300.0)
    assert n._should_send(("sig",)) == (True, 0)
    clock.t = 100.0
    assert n._should_send(("sig",)) == (False, 0)


def test_after_window_sends_with_suppressed_count():
    clock = FakeClock()
    n = make_notifier(clock=clock, dedup_window=300.0)
    n._should_send(("sig",))
    clock.t = 100.0
    n._should_send(("sig",))
    clock.t = 200.0
    n._should_send(("sig",))
    clock.t = 500.0
    assert n._should_send(("sig",)) == (True, 2)


def test_distinct_signatures_not_suppressed():
    n = make_notifier()
    assert n._should_send(("a",))[0] is True
    assert n._should_send(("b",))[0] is True


def test_maybe_send_no_dedup_always_enqueues():
    n = make_notifier()
    n.maybe_send("one", dedup_sig=None)
    n.maybe_send("one", dedup_sig=None)
    assert n._queue.get_nowait() == "one"
    assert n._queue.get_nowait() == "one"


def test_maybe_send_dedups_on_signature():
    clock = FakeClock()
    n = make_notifier(clock=clock, dedup_window=300.0)
    n.maybe_send("x", dedup_sig=("e",))
    n._queue.get_nowait()
    clock.t = 1.0
    n.maybe_send("x", dedup_sig=("e",))
    try:
        n._queue.get_nowait()
        assert False, "duplicate should not enqueue"
    except queue.Empty:
        pass


def test_maybe_send_truncates():
    n = make_notifier()
    n.maybe_send("z" * 5000, dedup_sig=None)
    text = n._queue.get_nowait()
    assert text.endswith("…(truncated)")
    assert len(text) <= 3520


def test_maybe_send_prepends_suppressed_note():
    clock = FakeClock()
    n = make_notifier(clock=clock, dedup_window=300.0)
    n.maybe_send("body", dedup_sig=("e",))
    n._queue.get_nowait()
    clock.t = 100.0
    n.maybe_send("body", dedup_sig=("e",))
    clock.t = 500.0
    n.maybe_send("body", dedup_sig=("e",))
    text = n._queue.get_nowait()
    assert "1 duplicates suppressed" in text
    assert "body" in text


def test_maybe_send_drops_when_queue_full():
    n = make_notifier(queue_maxsize=1)
    n.maybe_send("a", dedup_sig=None)
    n.maybe_send("b", dedup_sig=None)
    assert n._queue.qsize() == 1


def test_dropped_alert_does_not_arm_window():
    n = make_notifier(queue_maxsize=1)
    n.maybe_send("filler", dedup_sig=("f",))
    n.maybe_send("target", dedup_sig=("t",))
    n._queue.get_nowait()
    n.maybe_send("target2", dedup_sig=("t",))
    assert n._queue.get_nowait() == "target2"


def test_close_stops_worker_thread():
    n = TelegramNotifier("tok", "chat", time_fn=FakeClock(),
                         start_worker=True, sender=lambda text: None)
    n.close()
    n._queue.join()


def make_record(name="app.x", level=logging.ERROR, msg="boom %d", args=(1,), exc_info=None):
    return logging.LogRecord(name, level, "f.py", 1, msg, args, exc_info)


def test_handler_formats_and_delegates_to_notifier():
    n = make_notifier()
    h = TelegramAlertHandler(n)
    h.emit(make_record(msg="fail %d", args=(7,)))
    text = n._queue.get_nowait()
    assert "fail 7" in text
    assert "app.x" in text
    assert "ERROR" in text


def test_handler_dedups_by_record_template():
    clock = FakeClock()
    n = make_notifier(clock=clock, dedup_window=300.0)
    h = TelegramAlertHandler(n)
    h.emit(make_record())
    n._queue.get_nowait()
    clock.t = 1.0
    h.emit(make_record())
    try:
        n._queue.get_nowait()
        assert False, "duplicate should not enqueue"
    except queue.Empty:
        pass


def test_handler_format_includes_traceback():
    n = make_notifier()
    h = TelegramAlertHandler(n)
    try:
        raise ValueError("kaboom")
    except ValueError:
        rec = make_record(msg="oops", args=(), exc_info=sys.exc_info())
    text = h.format_alert(rec)
    assert "kaboom" in text
    assert "ValueError" in text


def _settings(token="", chat_id="", window=300.0, system_errors=True):
    return SimpleNamespace(
        alert_bot_token=token, alert_chat_id=chat_id, alert_dedup_window=window,
        notify_system_errors=system_errors,
    )


def _attached_handlers():
    return [h for h in logging.getLogger().handlers
            if isinstance(h, TelegramAlertHandler)]


def test_setup_no_creds_returns_none():
    assert setup_telegram_alerts(_settings()) is None


def test_setup_partial_creds_returns_none():
    assert setup_telegram_alerts(_settings(token="t")) is None
    assert setup_telegram_alerts(_settings(chat_id="c")) is None


def test_setup_with_creds_attaches_handler():
    handler = setup_telegram_alerts(_settings(token="t", chat_id="c"))
    try:
        assert handler is not None
        assert handler in _attached_handlers()
    finally:
        _reconfigure(_settings())


def test_setup_system_errors_off_builds_notifier_but_no_handler():
    import app.alerting as alerting
    handler = setup_telegram_alerts(_settings(token="t", chat_id="c", system_errors=False))
    try:
        assert handler is None
        assert _attached_handlers() == []
        assert alerting._notifier is not None
    finally:
        _reconfigure(_settings())


def test_reconfigure_no_duplicate_handlers():
    try:
        _reconfigure(_settings(token="t", chat_id="c"))
        _reconfigure(_settings(token="t2", chat_id="c2"))
        assert len(_attached_handlers()) == 1
    finally:
        _reconfigure(_settings())


def test_reconfigure_blank_creds_detaches_handler():
    _reconfigure(_settings(token="t", chat_id="c"))
    _reconfigure(_settings())
    assert _attached_handlers() == []


# --- helpers: _instance_label / _bounded ---
import html as _html
import socket as _socket
from app.alerting import _instance_label, _bounded
from app.settings_store import store as _store


def test_instance_label_falls_back_to_hostname(monkeypatch):
    monkeypatch.setitem(_store._cache, "instance_name", "")
    assert _instance_label() == _socket.gethostname()


def test_instance_label_uses_setting(monkeypatch):
    monkeypatch.setitem(_store._cache, "instance_name", "sms.deralsem.ru")
    assert _instance_label() == "sms.deralsem.ru"


def test_bounded_short_text_just_escapes():
    assert _bounded("a <b> & c", 100) == "a &lt;b&gt; &amp; c"


def test_bounded_truncates_long_text_within_budget():
    out = _bounded("z" * 500, 100)
    assert len(out) <= 101          # budget + the trailing ellipsis char
    assert out.endswith("…")


def test_bounded_never_splits_an_entity():
    out = _bounded("&" * 200, 50)
    assert "&amp;" in out
    assert not out.rstrip("…").endswith("&am")
    assert not out.rstrip("…").endswith("&")
