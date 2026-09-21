"""Task 4.17b: the `sms_out` rung, which the whole change routes *away from*, can carry.

🔴 **Everything downstream of an `sms_out`-borne code was built against a rung that did
not exist.** Measured 21.09.2026, before a line of this was written:

- `placement.carriers_for` built one carrier, `tg_gateway`, so `ladder.walk` met `sms_out`
  as a rung nothing carries — `ABSENT`, alerted, advanced past;
- `probes.build_probes` built three probes and `sms_out` was not among them, so the
  registry never offered the rung the shipped `verification_route_order` names **second**;
- `enqueue` had four call sites — the API, the admin console twice, and the restart
  resume — and not one of them belonged to a verification;
- so no message in this schema had ever belonged to a verification, and the requirement
  that a verification owns the message it creates (task 4.27) had no message to own.

Three properties are guarded here, and each of them is a way the rung can look built and
not be:

**The message belongs to the verification.** Without the link the code is an ordinary
message, its status is pushed to the application as a message status — a raw message id
answering a question nobody asked about a verification — and its failure ends nowhere.

**The sender does not re-decide the route the ladder chose.** `_send_one` asks the rule
what route this number's operator takes and refuses anything whose *first* rung is not
`sms_out`. A verification the ladder deliberately placed on the modem *behind* a paid
rung is exactly that shape, so the sender would refuse the code it was asked to carry —
naming `tg_gateway` in the reason, on a message the ladder had already decided. This is
the live hazard task 4.1 names, and the test for it is the second below.

**The fact survives a restart.** The sender reads the ownership from the database rather
than from the queued item: the restart resume path re-enqueues from `messages` rows, so
an ownership carried only in memory would be lost by the one path that re-sends — and
the symptom would be a code refused on its retry, with the rule named for it.
"""

import asyncio
import json

import pytest

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.modem import manager as manager_mod
from app.settings_store import store
from app.verification import ladder, placement, rule, sms_carrier
from app.verification.routes import SMS_OUT, TG_GATEWAY

PHONE = "+79851600019"
OPERATOR = "МегаФон"
TEMPLATE = "SokolParking: {code} is your code"


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        await store.set_many({
            "verification_templates":
                json.dumps([{"app_id": "app1", "template": TEMPLATE}]),
        })
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


class _Modem:
    """Only the one method the carrier is allowed to reach for."""

    def __init__(self):
        self.queued = []

    async def enqueue(self, message_id, phone, text, app_id=""):
        self.queued.append({"message_id": message_id, "phone": phone,
                            "text": text, "app_id": app_id})


async def _carry(modem, *, code="1234"):
    """Carry one verification the way production assembles the carriers."""
    vid = await queries.create_verification("app1", PHONE, code=code, ttl_seconds=300)
    rung_id = await queries.record_verification_rung(
        vid, route=SMS_OUT, outcome=ladder.ATTEMPTING)
    carriers = placement.carriers_for(vid, app_id="app1", modem=modem,
                                      operator=OPERATOR)
    attempt = await carriers[SMS_OUT](PHONE, seconds_left=5.0, rung_id=rung_id)
    return vid, attempt


# --- the rung carries, and what it creates belongs to the verification ----------------

