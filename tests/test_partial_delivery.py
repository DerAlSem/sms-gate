"""A message the network delivered must not be reported as expired.

The gateway waits for a report on every part before calling a multipart message delivered.
One network on this SIM reports the final segment and no more, so those messages never
complete, sit until the timeout, and are swept to `expired` — and that status goes to the
owning application. On that operator: single-part 180 delivered and 0 expired, two-part 1
delivered and 21 expired. Four test messages reproduced it exactly, and the recipient
confirmed all four arrived whole.

The rule is narrowed at the timeout only. Until it fires there is no evidence the remaining
reports are not coming, and "part 2 delivered" genuinely does not mean part 1 was.
"""

import asyncio

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.db import queries


async def _db():
    await init_db(":memory:")
    await run_migrations()
    db = await queries.get_db()
    await db.execute("INSERT OR IGNORE INTO apps (id, token) VALUES ('a','t')")
    await db.commit()
    return db


async def _stale_message(db, parts, *, age=600):
    """A `sent` message older than any timeout, with `parts` as (seq, status) pairs."""
    mid = await queries.create_message("a", "+79995550011", "x")
    await db.execute(
        "UPDATE messages SET status='sent', sent_at=datetime('now', ? || ' seconds') WHERE id=?",
        (f"-{age}", mid),
    )
    for seq, status in parts:
        ref = mid * 10 + seq
        await queries.add_message_part(mid, ref, seq, len(parts))
        if status == "delivered":
            await queries.set_part_delivered(ref)
        elif status == "failed":
            await queries.set_part_failed(ref)
    await db.commit()
    return mid


def _run(coro_fn):
    async def run():
        db = await _db()
        try:
            return await coro_fn(db)
        finally:
            await close_db()
    return asyncio.run(run())


def test_a_partly_reported_message_is_delivered_not_expired():
    """The case this exists for: the network took a segment and never spoke about the rest.
    Saying nothing about the others is what it does; a failure it would report."""

    async def body(db):
        mid = await _stale_message(db, [(1, "sent"), (2, "delivered")])
        done = await queries.complete_partly_reported_messages(300)
        expired = await queries.expire_stale_messages(300)
        row = await queries.get_message(mid, "a")
        return mid, done, expired, row["status"]

    mid, done, expired, status = _run(body)
    assert done == [mid], f"the sweep should have completed it: {done}"
    assert expired == [], "and it must not also be expired"
    assert status == "delivered"


def test_a_concluded_delivery_is_marked_as_concluded():
    """`We were told` and `we concluded` are different facts. An operator meeting a
    complaint asks how solid the delivery is, and a record that cannot answer is
    confidently wrong — worse than the `expired` this replaces, which nobody trusts."""

    async def body(db):
        mid = await _stale_message(db, [(1, "sent"), (2, "delivered")])
        await queries.complete_partly_reported_messages(300)
        row = await queries.get_message(mid, "a")
        return row["delivery_inferred"]

    assert _run(body) == 1


def test_a_fully_reported_delivery_is_not_marked_concluded():
    """The distinction is worthless if the ordinary path carries it too."""

    async def body(db):
        mid = await _stale_message(db, [(1, "delivered"), (2, "delivered")])
        await queries.set_message_delivered(mid)
        row = await queries.get_message(mid, "a")
        return row["status"], row["delivery_inferred"]

    assert _run(body) == ("delivered", 0)


def test_a_message_with_nothing_confirmed_still_expires():
    """Silence about everything is absence of evidence. Inventing a delivery from it would
    trade a wrong `expired` for a wrong `delivered`, which is the worse direction."""

    async def body(db):
        mid = await _stale_message(db, [(1, "sent"), (2, "sent")])
        done = await queries.complete_partly_reported_messages(300)
        expired = await queries.expire_stale_messages(300)
        row = await queries.get_message(mid, "a")
        return mid, done, expired, row["status"]

    mid, done, expired, status = _run(body)
    assert done == [], "nothing was confirmed, so nothing may be concluded"
    assert expired == [mid]
    assert status == "expired"


def test_a_single_part_message_with_no_report_still_expires():
    """So the change cannot quietly rescue the case it was never about."""

    async def body(db):
        mid = await _stale_message(db, [(1, "sent")])
        done = await queries.complete_partly_reported_messages(300)
        expired = await queries.expire_stale_messages(300)
        return mid, done, expired

    mid, done, expired = _run(body)
    assert done == []
    assert expired == [mid]


def test_a_failed_part_is_not_turned_into_a_delivery_by_the_timeout():
    """That path already has an answer and is not a timeout question."""

    async def body(db):
        mid = await _stale_message(db, [(1, "failed"), (2, "delivered")])
        done = await queries.complete_partly_reported_messages(300)
        return done

    assert _run(body) == []


def test_a_message_inside_its_timeout_is_left_alone():
    """Until the timeout fires there is no evidence the rest is not coming."""

    async def body(db):
        mid = await _stale_message(db, [(1, "sent"), (2, "delivered")], age=10)
        done = await queries.complete_partly_reported_messages(300)
        row = await queries.get_message(mid, "a")
        return done, row["status"]

    assert _run(body) == ([], "sent")


# --- what the application is told ---

def test_the_sweep_notifies_delivered_and_never_expired_for_the_same_message(monkeypatch):
    """One notification, and it is the conclusion. Emitting `expired` first would be honest
    about the sequence and harmful in practice: a receiver that acts on it has already acted
    by the time the correction lands, and here a failure webhook is answered by messaging a
    person."""
    import app.modem.manager as mgr
    from app.settings_store import store

    sent = []
    monkeypatch.setattr(mgr, "spawn_delivery_dispatch",
                        lambda mid, status, error=None: sent.append((mid, status)))
    monkeypatch.setitem(store._cache, "delivery_timeout_seconds", "300")

    async def run():
        db = await _db()
        try:
            partial = await _stale_message(db, [(1, "sent"), (2, "delivered")])
            silent = await _stale_message(db, [(1, "sent"), (2, "sent")])
            m = mgr.ModemManager("/dev/null", "/dev/null")
            await m._expire_step()
            return partial, silent
        finally:
            await close_db()

    partial, silent = asyncio.run(run())
    assert (partial, "delivered") in sent
    assert (partial, "expired") not in sent, "the correction must not follow a wrong verdict"
    assert (silent, "expired") in sent, "a message with nothing confirmed still expires"
    assert len([s for s in sent if s[0] == partial]) == 1, "exactly one notification"
