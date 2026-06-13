# tests/test_seed_from_env.py
import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.settings_store import SettingsStore, seed_from_env


def _run(coro):
    async def run():
        await init_db(":memory:")
        await run_migrations()
        return await coro()
    try:
        return asyncio.run(run())
    finally:
        asyncio.run(close_db())


def test_seed_uses_env_when_present(monkeypatch):
    async def body():
        monkeypatch.setenv("ALERT_CHAT_ID", "999")
        monkeypatch.setenv("VOXLINK_TIMEOUT", "8.0")
        await seed_from_env()
        store = SettingsStore()
        await store.load()
        assert store.alert_chat_id == "999"
        assert store.voxlink_timeout == 8.0
    _run(body)


def test_seed_uses_default_when_env_absent(monkeypatch):
    async def body():
        monkeypatch.delenv("BLACKLIST_THRESHOLD", raising=False)
        await seed_from_env()
        store = SettingsStore()
        await store.load()
        assert store.blacklist_threshold == 5
    _run(body)


def test_seed_does_not_overwrite_existing_row(monkeypatch):
    async def body():
        store = SettingsStore()
        await store.load()
        await store.set_many({"voxlink_timeout": "1.0"})
        monkeypatch.setenv("VOXLINK_TIMEOUT", "8.0")
        await seed_from_env()
        store2 = SettingsStore()
        await store2.load()
        assert store2.voxlink_timeout == 1.0
    _run(body)