def test_the_modem_rung_carries_a_code_and_the_message_belongs_to_it():
    modem = _Modem()

    async def body():
        vid, attempt = await _carry(modem)
        db = await get_db()
        async with db.execute(
            "SELECT id, app_id, phone, text, verification_id FROM messages"
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        return vid, attempt, rows

    vid, attempt, rows = _run(body)

    assert attempt.outcome == ladder.CARRIED, attempt.reason
    assert len(rows) == 1, "the modem rung created no message, or more than one"
    row = rows[0]
    assert row["verification_id"] == vid, \
        "the message the rung created does not belong to the verification"
    assert row["text"] == TEMPLATE.format(code="1234"), row["text"]
    assert row["phone"] == PHONE
    assert modem.queued and modem.queued[0]["message_id"] == row["id"], \
        "the message was written but never handed to the modem"


def test_a_rung_with_no_template_is_incapable_rather_than_sending_nothing():
    """An application with no template has no wording of ours to borrow.

    Not a decline — a decline is a statement about the subscriber, and a rung that
    appears to decline everyone is a rung taken out of the rule for the wrong reason.
    """
    modem = _Modem()

    async def body():
        await store.set_many({"verification_templates": json.dumps([])})
        vid, attempt = await _carry(modem)
        db = await get_db()
        async with db.execute("SELECT COUNT(*) FROM messages") as cur:
            (count,) = await cur.fetchone()
        return attempt, count

    attempt, count = _run(body)

    assert attempt.outcome == ladder.INCAPABLE, attempt.outcome
    assert "template" in attempt.reason, attempt.reason
    assert count == 0, "a message was composed for an application with no template"
    assert not modem.queued


def test_what_this_gateway_says_it_places_is_what_it_can_carry():
    """The two statements about a rung have to agree, and only one of them is reachable.

    `places_here` decides two things at the selection door: whether to walk the ladder,
    and whether to write a `selected` rung row instead. A route the gateway carries but
    does not claim to place would therefore be *selected* and never walked — the very
    defect `placement` was written to remove, one rung further along — and the row
    written in its stead is the bookkeeping that reads as money on a paid route.

    Asserted here as well as through the door, and it was written when it could only be
    asserted here: until the owner's decision of 21.09.2026 (task 4.17c) `sms_out` had no
    probe, so no consumer could select it. Measured then: with this assertion absent,
    removing `sms_out` from `PLACED_HERE` left both of these files green. It stays
    because it says the invariant itself — everything carried is claimed — rather than
    one instance of it.
    """
    modem = _Modem()

    def body():
        carried = placement.carriers_for(1, app_id="app1", modem=modem,
                                         operator=OPERATOR)
        return {route for route in carried if placement.places_here(route)}, set(carried)

    async def go():
        return body()

    placed, carried = _run(go)

    assert SMS_OUT in carried, "the gateway builds no carrier for the modem rung"
    assert placed == carried, \
        f"the gateway carries {carried - placed} without claiming to place it"


# --- the sender does not re-decide what the ladder decided ----------------------------

async def _refused(message_id, *, operator=OPERATOR):
    """Run the real refusal check over a real message row. True when it refused."""
    mgr = manager_mod.ModemManager.__new__(manager_mod.ModemManager)
    row = await queries.get_message_any(message_id)
    msg = manager_mod.OutgoingMessage(message_id, row["phone"], row["text"],
                                      row["app_id"])

    async def operator_for(phone):
        return operator

    mgr._operator_for = operator_for
    return await mgr._refuse_what_the_rule_routes_elsewhere(msg)


def _the_modem_behind_the_paid_rung():
    return json.dumps(
        [{"operator": OPERATOR, "routes": [TG_GATEWAY, SMS_OUT]},
         {"operator": rule.DEFAULT, "routes": [SMS_OUT]},
         {"operator": rule.UNKNOWN, "routes": [SMS_OUT]}], ensure_ascii=False)


def test_the_sender_carries_a_verifications_message_the_rule_routes_elsewhere():
    """The hazard task 4.1 names, in one assertion.

    The rule puts the modem *behind* `tg_gateway` for this operator, so the rule's
    **first** rung is not `sms_out` — and the sender refuses on the first rung. The
    ladder had already chosen the modem for this verification; the sender re-deciding it
    is the code refused for the route it was placed on.
    """
    modem = _Modem()

    async def body():
        await store.set_many({rule.KEY: _the_modem_behind_the_paid_rung()})
        await _carry(modem)
        message_id = modem.queued[0]["message_id"]
        refused = await _refused(message_id)
        row = await queries.get_message_any(message_id)
        return refused, row["status"]

    refused, status = _run(body)

    assert refused is False, \
        "the sender refused a message the ladder had already placed on this rung"
    assert status == "pending", status


def test_an_ordinary_message_on_the_same_rule_is_still_refused():
    """The positive control, and the one with teeth.

    The same rule, the same operator, the same sender — and an ordinary message, which
    the rule routes to a rung with no field for words. A carve-out written wide enough
    to let everything past passes the test above and fails this one.
    """
    async def body():
        await store.set_many({rule.KEY: _the_modem_behind_the_paid_rung()})
        message_id = await queries.create_message("app1", PHONE, "an ordinary message")
        refused = await _refused(message_id)
        row = await queries.get_message_any(message_id)
        return refused, row["status"]

    refused, status = _run(body)

    assert refused is True, "free text on a diverted operator was handed to the modem"
    assert status == "failed", status


def test_the_ownership_is_read_from_the_database_rather_than_the_queued_item():
    """The restart case: the resume path re-enqueues from rows, carrying no extra field.

    An `OutgoingMessage` built from nothing but a `messages` row — which is exactly what
    `due_pending_messages` gives the resume path — must still be recognised as a
    verification's. This is the same assertion as the one two tests above; what differs
    is that the item here is built the way a restart builds it, with no help from the
    carrier that queued it.
    """
    modem = _Modem()

    async def body():
        await store.set_many({rule.KEY: _the_modem_behind_the_paid_rung()})
        await _carry(modem)
        message_id = modem.queued[0]["message_id"]
        # The minute `create_message` schedules the recovery attempt for, having passed.
        db = await get_db()
        await db.execute(
            "UPDATE messages SET next_attempt_at = datetime('now', '-1 second') "
            "WHERE id = ?", (message_id,))
        await db.commit()
        rows = await queries.due_pending_messages(3600)
        assert [r["id"] for r in rows] == [message_id], \
            "the resume path cannot see the message at all"
        # Built from the row and nothing else, as `_resume` builds it.
        mgr = manager_mod.ModemManager.__new__(manager_mod.ModemManager)
        row = rows[0]
        msg = manager_mod.OutgoingMessage(row["id"], row["phone"], row["text"],
                                          row["app_id"])

        async def operator_for(phone):
            return OPERATOR

        mgr._operator_for = operator_for
        return await mgr._refuse_what_the_rule_routes_elsewhere(msg)

    assert _run(body) is False, \
        "after a restart the sender refuses the code it had already been asked to carry"
