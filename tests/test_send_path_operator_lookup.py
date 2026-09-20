"""Where the operator lookup is waited for, and where it must not be. Tasks 4.4 and 4.5.

The lookup is enrichment, and enrichment must not show up as a slow API. But since 4.6a
the **route** is read from the operator, and that turns "the lookup has not answered yet"
and "the lookup will not answer" into two different facts with two different right
answers. Only one place can tell them apart without making the application wait, and the
owner settled on 20.09.2026 which place that is:

- **the door does not wait.** `POST /sms/send` answers on the message being queued, and
  the lookup runs behind it;
- **the sender does**, under a short bound of its own, and only where the cache holds no
  operator at all.

🔴 **The failure this pairing exists to prevent is specific and was found before it
shipped.** Had the door stopped waiting and the sender not started, the first message
ever addressed to a МегаФон subscriber would be routed against an empty cache: it would
take the `?` entry, which ships pointing at the modem, and go out over the route that
operator has been rejecting — defeating 4.6 on exactly the message 4.6 exists for. The
test named for that race is the one to read first.

A **stale** row is deliberately not waited on. It still names an operator; refreshing it
changes no routing decision this rule can make, and every send behind it in the queue
would pay for the refresh.

Nothing is failed for want of an operator, whatever the lookup does — raises, hangs past
the bound, or stays unreachable for an hour. `?` answers, and what `?` answers with is
the owner's to configure.
"""

import asyncio
import json

import pytest

import app.api.router as api_router
import app.modem.manager as manager_mod
from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.modem.manager import ModemManager, OutgoingMessage
from app.settings_store import store
from app.verification import rule
from app.verification.routes import SMS_OUT, TG_GATEWAY

MEGAFON = "МегаФон"
MEGAFON_PHONE = "+79851600019"
OTHER_PHONE = "+79161234567"
TEXT = "Ваш заказ собран, курьер выедет в 14:00"


class _Modem:
    def __init__(self):
        self.pdus = []

    async def send_sms_pdu(self, parts, on_part_sent, **kw):
        self.pdus.append(parts)
        await on_part_sent(1, 42)

    async def registration_state(self):
        return True


class _Lookup:
    """A stand-in for `record_operator`, counted and steerable.

    It writes the same row the real one writes, so what the sender reads afterwards is
    read from the database rather than from this object — a fake that answered the sender
    directly would pass on a sender that never looked at the cache at all.
    """

    def __init__(self, *, answers: str | None = MEGAFON, delay: float = 0.0,
                 raises: BaseException | None = None):
        self.calls = []
        self._answers = answers
        self._delay = delay
        self._raises = raises

    async def __call__(self, phone: str) -> None:
        self.calls.append(phone)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises is not None:
            raise self._raises
        if self._answers is not None:
            await queries.save_number_operator(phone, self._answers, "Москва")


@pytest.fixture
def alerts(monkeypatch):
    sent = []

    class FakeNotifier:
        def maybe_send(self, body, dedup_sig=None, phone=None):
            sent.append((body, dedup_sig))

    import app.alerting as alerting
    monkeypatch.setattr(alerting, "_notifier", FakeNotifier())
    return sent


@pytest.fixture
def pushes(monkeypatch):
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


async def _row(message_id: int) -> dict:
    db = await get_db()
    async with db.execute(
        "SELECT status, attempts, error, routed_route, routed_operator "
        "  FROM messages WHERE id = ?", (message_id,),
    ) as cur:
        return dict(await cur.fetchone())


async def _send(modem: _Modem, phone: str, text: str = TEXT) -> int:
    message_id = await queries.create_message("app1", phone, text)
    await _manager(modem)._send_one(OutgoingMessage(message_id, phone, text, "app1"))
    return message_id


# --- the race 4.6 would lose without this ------------------------------------- 4.4

def test_a_first_ever_message_to_a_diverted_operator_is_not_routed_on_an_empty_cache(
        monkeypatch, alerts, pushes):
    """🔴 The whole reason the sender waits at all.

    No row exists for this number, so the rule would answer through `?` — which ships
    pointing at the modem, the very route МегаФон has been rejecting. The sender
    resolves it first, and the refusal that 4.6 promises happens.
    """
    async def body():
        lookup = _Lookup(answers=MEGAFON)
        monkeypatch.setattr(manager_mod, "record_operator", lookup)

        modem = _Modem()
        message_id = await _send(modem, MEGAFON_PHONE)

        assert lookup.calls == [MEGAFON_PHONE], lookup.calls
        row = await _row(message_id)
        assert row["status"] == "failed", row
        assert modem.pdus == []
        assert row["routed_route"] == TG_GATEWAY, row
        assert row["routed_operator"] == MEGAFON, row

    _run(body)


