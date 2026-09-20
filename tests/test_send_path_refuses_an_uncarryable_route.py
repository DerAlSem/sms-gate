"""A route carries only what it is capable of carrying. Tasks 4.6 and 4.2.

The rule diverts an operator's traffic to a paid rung, and the paid rungs have no field
for words: `sendVerificationMessage` takes a `code` and a `code_length`, and a flash
call's whole payload is the last four digits of the calling number. An application that
sends free text to a subscriber of that operator is therefore sending something no route
in force for it can carry.

**What the gateway must not do is the thing it did until now: send it over the modem
anyway.** That is the automatic failover this capability exists to refuse — arrived at
not by anyone's decision but by the send path never having asked the rule at all. For a
МегаФон subscriber the modem is the route that has been rejecting the traffic, so such a
send reads to the application as a delivery and behaves to the person as a silence.

Five things the refusal owes, and each is asserted separately here, because four of them
can be satisfied while the fifth is not:

- the message is `failed`, at once, with a reason naming the operator and the route;
- the owning application is told, by the same push a real failure produces;
- **the operator is alerted on stock settings.** `notify_send_errors` ships **off**, so a
  refusal carried only by `_finally_fail` would be silent on every install that has this
  defect. The alert that has to fire is the `routing` one, and it fires from
  `refusals.record`;
- **no AT command is issued** — the modem is not asked to do anything at all;
- **no attempt is consumed.** A refusal is not a failed attempt: retrying it would
  produce the same answer four more times and then report a send failure.

🔴 **The guard below is paired with a positive control, and the pairing is the point.**
A guard asserting "МегаФон text does not reach the modem" passes just as well on a send
path that reaches the modem for nobody — and twice on this change a guard has been hollow
for exactly that reason. `test_a_plain_send_to_an_operator_outside_the_rule_is_unchanged`
and its two neighbours assert that the same harness, the same message and the same modem
*do* transmit the moment the rule's answer can carry the item.

And the rule is read live rather than handed in: rewriting МегаФон's entry to `sms_out`
while the manager is running makes the identical send transmit. An implementation that
matched the operator's name, or that hard-coded which routes are paid, would fail that.
"""

import asyncio
import json

import pytest

import app.modem.manager as manager_mod
from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.modem.manager import ModemManager, OutgoingMessage
from app.settings_store import store
from app.verification import refusals, rule
from app.verification import routes
from app.verification.routes import SMS_OUT, TG_GATEWAY

MEGAFON = "МегаФон"
MTS = "МТС"

MEGAFON_PHONE = "+79851600019"
MTS_PHONE = "+79161234567"
UNKNOWN_PHONE = "+79001112233"

TEXT = "Ваш заказ собран, курьер выедет в 14:00 — https://example.org/o/8841"


class _Modem:
    """The AT surface, counted. Nothing below it is reached in the refusal case."""

    def __init__(self):
        self.pdus = []
        self.registration_asked = 0

    async def send_sms_pdu(self, parts, on_part_sent, **kw):
        self.pdus.append(parts)
        await on_part_sent(1, 42)

    async def registration_state(self):
        self.registration_asked += 1
        return True


@pytest.fixture
def alerts(monkeypatch):
    """The real `notify`, with a fake notifier under it.

    Patching `notify` would step over the toggles, and the toggles are half of what is
    being asserted: this refusal has to be audible on a gateway whose notification
    settings were never touched. `notify_send_errors` is off there.
    """
    sent = []

    class FakeNotifier:
        def maybe_send(self, body, dedup_sig=None, phone=None):
            sent.append((body, dedup_sig))

    import app.alerting as alerting
    monkeypatch.setattr(alerting, "_notifier", FakeNotifier())
    return sent


@pytest.fixture
def pushes(monkeypatch):
    """What the owning application is told."""
    seen = []
    monkeypatch.setattr(
        manager_mod, "spawn_delivery_dispatch",
        lambda mid, status, error=None: seen.append((mid, status, error)),
    )
    return seen


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


def _manager(modem: _Modem) -> ModemManager:
    m = ModemManager("/dev/null", "/dev/null")
    m._sender.send_sms_pdu = modem.send_sms_pdu
    m._sender.registration_state = modem.registration_state
    return m


async def _state(message_id: int) -> dict:
    db = await get_db()
    async with db.execute(
        "SELECT status, attempts, error FROM messages WHERE id = ?", (message_id,),
    ) as cur:
        return dict(await cur.fetchone())


async def _send(modem: _Modem, phone: str, operator: str | None, text: str = TEXT) -> int:
    """One plain text send, end to end through the sender, for this operator."""
    if operator is not None:
        await queries.save_number_operator(phone, operator, "Москва")
    message_id = await queries.create_message("app1", phone, text)
    await _manager(modem)._send_one(OutgoingMessage(message_id, phone, text, "app1"))
    return message_id


