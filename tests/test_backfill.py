# tests/test_backfill.py
import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries
from app.lookup import backfill, voxlink
from app.lookup.voxlink import RangeInfo


async def _fresh_db():
    await init_db(":memory:")
    await run_migrations()
    db = await queries.get_db()
    await db.execute("INSERT OR IGNORE INTO apps (id, token) VALUES ('admin', 'tok')")
    await db.commit()


def test_list_unresolved_numbers_fifo_excludes_cached_and_dedups():
    async def run():
        await _fresh_db()
        await queries.create_message("admin", "+79995550011", "a")   # id=1
        await queries.create_message("admin", "+79995550022", "b")   # id=2
        await queries.create_message("admin", "+79995550011", "c")   # dup number
        # one number already resolved -> excluded
        await queries.save_number_operator("+79995550022", "MegaFon", "Moscow")
        try:
            rows = await queries.list_unresolved_numbers()
            return [(r["phone"], r["msisdn10"]) for r in rows]
        finally:
            await close_db()
    # +79995550022 resolved -> excluded; only +79995550011 remains, once
    assert asyncio.run(run()) == [("+79995550011", "9995550011")]


def test_list_unresolved_numbers_orders_oldest_first():
    async def run():
        await _fresh_db()
        await queries.create_message("admin", "+79991112233", "a")   # id=1
        await queries.create_message("admin", "+79001112233", "b")   # id=2
        await queries.create_message("admin", "+79501112233", "c")   # id=3
        try:
            rows = await queries.list_unresolved_numbers()
            return [r["phone"] for r in rows]
        finally:
            await close_db()
    assert asyncio.run(run()) == ["+79991112233", "+79001112233", "+79501112233"]


def test_save_number_operator_upsert_refreshes():
    async def run():
        await _fresh_db()
        await queries.save_number_operator("+79995550011", "MTS", "Samara")
        await queries.save_number_operator("+79995550011", "T-Mobile", "Moscow")
        try:
            row = await queries.get_number_operator("+79995550011")
            return dict(row)
        finally:
            await close_db()
    row = asyncio.run(run())
    assert row["operator"] == "T-Mobile"
    assert row["region"] == "Moscow"


class _FakeAsyncClient:
    """No-op stand-in for httpx.AsyncClient (the real lookup is monkeypatched,
    so the client is never used; this just avoids env-proxy construction)."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def test_backfill_writes_only_resolved_with_retry(monkeypatch):
    monkeypatch.setattr(backfill.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient())

    async def run():
        await _fresh_db()
        await queries.create_message("admin", "+79995550011", "a")   # resolves on retry
        await queries.create_message("admin", "+79991112233", "x")   # never resolves

        calls = {}

        async def fake_lookup(msisdn10, url, timeout, client=None):
            calls[msisdn10] = calls.get(msisdn10, 0) + 1
            if msisdn10 == "9995550011":
                if calls[msisdn10] == 1:
                    return None                       # fail once
                return RangeInfo(allocated=True, operator="T-Mobile", region="Moscow")
            return None                               # 999... never resolves

        monkeypatch.setattr(voxlink, "lookup", fake_lookup)
        try:
            result = await backfill.backfill_ranges(throttle=0.0)
            ok = await queries.get_number_operator("+79995550011")
            missing = await queries.get_number_operator("+79991112233")
            return result, dict(ok) if ok else None, missing, calls
        finally:
            await close_db()

    result, ok, missing, calls = asyncio.run(run())
    assert result == {"total": 2, "resolved": 1, "skipped": 1}
    assert ok["operator"] == "T-Mobile"
    assert missing is None                            # unresolved -> nothing written
    assert calls["9995550011"] == 2                   # retried once
    assert calls["9991112233"] == 2                   # retried once
