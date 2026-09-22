"""The balance floor, held per vendor and never polled. Task 4.53.

A prepaid vendor fails by running out, and the first symptom is every verification
failing at once. The floor turns that into a sentence with a vendor's name in it.

🔴 **Telegram's balance cannot be read for free.** Measured 20.09.2026 inside one
request: `checkSendAbility` answered `remaining_balance: 99.99` and the send that
followed answered `remaining_balance: 0` with nothing in between that could have spent
it. A confirming ability check is the billed call, so the floor is held against what
arrives with ordinary traffic — and the tests below assert that no reading is taken from
anywhere else, which is the half that costs money if it is wrong.

**Two accounts, two floors, and never a sum.** One floor over the total is satisfied by a
funded account while the other is empty, and the empty one is a rung of the same ladder.
"""

import asyncio

import pytest

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import balance, tg_gateway
from app.verification.routes import FLASH_CALL, TG_GATEWAY


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
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


# --- the floor itself -------------------------------------------------------------------

def test_a_balance_under_the_floor_alerts_and_names_the_vendor(alerts):
    async def body():
        await store.set_many({"tg_gateway_balance_floor": "10"})
        balance.observe(TG_GATEWAY, 3.5)
        assert alerts, "a balance under the floor must reach the operator"
        event, text, dedup = alerts[0]
        assert event == "routing"
        assert "Telegram Gateway" in text, \
            f"with two paid vendors the alert must say which one: {text!r}"
        assert "3.5" in text and "10" in text
        assert dedup == f"balance_floor:{TG_GATEWAY}"

    _run(body)


def test_a_balance_above_the_floor_says_nothing(alerts):
    """The positive control. Without it the floor could be alerting on every reading."""
    async def body():
        await store.set_many({"tg_gateway_balance_floor": "10"})
        balance.observe(TG_GATEWAY, 99.99)
        assert alerts == []

    _run(body)


def test_a_balance_exactly_at_the_floor_is_not_yet_under_it(alerts):
    async def body():
        await store.set_many({"tg_gateway_balance_floor": "10"})
        balance.observe(TG_GATEWAY, 10.0)
        assert alerts == []

    _run(body)


def test_an_absent_balance_is_not_a_balance_of_zero(alerts):
    """The vendor omits the field from most answers, and its absence says nothing about
    the account. Read as zero it would alert on every status callback."""
    async def body():
        await store.set_many({"tg_gateway_balance_floor": "10"})
        balance.observe(TG_GATEWAY, None)
        assert alerts == []

    _run(body)


def test_the_floor_is_a_setting_and_takes_effect_without_a_restart(alerts):
    async def body():
        await store.set_many({"tg_gateway_balance_floor": "1"})
        balance.observe(TG_GATEWAY, 3.5)
        assert alerts == []
        await store.set_many({"tg_gateway_balance_floor": "10"})
        balance.observe(TG_GATEWAY, 3.5)
        assert alerts

    _run(body)


# --- two vendors, two floors, never a sum ----------------------------------------------

def test_each_vendor_is_held_against_its_own_floor(alerts):
    """The empty account must be found even while the other one is full — a floor over
    the sum would be satisfied by the funded half."""
    async def body():
        await store.set_many({"tg_gateway_balance_floor": "10",
                              "flash_call_balance_floor": "50"})
        balance.observe(TG_GATEWAY, 99.99)      # comfortably above its own floor
        balance.observe(FLASH_CALL, 12.0)       # above Telegram's, under its own
        assert len(alerts) == 1, \
            "exactly the vendor under its own floor must alert"
        assert "uCaller" in alerts[0][1]
        assert "Telegram" not in alerts[0][1], \
            "the alert must not name the vendor that is fine"
        assert alerts[0][2] == f"balance_floor:{FLASH_CALL}"

    _run(body)


def test_the_two_vendors_dedup_separately(alerts):
    """Both running low is two alerts, not one suppressed by the other."""
    async def body():
        await store.set_many({"tg_gateway_balance_floor": "10",
                              "flash_call_balance_floor": "50"})
        balance.observe(TG_GATEWAY, 1.0)
        balance.observe(FLASH_CALL, 1.0)
        assert len({d for _, _, d in alerts}) == 2

    _run(body)


def test_a_route_with_no_floor_configured_is_not_read_as_fine(alerts, caplog):
    """Zero is how a floor silently stops existing. A balance arriving for a rung nobody
    has set a floor for must be said out loud rather than passed over."""
    async def body():
        await store.set_many({"flash_call_balance_floor": "0"})
        with caplog.at_level("WARNING"):
            balance.observe(FLASH_CALL, 0.4)
        assert any("not being watched" in r.message or "not set" in r.message
                   for r in caplog.records), \
            "an unwatched vendor balance must be reported, not shrugged at"

    _run(body)


