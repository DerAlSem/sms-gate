"""What the paid rungs cost, answerable before the vendor's invoice: tasks 6.9 and 6.10.

Found by the conformance sweep of 22.09.2026, and found as an absence rather than as a
defect. Three scenarios of "What verifications cost is visible before the bill is" had
nothing behind them at all:

- **a fee that bought nothing** is recorded on the rung — `unanswered` is written by the
  ladder when a vendor does not answer inside the bound — but "the count is readable
  beside the attributed spend" was not: the only aggregate anywhere in `app/` was not
  about money, and `SUM(cost)` appeared nowhere in the estate;
- **a month's spend** and **the spend per application** were both recorded and neither
  was answerable: the data sat in `verification_rungs.cost` and `verifications.app_id`
  with no query and no view that read them.

The period is the estate's rolling window rather than a calendar month, for the reason
`app/periods.py` gives: a control labelled "month" that answers a rolling thirty days
answers a different question from the one it appears to, and the operator concludes the
counter is broken. "Last month" is `30d` here, and it says so on the page.

🔴 **A possibly-charged fee is a COUNT and not a sum, and that is the whole of why it is
reported separately.** The vendor may have confirmed and charged an ability check whose
`request_id` never reached us — so there is no number to add up, only a number of times it
happened. Folded into the spend it would be a guess; left out it is a balance that drifts
for no reason.
"""

import asyncio

import pytest

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import ladder
from app.verification.routes import FLASH_CALL, SMS_OUT, TG_GATEWAY

PHONE = "+79851600019"


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await queries.create_app("app2", "token-app2")
        await store.load()
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


async def _rung(app_id, route, *, cost=None, outcome=ladder.CARRIED, refunded=False,
                age_days=0):
    vid = await queries.create_verification(app_id, PHONE, code="1234", ttl_seconds=300)
    rung_id = await queries.record_verification_rung(
        vid, route=route, cost=cost, outcome=outcome)
    if refunded:
        from app.db.connection import get_db
        db = await get_db()
        await db.execute(
            "UPDATE verification_rungs SET refunded = 1, cost = 0 WHERE id = ?",
            (rung_id,))
        await db.commit()
    if age_days:
        from app.db.connection import get_db
        db = await get_db()
        await db.execute(
            "UPDATE verification_rungs SET started_at = datetime('now', ?) WHERE id = ?",
            (f"-{age_days} days", rung_id))
        await db.commit()
    return vid, rung_id


def _by_route(rows):
    return {row["route"]: dict(row) for row in rows}


# --- the month's spend, from our own records -------------------------------------------

def test_a_months_spend_is_answered_from_the_recorded_costs():
    """The scenario says it in as many words: the answer comes from recorded
    per-verification costs, not from the vendor's invoice."""
    async def body():
        await _rung("app1", TG_GATEWAY, cost=0.01)
        await _rung("app1", TG_GATEWAY, cost=0.02)
        await _rung("app1", FLASH_CALL, cost=3.5)
        return await queries.verification_spend("30d")

    rows = _by_route(_run(body))
    assert round(rows[TG_GATEWAY]["spend"], 4) == 0.03
    assert rows[TG_GATEWAY]["attempts"] == 2
    assert round(rows[FLASH_CALL]["spend"], 4) == 3.5


def test_what_fell_outside_the_window_is_not_in_the_answer():
    """The positive control on the period, and the one a query with no bound passes
    silently: an answer that quietly includes every month ever is not the answer to
    "what did it cost last month"."""
    async def body():
        await _rung("app1", TG_GATEWAY, cost=0.01)
        await _rung("app1", TG_GATEWAY, cost=99.0, age_days=400)
        return await queries.verification_spend("30d"), await queries.verification_spend("all")

    recent, ever = _run(body)
    assert round(_by_route(recent)[TG_GATEWAY]["spend"], 4) == 0.01
    assert round(_by_route(ever)[TG_GATEWAY]["spend"], 4) == 99.01


def test_a_refunded_fee_is_not_in_the_spend_and_is_still_visible():
    """A refund lowers the recorded spend rather than standing beside it as an asterisk —
    and the count of refunds stays readable, because a spend that silently shrank is a
    number nobody can check."""
    async def body():
        await _rung("app1", TG_GATEWAY, cost=0.01)
        await _rung("app1", TG_GATEWAY, cost=0.02, refunded=True)
        return await queries.verification_spend("30d")

    row = _by_route(_run(body))[TG_GATEWAY]
    assert round(row["spend"], 4) == 0.01
    assert row["refunded"] == 1


# --- the fee that bought nothing -------------------------------------------------------

