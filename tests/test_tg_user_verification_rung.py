"""SG-32: the `tg_user` rung on the verification ladder — GM+ codes from GM+'s own account.

One test per acceptance criterion of the task, walked through `placement.place` the way
the door walks it, with the Telegram client replaced at the route interface and nothing
else: the brand map, the limit rule, the ledgers and the ladder are the real ones.
"""

import asyncio
import json
import logging

import pytest

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.routing.route import Attempt, Outcome
from app.settings_store import store
from app.verification import ladder, placement, probes, tg_user_carrier
from app.verification.routes import SMS_OUT, TG_GATEWAY, TG_USER

PHONE = "+79851600019"
ACCOUNT = "@gmplus_support"
TEMPLATE = "ГМ+: ваш код {code}"
INTRO = "Это поддержка ГМ+, вы запросили код входа"

BRANDS = {
    "apps": {"gmp": {"brands": ["gmplus"], "default": "gmplus"}},
    "brands": {"gmplus": {"tg_user": {
        "account": ACCOUNT, "number": "+79998866822", "intro": INTRO}}},
}
LIMITS = {"accounts": {ACCOUNT: {"per_hour": 5, "per_day": 20}},
          "recipient_window_seconds": 0}
RULE = [{"operator": "*", "routes": [TG_USER, SMS_OUT]},
        {"operator": "?", "routes": [TG_USER, SMS_OUT]}]


class FakeRoute:
    """The route interface, answering what the test tells it to."""

    name = TG_USER

    def __init__(self, *answers):
        self.answers = list(answers) or [Attempt(Outcome.ACCEPTED)]
        self.offers = []

    def configured(self):
        return True

    async def offer(self, **kw):
        self.offers.append(kw)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if answer == "hang":
            await asyncio.sleep(60)
        return answer


