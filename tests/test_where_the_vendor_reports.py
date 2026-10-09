"""Task 4.57: the vendor is told where to report, or told nothing and we know why.

The Gateway takes its callback address **per request** — measured against the vendor's own
reference on 21.09.2026, read by layers, and there is no account-side setting to hold it:

- `core.telegram.org/gateway/api`, raw HTML. `callback_url` appears four times in the whole
  page: once as a row of `sendVerificationMessage`'s parameter table ("An HTTPS URL where you
  want to receive delivery reports related to the sent message, 0-256 bytes") and three times
  in the *Report delivery* prose, every one of them phrased around the request — *"When you
  include a `callback_url` parameter in your request"*, *"All reports submitted to your
  `callback_url`, **if you provided one**"*. The `<meta>` layer holds six tags and none of
  them speaks to it;
- `gateway.telegram.org`, the account side, both layers: zero occurrences of `callback` or
  `webhook` in the page's raw HTML, and zero in `/js/gateway.js`, which is the bundle that
  carries the cabinet's own behaviour. Its API-settings form enumerates what it submits —
  `{account_id, ip_list}` — so the enumeration is exhaustive by construction rather than by
  reading. Positive control on the same file and the same grep: `ip_list` five times,
  `revokeToken`, `getLogHistory`, `saveApiSettings`.

So the address is ours to supply on every send, and until it was supplied nothing could ever
arrive at the signed-callback door: `expired` would never fail a verification with that
reason, and no refund would ever be recorded. That whole mechanism — 4.39, 4.42, 4.43 — was
built, guarded, and unreachable in production.

Two of these fail on the implementation that is natural to write:

- one that lets the address keep a blank default at `tg_carrier.carrier`, where forgetting it
  is exactly how it came to be forgotten: a parameter every caller must decide has no right
  to a default, and the failure has to land on the signature;
- one that writes the door's path a second time in the builder, which drifts silently the
  day the door is renamed and reports itself only as a vendor that stopped reporting.
"""

import asyncio
import logging

import pytest

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store, validate_raw
from app.verification import ladder, placement, tg_callback, tg_gateway
from app.verification.routes import TG_GATEWAY

PHONE = "+79851600019"
TOKEN = "a-token"
BASE = "https://gate.example.org"


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


def _vendor(monkeypatch, sends):
    """The adapter's two methods, capturing everything the carrier hands them.

    `callback_url` and `sender_username` are read back here on purpose: the defect this
    file is about survived a green suite precisely because no test ever read back what the
    carrier passed on, only what it returned.
    """
    async def check(phone, *, token, timeout=5.0, client=None):
        return tg_gateway.Ability(
            kind=tg_gateway.ABLE, request_id="req-1",
            status=tg_gateway.RequestStatus(
                request_id="req-1", phone_number=phone.lstrip("+"),
                request_cost=0.01, remaining_balance=99.0))

    async def send(phone, *, code, ttl, token, request_id=None, callback_url="",
                   payload="", sender_username="", timeout=10.0, client=None):
        sends.append({"callback_url": callback_url, "sender_username": sender_username})
        return tg_gateway.Sent(ok=True)

    monkeypatch.setattr(tg_gateway, "check_send_ability", check)
    monkeypatch.setattr(tg_gateway, "send_verification_message", send)


async def _carry(settings):
    """Build the carriers the way production builds them, and carry one verification."""
    await store.set_many({"tg_gateway_token": TOKEN, **settings})
    vid = await queries.create_verification("app1", PHONE, code="1234", ttl_seconds=300)
    rung_id = await queries.record_verification_rung(
        vid, route=TG_GATEWAY, outcome=ladder.ATTEMPTING)
    carriers = placement.carriers_for(vid, app_id="app1", modem=None, operator=None)
    return await carriers[TG_GATEWAY](PHONE, seconds_left=5.0, rung_id=rung_id)


# --- the address reaches the vendor ---------------------------------------------------

def test_the_vendor_is_told_where_to_report(monkeypatch):
    """The whole of 4.57 in one assertion: what production builds hands the vendor the
    door that exists, assembled from the configured base and the door's own path."""
    sends = []
    _vendor(monkeypatch, sends)

    attempt = _run(lambda: _carry({"tg_gateway_callback_base": BASE}))

    assert attempt.outcome == ladder.CARRIED
    assert [s["callback_url"] for s in sends] == [BASE + tg_callback.PATH], \
        "the carrier production assembles did not tell the vendor where to report"