def test_a_resolved_operator_is_not_looked_up_again(monkeypatch, alerts, pushes):
    """The cache is read first, and a hit spends nothing.

    Positive control for the test above: without it, "the sender resolves" would pass on
    a sender that resolves on every single message, which would put a lookup in front of
    every send this gateway makes.
    """
    async def body():
        lookup = _Lookup(answers=MEGAFON)
        monkeypatch.setattr(manager_mod, "record_operator", lookup)
        await queries.save_number_operator(OTHER_PHONE, "МТС", "Москва")

        modem = _Modem()
        message_id = await _send(modem, OTHER_PHONE)

        assert lookup.calls == [], lookup.calls
        row = await _row(message_id)
        assert row["status"] == "sent", row
        assert row["routed_route"] == SMS_OUT
        assert row["routed_operator"] == "МТС"

    _run(body)


def test_a_stale_row_is_used_as_it_stands_and_not_refreshed(monkeypatch, alerts, pushes):
    """A stale row still names an operator, and refreshing it changes no route.

    Operators move numbers on a scale of years; this rule is reviewed on a scale of
    months. Waiting on the refresh would buy nothing and would be paid for by every send
    behind it in the single-file send queue.
    """
    async def body():
        lookup = _Lookup(answers=MEGAFON)
        monkeypatch.setattr(manager_mod, "record_operator", lookup)
        await queries.save_number_operator(OTHER_PHONE, "МТС", "Москва")
        db = await get_db()
        await db.execute(
            "UPDATE number_operators SET checked_at = datetime('now', '-400 days') "
            " WHERE phone = ?", (OTHER_PHONE,))
        await db.commit()

        modem = _Modem()
        message_id = await _send(modem, OTHER_PHONE)

        assert lookup.calls == [], lookup.calls
        assert (await _row(message_id))["status"] == "sent"

    _run(body)


def test_a_row_whose_operator_is_null_counts_as_absent(monkeypatch, alerts, pushes):
    """A row can exist and name nobody — `save_number_operator` takes `None`.

    Treating "there is a row" as "there is an operator" would route this number on an
    operator nobody ever resolved, which is the same defect as reading an empty cache and
    is invisible in exactly the same way.
    """
    async def body():
        lookup = _Lookup(answers=MEGAFON)
        monkeypatch.setattr(manager_mod, "record_operator", lookup)
        await queries.save_number_operator(MEGAFON_PHONE, None, None)

        modem = _Modem()
        message_id = await _send(modem, MEGAFON_PHONE)

        assert lookup.calls == [MEGAFON_PHONE], lookup.calls
        assert (await _row(message_id))["status"] == "failed"

    _run(body)


# --- the absence, recorded ----------------------------------------------------- 4.4

def test_a_row_whose_operator_is_blank_counts_as_absent(monkeypatch, alerts, pushes):
    """🔴 Found by a mutation that survived: NULL and blank are not the same test.

    `_cached_operator` folds a blank or whitespace-only operator to absent. Asserting
    only the NULL case leaves that fold unguarded — returning the column raw passes the
    NULL test unchanged, because NULL is already absent. What the fold actually protects
    is a row holding `""`, which is what a hand-edited row and a future writer look like:
    neither `record_operator` nor `backfill` can write one today, since both go through
    `voxlink.parse_response`, which answers None for a falsy operator. Guarding a value
    no current writer produces is the point — the fold exists for the writer that has not
    been written yet, and without this it would be deleted as dead the next time somebody
    tidied.
    """
    async def body():
        lookup = _Lookup(answers=MEGAFON)
        monkeypatch.setattr(manager_mod, "record_operator", lookup)
        await queries.save_number_operator(MEGAFON_PHONE, "   ", "Москва")

        modem = _Modem()
        message_id = await _send(modem, MEGAFON_PHONE)

        assert lookup.calls == [MEGAFON_PHONE], lookup.calls
        row = await _row(message_id)
        assert row["status"] == "failed", row
        assert row["routed_operator"] == MEGAFON, row

    _run(body)


def test_an_unresolved_operator_takes_the_unknown_entry_and_is_recorded_as_unknown(
        monkeypatch, alerts, pushes):
    """`?` answers, the send goes, and the case stays countable afterwards.

    Countable is the half that is easy to drop: without it "routed without a known
    operator" is indistinguishable from "routed for МТС" the moment a later lookup fills
    the row in, and the rule's cost cannot be read back.
    """
    async def body():
        lookup = _Lookup(answers=None)          # answers, resolves nobody
        monkeypatch.setattr(manager_mod, "record_operator", lookup)

        modem = _Modem()
        message_id = await _send(modem, OTHER_PHONE)

        row = await _row(message_id)
        assert row["status"] == "sent", row
        assert row["routed_route"] == SMS_OUT, row
        assert row["routed_operator"] is None, row

        # And it stays countable once the lookup finally does resolve the number.
        await queries.save_number_operator(OTHER_PHONE, "МТС", "Москва")
        assert (await _row(message_id))["routed_operator"] is None

    _run(body)


