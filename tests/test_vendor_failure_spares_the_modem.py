"""A vendor that refuses *us* wakes the operator and puts nothing on the modem. Task 4.14.

Two halves of one norm, and the quiet half is the one with money behind it.

The loud half — "the operator is alerted, with that vendor named" — is guarded where the
alert is raised (`tests/test_tg_gateway_carrier.py`, `tests/test_balance_floor.py`). What
had no guard at all is the other half: **nothing is rerouted over the modem.** For a
МегаФон subscriber the modem is the route that has been refusing, so a fallback there
would read to the application as a delivery and behave to the person as a silence — and
it would do so on exactly the day the vendor's token was rotated, when every verification
takes that path at once.

🔴 **The guarantee is not "the ladder cannot reach the modem", and a guard written that
way would be hollow.** It measures: given a rule that names `sms_out` behind a paid rung,
`ladder.walk` *does* carry the verification over it — that is the configured ladder doing
what it was configured to do, and the positive control below asserts exactly that, so
that the guard beside it cannot pass on a modem carrier nothing could ever have reached.

What the gateway guarantees is narrower and is the thing the requirement actually names:
**automatic failover is absent.** The rungs walked are exactly the ones
`rule.route_for` answers with, in that order, and a vendor refusing us appends nothing to
them. The rule in force puts no modem rung behind the paid ladder, so on a refusal the
verification advances to the second *paid* rung and stops — and the day someone adds one
by hand, it is a configuration change with an operator's name on it rather than the
gateway falling back on its own.

The rungs are therefore read from the real `rule.route_for` rather than handed in. Handing
in `[tg_gateway, flash_call]` would assert this module's opinion of the rule against
itself and would survive the rule's shipped content changing under it.
"""

import asyncio
import json

import pytest

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import ladder, rule, tg_carrier, tg_gateway
from app.verification.routes import FLASH_CALL, SMS_OUT, TG_GATEWAY

PHONE = "+79851600019"
OPERATOR = "МегаФон"


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


@pytest.fixture
def alerts(monkeypatch):
    sent = []
    import app.alerting as alerting
    monkeypatch.setattr(
        alerting, "notify",
        lambda event, text, dedup_extra=None, phone=None: sent.append(
            (event, text, dedup_extra)))
    return sent


def _vendor_answering(monkeypatch, error, verification_id):
    """The Telegram rung's own carrier, with the vendor answering `ok: false`.

    The real carrier rather than a stub: the alert this task is half about is raised
    inside it, and a stub returning `REFUSED` would assert the ladder's half while
    silently dropping the operator's. The error string decides which of the two cases
    this is — `_classify` is what separates a refusal of *us* from a decline of the
    subscriber, and the whole norm below turns on that line.
    """
    async def check(phone, *, token, timeout=5.0, client=None):
        return tg_gateway.Ability(kind=tg_gateway._classify(error), error=error)

    async def send(*a, **kw):
        raise AssertionError("a refused check must not be followed by a send")

    monkeypatch.setattr(tg_gateway, "check_send_ability", check)
    monkeypatch.setattr(tg_gateway, "send_verification_message", send)
    return tg_carrier.carrier(verification_id, app_id="app1", token="tok")


def _rule_with_the_modem_behind_the_paid_rung():
    """The one rule that can exercise the norm: the modem standing behind a paid rung.

    Written out rather than taken from `rule.SHIPPED`, because the point of the tests
    that use it is precisely that the shipped rule does **not** look like this.
    """
    return json.dumps(
        [{"operator": OPERATOR, "routes": [TG_GATEWAY, SMS_OUT]},
         {"operator": rule.DEFAULT, "routes": [SMS_OUT]},
         {"operator": rule.UNKNOWN, "routes": [SMS_OUT]}], ensure_ascii=False)


def _recording(route, seen, outcome):
    async def carry(phone, *, seconds_left, rung_id):
        seen.append(route)
        return ladder.Attempt(outcome=outcome)

    return carry


async def _walk_the_rule(monkeypatch, *, error, seen, second=ladder.DECLINED):
    """One walk down the rungs the rule in force names, with the modem wired and watched.

    `sms_out` is in `carriers` whether or not the rule names it. That is the point: the
    modem is reachable, so "the modem was not asked" is a statement about the ladder
    rather than about this fixture's furniture.

    🔴 **The second paid rung declines by default, and that is the whole stand.** With it
    carrying, the ladder stops there and a modem rung appended behind it is never
    reached — a fallback bolted onto the tail of the walk passes every assertion here
    while being exactly the defect. Measured: a mutation appending `sms_out` to the walk
    left all four of these green until the stand stopped letting anything carry. So the
    ladder is walked to its end, with nothing having carried, which is also the real
    shape of the day this norm is for: a rotated token refuses `tg_gateway`, and
    `flash_call` has no adapter yet.
    """
    vid = await queries.create_verification("app1", PHONE, code="1234", ttl_seconds=300)
    rungs = rule.route_for(OPERATOR)
    return rungs, await ladder.walk(
        vid, app_id="app1", operator=OPERATOR, phone=PHONE, rungs=rungs, gates=(),
        carriers={
            TG_GATEWAY: _vendor_answering(monkeypatch, error, vid),
            FLASH_CALL: _recording(FLASH_CALL, seen, second),
            SMS_OUT: _recording(SMS_OUT, seen, ladder.CARRIED),
        },
        bound=5.0), vid


