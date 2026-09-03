"""Losing the reader loop is silent and total — no `+CDS` and no `+CMTI`.

`inbound_loop` and `retry_loop` already hold this line; the `+CDS` path was the one bare
one, and this change is what starts feeding it text the network chose. A report is now
parsed for a phone number and a timestamp, and it reaches attribution, the ledger and the
alerting layer — several more places a raise can come from than "read one integer".
"""
import asyncio
import logging

import pytest

import app.modem.manager as manager_mod
from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.modem.manager import ModemManager
from app.settings_store import store

GOOD = ('+CDS: 6,42,"+79031680015",145,"26/09/02,11:00:00+00",'
        '"26/09/02,11:30:00+00",0')
POISON = ('+CDS: 6,77,"+79994445566",145,"26/09/02,11:00:00+00",'
          '"26/09/02,11:30:00+00",0')


class ScriptedPort:
    """Hands the loop a fixed sequence of URC chunks, then blocks for ever.

    Blocking rather than ending: the loop under test never returns, so the test cancels
    it. A port that raised at the end would prove nothing about the guard.
    """

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.in_service = True

    async def read_urc(self, timeout=1.0):
        if self._chunks:
            return self._chunks.pop(0)
        await asyncio.sleep(3600)


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


async def _drive(m, chunks, *, settle=0.05):
    m._reader_link = ScriptedPort(chunks)
    task = asyncio.get_event_loop().create_task(m.reader_loop())
    await asyncio.sleep(settle)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _outcomes() -> list[tuple]:
    db = await get_db()
    async with db.execute(
        "SELECT modem_ref, outcome FROM delivery_reports ORDER BY id"
    ) as cur:
        return [(r[0], r[1]) for r in await cur.fetchall()]


def _manager(monkeypatch):
    m = ModemManager("/dev/null", "/dev/null")
    monkeypatch.setattr(manager_mod, "spawn_delivery_dispatch", lambda *a, **kw: None)
    monkeypatch.setattr(manager_mod, "notify", lambda *a, **kw: None)
    return m


def test_a_report_that_cannot_be_processed_does_not_take_the_next_one_with_it(
    monkeypatch, caplog
):
    """Task 6.1 — recorded and abandoned, and the port keeps being read."""
    async def body():
        m = _manager(monkeypatch)
        mid = await queries.create_message("app1", "+79031680015", "hi")
        await queries.set_message_sent(mid, 42)
        await queries.add_message_part(mid, 42, 1, 1)

        real = manager_mod.attribute

        def poison(report, rows, **kw):
            if report.modem_ref == 77:
                raise ValueError("(1) The string supplied did not seem to be a number")
            return real(report, rows, **kw)

        monkeypatch.setattr(manager_mod, "attribute", poison)
        with caplog.at_level(logging.ERROR, logger="app.modem.manager"):
            await _drive(m, [POISON.encode() + b"\r\n", GOOD.encode() + b"\r\n"])
        db = await get_db()
        async with db.execute(
            "SELECT status FROM messages WHERE id = ?", (mid,)
        ) as cur:
            status = (await cur.fetchone())[0]
        return status, await _outcomes()

    with caplog.at_level(logging.ERROR, logger="app.modem.manager"):
        status, outcomes = _run(body)

    assert status == "delivered", "the next +CDS on the port was still processed"
    assert (77, "unprocessable") in outcomes, (
        "the report that could not be processed is kept, not lost: the whole complaint "
        "this change answers is a report about a message that can never be corrected"
    )
    assert any(r.levelno >= logging.ERROR for r in caplog.records)


def test_an_error_in_report_handling_leaves_a_later_cmti_still_handled(
    monkeypatch, caplog
):
    """Task 6.2 — the failure that matters is the loop ending, because it also carries
    every inbound SMS."""
    async def body():
        m = _manager(monkeypatch)

        def always_raises(*a, **kw):
            raise RuntimeError("something inside report handling")

        monkeypatch.setattr(manager_mod, "attribute", always_raises)
        with caplog.at_level(logging.ERROR, logger="app.modem.manager"):
            await _drive(m, [
                GOOD.encode() + b"\r\n",
                b'+CMTI: "ME",7\r\n',
            ])
        indices = []
        while not m._inbound_indices.empty():
            indices.append(m._inbound_indices.get_nowait())
        return indices

    with caplog.at_level(logging.ERROR, logger="app.modem.manager"):
        indices = _run(body)

    assert indices == [7], "the reader loop kept running and delivered the inbound index"
    assert any(r.levelno >= logging.ERROR for r in caplog.records), (
        "and the error was logged rather than swallowed"
    )


def test_an_ordinary_pair_of_lines_is_handled_without_the_guard_hiding_anything(
    monkeypatch
):
    """The positive control. Without it, both tests above pass against a loop that
    silently drops every `+CDS` it is given."""
    async def body():
        m = _manager(monkeypatch)
        mid = await queries.create_message("app1", "+79031680015", "hi")
        await queries.set_message_sent(mid, 42)
        await queries.add_message_part(mid, 42, 1, 1)
        await _drive(m, [GOOD.encode() + b"\r\n", b'+CMTI: "ME",7\r\n'])
        indices = []
        while not m._inbound_indices.empty():
            indices.append(m._inbound_indices.get_nowait())
        return await _outcomes(), indices

    outcomes, indices = _run(body)
    assert outcomes == [(42, "attributed")]
    assert indices == [7]
