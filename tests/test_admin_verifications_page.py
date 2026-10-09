# tests/test_admin_verifications_page.py
"""Every number's verifications, on a page of their own.

The messages view stitches a number's verifications under that number's SMS row, so a
route that places no message — flash_call dials, tg_user writes to a messenger — is
invisible at any click: there is no row to expand. This page is the whole list, codes
and all vendors' references, reached without a single message existing.

The two traps of the sibling file are guarded here too: the code must never reach the
screen, and the cost is printed as recorded (a refund already zeroed it).
"""

import asyncio
import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin.router import router
from app.db import queries
from app.db.connection import get_db, init_db, close_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import ladder

_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode()}

PHONE = "+79991112233"
OTHER = "+79994445566"
CODE = "483921"


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


def _anchor(verification_id: int) -> str:
    """How a verification is found on the page — see the sibling file for why not `#id`."""
    return f'id="verification-{verification_id}"'


async def _page(**params) -> str:
    """The verifications list, as a support call reaches it — no message needs to exist."""
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app, cookies={"lang": "ru"})
    r = c.get("/admin/verifications", headers=_AUTH, params=params or None,
              follow_redirects=True)
    assert r.status_code == 200, r.status_code
    return r.text


async def _app_row() -> None:
    await queries.create_app("sp_app", "tok-sp")


async def _verification(phone: str = PHONE, *, code: str = CODE) -> int:
    return await queries.create_verification(
        "sp_app", phone, code=code, ttl_seconds=300)


async def _carried(vid: int, *, route: str, vendor_ref: str, cost: float) -> None:
    """The route was selected, placed, and confirmed — the shape a paid rung leaves."""
    await queries.select_route(vid, "sp_app", route=route)
    rung = await queries.record_verification_rung(vid, route=route,
                                                  outcome=ladder.ATTEMPTING)
    await queries.set_rung_outcome(rung, outcome=ladder.CARRIED,
                                   vendor_ref=vendor_ref, cost=cost)


def test_a_flash_call_verification_is_visible_with_no_message_at_all():
    """The owner's case 09.10: verification 127, rung 132 carried at 0.8 ₽, and the
    messages page could not show it — flash_call writes no SMS row to expand."""
    async def body():
        await _app_row()
        vid = await _verification()
        await _carried(vid, route="flash_call", vendor_ref="uc-57415246", cost=0.8)
        assert await queries.check_verification(
            vid, "sp_app", code=CODE, max_attempts=3) == "confirmed"

        html = await _page()
        assert _anchor(vid) in html, "the verification is not on the page"
        assert PHONE in html, "the number the verification is about is not shown"
        assert "flash_call" in html, "the route is not shown"
        assert ladder.CARRIED in html, "the vendor's outcome is not shown"
        assert "uc-57415246" in html, "the vendor's own reference is not shown"
        assert "0.8" in html, "what the rung cost is not shown"
        assert "confirmed" in html
    _run(body)


def test_verifications_of_every_route_are_listed_alike():
    """Visibility must not depend on the route writing messages: the messenger rung and
    the SMS rung stand next to the call rung on the same page, rungs and all."""
    async def body():
        await _app_row()
        flash = await _verification(PHONE)
        await _carried(flash, route="flash_call", vendor_ref="uc-1", cost=0.8)
        tg = await _verification(OTHER, code="111112")
        await _carried(tg, route="tg_user", vendor_ref="tg-2", cost=0.07)
        sms = await _verification(PHONE, code="333313")
        await _carried(sms, route="sms_out", vendor_ref="uc-3", cost=0.0)

        html = await _page()
        for vid in (flash, tg, sms):
            assert _anchor(vid) in html, f"verification {vid} is not on the page"
        assert "tg_user" in html and "sms_out" in html and "flash_call" in html
    _run(body)


def test_a_verification_with_no_rung_yet_is_listed_too():
    """A verification exists from the moment it is created, before anything is placed —
    the page must not wait for a rung to show the person's login attempt."""
    async def body():
        await _app_row()
        vid = await _verification()
        html = await _page()
        assert _anchor(vid) in html
        assert "pending" in html
    _run(body)


def test_the_code_is_on_no_screen():
    """Same guarantee as the messages view: this page also renders a number next to its
    live secret, and the secret must not be the third thing on it."""
    async def body():
        await _app_row()
        vid = await _verification()
        html = await _page()
        assert _anchor(vid) in html, "positive control: the verification must be rendered"
        assert CODE not in html, "the code reached the screen"
    _run(body)


def test_the_rows_handed_to_the_page_have_no_code_in_them():
    """Not the page but the row behind it — the query, not the markup, carries the
    guarantee for this list exactly as `verifications_for_phone` does for its own."""
    async def body():
        await _app_row()
        await _verification()
        rows = await queries.list_verifications_page("30d", None, 50, 0)
        assert rows, "positive control: there is a verification to read"
        for row in rows:
            assert "code" not in row.keys(), f"the code is in the row: {row.keys()}"
    _run(body)


def test_the_phone_filter_and_the_period_bound_the_list():
    async def body():
        await _app_row()
        mine = await _verification(PHONE)
        theirs = await _verification(OTHER, code="111114")

        db = await get_db()
        await db.execute(
            "UPDATE verifications SET created_at = datetime('now', '-40 days') "
            "WHERE id = ?", (theirs,))
        await db.commit()

        html = await _page()
        assert _anchor(mine) in html
        assert _anchor(theirs) not in html, "a verification older than the window is listed"

        html = await _page(phone=PHONE[-4:])
        assert _anchor(mine) in html
        assert _anchor(theirs) not in html, "the phone filter let another number through"

        html = await _page(period="all")
        assert _anchor(mine) in html and _anchor(theirs) in html
    _run(body)