# --- the refusal ------------------------------------------------------------- 4.6

def test_free_text_to_an_operator_routed_to_a_paid_rung_is_failed_at_once(
        alerts, pushes):
    """The whole of task 4.6, asserted claim by claim."""
    async def body():
        modem = _Modem()
        message_id = await _send(modem, MEGAFON_PHONE, MEGAFON)

        state = await _state(message_id)
        assert state["status"] == "failed", state
        # The reason has to be usable by whoever reads the push: which operator, and
        # which route it is that cannot carry this.
        assert MEGAFON in state["error"], state["error"]
        assert TG_GATEWAY in state["error"], state["error"]

        # No AT command, and not even the question whether the modem is registered:
        # nothing about this send reaches the modem at all.
        assert modem.pdus == [], modem.pdus
        assert modem.registration_asked == 0

        # Not a failed attempt. Retrying would ask the same rule and get the same answer.
        assert state["attempts"] == 0, state

        # The owning application hears about it by the same push a real failure produces.
        assert [(mid, status) for mid, status, _ in pushes] == [(message_id, "failed")]

    _run(body)


def test_the_refusal_is_audible_on_stock_settings(alerts):
    """🔴 `notify_send_errors` ships off, and every install with this defect is stock.

    The alert that has to fire is the `routing` one. A refusal raised only through
    `_finally_fail` — which notifies `send_error` — would be silent here, and the
    gateway would look to its operator exactly as it did before the rule existed.
    """
    async def body():
        assert store.notify_send_errors is False, "the premise of this test moved"
        assert store.notify_routing_errors is True

        modem = _Modem()
        await _send(modem, MEGAFON_PHONE, MEGAFON)

        bodies = [body_ for body_, _ in alerts]
        assert bodies, "the refusal woke nobody on a gateway nobody configured"
        assert any(MEGAFON in b and TG_GATEWAY in b for b in bodies), bodies

    _run(body)


def test_the_refusal_is_counted_against_the_operator_and_the_application(alerts):
    """The send path is the missing producer of the refusals the count was built for.

    `refusals.record` was written for the seventy-odd refusals a month this rule costs,
    and until now its only caller was the ladder, which has no live caller of its own.
    """
    async def body():
        modem = _Modem()
        await _send(modem, MEGAFON_PHONE, MEGAFON)

        rows = await refusals.counts()
        assert len(rows) == 1, rows
        assert rows[0]["operator"] == MEGAFON
        assert rows[0]["total"] == 1
        assert rows[0]["by_app"] == {"app1": 1}
        assert rows[0]["by_route"] == {TG_GATEWAY: 1}

    _run(body)


def test_the_operator_is_matched_the_way_the_rule_matches_it(alerts, pushes):
    """`number_operators` holds this operator under two spellings, 120 rows and 57.

    A send path comparing by `==`, or by SQLite's ASCII-only `upper()`, would refuse one
    spelling and quietly hand the other to the route that is rejecting it.
    """
    async def body():
        modem = _Modem()
        message_id = await _send(modem, MEGAFON_PHONE, "МЕГАФОН")
        assert (await _state(message_id))["status"] == "failed"
        assert modem.pdus == []

    _run(body)


def test_the_rule_is_read_live_rather_than_the_operator_being_known_to_the_code(
        alerts, pushes):
    """Rewriting the entry to the modem route makes the identical send transmit.

    This is what stops the guard above from passing on an implementation that knows
    which operator is in trouble, or which routes are the paid ones.
    """
    async def body():
        modem = _Modem()
        await store.set_many({rule.KEY: json.dumps(
            [
                {"operator": MEGAFON, "routes": [SMS_OUT]},
                {"operator": rule.DEFAULT, "routes": [SMS_OUT]},
                {"operator": rule.UNKNOWN, "routes": [SMS_OUT]},
            ],
            ensure_ascii=False,
        )})
        message_id = await _send(modem, MEGAFON_PHONE, MEGAFON)

        assert (await _state(message_id))["status"] == "sent", await _state(message_id)
        assert len(modem.pdus) == 1
        assert await refusals.counts() == []

    _run(body)


# --- the positive control ----------------------------------------------------- 4.2

def test_a_plain_send_to_an_operator_outside_the_rule_is_unchanged(alerts, pushes):
    """МТС has no entry; `*` answers for it, and `*` is the modem.

    Without this the guard above would pass on a send path that transmits for nobody.
    """
    async def body():
        modem = _Modem()
        message_id = await _send(modem, MTS_PHONE, MTS)

        state = await _state(message_id)
        assert state["status"] == "sent", state
        assert len(modem.pdus) == 1
        assert state["attempts"] == 1, state
        assert await refusals.counts() == []
        assert [b for b, _ in alerts] == []

    _run(body)


