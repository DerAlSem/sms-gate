"""The one rule in this change that can refuse a delivery, and the switch it lives behind.

Dropping a report is not neutral. For a message still `sent`, "no status changes" lasts
until the sweep moves it to `expired` and the owning application is told so; for a
negative report it is also a suppressed blacklist increment and a suppressed alert. The
trade is not "delivered or nothing", it is "delivered or expired" — which is why this
ships switched off and is turned on against a week of the ledger's own evidence.
"""
import asyncio
import json

import app.modem.manager as manager_mod
from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.modem.manager import ModemManager
from app.settings_store import SPEC_BY_KEY, store

OURS = "+79031680015"
THEIRS = "+79994445566"


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


def _manager(monkeypatch):
    m = ModemManager("/dev/null", "/dev/null")
    dispatched: list = []
    alerts: list = []
    monkeypatch.setattr(
        manager_mod, "spawn_delivery_dispatch",
        lambda mid, status, error=None: dispatched.append((mid, status, error)),
    )
    monkeypatch.setattr(
        manager_mod, "notify",
        lambda event, text, dedup_extra=None, phone=None: alerts.append((event, text)),
    )
    return m, dispatched, alerts


def _cds(ref=42, *, ra=THEIRS, st=0):
    return f'+CDS: 6,{ref},"{ra}",145,"26/09/02,11:00:00+00","26/09/02,11:30:00+00",{st}'


async def _sent_message(phone=OURS, ref=42):
    mid = await queries.create_message("app1", phone, "hi")
    await queries.set_message_sent(mid, ref)
    await queries.add_message_part(mid, ref, 1, 1)
    return mid


async def _record() -> dict:
    db = await get_db()
    async with db.execute("SELECT * FROM delivery_reports ORDER BY id") as cur:
        rows = [dict(r) for r in await cur.fetchall()]
    return rows[-1] if rows else {}


async def _part_status(mid) -> str:
    db = await get_db()
    async with db.execute(
        "SELECT status FROM message_parts WHERE message_id = ?", (mid,)
    ) as cur:
        return (await cur.fetchone())[0]


def test_the_switch_defaults_to_off():
    """Task 5.5 — the flip is a separate, evidence-led decision, not part of the deploy."""
    spec = SPEC_BY_KEY["delivery_report_strict_attribution"]
    assert spec.type == "bool"
    assert spec.default is False


def test_strict_on_the_sole_candidate_addressed_elsewhere_is_refused(monkeypatch):
    """Task 5.1 — including when it is the only candidate, which is the whole point.

    A rule applied only to ties would leave the single-candidate misattribution exactly
    where it is, and that is the case production is full of: 130 messages carry a
    reference `message_parts` now attributes to somebody else.
    """
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        await store.set_many({"delivery_report_strict_attribution": "true"})
        mid = await _sent_message(phone=OURS)
        await m._on_cds_line(_cds(ra=THEIRS))
        db = await get_db()
        async with db.execute(
            "SELECT status FROM messages WHERE id = ?", (mid,)
        ) as cur:
            status = (await cur.fetchone())[0]
        return mid, status, await _part_status(mid), await _record(), alerts, dispatched

    mid, status, part_status, record, alerts, dispatched = _run(body)
    assert status == "sent" and part_status == "sent", "nothing changed"
    assert dispatched == [], "and no application was told anything"
    assert record["outcome"] == "unplaced"
    assert record["recipient"] == THEIRS, "the number the report named"
    candidates = json.loads(record["candidates"])
    assert candidates[0]["outcome"] == "contradicted"
    assert candidates[0]["phone"] == OURS, (
        "and the number we hold — without both, nobody can tell a real misattribution "
        "from our own formatting, which is the question the switch is flipped on"
    )
    assert [event for event, _ in alerts] == ["delivery_unplaced"]


def test_strict_on_a_candidate_whose_digits_agree_is_still_updated(monkeypatch):
    """Task 5.2 — the positive control. Without it, the test above passes against a
    lookup that finds nothing at all."""
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        await store.set_many({"delivery_report_strict_attribution": "true"})
        mid = await _sent_message(phone=OURS)
        await m._on_cds_line(_cds(ra="8" + OURS[2:]))   # national form of the same number
        return mid, await _part_status(mid), await _record(), alerts

    mid, part_status, record, alerts = _run(body)
    assert part_status == "delivered"
    assert record["outcome"] == "attributed" and record["message_id"] == mid
    assert alerts == []


def test_strict_off_the_same_report_is_attributed_and_the_contradiction_recorded(
    monkeypatch
):
    """Task 5.3 — off, behaviour is exactly today's and the evidence is collected."""
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        mid = await _sent_message(phone=OURS)
        await m._on_cds_line(_cds(ra=THEIRS))
        return mid, await _part_status(mid), await _record(), alerts

    mid, part_status, record, alerts = _run(body)
    assert part_status == "delivered", "off, the report is attributed as it was before"
    assert record["outcome"] == "attributed"
    assert record["strict"] == 0
    candidates = json.loads(record["candidates"])
    assert candidates[0]["outcome"] == "chosen"
    assert candidates[0]["contradicted"] is True, (
        "the contradiction is recorded even though it did not eliminate — this is the "
        "evidence the flip decision is taken on"
    )


def test_the_switch_is_read_for_each_report(monkeypatch):
    """Task 5.4 — changing it takes effect without a restart."""
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        first = await _sent_message(phone=OURS, ref=42)
        await m._on_cds_line(_cds(ref=42, ra=THEIRS))
        off_result = await _part_status(first)

        await store.set_many({"delivery_report_strict_attribution": "true"})
        second = await _sent_message(phone=OURS, ref=43)
        await m._on_cds_line(_cds(ref=43, ra=THEIRS))
        on_result = await _part_status(second)
        return off_result, on_result, await _record()

    off_result, on_result, record = _run(body)
    assert off_result == "delivered", "before the flip"
    assert on_result == "sent", "after it, with no restart in between"
    assert record["strict"] == 1, "and the record says which rule applied"