class Modem:
    def __init__(self):
        self.queued = []

    async def enqueue(self, message_id, phone, text, app_id=""):
        self.queued.append(text)


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Keys set and a session file on disk; the route itself is the fake."""
    from app.config import settings
    (tmp_path / "gmplus_support.session").write_bytes(b"")
    monkeypatch.setattr(settings, "tg_api_id", 1)
    monkeypatch.setattr(settings, "tg_api_hash", "h")
    monkeypatch.setattr(settings, "tg_session_dir", str(tmp_path))
    route = FakeRoute()
    monkeypatch.setattr(tg_user_carrier, "route", lambda: route)
    return route


@pytest.fixture
def alerts(monkeypatch):
    sent = []
    import app.alerting
    monkeypatch.setattr(app.alerting, "notify",
                        lambda kind, text, **kw: sent.append(text))
    return sent


def _run(body, *, limits=LIMITS, brands=BRANDS):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("gmp", "token-gmp")
        await store.load()
        await store.set_many({
            "verification_templates":
                json.dumps([{"app_id": "gmp", "template": TEMPLATE}], ensure_ascii=False),
            "operator_routes": json.dumps(RULE),
            "messenger_limits": json.dumps(limits),
            "messenger_brands": json.dumps(brands, ensure_ascii=False),
        })
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


async def _place(modem=None, *, code="1234", route=TG_USER):
    vid = await queries.create_verification("gmp", PHONE, code=code, ttl_seconds=300)
    await queries.select_route(vid, "gmp", route=route)
    walk = await placement.place(vid, app_id="gmp", operator=None, phone=PHONE,
                                 route=route, modem=modem or Modem())
    return vid, walk, await queries.get_verification(vid, "gmp")


def _outcomes(walk):
    return [(a.route, a.outcome) for a in walk.attempts]


async def _claims():
    db = await get_db()
    async with db.execute("SELECT COUNT(*) FROM messenger_rate_claims") as cur:
        return (await cur.fetchone())[0]


# --- #1 the code goes from the account, inside the application's own words -------------

def test_the_code_goes_from_the_account_inside_the_template(wired):
    async def body():
        return await _place()

    _, walk, row = _run(body)
    assert walk.carried_by == TG_USER, walk
    assert row["route"] == TG_USER
    offer = wired.offers[0]
    assert offer["account"] == ACCOUNT
    assert TEMPLATE.format(code="1234") in offer["text"]
    assert offer["message_id"] < 0, "a verification id must not share the message-id space"


# --- #2 a number with no Telegram falls to the next rung ------------------------------

def test_a_miss_is_a_decline_and_the_modem_carries(wired):
    wired.answers = [Attempt(Outcome.MISS, reason="no account")]
    modem = Modem()

    async def body():
        return await _place(modem)

    _, walk, row = _run(body)
    assert _outcomes(walk) == [(TG_USER, ladder.DECLINED), (SMS_OUT, ladder.CARRIED)]
    assert row["route"] == SMS_OUT
    assert modem.queued and "1234" in modem.queued[0]


# --- #3 a send that may have left still advances --------------------------------------

@pytest.mark.parametrize("answer", [Attempt(Outcome.INDETERMINATE, reason="severed"),
                                    "hang"])
def test_an_unanswered_send_advances_to_the_next_rung(wired, answer, monkeypatch):
    wired.answers = [answer]
    # The ladder's whole bound, so that a hung rung leaves time for the one below it.
    monkeypatch.setattr(tg_user_carrier, "_offer", _short(tg_user_carrier._offer))

    async def body():
        return await _place()

    _, walk, _ = _run(body)
    assert _outcomes(walk) == [(TG_USER, ladder.UNANSWERED), (SMS_OUT, ladder.CARRIED)]


def _short(offer):
    async def bounded(rung, *, seconds_left, **kw):
        return await offer(rung, seconds_left=min(seconds_left, 0.2), **kw)
    return bounded


# --- #4 without keys or a session the rung is not wired and spends nothing -------------

@pytest.mark.parametrize("missing", ["keys", "session"])
def test_an_unwired_rung_takes_no_claim_and_says_so(tmp_path, monkeypatch, caplog,
                                                    alerts, missing):
    from app.config import settings
    monkeypatch.setattr(settings, "tg_session_dir", str(tmp_path))
    if missing == "session":
        monkeypatch.setattr(settings, "tg_api_id", 1)
        monkeypatch.setattr(settings, "tg_api_hash", "h")
    else:
        (tmp_path / "gmplus_support.session").write_bytes(b"")
        monkeypatch.setattr(settings, "tg_api_id", 0)
    monkeypatch.setattr(tg_user_carrier, "_wired", None)
    caplog.set_level(logging.WARNING)

    async def body():
        _, walk, _ = await _place()
        return walk, await _claims()

    walk, claims = _run(body)
    assert _outcomes(walk)[0] == (TG_USER, ladder.ABSENT)
    assert claims == 0, "an unwired rung spent the account's allowance"
    assert "route is configured but not wired" in caplog.text


def test_an_application_with_no_account_is_not_offered_the_rung(wired):
    async def body():
        offered = await probes.build_probes(
            None, tg_token="", ucaller_bearer="", app_id="hrm")[TG_USER](PHONE)
        mine = await probes.build_probes(
            None, tg_token="", ucaller_bearer="", app_id="gmp")[TG_USER](PHONE)
        return offered, mine

    other, mine = _run(body)
    assert not other.holds
    assert mine.holds, mine.reason
    assert not wired.offers, "a probe must not ask Telegram anything"


# --- #5 a refusal of us is loud, names the account, and the modem still carries -------

def test_a_refusal_of_the_account_is_loud_and_does_not_withhold_the_modem(wired, alerts):
    wired.answers = [Attempt(Outcome.UNAVAILABLE, reason="session revoked",
                             limits_account=True)]

    async def body():
        return await _place()

    _, walk, row = _run(body)
    assert _outcomes(walk) == [(TG_USER, ladder.REFUSED), (SMS_OUT, ladder.CARRIED)]
    assert any(ACCOUNT in text for text in alerts), alerts


def test_a_paid_vendor_refusal_still_withholds_the_modem(monkeypatch, alerts):
    """The rule of 20.09.2026 stands for the rungs it was written for."""
    async def refusing(phone, *, seconds_left, rung_id):
        return ladder.Attempt(outcome=ladder.REFUSED, reason="bad token")

    async def body():
        vid = await queries.create_verification("gmp", PHONE, code="1234", ttl_seconds=300)
        return await ladder.walk(vid, app_id="gmp", operator=None, phone=PHONE,
                                 rungs=[TG_GATEWAY, SMS_OUT], gates=(),
                                 carriers={TG_GATEWAY: refusing}, bound=5.0)

    walk = _run(body)
    assert _outcomes(walk) == [(TG_GATEWAY, ladder.REFUSED), (SMS_OUT, ladder.WITHHELD)]


# --- #6 the account's bounds hold, and survive a restart ------------------------------

def test_the_hourly_bound_refuses_and_survives_a_restart(wired, alerts):
    limits = {"accounts": {ACCOUNT: {"per_hour": 1, "per_day": 5}},
              "recipient_window_seconds": 0}

    async def body():
        # Each carry builds its own `DurableBounds`, so the second verification is
        # refused by what the database holds and by nothing in memory — which is what a
        # restart leaves. `test_rate_bounds_survive_a_restart.py` holds the table itself.
        _, first, _ = await _place(code="1111")
        _, second, _ = await _place(code="2222")
        return first, second

    first, second = _run(body, limits=limits)
    assert first.carried_by == TG_USER
    assert _outcomes(second)[0] == (TG_USER, ladder.REFUSED)
    assert len(wired.offers) == 1, "the bound was checked after Telegram was asked"


# --- #7 the first message introduces the account, and only the first ------------------

def test_the_first_message_introduces_and_the_second_does_not(wired):
    async def body():
        await _place(code="1111")
        await _place(code="2222")

    _run(body)
    first, second = (o["text"] for o in wired.offers)
    assert first.startswith(INTRO)
    assert not second.startswith(INTRO)
    assert TEMPLATE.format(code="2222") == second


def test_an_indeterminate_send_does_not_count_as_written(wired):
    wired.answers = [Attempt(Outcome.INDETERMINATE), Attempt(Outcome.ACCEPTED)]

    async def body():
        await _place(code="1111")
        await _place(code="2222")

    _run(body)
    assert all(o["text"].startswith(INTRO) for o in wired.offers)


def test_an_account_with_no_introduction_cannot_be_saved():
    """The first guard is at save time: a brand map with a `tg_user` account and no
    `intro` is refused, so the carrier's own refusal is the second statement of it."""
    brands = json.loads(json.dumps(BRANDS))
    del brands["brands"]["gmplus"]["tg_user"]["intro"]

    with pytest.raises(ValueError, match="intro"):
        _run(lambda: asyncio.sleep(0), brands=brands)