def test_a_number_with_no_operator_row_is_unchanged(alerts, pushes):
    """`?` answers for a number never looked up, and it ships pointing at the modem.

    Asserted rather than assumed, because it is the whole reason this change can leave
    tasks 4.4 and 4.5 — not waiting for the lookup, recording its absence — alone: the
    send path reads the cache it finds and takes the route the rule names for "unknown",
    which today is the route it was taking before.
    """
    async def body():
        modem = _Modem()
        message_id = await _send(modem, UNKNOWN_PHONE, None)

        state = await _state(message_id)
        assert state["status"] == "sent", state
        assert len(modem.pdus) == 1
        assert await refusals.counts() == []

    _run(body)


def test_the_unknown_entry_being_set_to_a_paid_rung_refuses_that_send_too(
        alerts, pushes):
    """The `?` entry is the owner's to set, and setting it is how they decline.

    The pair above and this one are the same send under two rules: what decides it is
    the rule, not whether a `number_operators` row happened to exist.
    """
    async def body():
        modem = _Modem()
        await store.set_many({rule.KEY: json.dumps(
            [
                {"operator": rule.DEFAULT, "routes": [SMS_OUT]},
                {"operator": rule.UNKNOWN, "routes": [TG_GATEWAY]},
            ],
            ensure_ascii=False,
        )})
        message_id = await _send(modem, UNKNOWN_PHONE, None)

        assert (await _state(message_id))["status"] == "failed"
        assert modem.pdus == []
        rows = await refusals.counts()
        assert len(rows) == 1 and rows[0]["total"] == 1, rows
        assert rows[0]["by_route"] == {TG_GATEWAY: 1}

    _run(body)


# --- the rule itself being the thing that refuses ------------------------------

def test_an_entry_set_to_refuse_refuses_a_plain_send(alerts, pushes):
    """`refuse` is a way of declining rather than a way out, and it stands alone.

    Recorded under its own name rather than under a route, because "the rule offers this
    operator no way out" and "the way out it offers cannot carry words" are two different
    things for whoever reviews the count.
    """
    async def body():
        modem = _Modem()
        await store.set_many({rule.KEY: json.dumps(
            [
                {"operator": MEGAFON, "routes": [rule.REFUSE]},
                {"operator": rule.DEFAULT, "routes": [SMS_OUT]},
                {"operator": rule.UNKNOWN, "routes": [SMS_OUT]},
            ],
            ensure_ascii=False,
        )})
        message_id = await _send(modem, MEGAFON_PHONE, MEGAFON)

        state = await _state(message_id)
        assert state["status"] == "failed", state
        assert modem.pdus == []
        rows = await refusals.counts()
        assert rows[0]["by_route"] == {rule.REFUSE: 1}, rows

    _run(body)


def test_an_unreadable_rule_does_not_send_and_does_not_crash_the_sender(alerts, pushes):
    """A rule that cannot be read is never read as an empty one — not here either.

    Read as empty, it would send the whole of an operator's traffic back to the route
    that is rejecting it, without a line in the log. Read as a crash, it would reach
    `sender_loop`'s catch-all and fail the message as "internal error while sending",
    which names neither the rule nor what to do about it.
    """
    async def body():
        modem = _Modem()
        db = await get_db()
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (rule.KEY, "{not json at all"))
        await db.commit()
        await store.load()
        message_id = await _send(modem, MEGAFON_PHONE, MEGAFON)

        state = await _state(message_id)
        assert state["status"] == "failed", state
        assert "rule" in state["error"].lower(), state["error"]
        assert modem.pdus == []
        assert state["attempts"] == 0, state
        assert [b for b, _ in alerts], "an unreadable rule woke nobody"

    _run(body)


def test_the_modem_named_behind_a_paid_rung_does_not_pick_the_item_up(alerts, pushes):
    """🔴 The route asked about is the **first** one the entry names, and only it.

    An entry reading `[tg_gateway, sms_out]` names the modem — and walking down to it
    would be the rerouting the requirement forbids in the same sentence as the refusal:
    "SHALL NOT be handed to that route, SHALL NOT be rerouted to another, and SHALL NOT
    be attempted". It is also the way the modem gets back underneath a paid rung by
    accident, which is the whole of what this capability exists to stop.

    The refusal stays loud rather than silent, so an owner who meant the second reading
    is told on the first message rather than by an absence: every refusal here is counted
    and alerted on stock settings.

    ⚠️ This is the narrower of two readings the requirement admits, and it is recorded in
    the spec as a decision rather than left to whoever implements it next. Nothing in the
    shipped rule distinguishes them — no entry in force names a modem route behind a paid
    one — so the reading costs nothing today and is guarded here for the day it does.
    """
    async def body():
        modem = _Modem()
        await store.set_many({rule.KEY: json.dumps(
            [
                {"operator": MEGAFON, "routes": [TG_GATEWAY, SMS_OUT]},
                {"operator": rule.DEFAULT, "routes": [SMS_OUT]},
                {"operator": rule.UNKNOWN, "routes": [SMS_OUT]},
            ],
            ensure_ascii=False,
        )})
        message_id = await _send(modem, MEGAFON_PHONE, MEGAFON)

        assert (await _state(message_id))["status"] == "failed"
        assert modem.pdus == []
        rows = await refusals.counts()
        assert rows[0]["by_route"] == {TG_GATEWAY: 1}, rows

    _run(body)


