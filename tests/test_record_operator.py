# tests/test_record_operator.py
import asyncio
from datetime import datetime

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries
from app.lookup import operator as op
from app.lookup import voxlink
from app.lookup.operator import is_stale
from app.lookup.voxlink import RangeInfo

NOW = datetime(2026, 6, 2, 12, 0, 0)


def test_is_stale_fresh():
    assert is_stale("2026-06-01 12:00:00", 7, NOW) is False


def test_is_stale_expired():
    assert is_stale("2026-05-01 12:00:00", 7, NOW) is True


def test_is_stale_missing():
    assert is_stale(None, 7, NOW) is True


def test_is_stale_unparseable():
    assert is_stale("not-a-date", 7, NOW) is True


async def _db():
    await init_db(":memory:")
    await run_migrations()


def test_miss_saves_then_fresh_cache_skips_lookup(monkeypatch):
    async def run():
        await _db()
        calls = []

        async def fake_lookup(msisdn10, url, timeout, client=None):
            calls.append(msisdn10)
            return RangeInfo(allocated=True, operator="T-Mobile", region="Moscow")

        monkeypatch.setattr(voxlink, "lookup", fake_lookup)
        try:
            await op.record_operator("+79995550011")
            row = await queries.get_number_operator("+79995550011")
            await op.record_operator("+79995550011")  # fresh -> no 2nd lookup
            return len(calls), row["operator"], row["region"]
        finally:
            await close_db()

    n, operator, region = asyncio.run(run())
    assert n == 1
    assert (operator, region) == ("T-Mobile", "Moscow")


def test_never_raises_even_on_not_found(monkeypatch):
    async def run():
        await _db()

        async def fake_none(msisdn10, url, timeout, client=None):
            return None

        monkeypatch.setattr(voxlink, "lookup", fake_none)
        try:
            # must not raise, must not create a row
            await op.record_operator("+79001112233")
            return await queries.get_number_operator("+79001112233")
        finally:
            await close_db()

    assert asyncio.run(run()) is None


def test_stale_row_failed_refresh_keeps_old_value(monkeypatch):
    async def run():
        await _db()

        async def fake_none(msisdn10, url, timeout, client=None):
            return None

        monkeypatch.setattr(voxlink, "lookup", fake_none)
        db = await queries.get_db()
        await db.execute(
            "INSERT INTO number_operators (phone, operator, region, checked_at) "
            "VALUES ('+79995550011', 'MTS', 'Samara', '2000-01-01 00:00:00')"
        )
        await db.commit()
        try:
            await op.record_operator("+79995550011")
            row = await queries.get_number_operator("+79995550011")
            return row["operator"]
        finally:
            await close_db()

    assert asyncio.run(run()) == "MTS"  # not downgraded to blank
