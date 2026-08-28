"""Reconciling a restored link with what the modem stored while it was down.

This is the bar the change is most likely to fail. Inbound SMS accumulate in modem memory
during an outage and the `+CMTI` announcing them are lost with the link; today the only
cure is the restart, whose startup scan drains them. Replacing the restart with a reopen
removes that scan — so the reopen has to bring it along, and scanning that often turns a
latent duplicate into a likely one.
"""

import asyncio

import pytest

import app.modem.manager as mgr
from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.modem.manager import ModemManager
from app.modem.pdu import inbound_pdu_key

# One SMS-DELIVER each, from different senders, so the assembler treats them as complete
# single-part messages.
PDU_A = "07919762020033F1040B917962534810F400008070102155428003C16536"
PDU_B = "07919762020033F1040B917962534899F400008070102155428003C16536"


class FakeSender:
    """A command port whose stored-message list and deletes are scripted and recorded."""

    def __init__(self, stored=(), reopen=True):
        self.usable = False
        self.link_lost = asyncio.Event()
        self.reopens = 0
        self.port = "/dev/ttyUSB2"
        self.stored = list(stored)
        self.deleted = []
        self._reopen = reopen

    @property
    def in_service(self):
        """A scripted port has no transport to point at, so `usable` is the whole
        answer for it."""
        return self.usable

    async def registration_ok(self):
        if not self.usable:
            raise mgr.ModemTransportError("link to /dev/ttyUSB2 is not open")
        return True

    async def reconnect(self, *, init=True):
        if not self._reopen:
            return False
        self.usable = True
        self.reopens += 1
        return True

    async def list_all_sms(self, timeout=10.0):
        return "".join(
            f"\r\n+CMGL: {i},0,,{len(pdu) // 2}\r\n{pdu}\r\n"
            for i, pdu in self.stored
        ) + "\r\nOK\r\n"

    async def delete_sms(self, index, timeout=5.0):
        self.deleted.append(index)
        self.stored = [(i, p) for i, p in self.stored if i != index]

    def link_snapshot(self):
        return {"link": "open" if self.usable else "lost",
                "link_last_good": "—", "link_reopens": self.reopens}


@pytest.fixture(autouse=True)
def _fast_recovery(monkeypatch):
    monkeypatch.setattr(mgr, "_RECOVERY_SETTLE", 0.05)
    monkeypatch.setattr(mgr, "_RECOVERY_POLL", 0.005)
    monkeypatch.setattr(mgr, "_RECOVERY_TIMEOUT", 2.0)


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch):
    """Delivery to the owning application is what we count, not what we perform."""
    delivered = []
    monkeypatch.setattr(
        ModemManager, "_spawn_dispatch",
        lambda self, phone, text: delivered.append((phone, text)),
    )
    return delivered


def _mgr(sender):
    m = ModemManager("/dev/null", "/dev/null")
    m._sender = sender
    # The URC port is not what these tests are about; leave it in service so `ensure_link`
    # goes straight to the command port and the reconciliation that follows it.
    m._reader_link._writer = object()
    return m


async def _fresh_db():
    await init_db(":memory:")
    await run_migrations()


def test_inbound_arriving_during_an_outage_is_delivered_after_a_reopen(_no_dispatch):
    """Without a restart — which is the whole point, and the way the change could
    silently make inbound delivery worse than it is today."""

    async def run():
        await _fresh_db()
        try:
            sender = FakeSender(stored=[(1, PDU_A), (2, PDU_B)])
            m = _mgr(sender)
            assert await m.ensure_link() is True
            return sender.deleted, len(await queries.list_inbound(None, 50, 0))
        finally:
            await close_db()

    deleted, persisted = asyncio.run(run())
    assert deleted == [1, 2], "the scan must drain what the modem stored during the outage"
    assert persisted == 2
    assert len(_no_dispatch) == 2


def test_a_message_persisted_but_not_deleted_is_not_delivered_twice(_no_dispatch):
    """A stored message is deleted only after it has been persisted, so a link that dies
    in between leaves it to be found again by the next scan."""

    async def run():
        await _fresh_db()
        try:
            sender = FakeSender(stored=[(1, PDU_A)])
            m = _mgr(sender)
            # The interrupted read: persisted, marked, and then the link died before the
            # modem's copy could be deleted.
            await queries.save_inbound("+79999999999", "already delivered")
            await queries.mark_inbound_pdu_seen(inbound_pdu_key(PDU_A))
            _no_dispatch.clear()

            await m.ensure_link()
            return sender.deleted, len(await queries.list_inbound(None, 50, 0))
        finally:
            await close_db()

    deleted, persisted = asyncio.run(run())
    assert deleted == [1], "the copy still in modem memory must be cleaned up"
    assert persisted == 1, "it must not be persisted a second time"
    assert _no_dispatch == [], "and must not reach the application a second time"


def test_indexes_queued_before_the_outage_are_not_relied_upon(_no_dispatch):
    """They describe what was announced before the link died, not what arrived while
    nothing was listening — and the slots they name have been emptied by the scan."""

    async def run():
        await _fresh_db()
        try:
            sender = FakeSender(stored=[(1, PDU_A)])
            m = _mgr(sender)
            await m._inbound_indices.put(1)
            await m._inbound_indices.put(7)
            await m.ensure_link()
            return m._inbound_indices.qsize(), sender.deleted
        finally:
            await close_db()

    queued, deleted = asyncio.run(run())
    assert queued == 0, "stale indexes must be dropped, not read against reused slots"
    assert deleted == [1], "and the scan is what covers them"


def test_a_reopen_that_failed_does_not_scan(_no_dispatch):
    """There is nothing to scan through a port that is not there, and the linker's next
    move is another attempt."""

    async def run():
        await _fresh_db()
        try:
            sender = FakeSender(stored=[(1, PDU_A)], reopen=False)
            m = _mgr(sender)
            await m.ensure_link()
            return sender.deleted
        finally:
            await close_db()

    assert asyncio.run(run()) == []


def test_the_deduplication_keys_are_pruned_by_age():
    async def run():
        await _fresh_db()
        try:
            await queries.mark_inbound_pdu_seen("old")
            await queries.mark_inbound_pdu_seen("fresh")
            db = await queries.get_db()
            await db.execute(
                "UPDATE inbound_seen SET received_at = datetime('now', '-30 days') "
                "WHERE pdu_key = 'old'"
            )
            await db.commit()
            gone = await queries.prune_inbound_seen(7 * 24 * 3600)
            return gone, await queries.inbound_pdu_seen("old"), \
                await queries.inbound_pdu_seen("fresh")
        finally:
            await close_db()

    assert asyncio.run(run()) == (1, False, True)
