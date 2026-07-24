"""Every writer of `messages.status` must notify the owning app.

This is the load-bearing test of delivery dispatch (design D7). The feature's real
failure mode is not a broken POST — it is a *missing* one: someone adds a new place
that changes a message's status, forgets the webhook, and the app silently stops
hearing about that transition. Exactly how the inbound `webhook_url` bug survived.

Two halves:
  * the census below fails when a new status writer appears in queries.py;
  * the behavioural tests fail when a known writer's call site drops its dispatch.
"""
import ast
import asyncio
import pathlib

import pytest

import app.modem.manager as manager_mod
from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations

QUERIES_PY = pathlib.Path(__file__).resolve().parents[1] / "app" / "db" / "queries.py"
MANAGER_PY = pathlib.Path(__file__).resolve().parents[1] / "app" / "modem" / "manager.py"

# Every queries.py helper that moves a message between statuses, and the status it
# writes. Adding a writer without adding it here fails test_status_writer_census —
# which is the point: the failure forces a decision about the webhook.
KNOWN_STATUS_WRITERS = {
    "set_message_sent": "sent",
    "set_message_failed": "failed",
    "set_message_delivered": "delivered",
    "set_message_delivery_failed": "failed",
    "expire_stale_messages": "expired",
}


def _functions_writing_message_status() -> set[str]:
    """Names of queries.py functions whose body contains an UPDATE of messages.status."""
    tree = ast.parse(QUERIES_PY.read_text())
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Constant) or not isinstance(sub.value, str):
                continue
            sql = " ".join(sub.value.split()).upper()
            if "UPDATE MESSAGES" in sql and "STATUS =" in sql:
                found.add(node.name)
    return found


def test_status_writer_census():
    """A new status writer must be registered here — and then wired to a dispatch."""
    assert _functions_writing_message_status() == set(KNOWN_STATUS_WRITERS), (
        "queries.py gained or lost a writer of messages.status. Add it to "
        "KNOWN_STATUS_WRITERS and give its call site a spawn_delivery_dispatch(...), "
        "or the owning app will never hear about that transition."
    )


def test_every_known_writer_is_dispatched_at_its_call_site():
    """Each writer's caller in manager.py dispatches within the same block.

    Cheap structural check: for every call to a known writer, a spawn_delivery_dispatch
    must appear among that statement's siblings. Catches a call site that lost its
    dispatch in a refactor.
    """
    tree = ast.parse(MANAGER_PY.read_text())
    missing = []

    def call_names(node) -> set[str]:
        return {
            n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
            for n in ast.walk(node) if isinstance(n, ast.Call)
        }

    for parent in ast.walk(tree):
        body = getattr(parent, "body", None)
        if not isinstance(body, list):
            continue
        for block in (body, getattr(parent, "orelse", []) or []):
            names = set()
            for stmt in block:
                names |= call_names(stmt)
            for writer in KNOWN_STATUS_WRITERS:
                if writer in names and "spawn_delivery_dispatch" not in names:
                    missing.append(writer)

    assert not missing, (
        f"these status writers are called in manager.py without a "
        f"spawn_delivery_dispatch beside them: {sorted(set(missing))}"
    )


def test_manager_imports_the_dispatcher():
    assert hasattr(manager_mod, "spawn_delivery_dispatch")


# --- behaviour: the bulk writer, which is the one that can go silent en masse ---

def _with_db(coro):
    async def run():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        return await coro()
    try:
        return asyncio.run(run())
    finally:
        asyncio.run(close_db())


def test_expire_sweep_returns_every_id_it_expired():
    """The sweep is the only bulk status writer: without the ids the whole batch would
    change status with no webhooks at all."""
    async def body():
        ids = []
        for _ in range(3):
            mid = await queries.create_message("app1", "+7985", "hi")
            await queries.set_message_sent(mid, modem_ref=mid % 256)
            ids.append(mid)
        # backdate so the sweep picks them up
        db = await queries.get_db()
        await db.execute("UPDATE messages SET sent_at = datetime('now', '-1 hour')")
        await db.commit()
        return ids, await queries.expire_stale_messages(60)

    ids, expired = _with_db(body)
    assert sorted(expired) == sorted(ids)


def test_expire_sweep_returns_nothing_when_none_are_stale():
    async def body():
        mid = await queries.create_message("app1", "+7985", "hi")
        await queries.set_message_sent(mid, modem_ref=1)
        return await queries.expire_stale_messages(3600)

    assert _with_db(body) == []


def _record_dispatches(monkeypatch):
    """Capture spawn_delivery_dispatch(...) instead of firing real webhooks."""
    calls = []
    monkeypatch.setattr(
        manager_mod, "spawn_delivery_dispatch",
        lambda mid, status, error=None: calls.append((mid, status, error)),
    )
    return calls


def test_multipart_notifies_delivered_once_after_the_last_part(monkeypatch):
    """One notification per message, not per part (design D3)."""
    from app.modem.manager import ModemManager
    from app.modem.parser import DeliveryReport

    calls = _record_dispatches(monkeypatch)

    async def body():
        mid = await queries.create_message("app1", "+7985", "long text")
        await queries.set_message_sent(mid, 10)
        await queries.add_message_part(mid, 10, seq=1, total=2)
        await queries.add_message_part(mid, 11, seq=2, total=2)
        m = ModemManager("/dev/null", "/dev/null")
        await m._handle_cds(DeliveryReport(modem_ref=10, delivered=True, status_code=0))
        after_first = list(calls)
        await m._handle_cds(DeliveryReport(modem_ref=11, delivered=True, status_code=0))
        return mid, after_first

    mid, after_first = _with_db(body)
    assert after_first == [], "no delivered notification until every part is reported"
    assert calls == [(mid, "delivered", None)]


def test_expired_message_can_still_become_delivered():
    """`expired` is not terminal: a late +CDS moves it on, and that is a second
    transition the app must hear about."""
    async def body():
        mid = await queries.create_message("app1", "+7985", "hi")
        await queries.set_message_sent(mid, modem_ref=7)
        db = await queries.get_db()
        await db.execute("UPDATE messages SET sent_at = datetime('now', '-1 hour')")
        await db.commit()
        await queries.expire_stale_messages(60)
        # a delivery report arriving after the sweep still finds the message
        await queries.add_message_part(mid, 7, seq=1, total=1)
        row = await queries.find_message_by_part_ref(7)
        return mid, row

    mid, row = _with_db(body)
    assert row is not None and row["message_id"] == mid, (
        "an expired message must still be eligible for a late delivery report"
    )
    assert row["msg_status"] == "expired"
