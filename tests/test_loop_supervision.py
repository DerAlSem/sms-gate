"""Background loops that die, and the silence that hid one for five hours.

`reader_loop` has no exception handling inside its `while True`, and `main.py` collected
every background task with `asyncio.gather(..., return_exceptions=True)` — which returns
each exception and then drops it. So the loop delivering `+CDS` and `+CMTI` could
terminate without a single line anywhere: no delivery reports, no inbound SMS, and no
health check able to notice.

The guards matter as much as the supervision. Shutdown cancels every task by design, so a
callback that cannot tell cancellation from a crash would alert on every loop at every
deploy and exit instead of closing the modem and the database.
"""

import asyncio
import logging

import pytest

from app.supervision import supervise


def _run(body):
    return asyncio.run(body())


def test_a_loop_that_dies_is_logged_with_its_traceback(caplog):
    async def body():
        async def boom():
            raise RuntimeError("the reader loop fell over")

        task = asyncio.get_event_loop().create_task(boom())
        supervise(task, name="reader", essential=False)
        await asyncio.sleep(0.01)

    with caplog.at_level(logging.ERROR):
        _run(body)

    assert any("reader" in r.message for r in caplog.records), "a loop died in silence"
    assert any(r.exc_info for r in caplog.records), "no traceback was recorded"


def test_an_essential_loop_that_dies_ends_the_service():
    exits = []

    async def body():
        async def boom():
            raise RuntimeError("the sender loop fell over")

        task = asyncio.get_event_loop().create_task(boom())
        supervise(task, name="sender", essential=True, on_fatal=lambda n: exits.append(n))
        await asyncio.sleep(0.01)

    _run(body)
    assert exits == ["sender"], "a loop the gateway cannot work without died quietly"


def test_cancellation_during_shutdown_is_not_a_death(caplog):
    """Shutdown cancels every task. Without this guard every deploy alerts on every loop
    and exits instead of closing the modem and the database."""
    exits = []

    async def body():
        async def forever():
            await asyncio.sleep(3600)

        task = asyncio.get_event_loop().create_task(forever())
        supervise(task, name="expire", essential=True, on_fatal=lambda n: exits.append(n))
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.01)

    with caplog.at_level(logging.ERROR):
        _run(body)

    assert exits == [], "an orderly shutdown was treated as a crash"
    assert not [r for r in caplog.records if "expire" in r.message], "shutdown logged a failure"


def test_a_loop_that_returns_normally_is_not_a_death():
    exits = []

    async def body():
        async def finishes():
            return None

        task = asyncio.get_event_loop().create_task(finishes())
        supervise(task, name="oneshot", essential=True, on_fatal=lambda n: exits.append(n))
        await asyncio.sleep(0.01)

    _run(body)
    assert exits == []


# --- the alert has to outlive the decision to exit -----------------------------


def test_a_fatal_alert_is_delivered_before_the_process_ends(monkeypatch):
    """Alerts are queued and delivered by a background thread; an immediate exit throws
    the queue away. A loud new exit that nobody hears is the same silence again."""
    import app.alerting as alerting

    sent = []
    notifier = alerting.TelegramNotifier(
        "t", "c", sender=lambda text: sent.append(text) or 1
    )
    monkeypatch.setattr(alerting, "_notifier", notifier)

    order = []
    monkeypatch.setattr(alerting, "drain", lambda timeout=5.0: order.append("drained"))

    from app import supervision

    monkeypatch.setattr(supervision.os, "_exit", lambda code: order.append("exited"))
    supervision._exit_service("sender")

    assert order == ["drained", "exited"], f"the alert was discarded by the exit: {order}"


def test_a_notification_that_cannot_be_queued_is_recorded(caplog):
    """`queue.Full` dropped the notification and said nothing — and a long incident is
    exactly when the queue is most likely to fill."""
    import app.alerting as alerting

    notifier = alerting.TelegramNotifier(
        "t", "c", queue_maxsize=1, start_worker=False, sender=lambda text: 1
    )
    with caplog.at_level(logging.WARNING):
        notifier.maybe_send("first")
        notifier.maybe_send("second")   # no worker is draining, so this one cannot fit

    assert notifier.dropped == 1
    assert any("drop" in r.message.lower() for r in caplog.records), (
        "a dropped notification left no trace"
    )


def test_a_notification_that_cannot_be_delivered_is_recorded(caplog):
    """The worker swallows every exception on purpose, to keep alerting from failing the
    thing it reports on. Swallowing it *silently* makes a broken alerting path
    indistinguishable from a system with nothing to report."""
    import app.alerting as alerting

    def refuse(text):
        raise RuntimeError("telegram unreachable")

    notifier = alerting.TelegramNotifier("t", "c", start_worker=False, sender=refuse)
    notifier.maybe_send("hello")
    with caplog.at_level(logging.WARNING):
        notifier._drain_once()

    assert notifier.undelivered == 1
    assert any("deliver" in r.message.lower() for r in caplog.records)


def test_the_application_module_imports():
    """A guard, not a formality: the whole suite passed while `app.main` was broken by a
    mangled import, because nothing imports it. A gateway that cannot start is the one
    failure no unit test was catching."""
    import importlib

    import app.main

    importlib.reload(app.main)
    assert hasattr(app.main, "app")