def test_the_fee_that_bought_nothing_is_counted_beside_the_spend():
    """Task 6.9. `unanswered` means the ability check did not answer inside the bound: the
    vendor may have confirmed and charged it, and we never learned the `request_id`. It
    is a **count** and not a sum — there is no figure to add — and it is readable beside
    the spend rather than folded into it."""
    async def body():
        await _rung("app1", TG_GATEWAY, cost=0.01)
        await _rung("app1", TG_GATEWAY, outcome=ladder.UNANSWERED)
        await _rung("app1", TG_GATEWAY, outcome=ladder.UNANSWERED)
        return await queries.verification_spend("30d")

    row = _by_route(_run(body))[TG_GATEWAY]
    assert row["possibly_charged"] == 2
    assert round(row["spend"], 4) == 0.01, "a fee with no figure was added to the spend"


def test_a_free_rung_is_not_reported_as_paid():
    """The positive control against an answer built from every rung: the modem rung
    carries no cost and never did, and a row of zeros under it invites the question of
    which vendor it is with."""
    async def body():
        await _rung("app1", SMS_OUT)
        await _rung("app1", TG_GATEWAY, cost=0.01)
        return await queries.verification_spend("30d")

    rows = _by_route(_run(body))
    assert SMS_OUT not in rows
    assert TG_GATEWAY in rows


# --- who spent it ----------------------------------------------------------------------

def test_the_spend_is_answerable_per_application():
    """Task 6.10, second scenario: the answer comes from the application recorded on each
    verification — which is where it is recorded, and the join nobody had written."""
    async def body():
        await _rung("app1", TG_GATEWAY, cost=0.01)
        await _rung("app2", FLASH_CALL, cost=3.5)
        await _rung("app2", TG_GATEWAY, cost=0.02)
        return await queries.verification_spend_by_app("30d")

    rows = {row["app_id"]: dict(row) for row in _run(body)}
    assert round(rows["app1"]["spend"], 4) == 0.01
    assert round(rows["app2"]["spend"], 4) == 3.52
    assert rows["app2"]["attempts"] == 2


def test_an_application_that_spent_nothing_is_not_invented():
    """`app2` exists and has never spent. A report that lists it at zero is answering
    "which applications are there", which is another page's question."""
    async def body():
        await _rung("app1", TG_GATEWAY, cost=0.01)
        return await queries.verification_spend_by_app("30d")

    rows = {row["app_id"] for row in _run(body)}
    assert rows == {"app1"}


# --- readable, which is a screen and not a query ---------------------------------------

def _stats_page(period: str = "30d", locale: str = "en") -> str:
    """The counters page, which is where an operator asks this question."""
    import base64

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.admin.router import router

    app = FastAPI()
    app.include_router(router)
    r = TestClient(app).get(
        f"/admin/stats?period={period}",
        headers={"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode(),
                 "Cookie": f"lang={locale}"},
    )
    assert r.status_code == 200, r.status_code
    return r.text


def test_the_spend_is_on_the_counters_page_and_not_only_in_a_query():
    """"Readable" is a screen. A query nobody renders answers this scenario the way a
    number in a log answers an alert — only for somebody who already suspected it.

    Rendered inside the same run as the rows, because the database is in memory and
    closes with it: a page fetched afterwards would be a page with nothing on it, and
    every assertion here would be about an empty table.
    """
    async def body():
        await _rung("app1", TG_GATEWAY, cost=0.01)
        await _rung("app2", FLASH_CALL, cost=3.5)
        await _rung("app1", TG_GATEWAY, outcome=ladder.UNANSWERED)
        return _stats_page()

    page = _run(body)
    assert "What verifications cost" in page
    assert "Possibly charged" in page
    assert "Who spent it" in page
    # 🔴 The empty-state sentence rather than the figures, and the bite is why. `3.50`
    # appears twice on this page — once per route and once per application — so a
    # guard written on the number stayed green with the per-route table wired to an
    # empty list, which is exactly the half a view loses in a refactor. The sentence
    # each table prints when it has nothing is the only string unique to that table.
    assert "No paid rung has been attempted" not in page, \
        "the per-route table rendered its empty state while rows existed"
    assert "Nothing has been spent on a verification" not in page, \
        "the per-application table rendered its empty state while rows existed"
    assert "3.50" in page, "the spend of the call rung is not on the page"
    assert "0.01" in page
    assert "app2" in page and "app1" in page


def test_the_word_for_a_fee_that_bought_nothing_is_the_ladders_own():
    """The store counts it and the ladder writes it; kept apart they drift, and the drift
    is silent — a column of zeros under a heading that is counting the wrong word."""
    assert queries.POSSIBLY_CHARGED == ladder.UNANSWERED
