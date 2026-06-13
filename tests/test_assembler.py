import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries
from app.modem import assembler
from app.modem.pdu import ConcatInfo


async def _fresh_db():
    await init_db(":memory:")
    await run_migrations()


def test_single_part_saved_immediately():
    async def run():
        await _fresh_db()
        try:
            full = await assembler.handle_inbound("+7999", "hi", None)
            rows = await queries.list_inbound(None, 10, 0)
            return full, [(r["phone"], r["text"]) for r in rows]
        finally:
            await close_db()
    full, rows = asyncio.run(run())
    assert full == "hi"
    assert rows == [("+7999", "hi")]


def test_multipart_waits_then_assembles_in_seq_order():
    async def run():
        await _fresh_db()
        try:
            r2 = await assembler.handle_inbound("+7999", "part2", ConcatInfo(5, 2, 2))
            mid = await queries.list_inbound(None, 10, 0)
            r1 = await assembler.handle_inbound("+7999", "part1", ConcatInfo(5, 2, 1))
            rows = await queries.list_inbound(None, 10, 0)
            parts_left = await queries.get_inbound_parts("+7999", 5, 2)
            return r2, len(mid), r1, [r["text"] for r in rows], len(parts_left)
        finally:
            await close_db()
    r2, mid_count, r1, texts, parts_left = asyncio.run(run())
    assert r2 is None and mid_count == 0
    assert r1 == "part1part2"
    assert texts == ["part1part2"]
    assert parts_left == 0


def test_duplicate_part_does_not_complete():
    async def run():
        await _fresh_db()
        try:
            a = await assembler.handle_inbound("+7999", "p1", ConcatInfo(5, 2, 1))
            b = await assembler.handle_inbound("+7999", "p1", ConcatInfo(5, 2, 1))
            return a, b
        finally:
            await close_db()
    assert asyncio.run(run()) == (None, None)


def test_single_part_concat_total_1_saved_immediately():
    # Some SMSCs send a concat-UDH even for a single part (total=1)
    async def run():
        await _fresh_db()
        try:
            full = await assembler.handle_inbound("+7999", "solo", ConcatInfo(7, 1, 1))
            rows = await queries.list_inbound(None, 10, 0)
            return full, [r["text"] for r in rows]
        finally:
            await close_db()
    full, texts = asyncio.run(run())
    assert full == "solo"
    assert texts == ["solo"]


def test_flush_stale_parts():
    async def run():
        await _fresh_db()
        try:
            await assembler.handle_inbound("+7999", "p1", ConcatInfo(5, 3, 1))
            await assembler.handle_inbound("+7999", "p2", ConcatInfo(5, 3, 2))
            db = await queries.get_db()
            await db.execute(
                "UPDATE inbound_parts SET received_at = datetime('now', '-600 seconds')"
            )
            await db.commit()
            flushed = await assembler.flush_stale_parts(300)
            rows = await queries.list_inbound(None, 10, 0)
            parts_left = await queries.get_inbound_parts("+7999", 5, 3)
            return flushed, [r["text"] for r in rows], len(parts_left)
        finally:
            await close_db()
    flushed, texts, parts_left = asyncio.run(run())
    assert flushed == [("+7999", "p1p2")]
    assert texts == ["p1p2"]
    assert parts_left == 0


def test_flush_nothing_when_fresh():
    async def run():
        await _fresh_db()
        try:
            await assembler.handle_inbound("+7999", "p1", ConcatInfo(5, 3, 1))
            flushed = await assembler.flush_stale_parts(300)
            rows = await queries.list_inbound(None, 10, 0)
            return flushed, len(rows)
        finally:
            await close_db()
    assert asyncio.run(run()) == ([], 0)


def test_claim_branch_skips_save_when_group_already_deleted(monkeypatch):
    # Pin for the claim branch: if DELETE removed nothing (the flush loop
    # already took the group), the assembled message must not be saved
    async def run():
        await _fresh_db()
        try:
            await queries.save_inbound_part("+7999", 5, 2, 1, "p1")
            real_get = queries.get_inbound_parts

            async def fake_get(phone, ref, total):
                rows = await real_get(phone, ref, total)
                if len(rows) == total:
                    # simulate the flush loop winning the race in the window (without a lock this would be a race)
                    await queries.delete_inbound_parts(phone, ref, total)
                return rows

            monkeypatch.setattr(queries, "get_inbound_parts", fake_get)
            r = await assembler.handle_inbound("+7999", "p2", ConcatInfo(5, 2, 2))
            rows = await queries.list_inbound(None, 10, 0)
            return r, len(rows)
        finally:
            await close_db()
    r, n = asyncio.run(run())
    assert r is None
    assert n == 0