def test_a_vendor_refusing_our_credentials_alerts_and_puts_nothing_on_the_modem(
        monkeypatch, alerts):
    """Both halves of the task in one walk: the operator hears it, the modem does not."""
    async def body():
        seen = []
        rungs, walk, vid = await _walk_the_rule(
            monkeypatch, error="ACCESS_TOKEN_INVALID", seen=seen)

        assert alerts, "a vendor refusing our credentials must reach the operator"
        assert "Telegram" in alerts[0][1], "the alert must name which vendor"

        assert SMS_OUT not in seen, "a vendor refusal was rerouted over the modem"
        assert SMS_OUT not in rungs, "the rule in force puts the modem behind a paid rung"
        carried = [r["route"] for r in await queries.verification_rungs(vid)]
        assert SMS_OUT not in carried, "a modem rung was recorded for a vendor refusal"
        assert walk.carried_by is None, (
            "every rung the rule named refused; the verification fails rather than "
            "finding its way onto the modem")
        assert seen == [FLASH_CALL], "the ladder walked a rung the rule never named"

    _run(body)


def test_a_vendor_out_of_credit_alerts_and_puts_nothing_on_the_modem(monkeypatch, alerts):
    """The other half of the task's `or`.

    Running out of credit has no captured error string — ten samples and counting — so it
    arrives as an `ok: false` the gateway cannot place. That is `unclassified`: loud, and
    advancing as past a decline. What it must not do is advance onto the modem.
    """
    async def body():
        seen = []
        rungs, walk, vid = await _walk_the_rule(
            monkeypatch, error="BALANCE_EXHAUSTED", seen=seen)

        assert alerts and "BALANCE_EXHAUSTED" in alerts[0][1]
        assert SMS_OUT not in seen, "an out-of-credit vendor was rerouted over the modem"
        assert walk.carried_by is None
        assert seen == [FLASH_CALL]

    _run(body)


def test_the_ladder_appends_nothing_to_the_rungs_the_rule_names(monkeypatch, alerts):
    """Automatic failover is absent, said as the thing that can actually be measured.

    Not "the modem is unreachable" — it is reachable, and the control below proves it —
    but "the rungs attempted are the rule's answer and nothing else". A fallback the
    gateway added on its own would show up here as a rung the rule never named.
    """
    async def body():
        seen = []
        rungs, walk, vid = await _walk_the_rule(
            monkeypatch, error="ACCESS_TOKEN_INVALID", seen=seen)

        attempted = [r["route"] for r in await queries.verification_rungs(vid)]
        assert attempted == rungs, (
            f"the ladder walked {attempted} where the rule answers {rungs}; nothing "
            f"carried, so every rung the rule names was walked and no other")

    _run(body)


def test_a_declined_subscriber_still_reaches_the_modem_the_rule_names(
        monkeypatch, alerts):
    """The positive control, without which every assertion above is empty.

    It is also what keeps the norm narrow. A rung the **subscriber** declined says
    nothing about this gateway — one person is not in Telegram — and the modem behind it
    is an ordinary configured fallback that must go on working. Only a refusal of *us*
    withholds it. Without this test the whole of the above would pass on a modem carrier
    nothing could ever reach, and the narrowness would be an intention rather than a
    measured fact.
    """
    async def body():
        await store.set_many({rule.KEY: _rule_with_the_modem_behind_the_paid_rung()})
        seen = []
        rungs, walk, vid = await _walk_the_rule(
            monkeypatch, error="PHONE_NUMBER_NOT_AVAILABLE", seen=seen)

        assert rungs == [TG_GATEWAY, SMS_OUT]
        assert seen == [SMS_OUT], (
            "the modem carrier was never reachable, so the guards above prove nothing")
        assert walk.carried_by == SMS_OUT

    _run(body)


def test_a_refusal_of_us_withholds_the_modem_rung_the_rule_does_name(
        monkeypatch, alerts):
    """The owner's decision of 20.09.2026, on the one rule that can exercise it.

    Every other test here rests on the rule in force naming no modem rung behind the
    paid ladder — true today, and a fact about configuration rather than about the
    gateway. This one hands the ladder exactly the rule that would carry the traffic of
    a vendor outage onto the modem, and asserts it does not.

    The rung is **recorded** rather than skipped: a rung that vanishes from the row list
    is a verification whose failure has no reason on any screen.
    """
    async def body():
        await store.set_many({rule.KEY: _rule_with_the_modem_behind_the_paid_rung()})
        seen = []
        rungs, walk, vid = await _walk_the_rule(
            monkeypatch, error="ACCESS_TOKEN_INVALID", seen=seen)

        assert rungs == [TG_GATEWAY, SMS_OUT], "the stand must hand over that very rule"
        assert seen == [], "a vendor refusing us was carried over the modem"
        assert walk.carried_by is None

        rows = [(r["route"], r["outcome"]) for r in await queries.verification_rungs(vid)]
        assert rows == [(TG_GATEWAY, ladder.REFUSED), (SMS_OUT, ladder.WITHHELD)]
        assert alerts and "Telegram" in alerts[0][1], (
            "the refusal that withheld the modem must still name its vendor")
        assert len(alerts) == 1, (
            "withholding raises no second alert: one event, one line for the operator")

    _run(body)


def test_withholding_the_modem_says_why_in_the_verifications_reason(
        monkeypatch, alerts):
    """A failure whose reason reads "expired" is the one thing that did not happen."""
    async def body():
        await store.set_many({rule.KEY: _rule_with_the_modem_behind_the_paid_rung()})
        rungs, walk, vid = await _walk_the_rule(
            monkeypatch, error="ACCESS_TOKEN_INVALID", seen=[])

        assert SMS_OUT in walk.reason and ladder.WITHHELD in walk.reason, walk.reason

    _run(body)
