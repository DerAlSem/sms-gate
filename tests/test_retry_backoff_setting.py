"""The `send_retry_backoff` setting: one knob that fixes both the delays and, by its
length, how many attempts a message gets. Empty disables retrying, which is also the
rollback switch."""

import asyncio

import pytest

from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store, validate_raw


def _with_db(coro):
    async def run():
        await init_db(":memory:")
        await run_migrations()
        await store.load()
        return await coro()
    try:
        return asyncio.run(run())
    finally:
        asyncio.run(close_db())


def test_the_default_is_four_attempts_inside_eight_minutes():
    delays = _with_db(lambda: _as_coro(store.send_retry_backoff_parsed))
    assert delays == [30, 120, 300]
    assert len(delays) + 1 == 4
    assert sum(delays) < 600


async def _as_coro(value):
    return value


def test_an_empty_value_disables_retrying():
    async def body():
        await store.set_many({"send_retry_backoff": ""})
        return store.send_retry_backoff_parsed

    assert _with_db(body) == []


def test_a_saved_value_applies_without_a_restart():
    async def body():
        await store.set_many({"send_retry_backoff": "5, 10 ,15"})
        return store.send_retry_backoff_parsed

    assert _with_db(body) == [5, 10, 15]


@pytest.mark.parametrize("raw", ["abc", "30,abc", "30,-5", "30,0", "1.5"])
def test_a_value_that_is_not_positive_whole_seconds_is_rejected(raw):
    with pytest.raises(ValueError):
        validate_raw("delays", raw)


@pytest.mark.parametrize("raw", ["", "30", "30,120,300", " 30 , 120 ", "30,,120"])
def test_a_usable_value_is_accepted(raw):
    validate_raw("delays", raw)
