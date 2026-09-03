"""`delivery_report_max_age_hours`: a positive number of hours, or the default.

A window of zero discards every report the gateway receives and would announce itself
only as every message expiring — a setting whose worst value looks like a network outage
is one the settings layer has to refuse rather than the operator has to remember.

The default of 168 is measured, not guessed: over 1544 reported deliveries the mean
report arrived 93 seconds after submission and the slowest took 13 hours, none over a
day; the negative verdict that prompted this change took 27 hours, which is what a
permanent failure costs while the network exhausts its retries. Seven days is six times
the worst verdict this gateway has ever seen.
"""
import asyncio

import pytest

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import SPEC_BY_KEY, store, validate_raw


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await store.load()
        return await body()
    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


def test_the_default_is_seven_days():
    spec = SPEC_BY_KEY["delivery_report_max_age_hours"]
    assert spec.default == 168


def test_zero_and_negative_are_refused():
    """Task 4.13, first half."""
    for bad in ("0", "-1", "-720"):
        with pytest.raises(ValueError):
            validate_raw(SPEC_BY_KEY["delivery_report_max_age_hours"].type, bad)


def test_a_non_number_is_refused():
    with pytest.raises(ValueError):
        validate_raw(SPEC_BY_KEY["delivery_report_max_age_hours"].type, "a week")


def test_a_positive_value_is_accepted_and_read_back():
    def body():
        async def inner():
            await store.set_many({"delivery_report_max_age_hours": "24"})
            return store.delivery_report_max_age_hours
        return inner()

    assert _run(body) == 24


def test_saving_zero_leaves_the_previous_value_standing():
    async def body():
        await store.set_many({"delivery_report_max_age_hours": "24"})
        with pytest.raises(ValueError):
            await store.set_many({"delivery_report_max_age_hours": "0"})
        return store.delivery_report_max_age_hours

    assert _run(body) == 24


def test_an_unreadable_stored_value_falls_back_to_the_default(monkeypatch):
    """Task 4.13, second half — never taken literally.

    A stored value that cannot be read as a positive integer must not become a window of
    zero by accident, which would discard every report the gateway receives.
    """
    monkeypatch.setitem(store._cache, "delivery_report_max_age_hours", "not a number")
    assert store.delivery_report_max_age_hours == 168
    monkeypatch.setitem(store._cache, "delivery_report_max_age_hours", "0")
    assert store.delivery_report_max_age_hours == 168, (
        "a zero that got past validation — an older row, a hand-edited database — is "
        "still not a window"
    )
