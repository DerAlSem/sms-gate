# tests/test_route_refusals.py
"""What the routing rule costs, counted, and said out loud.

A rule set during an outage outlives the outage. When МегаФон starts accepting traffic
again the rule stays in force, the applications that do not send codes stay refused, and
nothing on any screen says so. These are the two instruments that make the difference
between a rule that is reviewed and a rule that is forgotten: a count, and an alert once
an entry has been in force longer than the review period.
"""

import asyncio
import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.router import router
from app.db.connection import get_db, init_db, close_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import refusals, rule

_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode()}

MEGAFON = "МегаФон"
MEGAFON_SHOUTED = "МЕГАФОН"      # the same operator, as `number_operators` also holds it


def _run(body):
    async def wrapper():
        await init_db(":memory:")
        await run_migrations()
        await store.load()
        try:
            await body()
        finally:
            await close_db()
    asyncio.run(wrapper())


@pytest.fixture
def alerts(monkeypatch):
    """The real `notify`, with a fake notifier under it.

    Patching `notify` itself would step over the toggle, and the toggle is half of what
    task 4.25 asserts: this refusal has to be audible on a gateway whose notification
    settings were never touched.
    """
    sent = []

    class FakeNotifier:
        def maybe_send(self, body, dedup_sig=None, phone=None):
            sent.append((body, dedup_sig))

    import app.alerting as alerting
    monkeypatch.setattr(alerting, "_notifier", FakeNotifier())
    return sent


# --- the count -------------------------------------------------------------------

def test_a_refusal_is_counted_against_its_operator():
    async def body():
        for app_id in ("sp_app", "gmp_app", "mprz_bot"):
            await refusals.record(operator=MEGAFON, app_id=app_id, route="refuse")
        rows = await refusals.counts()
        assert len(rows) == 1, rows
        assert rows[0]["operator"] == MEGAFON
        assert rows[0]["total"] == 3
    _run(body)


def test_the_count_is_answerable_per_application():
    """"Seventy refusals" answers neither "call whose developer" nor "drop the rule"."""
    async def body():
        await refusals.record(operator=MEGAFON, app_id="sp_app", route="refuse")
        await refusals.record(operator=MEGAFON, app_id="sp_app", route="refuse")
        await refusals.record(operator=MEGAFON, app_id="gmp_app", route="refuse")
        rows = await refusals.counts()
        assert rows[0]["by_app"] == {"sp_app": 2, "gmp_app": 1}
    _run(body)


def test_two_spellings_of_one_operator_are_one_count():
    """This test fails on any implementation built on SQLite `upper()`/`LIKE` or on `==`.

    `number_operators` holds МегаФон under both spellings, written by the same lookup at
    different times, and a count split in two is a rule that looks half as expensive as
    it is.
    """
    async def body():
        await refusals.record(operator=MEGAFON, app_id="sp_app", route="refuse")
        await refusals.record(operator=MEGAFON_SHOUTED, app_id="sp_app", route="refuse")
        rows = await refusals.counts()
        assert len(rows) == 1, f"two spellings were counted apart: {rows}"
        assert rows[0]["total"] == 2
    _run(body)


def test_an_unresolved_operator_is_counted_as_the_rule_spells_it():
    """The numbers most likely to lack an operator row are the ones never messaged
    before, and they are exactly who a confirmation code is usually for."""
    async def body():
        await refusals.record(operator=None, app_id="sp_app", route="refuse")
        rows = await refusals.counts()
        assert rows[0]["operator"] == rule.UNKNOWN
    _run(body)


def test_the_count_is_in_the_database_rather_than_in_the_process():
    """The rule is reviewed on a scale of months and this gateway is deployed on a scale
    of days: a counter in memory answers zero every time anybody asks."""
    async def body():
        await refusals.record(operator=MEGAFON, app_id="sp_app", route="refuse")
        db = await get_db()
        async with db.execute("SELECT COUNT(*) AS n FROM route_refusals") as cur:
            row = await cur.fetchone()
        assert row["n"] == 1
    _run(body)


def test_the_route_that_could_not_carry_it_is_recorded():
    async def body():
        await refusals.record(operator=MEGAFON, app_id="sp_app", route="flash_call")
        rows = await refusals.counts()
        assert rows[0]["by_route"] == {"flash_call": 1}
    _run(body)


