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
    vendor whose balance nobody watches, and it has to be loud on the way in."""
    async def body():
        with caplog.at_level("WARNING"):
            balance.observe("some_new_paid_rung", 0.4)
        assert any("no balance floor is configured" in r.message
                   for r in caplog.records)
        assert alerts == []

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
        carry = tg_carrier.carrier(vid, app_id="app1", token="tok")
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
        carry = tg_carrier.carrier(vid, app_id="app1", token="tok")
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
