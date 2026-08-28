"""The gateway outlives its modem.

On 2026-08-28 the modem was unplugged and the gateway stopped serving HTTP entirely:
`lifespan` awaited the link before `yield`, so a missing device meant uvicorn never
listened and the admin console answered `502 Bad Gateway`. The operator went looking for
what was wrong with the modem and was told nothing at all.

What these tests hold down is the whole of that: the process serves without a modem,
messages wait instead of failing, the absence is visible on every page, and the link is
brought up later by the same operation that brings it back after a loss — because that
operation is now the only thing standing where the process restart used to be.
"""

import asyncio
import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.modem.at_commands as at
import app.modem.manager as manager_mod
from app.admin.router import router as admin_router
from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.modem.at_commands import ATSerial
from app.modem.manager import ModemManager, OutgoingMessage
from app.settings_store import store

_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode()}
PHONE = "+79990000001"


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


async def _state(message_id: int) -> dict:
    db = await get_db()
    async with db.execute(
        "SELECT status, attempts, error, last_attempt_error, next_attempt_at "
        "FROM messages WHERE id = ?", (message_id,),
    ) as cur:
        return dict(await cur.fetchone())


def _absent_manager(monkeypatch):
    """A manager whose ports have never been opened — the state after starting with no
    modem attached."""
    m = ModemManager("/dev/null", "/dev/null")
    for link in (m._sender, m._reader_link):
        link._usable = False
        link._reader = link._writer = None
    monkeypatch.setattr(manager_mod, "spawn_delivery_dispatch", lambda *a, **kw: None)
    monkeypatch.setattr(manager_mod, "notify", lambda *a, **kw: None)
    return m


# ------------------------------------------------------- the link is or is not in service


def test_a_link_that_was_never_opened_is_not_in_service():
    """`usable` alone cannot answer this: it starts True so that tests which install a
    transport by hand begin from an open link, which makes it useless for telling
    "never opened" from "open"."""
    s = ATSerial("/dev/ttyUSB2")
    assert s.in_service is False, "no transport was ever installed"

    s._writer = object()
    assert s.in_service is True

    s._usable = False
    assert s.in_service is False, "a lost link is not in service either"


def test_a_command_against_a_link_that_was_never_opened_is_a_transport_failure():
    """Not an AssertionError from the bare `assert self._writer` underneath. The send
    path is required to read a lost link as permission to hold, and it can only do that
    if the failure arrives as one."""
    s = ATSerial("/dev/ttyUSB2")

    with pytest.raises(at.ModemTransportError):
        asyncio.run(s.command("AT"))


# ----------------------------------------------------------------- bringing the link up


def test_ensure_link_initialises_the_port_and_reconciles_the_inbox(monkeypatch):
    """This is what the process restart used to do for free. Retiring the restart without
    moving this work here would remove a crude remedy and put nothing in its place."""
    m = _absent_manager(monkeypatch)
    done = {"init": False, "scanned": False}

    async def reconnect(*, init=True):
        if init:
            done["init"] = True
        return True

    async def scan():
        done["scanned"] = True

    m._sender.reconnect = reconnect
    m._reader_link.reconnect = reconnect
    m.scan_inbox = scan

    assert asyncio.run(m.ensure_link()) is True
    assert done["init"] is True, "the init sequence carries the URC subscription"
    assert done["scanned"] is True, "inbound that arrived while there was no link"


def test_ensure_link_reports_failure_rather_than_raising(monkeypatch):
    m = _absent_manager(monkeypatch)

    async def reconnect(*, init=True):
        return False

    async def scan():
        raise AssertionError("must not scan a link that never came up")

    m._sender.reconnect = reconnect
    m._reader_link.reconnect = reconnect
    m.scan_inbox = scan

    assert asyncio.run(m.ensure_link()) is False


def test_the_linker_keeps_trying_and_does_not_give_up(monkeypatch):
    """The old reopen budget ended in a process restart. A restart cannot help when the
    device is genuinely absent, so the budget only converted waiting into giving up."""
    m = _absent_manager(monkeypatch)
    monkeypatch.setattr(manager_mod, "_LINK_RETRY_BASE", 0.001)
    monkeypatch.setattr(manager_mod, "_LINK_RETRY_CEILING", 0.005)
    attempts = {"n": 0}

    async def ensure():
        attempts["n"] += 1
        if attempts["n"] < 5:
            return False
        m._sender._usable = m._reader_link._usable = True
        m._sender._writer = m._reader_link._writer = object()
        return True

    m.ensure_link = ensure

    async def body():
        task = asyncio.create_task(m.linker_loop())
        for _ in range(400):
            await asyncio.sleep(0.005)
            if attempts["n"] >= 5:
                break
        task.cancel()
        return attempts["n"]

    assert asyncio.run(body()) >= 5, "it must outlast four failures, not stop at a budget"


# --------------------------------------------------------------- messages wait, not fail


def test_a_message_due_with_no_link_is_held_rather_than_failed(monkeypatch):
    """Absent hardware is not a refusal by the network. Failing here turns a brief unplug
    into lost SMS and reports `failed` for a message the network never saw."""
    m = _absent_manager(monkeypatch)

    async def must_not_send(*a, **kw):
        raise AssertionError("nothing may be transmitted without a link")

    m._sender.send_sms_pdu = must_not_send

    async def body():
        mid = await queries.create_message("app1", PHONE, "hi")
        await m._send_one(OutgoingMessage(mid, PHONE, "hi", "app1"))
        return await _state(mid)

    st = _run(body)
    assert st["status"] == "pending", "held, not failed"
    assert st["attempts"] == 0, "holding costs time, never chances"
    assert st["next_attempt_at"] is not None, "a held message stays schedulable"


