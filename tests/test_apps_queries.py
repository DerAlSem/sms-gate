import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries


def _run(coro):
    async def run():
        await init_db(":memory:")
        await run_migrations()
        return await coro()
    try:
        return asyncio.run(run())
    finally:
        asyncio.run(close_db())


def test_create_list_toggle_app():
    async def body():
        await queries.create_app("bot1", "tok-bot1", "first bot")
        apps = await queries.list_apps()
        ids = [a["id"] for a in apps]
        assert "bot1" in ids
        await queries.set_app_active("bot1", False)
        apps = {a["id"]: a for a in await queries.list_apps()}
        assert apps["bot1"]["is_active"] == 0
    _run(body)


def test_message_count_and_fk_guard():
    async def body():
        import aiosqlite, pytest
        await queries.create_app("bot2", "tok-bot2", "")
        assert await queries.app_message_count("bot2") == 0
        await queries.create_message("bot2", "+79995550011", "x")
        assert await queries.app_message_count("bot2") == 1
        # deleting an app with messages violates the FK (guarded at router layer)
        with pytest.raises(aiosqlite.IntegrityError):
            await queries.delete_app("bot2")
    _run(body)


def test_delete_app_with_no_messages():
    async def body():
        await queries.create_app("bot3", "tok-bot3", "")
        await queries.delete_app("bot3")
        ids = [a["id"] for a in await queries.list_apps()]
        assert "bot3" not in ids
    _run(body)
