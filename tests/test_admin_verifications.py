# tests/test_admin_verifications.py
"""One person's verification, beside that person's messages.

The counters answer "how much"; a support call is always about one person, and the
question it asks is "what happened to this number" — every rung attempted, what each
vendor said, whether it was confirmed, what it is recorded as costing.

Two traps are guarded here rather than remembered. The code must never reach a screen
(task 4.22), and the cost shown is the cost **as recorded**: since 20.09.2026 a refund
zeroes it, and helpfully printing the gross figure beside it would restore exactly the
asterisk that change removed.
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
    """How a verification is found on the page.

    Not `f"#{id}"`: that matches inside every hex colour in the stylesheet, so a control
    written that way passes on a page that renders no verification at all — which is
    exactly what it was there to rule out.
    """
    return f'id="verification-{verification_id}"'


async def _page(phone: str = PHONE, locale: str = "ru") -> str:
    """The messages view with this number's row expanded — the surface a support call
    lands on."""
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app, cookies={"lang": locale})
    r = c.get(f"/admin/dialogs/{phone}", headers=_AUTH, follow_redirects=True)
    assert r.status_code == 200, r.status_code
    return r.text


async def _message(phone: str = PHONE) -> int:
    """Something for the number to have a row in the view at all."""
    await queries.create_app("sp_app", "tok-sp")
    return await queries.create_message("sp_app", phone, "hello")


async def _verification(phone: str = PHONE, *, code: str = CODE) -> int:
    return await queries.create_verification(
        "sp_app", phone, code=code, ttl_seconds=300)


def test_the_rungs_of_a_verification_are_visible_beside_the_messages():
    async def body():
        await _message()
        vid = await _verification()
        tg = await queries.record_verification_rung(vid, route="tg_gateway",
                                                    outcome=ladder.ATTEMPTING)
        await queries.set_rung_outcome(tg, outcome=ladder.DECLINED,
                                       reason="unreachable", vendor_ref=None, cost=0.0)
        call = await queries.record_verification_rung(vid, route="flash_call",
                                                      outcome=ladder.ATTEMPTING)
        await queries.set_rung_outcome(call, outcome=ladder.CARRIED, reason=None,
                                       vendor_ref="uc-778", cost=1.5)

        html = await _page()
        assert _anchor(vid) in html, "the verification is not on the page"
        assert "tg_gateway" in html, "a rung attempted is not shown"
        assert "flash_call" in html
        assert ladder.DECLINED in html, "the vendor's outcome for a rung is not shown"
        assert ladder.CARRIED in html
        assert "uc-778" in html, "the vendor's own reference is not shown"
        assert "1.5" in html, "what the rung cost is not shown"
    _run(body)


def test_the_code_is_on_no_screen():
    """Task 4.22. The row holds a subscriber's number next to a live secret, and the
    console is the one place both are rendered together."""
    async def body():
        await _message()
        vid = await _verification()
        html = await _page()
        assert _anchor(vid) in html, "positive control: the verification must be rendered"
        assert CODE not in html, "the code reached the screen"
    _run(body)


def test_a_refunded_rung_shows_what_it_cost_and_not_what_it_was_charged():
    """Task 4.54 lowered the recorded spend to nothing on a refund rather than leaving an
    asterisk beside it. Printing the gross figure here would put the asterisk back."""
    async def body():
        await _message()
        vid = await _verification()
        rung = await queries.record_verification_rung(vid, route="tg_gateway",
                                                      outcome=ladder.ATTEMPTING)
        await queries.set_rung_outcome(rung, outcome=ladder.CARRIED, reason=None,
                                       vendor_ref="tg-991", cost=0.07)
        db = await get_db()
        await db.execute(
            "UPDATE verification_rungs SET refunded = 1, cost = 0 WHERE id = ?", (rung,))
        await db.commit()

        html = await _page()
        assert "tg-991" in html, "positive control: the rung must be rendered"
        assert "0.07" not in html, "the pre-refund charge is shown beside the refund"
    _run(body)


def test_another_number_s_verifications_are_not_shown():
    async def body():
        await _message()
        await queries.create_message("sp_app", OTHER, "hello")
        mine = await _verification()
        theirs = await _verification(OTHER, code="111111")
        await queries.record_verification_rung(theirs, route="tg_gateway",
                                               outcome=ladder.ATTEMPTING)
        html = await _page()
        assert _anchor(mine) in html
        assert _anchor(theirs) not in html, "another number's verification is here"
    _run(body)


def test_a_number_with_no_verifications_renders_without_them():
    async def body():
        await _message()
        for locale in ("ru", "en"):
            html = await _page(locale=locale)
            assert "hello" in html, f"[{locale}] the conversation itself is gone"
    _run(body)


def test_the_row_handed_to_the_page_has_no_code_in_it():
    """Not the page but the row behind it.

    The page is clean today because the template never prints `v.code`, so a query that
    selected it would still render nothing — which puts the whole guarantee on one line
    of markup and hands a live secret to whoever edits that template next. The row is
    what the query produces directly, so it is what this asserts.
    """
    async def body():
        await _message()
        await _verification()
        rows = await queries.verifications_for_phone(PHONE)
        assert rows, "positive control: there is a verification to read"
        for row in rows:
            assert "code" not in row.keys(), f"the code is in the row: {row.keys()}"
    _run(body)