def test_the_address_given_to_the_vendor_is_a_door_that_exists(monkeypatch):
    """The path is not written twice.

    Read off the live route table rather than off the source, because a builder holding its
    own copy of the path is green against a grep and wrong against the app: the vendor posts
    to a 404, retries ten times, and gives up — and the only symptom is deliveries that stop
    being reported.
    """
    from fastapi import FastAPI

    from app.api.router import router

    application = FastAPI()
    application.include_router(router)
    paths = {route.path for route in application.routes}

    assert tg_callback.PATH in paths, \
        f"the vendor would be sent to {tg_callback.PATH}, which this app does not serve"
    assert "/verifications/tg-callback-that-is-not-there" not in paths, \
        "the positive control: this route table would accept any path at all"


def test_the_verified_channel_rides_along(monkeypatch):
    """`sender_username` is the only lever on what the subscriber sees (task 1.11).

    ⚠️ What it is, per the vendor's reference read 21.09.2026: *"Username of the Telegram
    channel from which the code will be sent. The specified channel, if any, must be verified
    and owned by the same account who owns the Gateway API token."* So it is not a display
    name of our choosing — it costs a verified channel, which is the owner's to obtain. This
    asserts only that the setting reaches the vendor when there is one to reach it with.
    """
    sends = []
    _vendor(monkeypatch, sends)

    _run(lambda: _carry({"tg_gateway_callback_base": BASE,
                         "tg_gateway_sender_username": "sokolparking"}))

    assert [s["sender_username"] for s in sends] == ["sokolparking"], \
        "the configured channel never reached the vendor"


# --- and when there is no address -----------------------------------------------------

def test_a_blank_base_sends_no_address_and_says_what_it_costs(monkeypatch, caplog):
    """Blank is a legitimate estate — the rung still carries — but it is degraded, and the
    degradation is invisible from the outside: messages go out and nothing ever reports back.
    It is said once, where the carrier is assembled, rather than on every send."""
    sends = []
    _vendor(monkeypatch, sends)

    with caplog.at_level(logging.WARNING, logger="app.verification.placement"):
        attempt = _run(lambda: _carry({"tg_gateway_callback_base": ""}))

    assert attempt.outcome == ladder.CARRIED, \
        "a missing callback address must not stop the rung carrying"
    assert [s["callback_url"] for s in sends] == [""], \
        "a blank base must send no address at all, not a half-built one"
    said = " ".join(r.message % r.args if r.args else r.message for r in caplog.records)
    assert "tg_gateway_callback_base" in said and "report" in said, \
        f"nothing named the setting or what is lost without it: {said!r}"


def test_the_carrier_cannot_be_built_without_deciding_the_address():
    """The defect class 4.57 *is*: a parameter with a default that every caller forgot.

    `sender_username` keeps its default — absent, the vendor sends under its own name and
    nothing silently stops working. `callback_url` does not: absent, an entire mechanism is
    unreachable and the suite stays green. So the forgetting has to land on the signature.
    """
    from app.verification.tg_carrier import carrier

    with pytest.raises(TypeError):
        carrier(1, app_id="app1", token=TOKEN)

    assert carrier(1, app_id="app1", token=TOKEN, callback_url="") is not None, \
        "the positive control: an address decided and empty must still build"


# --- what the vendor would refuse is refused at save time -----------------------------

def test_the_base_is_refused_when_the_vendor_would_refuse_it():
    """Caught on save rather than hours later at the vendor, which is where the existing
    `webhook_url` check in this store already stands, and for the same reason.

    The bounds are the vendor's own, off its parameter table: an **HTTPS** URL of 0-256
    bytes. The bound is checked against the address that will actually travel — base plus
    the door's path — because that is the string the vendor measures.
    """
    validate_raw("callbackbase", "")                      # blank: the rung still carries
    validate_raw("callbackbase", BASE)                    # the positive control
    validate_raw("callbackbase", BASE + "/")              # a pasted trailing slash

    with pytest.raises(ValueError):
        validate_raw("callbackbase", "http://gate.example.org")
    with pytest.raises(ValueError):
        validate_raw("callbackbase", "gate.example.org")
    with pytest.raises(ValueError):
        validate_raw("callbackbase", "https://" + "x" * 256)


def test_a_pasted_base_is_stored_as_it_will_be_used():
    """A trailing slash is what a pasted address carries, and two of them in the middle of
    a URL is a different path at some servers. Stripped once, on the way in."""
    from app.settings_store import normalize_raw

    assert normalize_raw("callbackbase", "  https://gate.example.org/  ") == BASE
    assert tg_callback.url_for(" " + BASE + "/ ") == BASE + tg_callback.PATH