# --- #8 a verification that ended before the send sends nothing -----------------------

def test_a_code_gone_before_the_send_is_not_sent(wired):
    async def body():
        vid = await queries.create_verification("gmp", PHONE, code="1234", ttl_seconds=300)
        await queries.fail_verification(vid, reason="ended under the ladder")
        rung_id = await queries.record_verification_rung(
            vid, route=TG_USER, outcome=ladder.ATTEMPTING)
        carry = tg_user_carrier.carrier(vid, app_id="gmp")
        return await carry(PHONE, seconds_left=5.0, rung_id=rung_id)

    attempt = _run(body)
    assert attempt.outcome == ladder.FAILED
    assert not wired.offers


# --- review of 26.09.2026 ------------------------------------------------------------

def test_the_ladder_stops_waiting_without_cancelling_the_offer(wired):
    """A cancellation inside the route's first connect skips its cleanup and leaves the
    session file held — the next verification then meets `database is locked`."""
    cancelled = []

    async def slow(**kw):
        try:
            await asyncio.sleep(0.3)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
        return Attempt(Outcome.ACCEPTED)

    async def body():
        attempt = await tg_user_carrier._offer(
            type("R", (), {"offer": staticmethod(slow)})(), seconds_left=0.05,
            message_id=-1, phone=PHONE, text="x", brand="gmplus", account=ACCOUNT)
        await asyncio.sleep(0.4)
        return attempt

    attempt = asyncio.run(body())
    assert attempt.outcome is Outcome.INDETERMINATE
    assert not cancelled, "the ladder's deadline cancelled the route mid-flight"


def test_our_own_limit_is_not_reported_as_telegram_refusing(wired, alerts):
    limits = {"accounts": {ACCOUNT: {"per_hour": 1, "per_day": 5}},
              "recipient_window_seconds": 0}

    async def body():
        await _place(code="1111")
        await _place(code="2222")

    _run(body, limits=limits)
    assert alerts and "Telegram was not contacted" in alerts[-1], alerts
    assert not alerts[-1].startswith("Telegram refused")


# --- tg_user stands in front of the rule, never inside it (26.09.2026) ----------------

def test_a_rule_that_does_not_name_tg_user_still_continues_below_it(wired):
    """The live rule names no `tg_user`, and must not: the modem sender refuses every
    plain `/send` whose rule entry does not start with `sms_out`. A code Telegram missed
    still goes down the operator's own entry."""
    wired.answers = [Attempt(Outcome.MISS)]

    async def body():
        await store.set_many({"operator_routes": json.dumps(
            [{"operator": "*", "routes": [SMS_OUT]},
             {"operator": "?", "routes": [SMS_OUT]}])})
        assert placement.ladder_from(TG_USER, None) == [TG_USER, SMS_OUT]
        return await _place()

    _, walk, row = _run(body)
    assert _outcomes(walk) == [(TG_USER, ladder.DECLINED), (SMS_OUT, ladder.CARRIED)]
    assert row["route"] == SMS_OUT


def test_another_unnamed_rung_is_still_carried_alone():
    """The owner's decision of 21.09.2026 stands for every other rung."""
    async def body():
        await store.set_many({"operator_routes": json.dumps(
            [{"operator": "*", "routes": [SMS_OUT]},
             {"operator": "?", "routes": [SMS_OUT]}])})
        return placement.ladder_from(TG_GATEWAY, None)

    assert _run(body) == [TG_GATEWAY]
