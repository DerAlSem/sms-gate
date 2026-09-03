"""A +CDS from the port, end to end: what changes, who is told, what is written down.

The unit tests of the chain build their own rows. These cross the boundary the unit tests
cannot: the report really comes from a line, the candidates really come from the database,
and the decision really reaches three different consumers — the ledger writes all of it,
the alert fires on `unplaced` alone, and `record_permanent_fail` is skipped when the
choice was made by recency.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

import app.modem.manager as manager_mod
from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.modem.manager import ModemManager
from app.settings_store import store

PHONE = "+79031680015"
OTHER = "+79994445566"


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


def _scts(seconds_ago: int) -> str:
    """A service-centre timestamp that many seconds before now, in the wire format.

    Built against the clock rather than hard-coded: the rules order candidates by the
    distance between the report's submit time and each part's own, and a fixed date in
    the past makes every candidate equally ancient — which decides the tests by accident.
    """
    when = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return when.strftime("%y/%m/%d,%H:%M:%S") + "+00"


def _cds(ref, *, st=0, ra=PHONE, scts=None, submitted_seconds_ago=600):
    scts = scts if scts is not None else _scts(submitted_seconds_ago)
    return (f'+CDS: 6,{ref},"{ra}",145,"{scts}","{_scts(0)}",{st}')


async def _sent_message(phone=PHONE, ref=42, *, seq=1, total=1, age_seconds=600):
    mid = await queries.create_message("app1", phone, "hi")
    await queries.set_message_sent(mid, ref)
    await queries.add_message_part(mid, ref, seq, total)
    db = await get_db()
    await db.execute(
        "UPDATE messages SET sent_at = datetime('now', ? || ' seconds') WHERE id = ?",
        (f"-{age_seconds}", mid),
    )
    await db.execute(
        "UPDATE message_parts SET sent_at = datetime('now', ? || ' seconds') "
        "WHERE message_id = ?",
        (f"-{age_seconds}", mid),
    )
    await db.commit()
    return mid


async def _records() -> list[dict]:
    db = await get_db()
    async with db.execute("SELECT * FROM delivery_reports ORDER BY id") as cur:
        return [dict(r) for r in await cur.fetchall()]


async def _message(mid) -> dict:
    db = await get_db()
    async with db.execute(
        "SELECT status, error, delivery_inferred FROM messages WHERE id = ?", (mid,)
    ) as cur:
        return dict(await cur.fetchone())


async def _parts(mid) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT seq, status FROM message_parts WHERE message_id = ? ORDER BY seq", (mid,)
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


# --- the ledger ----------------------------------------------------------------


def test_an_attributed_report_is_recorded_and_wakes_nobody(monkeypatch):
    """Task 2.1."""
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        mid = await _sent_message()
        await m._on_cds_line(_cds(42))
        return mid, await _records(), alerts, await _message(mid)

    mid, records, alerts, message = _run(body)
    assert len(records) == 1
    row = records[0]
    assert row["outcome"] == "attributed"
    assert (row["message_id"], row["seq"]) == (mid, 1)
    assert row["decided_by"] == "sole", "the record says how the part was chosen"
    assert row["modem_ref"] == 42 and row["recipient"] == PHONE
    assert alerts == [], "an ordinary delivery does not wake an operator"
    assert message["status"] == "delivered"


def test_a_report_about_nothing_is_recorded_and_notified(monkeypatch):
    """Task 2.2 — every consequence of dropping a report is otherwise invisible."""
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        await m._on_cds_line(_cds(99))
        return await _records(), alerts, dispatched

    records, alerts, dispatched = _run(body)
    assert len(records) == 1
    row = records[0]
    assert row["outcome"] == "unplaced"
    assert row["modem_ref"] == 99
    assert row["recipient"] == PHONE
    assert row["reason"] and "reference" in row["reason"], (
        "the record says why, or the ledger cannot answer the question the switch is "
        "flipped on"
    )
    assert [event for event, _ in alerts] == ["delivery_unplaced"]
    assert dispatched == [], "no status changed, so no application is told anything"


def test_a_superseded_report_is_recorded_and_silent(monkeypatch):
    """Task 2.3 — ordinary network behaviour: a multipart message completed at the
    timeout still receives its remaining reports afterwards."""
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        mid = await _sent_message()
        await queries.set_message_delivered(mid)
        await m._on_cds_line(_cds(42))
        return mid, await _records(), alerts, await _message(mid)

    mid, records, alerts, message = _run(body)
    assert records[0]["outcome"] == "superseded"
    assert records[0]["message_id"] == mid, "it names the part it was superseded by"
    assert alerts == [], "an operator woken by ordinary traffic stops reading alerts"
    assert message["status"] == "delivered"


def test_a_line_the_parser_cannot_read_is_recorded_and_logged_at_error(
    monkeypatch, caplog
):
    """Tasks 2.5 and 2.6b — the one class of event that must not reach nobody.

    Our own parser failing on a line the network sent is either a wire-format change or
    the group-renumbering fault, and that fault presents as every delivery in the system
    turning into a failure.
    """
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        with caplog.at_level(logging.ERROR, logger="app.modem.manager"):
            await m._on_cds_line("+CDS: this is not a report")
        return await _records()

    with caplog.at_level(logging.ERROR, logger="app.modem.manager"):
        records = _run(body)

    assert len(records) == 1
    assert records[0]["outcome"] == "unparsable"
    assert records[0]["raw_line"] == "+CDS: this is not a report"
    assert records[0]["received_at"] is not None
    assert any(r.levelno >= logging.ERROR and "+CDS" in r.getMessage()
               for r in caplog.records), "an unreadable line is an error, not a shrug"


def test_the_record_names_every_matching_part_not_only_the_winner(monkeypatch):
    """Task 2.6 — "how many reports did we contradict" is unanswerable from a record
    that stores the choice and forgets the alternatives."""
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        older = await _sent_message(ref=42, age_seconds=7200)
        newer = await _sent_message(ref=42, age_seconds=600)
        await m._on_cds_line(_cds(42, submitted_seconds_ago=600))
        return older, newer, await _records()

    older, newer, records = _run(body)
    candidates = json.loads(records[0]["candidates"])
    by_id = {c["message_id"]: c["outcome"] for c in candidates}
    assert set(by_id) == {older, newer}, "both parts sharing the reference are named"
    assert sorted(by_id.values()) == ["chosen", "eligible"]


def test_the_record_carries_the_settings_in_force(monkeypatch):
    """Task 2.7 — a setting read a week later cannot answer for a decision made before
    it changed."""
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        await store.set_many({"delivery_report_max_age_hours": "24"})
        await _sent_message()
        await m._on_cds_line(_cds(42))
        return await _records()

    row = _run(body)[0]
    assert row["window_hours"] == 24
    assert row["strict"] == 0


def test_a_failing_record_write_leaves_the_attribution_standing(monkeypatch, caplog):
    """Task 2.8 — the status write is the commitment; the record is the account of it."""
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        mid = await _sent_message()

        async def explode(**kw):
            raise RuntimeError("the ledger is unavailable")

        monkeypatch.setattr(queries, "record_delivery_report", explode)
        with caplog.at_level(logging.ERROR, logger="app.modem.manager"):
            await m._on_cds_line(_cds(42))
        return mid, await _message(mid), dispatched

    with caplog.at_level(logging.ERROR, logger="app.modem.manager"):
        mid, message, dispatched = _run(body)

    assert message["status"] == "delivered", "a failed record may not fail the report"
    assert (mid, "delivered", None) in dispatched
    assert any("record delivery report" in r.getMessage().lower()
               for r in caplog.records), "and it is logged, not swallowed"


def test_the_status_write_commits_before_the_record_is_written(monkeypatch):
    """Task 4.23 — an attribution that happened and was not written down is a gap in the
    account; a record written for an attribution that then failed is a false account."""
    seen: list = []

    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        mid = await _sent_message()
        real = queries.record_delivery_report

        async def watch(**kw):
            seen.append((await _message(mid))["status"])
            return await real(**kw)

        monkeypatch.setattr(queries, "record_delivery_report", watch)
        await m._on_cds_line(_cds(42))
        return mid

    _run(body)
    assert seen == ["delivered"], (
        "the message had already reached its new status when the record was written"
    )


# --- the wiring ----------------------------------------------------------------


def test_a_report_leaves_another_messages_part_with_the_same_reference_alone(monkeypatch):
    """Task 4.18 — the defect, from the other end. `set_part_delivered` used to say
    `WHERE modem_ref = ?` with no `LIMIT`."""
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        old = await _sent_message(phone=OTHER, ref=42, age_seconds=7200)
        new = await _sent_message(phone=PHONE, ref=42, age_seconds=600)
        await m._on_cds_line(_cds(42, ra=PHONE, submitted_seconds_ago=600))
        return old, new, await _parts(old), await _parts(new), await _message(old), \
            await _records()

    old, new, old_parts, new_parts, old_message, records = _run(body)
    assert records[0]["outcome"] == "attributed"
    assert records[0]["message_id"] == new, "the nearer submit time decided it"
    assert new_parts[0]["status"] == "delivered"
    assert old_parts[0]["status"] == "sent", "the other message's part was untouched"
    assert old_message["status"] == "sent"


def test_no_webhook_is_sent_for_a_report_that_was_not_attributed(monkeypatch):
    """Task 7.4."""
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        await _sent_message(ref=42)
        await m._on_cds_line(_cds(77, st=64))       # a reference nothing carries
        return dispatched

    assert _run(body) == []


def test_a_recency_choice_does_not_count_toward_the_blacklist(monkeypatch):
    """Tasks 4.9 and 4.15 — an irreversible penalty may not rest on a tiebreak.

    Blocking a destination 422s every later send to it, and unblocking deliberately does
    not reset the count.
    """
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        a = await _sent_message(phone=PHONE, ref=42, age_seconds=600)
        b = await _sent_message(phone=PHONE, ref=42, age_seconds=600)
        db = await get_db()
        # the same instant on both, so nothing separates them
        await db.execute("UPDATE message_parts SET sent_at = '2026-09-02 11:00:00'")
        await db.commit()
        await m._on_cds_line(_cds(42, st=64, scts="not a timestamp"))
        return a, b, await _records(), await queries.is_phone_blocked(PHONE), \
            await queries.list_bad_numbers()

    a, b, records, blocked, bad = _run(body)
    assert records[0]["decided_by"] == "recency"
    assert bad == [], "no failure was counted against the destination"
    assert blocked is False


def test_a_permanent_failure_chosen_outright_still_counts(monkeypatch):
    """The positive control for the carve-out above: without it, that test passes
    against an implementation that never counts a failure at all."""
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        await _sent_message(phone=PHONE, ref=42)
        await m._on_cds_line(_cds(42, st=64))
        return await _records(), await queries.list_bad_numbers()

    records, bad = _run(body)
    assert records[0]["decided_by"] == "sole"
    assert [row["phone"] for row in bad] == [PHONE]
    assert bad[0]["fail_count"] == 1


# --- the two vacuous truths ------------------------------------------------------


def test_a_message_with_no_part_records_has_parts_outstanding():
    """Task 4.19 — "nothing is outstanding" and "nothing is known" are different
    answers, and only the first is a delivery."""
    async def body():
        mid = await queries.create_message("app1", PHONE, "hi")
        await queries.set_message_sent(mid, 42)
        return await queries.message_parts_all_delivered(mid)

    assert _run(body) is False


def test_a_message_no_report_named_is_not_completed_at_the_timeout(monkeypatch):
    """Task 4.20 — the worst consequence of the defect, and the one the original
    proposal missed: a single misattributed positive report used to manufacture a
    delivery for a message no report ever named, recorded as one the gateway concluded.
    """
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        innocent = await _sent_message(phone=OTHER, ref=42, age_seconds=7200)
        reported = await _sent_message(phone=PHONE, ref=42, seq=1, total=2,
                                       age_seconds=600)
        await queries.add_message_part(reported, 43, seq=2, total=2)
        await m._on_cds_line(_cds(42, ra=PHONE, submitted_seconds_ago=600))

        await m._expire_step()
        return innocent, reported, await _message(innocent), await _message(reported)

    innocent, reported, innocent_state, reported_state = _run(body)
    assert innocent_state["status"] == "expired", (
        "a message no report was attributed to must not become a delivery"
    )
    assert innocent_state["delivery_inferred"] == 0
    assert reported_state["status"] == "delivered", (
        "and the message the report was really about is still completed"
    )
    assert reported_state["delivery_inferred"] == 1


def test_a_late_negative_report_moves_an_expired_message_to_failed(monkeypatch):
    """Task 4.21 — inside the window, `expired` is not terminal."""
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        mid = await _sent_message(phone=PHONE, ref=42, age_seconds=600)
        await m._expire_step()
        after_sweep = list(dispatched)
        await m._on_cds_line(_cds(42, st=64))
        return mid, after_sweep, dispatched, await _message(mid), \
            await queries.list_bad_numbers()

    mid, after_sweep, dispatched, message, bad = _run(body)
    assert after_sweep == [(mid, "expired", None)]
    assert message["status"] == "failed"
    assert dispatched[-1][0] == mid and dispatched[-1][1] == "failed"
    assert "remote procedure error" in (message["error"] or "")
    assert [row["phone"] for row in bad] == [PHONE], (
        "a permanent status counts toward the destination's blacklist"
    )


def test_every_parsed_field_crosses_the_boundary_into_the_record(monkeypatch):
    """Task 7.3 — the gap no unit test can see.

    The chain's tests build a `DeliveryReport` themselves and the parser's tests stop at
    the dataclass, so between them they prove that each end is correct and nothing about
    whether the values travel. A field the parser reads and `_handle_cds` drops would
    leave both suites green and the ledger empty where it matters.
    """
    line = ('+CDS: 6,42,"+79031680015",145,"26/09/02,11:00:01+12",'
            '"26/09/02,15:37:44+12",64')

    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        mid = await _sent_message(phone=PHONE, ref=42)
        await m._on_cds_line(line)
        return mid, await _records()

    mid, records = _run(body)
    row = records[0]
    assert row["raw_line"] == line, "the line itself"
    assert row["modem_ref"] == 42
    assert row["status_code"] == 64
    assert row["recipient"] == "+79031680015"
    # +12 quarter-hours is UTC+03:00, so 11:00:01 local is 08:00:01 UTC. An
    # implementation reading the offset as hours would land nine hours away, and nothing
    # else in the system would ever notice.
    assert row["submitted_at"] == "2026-09-02 08:00:01"
    assert row["discharged_at"] == "2026-09-02 12:37:44"
    assert row["message_id"] == mid and row["seq"] == 1
    assert row["decided_by"] == "sole"
    assert row["window_hours"] == 168 and row["strict"] == 0


def test_the_window_is_read_for_each_report(monkeypatch):
    """The window is re-read per report, as `delivery_timeout_seconds` is re-read per
    sweep. The strict switch has this test; without one here the window could be read
    once at startup and nothing would say so until a change failed to take effect."""
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        first = await _sent_message(ref=42, age_seconds=7200)     # two hours old
        await m._on_cds_line(_cds(42))
        wide = (await _message(first))["status"]

        await store.set_many({"delivery_report_max_age_hours": "1"})
        second = await _sent_message(ref=43, age_seconds=7200)
        await m._on_cds_line(_cds(43))
        narrow = (await _message(second))["status"]
        return wide, narrow, await _records()

    wide, narrow, records = _run(body)
    assert wide == "delivered", "inside the default window"
    assert narrow == "sent", "outside a one-hour window, with no restart in between"
    assert records[-1]["window_hours"] == 1


def test_a_report_bounded_out_by_the_window_sends_no_second_notification(monkeypatch):
    """`delivery-dispatch` promises an application that a correction *inside* the window
    reaches it, not that one always arrives. Past the bound the report is recorded and
    the application hears nothing further."""
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        mid = await _sent_message(ref=42, age_seconds=7200)
        await m._expire_step()
        after_sweep = list(dispatched)

        await store.set_many({"delivery_report_max_age_hours": "1"})
        await m._on_cds_line(_cds(42))
        return mid, after_sweep, dispatched, await _message(mid), await _records()

    mid, after_sweep, dispatched, message, records = _run(body)
    assert after_sweep == [(mid, "expired", None)]
    assert dispatched == after_sweep, "no second notification for a bounded-out report"
    assert message["status"] == "expired"
    assert records[0]["outcome"] == "unplaced"
    candidates = json.loads(records[0]["candidates"])
    assert candidates[0]["outcome"] == "outside_window", (
        "and the record names the part it bounded out, not 'nothing matched'"
    )


def test_the_recency_carve_out_holds_on_the_late_negative_path(monkeypatch):
    """Task 4.9a — the same carve-out, reached through `expired` rather than `sent`.

    Blocking a destination 422s every later send to it, and unblocking deliberately does
    not reset the count. The path that moves an expired message to `failed` must not be
    the one that slips a tiebreak-chosen failure past the rule.
    """
    async def body():
        m, dispatched, alerts = _manager(monkeypatch)
        await _sent_message(phone=PHONE, ref=42, age_seconds=600)
        await _sent_message(phone=PHONE, ref=42, age_seconds=600)
        await m._expire_step()                     # both messages reach `expired`
        db = await get_db()
        await db.execute("UPDATE message_parts SET sent_at = '2026-09-02 11:00:00'")
        await db.commit()

        await m._on_cds_line(_cds(42, st=64, scts="not a timestamp"))
        return await _records(), await queries.list_bad_numbers(), dispatched

    records, bad, dispatched = _run(body)
    assert records[0]["decided_by"] == "recency"
    assert [status for _, status, _ in dispatched][-1] == "failed", (
        "the message really was moved on, so this is not passing by doing nothing"
    )
    assert bad == [], "and the destination's failure count was not incremented"