def test_the_unknown_entry_is_the_owners_to_point_anywhere(monkeypatch, alerts, pushes):
    """An unknown operator on a network being refused is a coin toss with a login on it.

    Which way the coin falls is configuration and not this gateway's opinion, so `?` set
    to a refusal refuses — the same send, the same sender, a different rule.
    """
    async def body():
        lookup = _Lookup(answers=None)
        monkeypatch.setattr(manager_mod, "record_operator", lookup)
        await store.set_many({rule.KEY: json.dumps(
            [
                {"operator": rule.DEFAULT, "routes": [SMS_OUT]},
                {"operator": rule.UNKNOWN, "routes": [rule.REFUSE]},
            ],
            ensure_ascii=False,
        )})

        modem = _Modem()
        message_id = await _send(modem, OTHER_PHONE)

        row = await _row(message_id)
        assert row["status"] == "failed", row
        assert modem.pdus == []
        assert row["routed_route"] == rule.REFUSE, row
        assert row["routed_operator"] is None, row

    _run(body)


# --- the lookup being unreachable ---------------------------------------------- 4.5

def test_a_lookup_that_hangs_is_abandoned_at_the_bound_and_fails_nothing(
        monkeypatch, alerts, pushes):
    """The bound is the gateway's, not the lookup's.

    `voxlink.lookup` bounds its own HTTP call, but a bound that lives in the thing being
    waited for is not a bound: it fails open on `httpx` errors only, and anything else —
    a resolver that never returns, a raise from a layer below — escapes it. Asserted on
    the clock rather than on a mock being called, because what the requirement promises
    is that nothing is delayed beyond it.
    """
    async def body():
        await store.set_many({"operator_lookup_bound": "0.05"})
        lookup = _Lookup(answers=MEGAFON, delay=30.0)
        monkeypatch.setattr(manager_mod, "record_operator", lookup)

        modem = _Modem()
        started = asyncio.get_event_loop().time()
        message_id = await _send(modem, OTHER_PHONE)
        spent = asyncio.get_event_loop().time() - started

        assert spent < 5.0, f"the send waited {spent:.1f}s on a hanging lookup"
        row = await _row(message_id)
        assert row["status"] == "sent", row
        assert row["routed_operator"] is None, row

    _run(body)


def test_a_lookup_that_raises_fails_nothing(monkeypatch, alerts, pushes):
    """Enrichment raising is not a reason to refuse somebody their message."""
    async def body():
        lookup = _Lookup(raises=RuntimeError("the resolver is on fire"))
        monkeypatch.setattr(manager_mod, "record_operator", lookup)

        modem = _Modem()
        message_id = await _send(modem, OTHER_PHONE)

        row = await _row(message_id)
        assert row["status"] == "sent", row
        assert row["routed_operator"] is None, row
        assert len(modem.pdus) == 1

    _run(body)


def test_an_hour_of_unreachable_lookups_delays_and_fails_nothing(
        monkeypatch, alerts, pushes):
    """The scenario as the spec words it: every number, for an hour.

    Stated as a run of sends rather than one, because the failure it guards against is
    cumulative: a bound spent per message turns a dead lookup into a send queue that
    never drains, and one message cannot show that.
    """
    async def body():
        await store.set_many({"operator_lookup_bound": "0.02"})
        lookup = _Lookup(answers=None, delay=5.0)
        monkeypatch.setattr(manager_mod, "record_operator", lookup)

        modem = _Modem()
        started = asyncio.get_event_loop().time()
        ids = [await _send(modem, f"+7985160{n:04d}") for n in range(12)]
        spent = asyncio.get_event_loop().time() - started

        assert spent < 3.0, f"twelve sends spent {spent:.1f}s on a dead lookup"
        for message_id in ids:
            row = await _row(message_id)
            assert row["status"] == "sent", row
            assert row["routed_operator"] is None, row
        assert len(modem.pdus) == 12

    _run(body)


# --- the door ------------------------------------------------------------------ 4.5

def test_the_api_door_does_not_wait_for_the_lookup(monkeypatch):
    """`POST /sms/send` answers on the message being queued, not on the enrichment.

    Asserted as "the door returned before the lookup finished", which is the claim, and
    not as "`record_operator` was never called" — the lookup still has to happen, just
    not in front of the person waiting for an HTTP response.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    async def body():
        finished = []

        async def slow_lookup(phone: str) -> None:
            await asyncio.sleep(0.3)
            finished.append(phone)

        monkeypatch.setattr(api_router, "record_operator", slow_lookup)

        enqueued = []

        class _FakeModem:
            async def enqueue(self, message_id, phone, text, app_id=""):
                enqueued.append(message_id)

        app = FastAPI()
        app.include_router(api_router.router)
        app.state.modem = _FakeModem()

        with TestClient(app) as client:
            resp = client.post(
                "/sms/send",
                json={"phone": OTHER_PHONE, "text": TEXT},
                headers={"Authorization": "Bearer token-app1"},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "pending"
        assert enqueued, "the message never reached the queue"
        assert finished == [], "the door waited for the lookup to finish"

    _run(body)
