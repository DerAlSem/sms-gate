import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries
from app.modem.manager import ModemManager
from app.modem.parser import DeliveryReport


async def _fresh_db():
    await init_db(":memory:")
    await run_migrations()
    await queries.create_app("app1", "tok1", "test")


def _manager():
    return ModemManager("/dev/null", "/dev/null")


def test_message_delivered_only_after_all_parts():
    async def run():
        await _fresh_db()
        try:
            mid = await queries.create_message("app1", "+7999", "hi")
            await queries.set_message_sent(mid, 100)
            await queries.add_message_part(mid, 100, 1, 2)
            await queries.add_message_part(mid, 101, 2, 2)
            m = _manager()
            await m._handle_cds(DeliveryReport(modem_ref=100, delivered=True, status_code=0))
            row1 = await queries.get_message(mid, "app1")
            await m._handle_cds(DeliveryReport(modem_ref=101, delivered=True, status_code=0))
            row2 = await queries.get_message(mid, "app1")
            return row1["status"], row2["status"]
        finally:
            await close_db()
    assert asyncio.run(run()) == ("sent", "delivered")


def test_one_permanent_fail_part_fails_message():
    async def run():
        await _fresh_db()
        try:
            mid = await queries.create_message("app1", "+7999", "hi")
            await queries.set_message_sent(mid, 100)
            await queries.add_message_part(mid, 100, 1, 2)
            await queries.add_message_part(mid, 101, 2, 2)
            m = _manager()
            await m._handle_cds(DeliveryReport(modem_ref=101, delivered=False, status_code=0x41))
            row = await queries.get_message(mid, "app1")
            return row["status"], row["error"]
        finally:
            await close_db()
    status, error = asyncio.run(run())
    assert status == "failed"
    assert "incompatible destination" in error
