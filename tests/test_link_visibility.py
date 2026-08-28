"""The link's state, where an operator actually looks.

The admin page reported what the gateway believed about the *modem* — recovering, stalled
— and nothing about the link underneath. During the 2026-07-29 incident the only external
symptom was silence and the only evidence was a traceback in the journal.
"""

import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

import asyncio

from app.admin.router import router
from app.modem.at_commands import ATSerial, ModemTransportError
from app.modem.manager import ModemManager

_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:change-me").decode()}


def _mgr():
    return ModemManager("/dev/ttyUSB2", "/dev/ttyUSB1")


def test_the_snapshot_reports_a_healthy_link():
    m = _mgr()
    m._sender._last_good = 1_700_000_000.0
    snap = m.health_snapshot()
    assert snap["link"] == "open"
    assert snap["urc_link"] == "open"
    assert snap["link_reopens"] == 0
    assert snap["link_last_good"].startswith("2023-11-")


def test_the_snapshot_reports_a_lost_link():
    m = _mgr()
    m._sender._lose_link("end of stream")
    snap = m.health_snapshot()
    assert snap["link"] == "lost"
    assert snap["urc_link"] == "open", "the two ports are reported apart"


def test_the_snapshot_reports_a_lost_urc_port():
    """It carries every +CDS and +CMTI; losing it is silent and total."""
    m = _mgr()
    m._reader_link._lose_link("end of stream")
    assert m.health_snapshot()["urc_link"] == "lost"


def test_the_snapshot_counts_reopens():
    """A link being reopened over and over is the condition an operator needs to see
    without reading logs — the fault this change could otherwise make quieter."""
    s = ATSerial("/dev/ttyUSB2")
    s._reopens = 4
    m = _mgr()
    m._sender = s
    assert m.health_snapshot()["link_reopens"] == 4


def test_the_last_known_good_time_survives_the_loss_that_follows_it():
    """It is the answer to "since when", so losing the link must not erase it."""
    m = _mgr()
    m._sender._last_good = 1_700_000_000.0
    m._sender._lose_link("end of stream")
    snap = m.health_snapshot()
    assert snap["link"] == "lost"
    assert snap["link_last_good"].startswith("2023-11-")


class _DeadModem:
    """A gateway whose port is gone: the AT liveness pre-check short-circuits the sweep."""

    def __init__(self):
        self._m = _mgr()
        self._m._sender._lose_link("end of stream")

    async def collect_diagnostics(self):
        return await ModemManager.collect_diagnostics(self._m)


def test_the_diagnostics_page_shows_the_link_when_the_modem_cannot_answer():
    """The moment it matters: every AT query fails, and the gateway row is all there is."""
    app = FastAPI()
    app.include_router(router)
    app.state.modem = _DeadModem()

    page = TestClient(app).get("/admin/modem", headers=_AUTH)
    assert page.status_code == 200
    assert "link=lost" in page.text
    assert "link_reopens=0" in page.text
    assert "link_last_good=" in page.text


def test_the_diagnostics_sweep_still_reports_the_link_when_the_modem_answers():
    class _Live:
        async def command(self, cmd, timeout=5.0):
            if cmd == "AT":
                return "OK"
            raise ModemTransportError("not the point of this test")

        usable = True
        in_service = True

        def link_snapshot(self):
            return {"link": "open", "link_last_good": "—", "link_reopens": 2}

    m = _mgr()
    m._sender = _Live()
    rows = asyncio.run(m.collect_diagnostics())
    assert rows[0]["parsed"]["link"] == "open"
    assert rows[0]["parsed"]["link_reopens"] == 2
    assert len(rows) > 2, "the sweep must continue past the gateway row"
