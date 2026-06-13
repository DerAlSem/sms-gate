import logging
import queue
import sys

from app.alerting import TelegramAlertHandler


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make_record(name="app.x", level=logging.ERROR, msg="boom %d", args=(1,), exc_info=None):
    return logging.LogRecord(name, level, "f.py", 1, msg, args, exc_info)


def make_handler(clock=None, **kw):
    return TelegramAlertHandler(
        "tok", "chat", time_fn=clock or FakeClock(), start_worker=False, **kw
    )


def test_first_event_sends():
    h = make_handler()
    assert h._should_send(make_record()) == (True, 0)


def test_duplicate_within_window_suppressed():
    clock = FakeClock()
    h = make_handler(clock=clock, dedup_window=300.0)
    assert h._should_send(make_record()) == (True, 0)
    clock.t = 100.0
    assert h._should_send(make_record()) == (False, 0)


def test_after_window_sends_with_suppressed_count():
    clock = FakeClock()
    h = make_handler(clock=clock, dedup_window=300.0)
    h._should_send(make_record())          # t=0, send
    clock.t = 100.0
    h._should_send(make_record())          # suppressed #1
    clock.t = 200.0
    h._should_send(make_record())          # suppressed #2
    clock.t = 500.0                         # 500 - 0 >= 300 -> send again
    assert h._should_send(make_record()) == (True, 2)


def test_distinct_signatures_not_suppressed():
    h = make_handler()
    assert h._should_send(make_record(msg="alpha %d"))[0] is True
    assert h._should_send(make_record(msg="beta %d"))[0] is True


def test_emit_enqueues_formatted_text():
    h = make_handler()
    h.emit(make_record(msg="fail %d", args=(7,)))
    text = h._queue.get_nowait()
    assert "fail 7" in text
    assert "app.x" in text
    assert "ERROR" in text


def test_emit_suppressed_does_not_enqueue():
    clock = FakeClock()
    h = make_handler(clock=clock, dedup_window=300.0)
    h.emit(make_record())
    h._queue.get_nowait()                   # first one enqueued
    clock.t = 1.0
    h.emit(make_record())                   # duplicate -> suppressed
    try:
        h._queue.get_nowait()
        assert False, "duplicate should not have been enqueued"
    except queue.Empty:
        pass


def test_format_includes_traceback():
    h = make_handler()
    try:
        raise ValueError("kaboom")
    except ValueError:
        rec = make_record(msg="oops", args=(), exc_info=sys.exc_info())
    text = h.format_alert(rec)
    assert "kaboom" in text
    assert "ValueError" in text


def test_emit_drops_when_queue_full():
    h = make_handler(queue_maxsize=1)
    h.emit(make_record(msg="a %d", args=(1,)))   # fills queue
    h.emit(make_record(msg="b %d", args=(2,)))   # would block -> must drop, not raise
    assert h._queue.qsize() == 1


import logging as _logging
from types import SimpleNamespace

from app.alerting import setup_telegram_alerts


def _settings(token="", chat_id="", window=300.0):
    return SimpleNamespace(
        alert_bot_token=token, alert_chat_id=chat_id, alert_dedup_window=window
    )


def test_setup_no_creds_returns_none():
    assert setup_telegram_alerts(_settings()) is None


def test_setup_partial_creds_returns_none():
    assert setup_telegram_alerts(_settings(token="t")) is None
    assert setup_telegram_alerts(_settings(chat_id="c")) is None


def test_setup_with_creds_attaches_handler():
    handler = setup_telegram_alerts(_settings(token="t", chat_id="c"))
    try:
        assert handler is not None
        assert handler in _logging.getLogger().handlers
    finally:
        _logging.getLogger().removeHandler(handler)


def test_dropped_alert_does_not_arm_window():
    h = make_handler(queue_maxsize=1)
    h.emit(make_record(msg="filler %d", args=(0,)))   # fills the queue (size 1)
    h.emit(make_record(msg="target %d", args=(1,)))   # queue Full -> dropped, window must NOT arm
    h._queue.get_nowait()                              # drain the filler
    h.emit(make_record(msg="target %d", args=(2,)))    # identical sig -> must send, not be suppressed
    text = h._queue.get_nowait()
    assert "target 2" in text


# --- append to tests/test_alerting.py ---
from app.alerting import reconfigure as _reconfigure


def test_reconfigure_is_idempotent_no_duplicate_handlers():
    import logging as _logging
    from app.alerting import TelegramAlertHandler

    root = _logging.getLogger()
    before = [h for h in root.handlers if isinstance(h, TelegramAlertHandler)]
    try:
        _reconfigure(_settings(token="t", chat_id="c"))
        _reconfigure(_settings(token="t2", chat_id="c2"))
        attached = [h for h in root.handlers if isinstance(h, TelegramAlertHandler)]
        assert len(attached) == len(before) + 1
    finally:
        for h in [h for h in root.handlers if isinstance(h, TelegramAlertHandler)]:
            root.removeHandler(h)


def test_reconfigure_blank_creds_detaches_handler():
    import logging as _logging
    from app.alerting import TelegramAlertHandler

    root = _logging.getLogger()
    _reconfigure(_settings(token="t", chat_id="c"))
    _reconfigure(_settings())
    attached = [h for h in root.handlers if isinstance(h, TelegramAlertHandler)]
    assert attached == []


def test_close_stops_worker_thread():
    h = TelegramAlertHandler(
        "tok", "chat", time_fn=FakeClock(), start_worker=True,
        sender=lambda text: None,
    )
    h.close()
    # join() returns once the sentinel has been processed (worker called task_done and exited)
    h._queue.join()   # deterministic: no sleep needed
