"""The ledger is pruned by something that runs while the gateway is simply running.

`prune_inbound_seen` is called from `scan_inbox`, which fires at startup and on link
recovery. Copying that placement would satisfy "the prune does not depend on a link
recovery" and still never run on a gateway that stays up — the records would accumulate
for months and the retention would be a comment. The expiry sweep ticks every 60 seconds
regardless of anything the modem does, which is why the prune lives there.
"""
import asyncio

import app.modem.manager as manager_mod
from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.modem.manager import ModemManager
from app.settings_store import store


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        return await body()
    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


async def _raw_lines() -> list[str]:
    db = await get_db()
    async with db.execute("SELECT raw_line FROM delivery_reports ORDER BY id") as cur:
        return [r[0] for r in await cur.fetchall()]


def test_the_expiry_sweep_prunes_the_ledger(monkeypatch):
    """Tasks 2.11 and 2.11a — the prune runs from the recurring sweep."""
    async def body():
        monkeypatch.setattr(
            manager_mod, "spawn_delivery_dispatch", lambda *a, **kw: None
        )
        await queries.record_delivery_report(raw_line="ancient", outcome="unplaced")
        await queries.record_delivery_report(raw_line="recent", outcome="attributed")
        db = await get_db()
        await db.execute(
            "UPDATE delivery_reports SET received_at = datetime('now', '-60 days') "
            "WHERE raw_line = 'ancient'"
        )
        await db.commit()

        m = ModemManager("/dev/null", "/dev/null")
        await m._expire_step()          # exactly what expire_loop calls every 60 seconds
        return await _raw_lines()

    assert _run(body) == ["recent"]


def test_the_retention_is_a_named_constant_with_a_thirty_day_default():
    """Long enough that the strict-attribution switch is flipped against a full window
    of evidence rather than an argument."""
    assert manager_mod._DELIVERY_REPORT_RETENTION == 30 * 24 * 3600


def test_the_prune_is_not_tied_to_the_inbox_scan():
    """A boot-and-link-recovery placement is the failure this pins: correct-looking,
    and never running on a gateway that stays up."""
    import inspect
    source = inspect.getsource(ModemManager.scan_inbox)
    assert "prune_delivery_reports" not in source
    assert "prune_delivery_reports" in inspect.getsource(ModemManager._expire_step)