def test_a_route_nothing_carries_is_refused_rather_than_sent_over_the_modem(
        alerts, pushes):
    """A rule may name a way out before anything can carry it — three of them today.

    `tg_user`, `max_user` and `app_bot` were named by the same decision that named the
    Gateway rung, and no adapter carries any of them. What must not happen is the modem
    picking the item up because the named route is not a paid one: "not paid" is not
    "mine". The route this sender answers to is `sms_out` and nothing else.
    """
    async def body():
        modem = _Modem()
        await store.set_many({rule.KEY: json.dumps(
            [
                {"operator": MEGAFON, "routes": ["tg_user"]},
                {"operator": rule.DEFAULT, "routes": [SMS_OUT]},
                {"operator": rule.UNKNOWN, "routes": [SMS_OUT]},
            ],
            ensure_ascii=False,
        )})
        message_id = await _send(modem, MEGAFON_PHONE, MEGAFON)

        assert (await _state(message_id))["status"] == "failed"
        assert modem.pdus == []
        rows = await refusals.counts()
        assert rows[0]["by_route"] == {"tg_user": 1}, rows

    _run(body)


# --- what each route declares it can carry -------------------------------------

def test_neither_paid_rung_declares_itself_able_to_carry_words():
    """The declaration itself, asserted where it lives rather than through the sender.

    🔴 **Through the sender it is unguardable, and that was measured rather than
    assumed.** The send path asks "is this item assigned to me?" before it asks "could
    the assigned route carry it?", so the second question only ever decides the wording
    of the reason: declaring `tg_gateway` able to carry words leaves every test above
    green. A declaration nothing reads is a declaration that rots, and the requirement
    that each route say what it can carry is the requirement being guarded here.

    What the two paid rungs cannot carry is not a policy but a shape. A flash call's
    whole payload is the last four digits of the calling number. `sendVerificationMessage`
    accepts a `code` and a `code_length`, and the wording around them is Telegram's.
    """
    for paid in (TG_GATEWAY, "flash_call"):
        assert routes.carries(paid, routes.VERIFICATION_CODE), paid
        assert not routes.carries(paid, routes.ARBITRARY_TEXT), paid
    assert routes.carries(SMS_OUT, routes.ARBITRARY_TEXT)
    assert routes.carries(SMS_OUT, routes.VERIFICATION_CODE)


def test_a_route_nothing_has_declared_carries_nothing():
    """Absent means "cannot", and the three messenger routes are absent on purpose.

    They are names in the vocabulary with no adapter behind them and no wire contract
    anybody here has read. Answering yes by default is the one direction that cannot be
    taken back: an item let out over a route on a supposition is an item delivered.
    """
    for undeclared in ("tg_user", "max_user", "app_bot", "not_a_route_at_all"):
        assert not routes.carries(undeclared, routes.ARBITRARY_TEXT), undeclared
        assert not routes.carries(undeclared, routes.VERIFICATION_CODE), undeclared


def test_the_reason_distinguishes_a_route_that_cannot_from_one_that_is_not_the_modem(
        alerts, pushes):
    """Both refuse, and whoever reads the push has to be able to tell them apart.

    "`tg_gateway` cannot carry arbitrary text" is a fact about the route and will not
    change. "`tg_user` is not the modem" is a fact about which sender was asked, and it
    changes the day a messenger adapter lands. Reported as one sentence they would send
    an operator looking for the same fix twice.
    """
    async def body():
        modem = _Modem()
        cannot = await _send(modem, MEGAFON_PHONE, MEGAFON)
        assert "cannot carry" in (await _state(cannot))["error"], await _state(cannot)

        # No entry for this operator and no `*` to answer for it: the rule has no way
        # out to name, which is a different sentence from "the way out it names cannot
        # carry this" and has a different fix.
        await store.set_many({rule.KEY: json.dumps(
            [{"operator": MTS, "routes": [SMS_OUT]}], ensure_ascii=False)})
        refused_by_rule = await _send(modem, MEGAFON_PHONE, MEGAFON)
        assert "no way out" in (await _state(refused_by_rule))["error"]

    _run(body)
