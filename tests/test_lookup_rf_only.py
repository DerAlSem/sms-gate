import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries
from app.lookup import operator, voxlink


async def _fresh():
    await init_db(":memory:")
    await run_migrations()
    db = await queries.get_db()
    await db.execute("INSERT OR IGNORE INTO apps (id, token) VALUES ('admin','t')")
    await db.commit()


def test_record_operator_skips_non_ru(monkeypatch):
    calls = []
    async def fake_lookup(*a, **k):
        calls.append(a)
        return None
    monkeypatch.setattr(voxlink, "lookup", fake_lookup)

    async def run():
        await _fresh()
        try:
            await operator.record_operator("+441234567890")
        finally:
            await close_db()
    asyncio.run(run())
    assert calls == []


def test_record_operator_runs_for_ru(monkeypatch):
    calls = []
    async def fake_lookup(msisdn10, *a, **k):
        calls.append(msisdn10)
        return None
    monkeypatch.setattr(voxlink, "lookup", fake_lookup)

    async def run():
        await _fresh()
        try:
            await operator.record_operator("+79991234567")
        finally:
            await close_db()
    asyncio.run(run())
    assert calls == ["9991234567"]


def test_list_unresolved_excludes_non_ru():
    async def run():
        await _fresh()
        try:
            await queries.create_message("admin", "+79991234567", "a")
            await queries.create_message("admin", "+441234567890", "b")
            rows = await queries.list_unresolved_numbers()
            return [r["phone"] for r in rows]
        finally:
            await close_db()
    phones = asyncio.run(run())
    assert phones == ["+79991234567"]