# --- the alert (task 4.25) --------------------------------------------------------

def test_the_refusal_is_audible_on_a_stock_install(alerts):
    async def body():
        assert store.notify_send_errors is False, (
            "the premise of this test: the send-failure toggle is off out of the box")
        await refusals.record(operator=MEGAFON, app_id="sp_app", route="refuse")
        assert alerts, "a refusal reached nobody on settings that were never touched"
        body_text, _sig = alerts[0]
        assert MEGAFON in body_text
        assert "sp_app" in body_text
    _run(body)


def test_the_refusal_alert_does_not_hang_on_the_send_failure_toggle(alerts):
    async def body():
        await store.set_many({"notify_send_errors": "false",
                              "notify_routing_errors": "true"})
        await refusals.record(operator=MEGAFON, app_id="sp_app", route="refuse")
        assert alerts
    _run(body)


def test_the_alert_is_deduplicated_on_the_operator_and_the_route(alerts):
    """One refusing operator must not silence the alert about another — and about seventy
    refusals a month, one alert each, teaches an operator to ignore the channel."""
    async def body():
        await refusals.record(operator=MEGAFON, app_id="sp_app", route="refuse")
        await refusals.record(operator=MEGAFON, app_id="gmp_app", route="refuse")
        await refusals.record(operator=MEGAFON_SHOUTED, app_id="sp_app", route="refuse")
        await refusals.record(operator="Билайн", app_id="sp_app", route="refuse")
        await refusals.record(operator=MEGAFON, app_id="sp_app", route="flash_call")

        sigs = [sig for _body, sig in alerts]
        assert all(sig is not None for sig in sigs), "an undeduplicated refusal alert"
        # one operator, one route: the same signature however many applications and
        # however the operator is spelled
        assert sigs[0] == sigs[1] == sigs[2]
        # a different operator, and the same operator on a different route, are each
        # their own alert
        assert sigs[3] != sigs[0]
        assert sigs[4] != sigs[0]
    _run(body)


# --- the rule that outlived its outage --------------------------------------------

def test_a_fresh_entry_is_not_reported_as_unreviewed(alerts):
    async def body():
        await refusals.review_step()
        assert not alerts, alerts
    _run(body)


def test_an_entry_in_force_longer_than_the_review_period_is_reported(alerts):
    async def body():
        await refusals.review_step()                     # records what is in force now
        await refusals.record(operator=MEGAFON, app_id="sp_app", route="refuse")
        alerts.clear()
        await _age_entries(days=40)
        await refusals.review_step()
        assert alerts, "a rule in force for forty days said nothing"
        body_text = alerts[0][0]
        assert MEGAFON in body_text
        assert "sp_app" in body_text, "the alert does not say which application pays"
    _run(body)


def test_it_reports_once_per_period_rather_than_once_per_tick(alerts):
    async def body():
        await refusals.review_step()
        await _age_entries(days=40)
        await refusals.review_step()
        assert len(alerts) == 1
        await refusals.review_step()
        await refusals.review_step()
        assert len(alerts) == 1, "the same stale rule was reported on every tick"
    _run(body)


def test_changing_an_entry_starts_its_review_period_again(alerts):
    async def body():
        await refusals.review_step()
        await _age_entries(days=40)
        await refusals.review_step()
        assert len(alerts) == 1

        await store.set_many({rule.KEY: '[{"operator": "МегаФон", "routes": '
                                       '["flash_call", "tg_gateway"]}]'})
        await refusals.review_step()
        assert len(alerts) == 1, "a rewritten entry was reported as if it had not moved"
        # the age itself, not only the silence: an entry that kept its old date but had
        # its report suppressed is silent for one period and then reports an age that
        # never happened. `days` is what the reset feeds directly.
        entry = (await refusals.rule_entries())[0]
        assert entry["days"] == 0, entry
        assert entry["reviewed_at"] is None, entry
    _run(body)