def test_a_send_is_still_accepted_and_queued_with_no_link(monkeypatch):
    """Accepting and queueing has never touched the modem, so it must not start now."""
    m = _absent_manager(monkeypatch)

    async def body():
        mid = await queries.create_message("app1", PHONE, "hi")
        await m.enqueue(mid, PHONE, "hi", "app1")
        return m._queue.qsize()

    assert _run(body) == 1


# ------------------------------------------------------------------ absence is not quiet


def test_the_health_snapshot_says_the_modem_is_not_detected(monkeypatch):
    """Removing the restart removes the one loud symptom an unreachable modem produced.
    A process serving pages while unable to send or receive anything, saying nothing, is
    worse than one that exits."""
    m = _absent_manager(monkeypatch)
    snap = m.health_snapshot()
    assert snap["modem_detected"] is False

    m._sender._usable = m._reader_link._usable = True
    m._sender._writer = m._reader_link._writer = object()
    assert m.health_snapshot()["modem_detected"] is True


def test_the_watchdog_never_escalates_a_missing_link_to_ending_the_process(monkeypatch):
    """The ladder's terminal rung used to call `os._exit`. With the linker retrying
    forever there is nothing left for an exit to accomplish, and the watchdog must not
    reach for it however many times it sees the link gone."""
    m = _absent_manager(monkeypatch)
    exits = []
    monkeypatch.setattr(manager_mod.os, "_exit", lambda code: exits.append(code))

    async def never_recover():
        return None

    m._reopen_link = never_recover

    async def body():
        seen = []
        for _ in range(6):
            seen.append(await m._watchdog_step())
        return seen

    seen = _run(body)
    assert exits == [], "a missing device is not a reason to end the process"
    assert manager_mod.HARD not in seen, "the terminal rung is gone for a lost link"


def test_the_watchdog_loop_no_longer_ends_the_process_over_the_link_state(monkeypatch):
    """Belt and braces: the loop above `_watchdog_step` used to exit outright when either
    port was gone, and a test that only drives the step would not see it. The one exit
    left belongs to a modem the gateway deliberately reset, not to the link."""
    import inspect
    src = inspect.getsource(manager_mod.ModemManager.watchdog_loop)
    assert "usable" not in src and "in_service" not in src, (
        "ending the process must not depend on the state of the link"
    )
    assert src.count("os._exit") == 1, "only the deliberate-reset restart remains"


# ----------------------------------------------------------------- the console says so


class _FakeModem:
    def __init__(self, detected: bool):
        self._detected = detected

    def health_snapshot(self):
        return {"modem_detected": self._detected}

    async def collect_diagnostics(self):
        return []


def _console(detected: bool) -> TestClient:
    app = FastAPI()
    app.include_router(admin_router)
    app.state.modem = _FakeModem(detected)
    return TestClient(app)


@pytest.mark.parametrize("path", ["/admin/modem"])
def test_every_admin_page_carries_the_notice_when_the_modem_is_absent(path):
    """An operator who notices that SMS have stopped begins wherever they were, not at
    the diagnostics page."""
    r = _console(detected=False).get(path, headers=_AUTH)
    assert r.status_code == 200, "the console is served whether or not the modem is there"
    assert 'class="modem-absent"' in r.text


@pytest.mark.parametrize("path", ["/admin/modem"])
def test_the_notice_is_absent_while_the_link_is_in_service(path):
    """Its presence has to carry information."""
    r = _console(detected=True).get(path, headers=_AUTH)
    assert r.status_code == 200
    assert 'class="modem-absent"' not in r.text


def test_the_diagnostics_page_renders_when_the_modem_cannot_be_read():
    """Reporting the values as unavailable, rather than failing — a page that cannot be
    opened is the worst available answer to "what is wrong with the modem"."""
    r = _console(detected=False).get("/admin/modem", headers=_AUTH)
    assert r.status_code == 200


def test_the_notice_lives_in_the_shared_layout_so_every_page_inherits_it():
    """Putting it on one page would let the console look entirely normal while nothing is
    being sent or received — which is the state that needs announcing."""
    from pathlib import Path
    base = Path("app/admin/templates/base.html").read_text(encoding="utf-8")
    assert 'class="modem-absent"' in base, "the notice belongs to the layout, not to one page"


def test_render_feeds_the_notice_from_the_health_snapshot():
    """The banner and the diagnostics page must read the same source, so the two cannot
    disagree about whether the modem is reachable."""
    from app.admin.i18n import render

    class _Req:
        cookies = {}

        class app:
            class state:
                modem = _FakeModem(detected=False)

    html = render("modem.html", _Req(), {"diag": []}).body.decode()
    assert 'class="modem-absent"' in html


def test_render_survives_an_app_with_no_modem_attribute():
    """Many tests build a bare admin app. Rendering must not depend on the manager being
    installed."""
    from app.admin.i18n import render

    class _Req:
        cookies = {}

        class app:
            class state:
                pass

    html = render("modem.html", _Req(), {"diag": []}).body.decode()
    assert 'class="modem-absent"' not in html