def test_a_paid_route_with_no_floor_setting_at_all_is_reported(alerts, caplog):
    """The guard for a third paid vendor added without its floor: the failure shape is a
    vendor whose balance nobody watches, and it has to be loud on the way in.

    ⚠️ This used to assert `alerts == []` — that the line stayed in the log. The owner
    reversed it on 22.09.2026 (task 4.65): a log line is read when somebody already
    suspects something, which is never the case for a floor nobody set. The channel is
    asserted next door; what stays here is that the log still carries it too.
    """
    async def body():
        with caplog.at_level("WARNING"):
            balance.observe("some_new_paid_rung", 0.4)
        assert any("no balance floor is configured" in r.message
                   for r in caplog.records)

    _run(body)


# --- and the reading is never bought --------------------------------------------------

def test_the_carrier_reads_the_balance_from_the_confirming_check_only(alerts, monkeypatch):
    """The whole cost argument, asserted where it is spent.

    The carrier is driven through a confirmed ability check whose answer carries a low
    balance and a send whose answer carries a high one. The floor must fire on the
    check's number: the send's `remaining_balance` is not the account's balance, and a
    gateway that believed it would announce that a draining account had refilled itself.
    """
    async def body():
        from app.verification import ladder, tg_carrier

        await store.set_many({"tg_gateway_balance_floor": "10"})

        async def fake_check(phone, *, token, timeout):
            return tg_gateway.Ability(
                kind=tg_gateway.ABLE, request_id="req-1",
                status=tg_gateway.RequestStatus(
                    request_id="req-1", phone_number="79851600019",
                    request_cost=0.01, remaining_balance=2.5))

        async def fake_send(phone, **kw):
            return tg_gateway.Sent(
                ok=True,
                status=tg_gateway.RequestStatus(
                    request_id="req-1", phone_number="79851600019",
                    remaining_balance=9999.0))

        monkeypatch.setattr(tg_gateway, "check_send_ability", fake_check)
        monkeypatch.setattr(tg_gateway, "send_verification_message", fake_send)

        await queries.create_app("app1", "token-app1")
        vid = await queries.create_verification("app1", "+79851600019", code="1234",
                                                ttl_seconds=300)
        rung_id = await queries.record_verification_rung(vid, route=TG_GATEWAY,
                                                         outcome=ladder.ATTEMPTING)
        carry = tg_carrier.carrier(vid, app_id="app1", token="tok",
                                   callback_url="")
        attempt = await carry("+79851600019", seconds_left=5.0, rung_id=rung_id)
        assert attempt.outcome == ladder.CARRIED

        low = [a for a in alerts if a[2] == f"balance_floor:{TG_GATEWAY}"]
        assert low, "the confirming check's balance of 2.5 is under the floor of 10"
        assert "2.5" in low[0][1]
        assert "9999" not in low[0][1], \
            "the send's number is not the account's balance and must not be read"

    _run(body)


def test_a_declining_check_reports_no_balance_at_all(alerts, monkeypatch):
    """A decline is not a confirming check, so whatever number it carries is not the
    account's balance — and reading it would alert on a figure that means something
    else."""
    async def body():
        from app.verification import ladder, tg_carrier

        await store.set_many({"tg_gateway_balance_floor": "10"})

        async def fake_check(phone, *, token, timeout):
            return tg_gateway.Ability(
                kind=tg_gateway.DECLINED, error="PHONE_NUMBER_NOT_AVAILABLE",
                status=tg_gateway.RequestStatus(
                    request_id="req-x", phone_number="79851600019",
                    remaining_balance=0.0))

        monkeypatch.setattr(tg_gateway, "check_send_ability", fake_check)

        await queries.create_app("app1", "token-app1")
        vid = await queries.create_verification("app1", "+79851600019", code="1234",
                                                ttl_seconds=300)
        rung_id = await queries.record_verification_rung(vid, route=TG_GATEWAY,
                                                         outcome=ladder.ATTEMPTING)
        carry = tg_carrier.carrier(vid, app_id="app1", token="tok",
                                   callback_url="")
        attempt = await carry("+79851600019", seconds_left=5.0, rung_id=rung_id)

        assert attempt.outcome == ladder.DECLINED
        assert [a for a in alerts if a[2] == f"balance_floor:{TG_GATEWAY}"] == [], \
            "a zero on a decline is not the account's balance"

    _run(body)


def test_nothing_here_asks_the_vendor_anything(monkeypatch):
    """The floor places no call of its own. Asserted on the transport rather than on the
    outcome: a poll would be free to write and would cost money on every idle rung."""
    async def body():
        called = []
        monkeypatch.setattr(tg_gateway, "check_send_ability",
                            lambda *a, **kw: called.append(a))
        await store.set_many({"tg_gateway_balance_floor": "10"})
        balance.observe(TG_GATEWAY, 1.0)
        assert called == []

    _run(body)


