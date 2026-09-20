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


def _refusing_vendor(monkeypatch, error, verification_id):
    """The Telegram rung's own carrier, with the vendor answering `ok: false`.

    The real carrier rather than a stub: the alert this task is half about is raised
    inside it, and a stub returning `REFUSED` would assert the ladder's half while
    silently dropping the operator's.
    """
    async def check(phone, *, token, timeout=5.0, client=None):
        return tg_gateway.Ability(kind=tg_gateway._classify(error), error=error)

    async def send(*a, **kw):
        raise AssertionError("a refused check must not be followed by a send")

    monkeypatch.setattr(tg_gateway, "check_send_ability", check)
    monkeypatch.setattr(tg_gateway, "send_verification_message", send)
    return tg_carrier.carrier(verification_id, app_id="app1", token="tok")


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
            TG_GATEWAY: _refusing_vendor(monkeypatch, error, vid),
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


def test_the_modem_carrier_is_reached_when_the_rule_itself_names_it(monkeypatch, alerts):
    """The positive control, without which every assertion above is empty.

    It also states the boundary plainly: a modem rung behind a paid one is configuration,
    not failover, and the gateway carries it. What the guards above hold is that nobody
    reaches it without an operator having written it down.
    """
    async def body():
        await store.set_many({rule.KEY: json.dumps(
            [{"operator": OPERATOR, "routes": [TG_GATEWAY, SMS_OUT]},
             {"operator": rule.DEFAULT, "routes": [SMS_OUT]},
             {"operator": rule.UNKNOWN, "routes": [SMS_OUT]}], ensure_ascii=False)})
        seen = []
        rungs, walk, vid = await _walk_the_rule(
            monkeypatch, error="ACCESS_TOKEN_INVALID", seen=seen)

        assert rungs == [TG_GATEWAY, SMS_OUT]
        assert seen == [SMS_OUT], (
            "the modem carrier was never reachable, so the guards above prove nothing")
        assert walk.carried_by == SMS_OUT

    _run(body)
