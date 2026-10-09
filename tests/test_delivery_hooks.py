"""Every writer of `messages.status` must notify the owning app.

This is the load-bearing test of delivery dispatch (design D7). The feature's real
failure mode is not a broken POST — it is a *missing* one: someone adds a new place
that changes a message's status, forgets the webhook, and the app silently stops
hearing about that transition. Exactly how the inbound `webhook_url` bug survived.

Two halves:
  * the census below fails when a new status **write** appears in queries.py — a new
    function, or a second transition inside one that is already known;
  * the behavioural tests fail when a known writer's call site drops its dispatch.
"""
import ast
import asyncio
import pathlib
import re

import pytest

import app.modem.manager as manager_mod
from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations

QUERIES_PY = pathlib.Path(__file__).resolve().parents[1] / "app" / "db" / "queries.py"
MANAGER_PY = pathlib.Path(__file__).resolve().parents[1] / "app" / "modem" / "manager.py"

# Every queries.py helper that moves a message between statuses, and **every status each
# one writes**. Adding a writer — or a second transition inside an existing one — without
# adding it here fails test_status_writer_census, which is the point: the failure forces a
# decision about the webhook.
#
# 🔴 **The value half is task 6.6, and what it cost is worth more than what it fixed.**
# Until 22.09.2026 this was a name → status map compared as `set(KNOWN_STATUS_WRITERS)`,
# so only the **names** were ever asserted. A second `UPDATE messages SET status =
# 'rejected'` added *inside* `set_message_delivered` went through green: no new name
# appeared, and the status nobody declared was read by nobody. The requirement says
# "every code path that writes `messages.status`" and the guard counted functions — the
# unit of counting has to be the unit of the norm, or the guard is green on the breach
# and looks healthy doing it. The verification half of this estate
# (`tests/test_verification_outcome_reaches_the_app.py`) was written with the stricter
# shape from the start and kills the same mutation; this is that shape, brought back
# here.
KNOWN_STATUS_WRITERS = {
    "set_message_sent": {"sent"},
    "set_message_failed": {"failed"},
    "set_message_delivered": {"delivered"},
    "set_message_delivery_failed": {"failed"},
    "expire_stale_messages": {"expired"},
    # Completes what the network partly confirmed, rather than expiring it. It writes
    # `delivered`, and its call site notifies that and nothing else: the application is owed
    # the conclusion, not the reasoning that reached it.
    "complete_partly_reported_messages": {"delivered"},
}


def _set_clause(sql: str) -> str | None:
    """The assignment half of an `UPDATE messages`, or None if it is not one.

    Split from the `WHERE` half on purpose: `status` appears in both — two of these
    writers select the rows to sweep by the status they are already in — and a condition
    on the status a row must already hold is the opposite of a write.
    """
    upper = sql.upper()
    start = upper.find("UPDATE MESSAGES")
    if start < 0:
        return None
    set_at = upper.find(" SET ", start)
    if set_at < 0:
        return None
    where_at = upper.find(" WHERE ", set_at)
    return sql[set_at + 5:where_at if where_at > 0 else len(sql)]


_SET_STATUS = re.compile(r"\bstatus\s*=\s*(?:'([^']*)'|(\?))", re.IGNORECASE)


def _message_status_writes() -> dict[str, set[str]]:
    """Every queries.py function that writes `messages.status`, and what it writes.

    A bound `?` is recorded as `"?"` rather than guessed at: a writer whose status comes
    from its caller is a decision somebody has to look at, which is the whole purpose of
    a census.
    """
    tree = ast.parse(QUERIES_PY.read_text())
    writes: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Constant) or not isinstance(sub.value, str):
                continue
            clause = _set_clause(" ".join(sub.value.split()))
            if clause is None:
                continue
            for literal, bound in _SET_STATUS.findall(clause):
                writes.setdefault(node.name, set()).add("?" if bound else literal.lower())
    return writes


def test_status_writer_census():
    """A new status writer — or a new status out of an old one — must be registered here,
    and then wired to a dispatch."""
    assert _message_status_writes() == KNOWN_STATUS_WRITERS, (
        "queries.py gained or lost a write of messages.status. Add it to "
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
        rows = await queries.parts_matching_ref(7)
        return mid, rows

    mid, rows = _with_db(body)
    assert len(rows) == 1 and rows[0]["message_id"] == mid, (
        "an expired message must still be eligible for a late delivery report"
    )
    assert rows[0]["msg_status"] == "expired"
