"""The SMS view: what it renders, what it expands, and where the old URLs go."""
import asyncio
import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries
from app.admin.router import router

_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode()}


class _RecordingModem:
    def __init__(self):
        self.sent = []

    async def enqueue(self, message_id, phone, text, app_id):
        self.sent.append((phone, text, app_id))


def _client(modem=None):
    app = FastAPI()
    app.include_router(router)
    app.state.modem = modem or _RecordingModem()
    return TestClient(app)


def _run(coro_fn):
    return asyncio.run(coro_fn())


def _seed():
    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("gm", "tok-gm")
        db = await queries.get_db()
        out = await queries.create_message("gm", "+79995550011", "sent to them")
        await db.execute(
            "INSERT INTO inbound_messages (phone, text) VALUES ('+79995550011', 'they replied')"
        )
        await db.execute(
            "INSERT INTO inbound_messages (phone, text) VALUES ('Tinkoff', 'service note')"
        )
        await db.commit()
        return out
    return _run(setup)


def test_default_view_is_thirty_days_and_carries_both_directions():
    _seed()
    try:
        html = _client().get("/admin/messages", headers=_AUTH).text
        assert "sent to them" in html
        assert "they replied" in html
        # the 30-day option is the selected one
        assert 'class="on"' in html
    finally:
        _run(close_db)


def test_a_row_expands_into_its_conversation_exactly_once():
    """A number holding several rows must not render its thread under each of them."""
    out = _seed()
    try:
        html = _client().get(f"/admin/messages?open=out-{out}", headers=_AUTH).text
        assert html.count('class="timeline"') == 1
        assert html.count('class="row-open"') == 1
    finally:
        _run(close_db)


def test_an_expansion_key_naming_nothing_renders_the_table_anyway():
    _seed()
    try:
        for key in ("out-9999", "nonsense", "out-", "in-abc", ""):
            r = _client().get(f"/admin/messages?open={key}", headers=_AUTH)
            assert r.status_code == 200, key
            assert 'class="timeline"' not in r.text, key
    finally:
        _run(close_db)


def test_the_conversation_is_not_bounded_by_the_period():
    """The period is a lens on the list; a thread cut off mid-sentence cannot be read."""
    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("gm", "tok-gm")
        db = await queries.get_db()
        await db.execute(
            "INSERT INTO messages (app_id, phone, text, status, created_at) "
            "VALUES ('gm', '+79995550011', 'ancient history', 'delivered', '2020-01-01 10:00:00')"
        )
        cursor = await db.execute(
            "INSERT INTO messages (app_id, phone, text, status) "
            "VALUES ('gm', '+79995550011', 'today', 'delivered')"
        )
        await db.commit()
        return cursor.lastrowid

    fresh = _run(setup)
    try:
        html = _client().get(f"/admin/messages?period=24h&open=out-{fresh}",
                             headers=_AUTH).text
        assert "ancient history" in html, "the thread reaches past the period"
        # …while the table itself does not
        table_only = _client().get("/admin/messages?period=24h", headers=_AUTH).text
        assert "ancient history" not in table_only
    finally:
        _run(close_db)


def test_a_service_sender_offers_no_reply_and_no_block():
    """An inbound sender is stored as the network delivered it and need not be a
    number — a reply would fail validation, a block would write a non-number."""
    _seed()
    try:
        html = _client().get("/admin/messages?open=in-2", headers=_AUTH).text
        assert "Tinkoff" in html
        assert "/admin/messages/reply" not in html
        assert "/admin/messages/block" not in html
    finally:
        _run(close_db)


def test_a_phone_sender_does_offer_reply_and_block():
    _seed()
    try:
        html = _client().get("/admin/messages?open=in-1", headers=_AUTH).text
        assert "/admin/messages/reply" in html
        assert "/admin/messages/block" in html
    finally:
        _run(close_db)


def test_period_travels_to_the_statistics_view():
    _seed()
    try:
        html = _client().get("/admin/messages?period=1y", headers=_AUTH).text
        assert '/admin/stats?period=1y' in html
    finally:
        _run(close_db)


def test_the_inbound_control_carries_no_status_with_it():
    """Both controls submit on every request, so the status is the deciding one and
    the inbound link has to drop it as it navigates."""
    _seed()
    try:
        html = _client().get("/admin/messages?status=delivered", headers=_AUTH).text
        inbound_links = [
            line for line in html.splitlines() if "direction=in" in line
        ]
        assert inbound_links, "the inbound control is rendered"
        assert all("status=" not in link for link in inbound_links)
    finally:
        _run(close_db)


def test_old_urls_still_answer():
    _seed()
    try:
        c = _client()
        assert c.get("/admin/inbound", headers=_AUTH,
                     follow_redirects=False).headers["location"] == "/admin/messages?direction=in"
        assert c.get("/admin/dialogs", headers=_AUTH,
                     follow_redirects=False).headers["location"] == "/admin/messages"
    finally:
        _run(close_db)


def test_a_dialog_deep_link_lands_on_that_conversation():
    """The `+` has to survive the trip into a query string, where it would otherwise
    decode to a space."""
    _seed()
    try:
        r = _client().get("/admin/dialogs/+79995550011", headers=_AUTH,
                          follow_redirects=False)
        assert r.status_code == 303
        location = r.headers["location"]
        assert "phone=%2B79995550011" in location
        assert "period=all" in location
        assert "open=" in location

        followed = _client().get(location, headers=_AUTH).text
        assert 'class="timeline"' in followed, "it lands with the conversation open"
        assert "they replied" in followed
    finally:
        _run(close_db)


def test_paging_keeps_the_encoded_number():
    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("gm", "tok-gm")
        for i in range(60):
            await queries.create_message("gm", "+79995550011", f"m{i}")
    _run(setup)
    try:
        html = _client().get("/admin/messages?phone=%2B79995550011", headers=_AUTH).text
        assert "phone=%2B79995550011" in html, "the next-page link keeps the + encoded"
    finally:
        _run(close_db)
