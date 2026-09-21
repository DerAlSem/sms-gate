"""Task 4.27: a verification carried by the modem takes that message's outcome.

The call route has this already — `call_status: 0` fails the verification and the
application is told. The modem route, which carries every operator but the one this
change moves, had nothing of the sort, and the modem has a dozen named ways to fail
(`app/modem/errors.py:19-38`). Without it a code the network has already refused to
carry leaves the person waiting at the barrier until the deadline, and the application
learns nothing until then.

It closes a hole in the other direction at the same time. The live rule is that every
status writer notifies — guarded by the writer census in task 4.28 — so the message
carrying a verification's code would push its own status to the application under a raw
**message** id. The application asked about a verification; the two id spaces overlap
from the first row of each table, and a receiver keyed on `id` and `status`, which is the
whole of the older contract, marks the wrong thing delivered.

🔴 **The guard is on the door rather than on the writers.** `spawn_delivery_dispatch` has
eight call sites in the sender, and the invariant is "no message-status push for a
verification's message" — a census of eight would be a census that stales the day a ninth
is added. `dispatch_delivery` is the one place every one of them passes through, and it
already reads the row this decision is made from.
"""

import asyncio

import pytest

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.modem import delivery_dispatch as message_dispatch
from app.settings_store import store
from app.verification.dispatch import announce_verification_outcomes

PHONE = "+79261234888"


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        await store.set_many({
            "delivery_dispatch": '[{"app_id":"app1","webhook_url":"https://x/hook"}]',
        })
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


@pytest.fixture
def pushes(monkeypatch):
    """Every payload either door tried to push, in order, without a network."""
    seen = {"message": [], "verification": []}

    async def fake_message_deliver(route, payload):
        seen["message"].append(payload)
        return True, None

    async def fake_verification_deliver(route, payload):
        seen["verification"].append(payload)
        return True, None

    from app.verification import dispatch as verification_dispatch

    monkeypatch.setattr(message_dispatch, "deliver", fake_message_deliver)
    monkeypatch.setattr(verification_dispatch, "deliver", fake_verification_deliver)
    return seen


async def _a_verification_carrying_a_message():
    vid = await queries.create_verification("app1", PHONE, code="1234", ttl_seconds=300)
    message_id = await queries.create_message(
        "app1", PHONE, "SokolParking: 1234", verification_id=vid)
    return vid, message_id


# --- the verification takes the message's outcome -------------------------------------

@pytest.mark.parametrize("status", ["failed", "expired"])
def test_a_failed_code_fails_the_verification_under_its_own_id(pushes, status):
    """The whole of the first scenario: the person stops waiting, and the application is
    told under the id it actually asked about."""
    async def body():
        vid, message_id = await _a_verification_carrying_a_message()
        await message_dispatch.dispatch_delivery(
            message_id, status, "modem said no")
        await announce_verification_outcomes()
        row = await queries.get_verification(vid, "app1")
        return vid, dict(row)

    vid, row = _run(body)

    assert row["status"] == "failed", \
        "the message carrying the code ended and the verification did not"
    assert "modem said no" in (row["reason"] or ""), row["reason"]
    assert [p["verification_id"] for p in pushes["verification"]] == [vid], \
        "the application was not told under the verification's id"
    assert pushes["verification"][0]["status"] == "failed"


def test_a_sent_code_leaves_the_verification_open(pushes):
    """The control on the rule above. `sent` is the message on its way, which is the
    ordinary path, and a rule that failed the verification on any status at all would
    end every modem-carried verification the moment its code went out."""
    async def body():
        vid, message_id = await _a_verification_carrying_a_message()
        for status in ("sent", "delivered"):
            await message_dispatch.dispatch_delivery(message_id, status)
        await announce_verification_outcomes()
        row = await queries.get_verification(vid, "app1")
        return dict(row)

    row = _run(body)

    assert row["status"] == "pending", row["status"]
    assert pushes["verification"] == [], \
        "a verification still being carried was announced as ended"


def test_a_verification_that_already_ended_is_not_re_failed(pushes):
    """A confirmed verification whose message expires afterwards stays confirmed.

    The person typed the code; the network gave up on the SMS later, or the report
    arrived late. Failing on the message's word here would take a login away from
    somebody who had already completed it.
    """
    async def body():
        vid, message_id = await _a_verification_carrying_a_message()
        confirmed = await queries.check_verification(vid, "app1", code="1234",
                                                     max_attempts=3)
        await message_dispatch.dispatch_delivery(message_id, "expired", "gave up")
        row = await queries.get_verification(vid, "app1")
        return confirmed, dict(row)

    confirmed, row = _run(body)

    assert row["status"] == "confirmed", \
        f"a confirmed verification was failed by its message's late report ({confirmed})"


# --- and its message does not notify as a message --------------------------------------

@pytest.mark.parametrize("status", ["sent", "delivered", "failed", "expired"])
def test_a_verifications_message_raises_no_message_status_push(pushes, status):
    """Every status the door pushes, not only the ending ones.

    A `delivered` for a code is the same defect as a `failed`: a raw message id arriving
    at a receiver that only ever asked about a verification, in a body whose shape is the
    older contract's.
    """
    async def body():
        _, message_id = await _a_verification_carrying_a_message()
        return await message_dispatch.dispatch_delivery(message_id, status, "why")

    delivered = _run(body)

    assert delivered is False, "the door reported a push it must not have made"
    assert pushes["message"] == [], \
        f"a {status} message-status push carried a verification's message id"


def test_an_ordinary_message_still_notifies_as_a_message(pushes):
    """The positive control, and the one with teeth: same door, same application, same
    status, and the only difference is that this message belongs to nobody. A guard
    written wide enough to silence the door passes every assertion above."""
    async def body():
        message_id = await queries.create_message("app1", PHONE, "an ordinary message")
        return message_id, await message_dispatch.dispatch_delivery(
            message_id, "failed", "modem said no")

    message_id, delivered = _run(body)

    assert delivered is True
    assert [p["id"] for p in pushes["message"]] == [message_id]
    assert pushes["verification"] == []