def test_the_review_period_is_the_setting_and_not_a_number_in_the_code(alerts):
    """A rule set for a week-long outage is reviewed on a different clock from one set
    for a regulatory withdrawal, and neither is knowable here."""
    async def body():
        await store.set_many({"operator_route_review_days": "5"})
        await refusals.review_step()
        await _age_entries(days=10)
        await refusals.review_step()
        assert alerts, "ten days against a five-day review period said nothing"
        assert "10 days" in alerts[0][0], alerts[0][0]
    _run(body)


def test_the_entries_that_name_no_operator_are_not_reported(alerts):
    """`*` and `?` are the baseline, not a diversion.

    A rule holding only them routes everything the way it always did, and reporting that
    every month teaches an operator to ignore the channel that also carries the entries
    that *do* divert. Either set to `refuse` is audible another way: every item it
    refuses is counted and alerted as a refusal.
    """
    async def body():
        await store.set_many({rule.KEY: '[{"operator": "*", "routes": ["sms_out"]},'
                                        ' {"operator": "?", "routes": ["refuse"]}]'})
        await refusals.review_step()
        await _age_entries(days=400)
        await refusals.review_step()
        assert not alerts, alerts
    _run(body)


def test_an_entry_dropped_from_the_rule_stops_being_watched():
    async def body():
        await refusals.review_step()
        await store.set_many({rule.KEY: '[{"operator": "*", "routes": ["sms_out"]}]'})
        await refusals.review_step()
        rows = await refusals.rule_entries()
        assert [r["operator"] for r in rows] == ["*"], rows
    _run(body)


async def _age_entries(*, days: int) -> None:
    """Push what is in force back in time, so the review period can be reached without
    waiting for it. The measured value is moved, never "now" — a probe that mutates from
    the clock measures a different thing on a slow machine."""
    db = await get_db()
    await db.execute(
        "UPDATE route_rule_entries "
        "   SET in_force_since = datetime(in_force_since, ?)", (f"-{days} days",))
    await db.commit()


# --- the console ------------------------------------------------------------------

def test_the_count_is_reachable_without_reading_the_database():
    async def body():
        await refusals.record(operator=MEGAFON, app_id="sp_app", route="refuse")
        await refusals.record(operator=MEGAFON, app_id="gmp_app", route="refuse")

        app = FastAPI()
        app.include_router(router)
        for locale in ("ru", "en"):
            c = TestClient(app, cookies={"lang": locale})
            r = c.get("/admin/stats", headers=_AUTH)
            assert r.status_code == 200, r.status_code
            assert MEGAFON in r.text, f"[{locale}] the operator is not on the page"
            assert "sp_app" in r.text, f"[{locale}] the applications are not on the page"
            assert "gmp_app" in r.text
    _run(body)


# --- who produces a refusal -------------------------------------------------------

def test_a_rule_that_refuses_this_operator_is_counted_by_the_ladder(alerts):
    """The one producer that exists today. The other — a message refused for want of a
    route that can carry text — is task 4.6 and calls `record` the same way."""
    async def body():
        from app.db import queries
        from app.verification import ladder

        await store.set_many({rule.KEY: '[{"operator": "МегаФон", "routes": ["refuse"]},'
                                        ' {"operator": "*", "routes": ["sms_out"]}]'})
        vid = await queries.create_verification(
            app_id="sp_app", phone="+79991112233", code="1234", ttl_seconds=300)

        walk = await ladder.walk(
            vid, app_id="sp_app", operator=MEGAFON, phone="+79991112233",
            rungs=rule.route_for(MEGAFON), gates=(), carriers={}, bound=5.0)

        assert walk.refused_by == "rule"
        rows = await refusals.counts()
        assert len(rows) == 1, rows
        assert rows[0]["operator"] == MEGAFON
        assert rows[0]["by_app"] == {"sp_app": 1}
        assert rows[0]["by_route"] == {rule.REFUSE: 1}
        assert alerts, "the rule refused an item and nobody was told"
    _run(body)


def test_the_operator_is_not_optional_at_the_call_site():
    """A default would file every refusal under "could not be resolved" — silently, and
    in the one number by which the rule is reviewed. So a caller that forgets it fails on
    the signature rather than on the count months later."""
    import inspect
    from app.verification import ladder
    operator = inspect.signature(ladder.walk).parameters["operator"]
    assert operator.default is inspect.Parameter.empty