# --- "nobody is watching this" is answerable without an event, task 4.65 ---------------
#
# Found by the critic circle of 22.09.2026 and decided by the owner the same day: a check
# at startup, and `notify` rather than the log. Both unwatched states used to leave through
# `logger.warning` while the floor they belong to wakes the operator — and worse, `observe`
# runs only once a balance has arrived, which is to say only once the rung is already
# carrying. The rung nobody has used yet is exactly the case the norm was written about,
# and it said nothing at all.

def test_an_unwatched_floor_wakes_the_operator_rather_than_the_log(alerts):
    """As loudly as the floor itself. A floor that is not set is indistinguishable, from
    the log's point of view, from a vendor that never runs out."""
    async def body():
        await store.set_many({"flash_call_balance_floor": "0"})
        balance.observe(FLASH_CALL, 0.4)

        assert alerts, "an unwatched vendor balance was left in the log"
        assert "uCaller" in alerts[0][1], "the alert must name which vendor"
        assert alerts[0][0] == "routing", alerts[0]

    _run(body)


def test_a_paid_route_with_no_floor_setting_at_all_wakes_the_operator(alerts):
    """The third paid vendor added without its floor. The route name is all there is to
    say, so the alert says it rather than staying quiet for want of a vendor name."""
    async def body():
        balance.observe("some_new_paid_rung", 0.4)
        assert alerts and "some_new_paid_rung" in alerts[0][1], alerts

    _run(body)


def test_a_watched_balance_above_its_floor_still_says_nothing(alerts):
    """The control on both of the above: the loudness is about being unwatched, not about
    every balance that arrives."""
    async def body():
        await store.set_many({"flash_call_balance_floor": "5"})
        balance.observe(FLASH_CALL, 40.0)
        assert alerts == []

    _run(body)


def test_a_configured_rung_with_no_floor_is_reported_before_it_carries_anything(alerts):
    """🔴 The half `observe` cannot reach at all: this rung has carried nothing, so no
    balance has arrived, so nothing calls `observe`. The norm was written about exactly
    this rung, and until 22.09.2026 it was the one case that said nothing."""
    async def body():
        await store.set_many({"tg_gateway_token": "a-token",
                              "tg_gateway_balance_floor": "0"})
        await balance.report_unwatched_rungs()

        assert alerts, "a configured paid rung with no floor was not reported at startup"
        assert "Telegram Gateway" in alerts[0][1], alerts
        assert alerts[0][0] == "routing", alerts[0]

    _run(body)


def test_a_configured_rung_with_a_floor_is_not_reported(alerts):
    """The control. Without it the check is satisfied by one that reports every rung."""
    async def body():
        await store.set_many({"tg_gateway_token": "a-token",
                              "tg_gateway_balance_floor": "10"})
        await balance.report_unwatched_rungs()
        assert alerts == []

    _run(body)


def test_an_unconfigured_rung_is_not_reported_for_want_of_a_floor(alerts):
    """The other control, and it is the one that keeps the channel worth reading.

    A rung with no credential is never offered — the registry refuses it at the probe and
    `placement.carriers_for` leaves it out of the map — so it spends nothing and its
    missing floor costs nothing. Reporting it on every start would teach an operator to
    ignore the channel that also carries "this vendor is running out".
    """
    async def body():
        await store.set_many({"tg_gateway_balance_floor": "0",
                              "flash_call_balance_floor": "0"})
        await balance.report_unwatched_rungs()
        assert alerts == [], "a rung nothing can carry was reported for want of a floor"

    _run(body)


def test_the_startup_path_actually_asks_before_it_serves():
    """🔴 The check exists and is called, and the second half is asserted here.

    Read as an AST rather than as text: `assert "report_unwatched_rungs" in source` goes
    green on an import line or a comment mentioning it, which is the form of evidence this
    change has repeatedly found worthless. What is asserted is an `await` of that name
    inside `lifespan`, **before the `yield`** — after it would be a check that runs at
    shutdown, when the answer is no use to anybody.
    """
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("app/main.py").read_text(encoding="utf-8"))
    lifespan = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan"), None)
    assert lifespan is not None, "app/main.py has no lifespan to start anything from"

    called_at, yielded_at = None, None
    for node in ast.walk(lifespan):
        if isinstance(node, ast.Yield) and yielded_at is None:
            yielded_at = node.lineno
        if (isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "report_unwatched_rungs"):
            called_at = node.lineno

    assert called_at is not None, \
        "nothing at startup asks which paid rung nobody is watching the balance of"
    assert yielded_at is not None and called_at < yielded_at, \
        "the check runs after the app yields, which is to say at shutdown"
