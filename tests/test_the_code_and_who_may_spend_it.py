"""The code: who may hold it, who may spend it, and where it must never appear.

Six guards the owner grouped together on 21.09.2026 because they share one property —
none of them touches production, and all of them are about the one value in this
capability that is a secret.

🔴 **Three of them were already green and two of those were hollow**, which is the reason
this file exists rather than a row of ticks. Measured by mutation on 21.09.2026, against
`tests/test_verification_store.py` and `tests/test_verification_api.py`:

- **the whole of 4.11 was unguarded.** `test_two_open_verifications_for_one_number_do_not_
  share_a_code` asserts what `open_codes_for` reports, never that the second code *differs*.
  Replacing the door's `_new_code(await queries.open_codes_for(phone))` with
  `_new_code(set())` left the suite green;
- **two of 4.10's conditions rest on a second filter.** `status = 'pending'` and
  `attempts < ?` can both be deleted from the confirming update and nothing reddens,
  because a terminal verification has already had its code nulled and so fails to match
  on `code = ?` instead. The guarantee is real but it is held by one line, and the day
  destruction is deferred — which is what task 4.30 is about — it is held by none;
- **4.29's second half was unasserted.** Nothing said that the *loser* of a confirmation
  race spends no attempt: bumping the attempt count in the already-confirmed branch, while
  leaving the answer word alone, left the suite green.

So the guards here assert against the value each line feeds **directly**: a code put back
into a terminal row, an attempt counted on the loser, a scripted source of digits the door
must be seen to consult.
"""

import asyncio
import logging
import types

import pytest
from fastapi.testclient import TestClient

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import ladder, tg_carrier, tg_gateway
from app.verification.routes import CALL_IN, Proof, TG_GATEWAY

PHONE = "+79261234888"
AUTH = {"Authorization": "Bearer token-app1"}
OTHER = {"Authorization": "Bearer token-app2"}
TOKEN = "a-token"
LIMIT = 5


# --- the door, built as the other door tests build it ----------------------------------

class FakeModem:
    caller_id_held = True
    link_in_service = True
    can_transmit = True
    can_receive = True

    def health_snapshot(self):
        return {"modem_detected": True}


def _holds():
    async def proof():
        return Proof(holds=True)
    return proof


@pytest.fixture
def app():
    from fastapi import FastAPI

    from app.api.router import router

    async def setup():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await queries.create_app("app2", "token-app2")
        await store.load()
        await store.set_many({"gateway_msisdn": "+79990001122"})

    asyncio.run(setup())
    application = FastAPI()
    application.include_router(router)
    application.state.modem = FakeModem()
    application.state.ims_proof = _holds()
    try:
        yield application
    finally:
        asyncio.run(close_db())


@pytest.fixture
def client(app):
    return TestClient(app)


def _run(body):
    """The store-level harness, for the guards that have no door to go through."""
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await queries.create_app("app2", "token-app2")
        await store.load()
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


async def _open(app_id="app1", phone=PHONE, code="1234", ttl=300):
    return await queries.create_verification(app_id, phone, code=code, ttl_seconds=ttl)


async def _put_the_code_back(vid, code="1234"):
    """Restore a code into a row that has already ended.

    The one move that tells the two mechanisms apart. Every refusal 4.10 asks for is
    enforced twice over — once by the row's state and once by the code no longer being
    there to match — and a guard that ends a verification and then offers the old code is
    asserting about the filter that is *not* the one the suite already proves.
    """
    db = await get_db()
    await db.execute("UPDATE verifications SET code = ? WHERE id = ?", (code, vid))
    await db.commit()


def _codes_for(phone):
    async def body():
        db = await get_db()
        async with db.execute(
            "SELECT code FROM verifications WHERE phone = ? ORDER BY id", (phone,)
        ) as cur:
            return [row[0] for row in await cur.fetchall()]
    return body


# --- 4.7 — the application does not choose the code -------------------------------------

def test_an_application_supplied_code_is_refused_and_opens_nothing(client):
    """Held already, and bitten on 21.09.2026: disarming `refuse_a_supplied_code` reddens
    it. What the inherited guard does not say is that the refusal happens **before** a row
    exists — a request rejected after a verification is opened would leave the number
    carrying a live code nobody asked for."""
    r = client.post("/verifications", json={"phone": PHONE, "code": "4321"}, headers=AUTH)
    assert r.status_code == 422
    assert "code" in r.text

    async def count():
        db = await get_db()
        async with db.execute("SELECT COUNT(*) FROM verifications") as cur:
            return (await cur.fetchone())[0]

    assert _in_the_doors_loop(count) == 0


def test_a_request_naming_only_the_number_is_accepted(client):
    """The positive control. Without it the guard above passes on a door that refuses
    every creation, which is the shape a schema mistake actually takes."""
    r = client.post("/verifications", json={"phone": PHONE}, headers=AUTH)
    assert r.status_code == 200, r.text


def _in_the_doors_loop(body):
    """Run a coroutine against the database the door fixture already opened."""
    return asyncio.run(body())


# --- 4.11 — two open verifications for one number do not share a code -------------------

class _ScriptedDigits:
    """A stand-in for `secrets`, scripted so a collision is certain rather than one in
    ten thousand.

    ⚠️ Replaces the name `secrets` **inside `app.api.router`**, never an attribute of the
    `secrets` module: a module object is shared by every importer, and this branch has
    already paid for that lesson once, in nine red tests, by setting `AsyncClient` on
    `httpx` itself.
    """

    def __init__(self, *draws):
        self.draws = list(draws)
        self.asked = 0

    def randbelow(self, n):
        self.asked += 1
        return self.draws.pop(0) if self.draws else 0


def _script(monkeypatch, *draws):
    import app.api.router as router_module
    scripted = _ScriptedDigits(*draws)
    monkeypatch.setattr(router_module, "secrets", scripted)
    return scripted


def test_a_second_verification_for_one_number_is_opened_rather_than_refused(client):
    """🔴 The reachability question the handoff raised, answered by measurement.

    A guard against two open verifications sharing a code is hollow if the gateway will
    not open a second one. It will: `POST /verifications` asks whether the number is
    blocked and whether any rung can prove itself, and nothing else. The per-number window
    that *does* refuse a second request belongs to the paid vendors and is evaluated when
    a rung is walked, not when a verification is opened.
    """
    first = client.post("/verifications", json={"phone": PHONE}, headers=AUTH)
    second = client.post("/verifications", json={"phone": PHONE}, headers=AUTH)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] != second.json()["id"]
    assert len(_in_the_doors_loop(_codes_for(PHONE))) == 2


def test_the_second_verification_does_not_repeat_the_live_code(client, monkeypatch):
    """The code's one job is to make an arriving answer attributable to one verification.
    Two alike and it is attributable to neither.

    The source of digits is scripted so that the first draw for the second verification
    is exactly the code already live. A door that does not consult what is taken hands
    that draw straight back.
    """
    scripted = _script(monkeypatch, 1234, 1234, 5678)
    first = client.post("/verifications", json={"phone": PHONE}, headers=AUTH)
    second = client.post("/verifications", json={"phone": PHONE}, headers=AUTH)
    assert first.status_code == 200 and second.status_code == 200

    codes = _in_the_doors_loop(_codes_for(PHONE))
    assert codes == ["1234", "5678"], codes
    assert scripted.asked == 3, "the door drew again instead of handing back a live code"


def test_another_numbers_code_is_not_this_numbers_business(client, monkeypatch):
    """The paired positive control, and the reason the guard above is not simply "the door
    redraws until the digits change". A code live on a different number is no collision,
    and a door that redraws for it would exhaust its hundred draws on a busy gateway."""
    scripted = _script(monkeypatch, 1234, 1234)
    assert client.post("/verifications", json={"phone": "+79031680015"},
                       headers=AUTH).status_code == 200
    assert client.post("/verifications", json={"phone": PHONE},
                       headers=AUTH).status_code == 200

    assert _in_the_doors_loop(_codes_for(PHONE)) == ["1234"]
    assert scripted.asked == 2, "the door redrew over another number's code"


# --- 4.10 — the conditions that a nulled code would otherwise hide ----------------------

def test_a_confirmed_verification_is_not_confirmed_again_when_its_code_comes_back():
    """Asserts about `status = 'pending'` in the confirming update, which is the condition
    the inherited guard cannot see: with the code gone, a confirmation that ignores the
    status fails on `code = ?` instead and the suite stays green."""
    async def body():
        vid = await _open()
        first = await queries.check_verification(vid, "app1", code="1234",
                                                 max_attempts=LIMIT)
        row = dict(await queries.get_verification(vid, "app1"))
        await _put_the_code_back(vid)
        second = await queries.check_verification(vid, "app1", code="1234",
                                                  max_attempts=LIMIT)
        after = dict(await queries.get_verification(vid, "app1"))
        return first, second, row["confirmed_at"], after

    first, second, when, after = _run(body)
    assert first == "confirmed"
    assert second == "already_confirmed"
    assert after["confirmed_at"] == when, "the second check moved the confirmation"
    assert after["attempts"] == 0, "a check against a finished verification cost an attempt"


def test_an_exhausted_verification_is_not_confirmed_when_its_code_comes_back():
    """The same move against the other half: a verification out of attempts stays out of
    them even when the right code is offered and the row can match it again."""
    async def body():
        vid = await _open()
        for _ in range(LIMIT):
            await queries.check_verification(vid, "app1", code="0000",
                                             max_attempts=LIMIT)
        await _put_the_code_back(vid)
        outcome = await queries.check_verification(vid, "app1", code="1234",
                                                   max_attempts=LIMIT)
        return outcome, dict(await queries.get_verification(vid, "app1"))

    outcome, row = _run(body)
    assert outcome == "no_attempts_left"
    assert row["status"] == "failed"
    assert row["confirmed_at"] is None


def test_an_expired_verification_is_not_confirmed_though_its_code_is_still_there():
    """The third terminal state, and the only one where the code is genuinely still in the
    row at the moment of the check: the sweep has not run yet. The deadline is therefore
    the only thing refusing it."""
    async def body():
        vid = await _open(ttl=-1)
        outcome = await queries.check_verification(vid, "app1", code="1234",
                                                   max_attempts=LIMIT)
        return outcome, dict(await queries.get_verification(vid, "app1"))

    outcome, row = _run(body)
    assert outcome == "expired"
    assert row["status"] == "pending" and row["code"] == "1234"
    assert row["confirmed_at"] is None


def test_a_lowered_attempt_limit_refuses_the_right_code_and_says_which(): 
    """🔴 The one state in which `attempts < ?` is the only thing standing between a
    spent verification and a confirmation: the limit is a **setting**, and lowering it
    while verifications are open leaves rows pending with more attempts spent than the
    limit now allows.

    Found by measurement on 21.09.2026 and it cost a fix — task 4.10a. Before it, this
    answered `expired`, which is the one thing that had not happened: the row was inside
    its deadline and the requirement asks the answer to say *which* of the three it is.
    """
    async def body():
        vid = await _open()
        for _ in range(2):
            await queries.check_verification(vid, "app1", code="0000", max_attempts=LIMIT)
        outcome = await queries.check_verification(vid, "app1", code="1234",
                                                   max_attempts=2)
        return outcome, dict(await queries.get_verification(vid, "app1"))

    outcome, row = _run(body)
    assert row["status"] == "pending", "the row is inside its deadline; nothing expired"
    assert outcome == "no_attempts_left"
    assert row["confirmed_at"] is None


def test_a_verification_both_out_of_time_and_out_of_attempts_is_called_expired():
    """The precedence, said out loud because it was a choice rather than a consequence.

    A row can be past its deadline *and* past a ceiling that has since been lowered, and
    the answer has to pick one word. It picks the deadline: that is the older of the two
    and the one the application was told at creation, so it is the one the person can see
    the truth of on their own screen. Unstated, this held by accident of branch order —
    reversing the two left every other guard here green.
    """
    async def body():
        vid = await _open()
        for _ in range(2):
            await queries.check_verification(vid, "app1", code="0000", max_attempts=LIMIT)
        db = await get_db()
        await db.execute(
            "UPDATE verifications SET expires_at = datetime('now','-1 hour') WHERE id = ?",
            (vid,))
        await db.commit()
        return await queries.check_verification(vid, "app1", code="1234", max_attempts=2)

    assert _run(body) == "expired"


def test_a_verification_inside_its_deadline_with_attempts_to_spare_still_confirms():
    """The positive control for the guard above. Without it, an implementation that
    answered `no_attempts_left` to everything would satisfy it."""
    async def body():
        vid = await _open()
        await queries.check_verification(vid, "app1", code="0000", max_attempts=LIMIT)
        return await queries.check_verification(vid, "app1", code="1234",
                                                max_attempts=LIMIT)

    assert _run(body) == "confirmed"


# --- 4.20 — one application's token does not walk another's verifications ---------------

def test_a_stranger_cannot_read_check_or_spend_a_verification_by_id(client):
    """All three verbs, with a **valid** token of another application — the token is not
    the question, the ownership is. Exhausting is the quiet one: a stranger need read
    nothing and can still burn a person's five attempts at a barrier they are standing at.
    """
    vid = client.post("/verifications", json={"phone": PHONE}, headers=AUTH).json()["id"]

    assert client.get(f"/verifications/{vid}", headers=OTHER).status_code == 404
    for _ in range(LIMIT + 2):
        assert client.post(f"/verifications/{vid}/check", json={"code": "0000"},
                           headers=OTHER).status_code == 404

    mine = client.get(f"/verifications/{vid}", headers=AUTH)
    assert mine.status_code == 200, "the owner lost their own verification"
    assert mine.json()["attempts"] == 0
    assert mine.json()["status"] == "pending"


def test_a_stranger_who_knows_the_code_confirms_nothing():
    """🔴 Written 22.09.2026 because `bite-code.py` found the hole: widening `app_id` on
    the **confirming update** turned nothing red.

    The guard above offers only a wrong code, so `code = ?` refuses the update whatever
    the ownership says, and the door's own prior read answers 404 before the matcher is
    reached — two filters standing in front of the one this asserts. Asked of the matcher
    directly for that reason: the claim is that *every* conditional update in
    `check_verification` is scoped, not that some door in front of it happens to be.

    Reachable: a code is shown to a person, and a person can be induced to read it out.
    Ownership is what keeps the verification that code belongs to out of another
    application's hands.
    """
    async def body():
        vid = await _open(code="1234")
        stranger = await queries.check_verification(vid, "app2", code="1234",
                                                    max_attempts=LIMIT)
        row = await queries.get_verification(vid, "app1")
        return stranger, row["status"], row["code"], row["attempts"]

    outcome, status, code, attempts = _run(body)
    assert outcome == "not_found", f"a stranger's check answered {outcome!r}"
    assert (status, code) == ("pending", "1234"), \
        "a stranger with the right code confirmed somebody else's verification"
    assert attempts == 0, "a stranger's check spent the owner's attempt"


def test_the_owner_with_the_right_code_does_confirm():
    """The control on the test above: the same call from the owning application confirms,
    so the guard is about ownership and not about a matcher that refuses everyone."""
    async def body():
        vid = await _open(code="1234")
        return await queries.check_verification(vid, "app1", code="1234",
                                                max_attempts=LIMIT)

    assert _run(body) == "confirmed"


def test_the_owner_of_the_verification_can_do_all_three(client):
    """The positive control the negative guard needs: the same three calls, from the token
    that opened it, all answer."""
    vid = client.post("/verifications", json={"phone": PHONE}, headers=AUTH).json()["id"]
    assert client.get(f"/verifications/{vid}", headers=AUTH).status_code == 200
    wrong = client.post(f"/verifications/{vid}/check", json={"code": "0000"},
                        headers=AUTH)
    assert wrong.status_code == 200 and wrong.json()["outcome"] == "wrong_code"
    assert client.get(f"/verifications/{vid}", headers=AUTH).json()["attempts"] == 1


# --- 4.29 — two checks at once ----------------------------------------------------------

def test_the_loser_of_a_confirmation_race_spends_no_attempt():
    """🔴 The half nothing asserted. Confirming at most once was guarded; "one attempt is
    consumed at most once" was not, and a person double-tapping Confirm with the **right**
    code is the commonest way to reach this branch. An attempt spent there is a person
    taxed for the gateway's own race."""
    async def body():
        vid = await _open()
        outcomes = await asyncio.gather(
            queries.check_verification(vid, "app1", code="1234", max_attempts=LIMIT),
            queries.check_verification(vid, "app1", code="1234", max_attempts=LIMIT),
        )
        return sorted(outcomes), dict(await queries.get_verification(vid, "app1"))

    outcomes, row = _run(body)
    assert outcomes == ["already_confirmed", "confirmed"]
    assert row["attempts"] == 0, "the loser of the race was charged an attempt"


def test_a_wrong_code_still_costs_exactly_one_attempt():
    """The positive control: the counter is reachable and does count. Without it, a
    verification that never spends an attempt at all would satisfy the guard above."""
    async def body():
        vid = await _open()
        await queries.check_verification(vid, "app1", code="0000", max_attempts=LIMIT)
        return dict(await queries.get_verification(vid, "app1"))["attempts"]

    assert _run(body) == 1


# --- 4.22 — the code appears nowhere outside the matcher --------------------------------

def test_no_verification_door_answers_with_the_code_except_the_one_rung_that_must():
    """Enumerated from the router rather than from a list kept here. A list would be a
    census, and a census of surfaces is never complete and goes stale in silence — the
    next response model added to this capability is exactly the one a list would miss.

    `RouteSelectResponse` is the single sanctioned exception and it belongs to a **rung**,
    not to an application: on `sms_in` the person reads the code off their own screen and
    texts it back, so the application has to be able to show it.
    """
    from app.api.router import router

    carrying = {}
    for route in router.routes:
        model = getattr(route, "response_model", None)
        if model is None:
            continue
        if "code" in getattr(model, "model_fields", {}):
            carrying[model.__name__] = sorted(route.methods)

    assert set(carrying) == {"RouteSelectResponse"}, carrying


# --- 6.1 — the message door is a door of this capability too ----------------------------

def test_the_message_carrying_a_code_is_not_readable_through_the_message_door(client):
    """The door the enumeration above could not see, because it is not on a
    `/verifications` path.

    The `sms_out` rung composes the code into a real `messages` row owned by the same
    application (`app/verification/sms_carrier.py`), and `GET /sms/{id}` answered it back
    with the text in it. Measured on 22.09.2026 by the conformance sweep: an application
    opened a verification on a number, walked the ids next to its own last send, read
    `'SokolParking: 3164 is your code'` out of the response and confirmed the
    verification with `POST /verifications/{id}/check` — without the message ever
    reaching the person, which is the whole of what this requirement buys.

    The answer is 404 rather than a redacted text, for two reasons. The code is nulled at
    every terminal ending, so a guard that strips "this verification's code" from the text
    stops stripping anything the moment the verification ends, while the text keeps the
    digits forever. And this id was never the application's to hold: the same branch
    already refuses to push a message-status webhook for a verification's message
    (`tests/test_a_verification_owns_its_message.py`), because the application asked about
    a verification, not about a message.
    """
    async def carried():
        vid = await queries.create_verification(
            "app1", PHONE, code="3164", ttl_seconds=300)
        return await queries.create_message(
            "app1", PHONE, "SokolParking: 3164 is your code", verification_id=vid)

    message_id = _in_the_doors_loop(carried)

    r = client.get(f"/sms/{message_id}", headers=AUTH)
    assert r.status_code == 404, r.text
    assert "3164" not in r.text


def test_an_ordinary_message_is_still_readable_through_the_message_door(client):
    """The positive control. Without it the guard above passes on a door that 404s every
    message, which is what an over-wide `WHERE` actually looks like — and `GET /sms/{id}`
    is the authoritative status source `delivery-dispatch` tells consumers to poll."""
    async def ordinary():
        return await queries.create_message("app1", PHONE, "your parking expires soon")

    message_id = _in_the_doors_loop(ordinary)

    r = client.get(f"/sms/{message_id}", headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "your parking expires soon"


def _fake_notifier(monkeypatch):
    """The real `notify`, with a fake notifier under it — the toggle lives inside `notify`
    and patching `notify` itself would step over the half that says "on stock settings"."""
    sent = []

    class FakeNotifier:
        def maybe_send(self, body, dedup_sig=None, phone=None):
            sent.append(body)

    import app.alerting as alerting
    monkeypatch.setattr(alerting, "_notifier", FakeNotifier())
    return sent


def _able(request_id="req-1", cost=0.01, balance=99.99):
    return tg_gateway.Ability(
        kind=tg_gateway.ABLE, request_id=request_id,
        status=tg_gateway.RequestStatus(
            request_id=request_id, phone_number=PHONE.lstrip("+"),
            request_cost=cost, remaining_balance=balance))


def _patch_vendor(monkeypatch, *, ability, sent=None, sends=None):
    async def check(phone, *, token, timeout=5.0, client=None):
        return ability

    async def send(phone, *, code, ttl, token, request_id=None, callback_url="",
                   payload="", sender_username="", timeout=10.0, client=None):
        if sends is not None:
            sends.append({"phone": phone, "code": code, "ttl": ttl})
        return sent

    monkeypatch.setattr(tg_gateway, "check_send_ability", check)
    monkeypatch.setattr(tg_gateway, "send_verification_message", send)


def _walk(vid, carriers, rungs=(TG_GATEWAY,)):
    return ladder.walk(vid, app_id="app1", operator="МТС", phone=PHONE,
                       rungs=list(rungs), gates=[], carriers=carriers, bound=5.0)


def test_the_code_a_rung_carried_reaches_the_vendor_and_no_log_line(monkeypatch, caplog):
    """The positive control and the guard in one run, which is the only shape that proves
    anything here: the code **did** travel this path — the vendor received it — and the
    rung then failed loudly, so the log lines this path writes are the ones a leak would
    ride out on."""
    # Levelled on the gateway's own loggers, not on the root. Root at DEBUG turns
    # asyncio's task reprs on, and a coroutine repr carries its arguments — the code
    # among them. That is the test harness printing the secret, not the gateway, and a
    # guard that reddens on it would be answering a question nobody asked.
    caplog.set_level(logging.DEBUG, logger="app")
    sends = []
    _patch_vendor(monkeypatch, ability=_able(),
                  sent=tg_gateway.Sent(ok=False, error="MESSAGE_NOT_SENT"), sends=sends)

    async def body():
        vid = await _open(code="9137")
        walk = await _walk(vid, {TG_GATEWAY: tg_carrier.carrier(
            vid, app_id="app1", token=TOKEN, callback_url="")})
        return vid, walk

    vid, walk = _run(body)

    assert sends and sends[0]["code"] == "9137", "the code never travelled; nothing proved"
    assert walk.carried_by is None and walk.reason
    lines = [r.getMessage() for r in caplog.records]
    assert lines, "no log line was written; the guard asserted over nothing"
    assert any(str(vid) in line for line in lines), "no line named the verification"
    leaked = [line for line in lines if "9137" in line]
    assert leaked == [], leaked


def test_an_alerting_rung_failure_names_the_vendor_and_not_the_code(monkeypatch, caplog):
    """The alert half. A vendor refusing *this gateway* is the loud case — it wakes the
    operator on stock settings — and it is raised while a live code is sitting in the row
    it is about."""
    # Levelled on the gateway's own loggers, not on the root. Root at DEBUG turns
    # asyncio's task reprs on, and a coroutine repr carries its arguments — the code
    # among them. That is the test harness printing the secret, not the gateway, and a
    # guard that reddens on it would be answering a question nobody asked.
    caplog.set_level(logging.DEBUG, logger="app")
    alerts = _fake_notifier(monkeypatch)
    _patch_vendor(monkeypatch, ability=tg_gateway.Ability(
        kind=tg_gateway.REFUSED, error="TOKEN_INVALID"))

    async def body():
        vid = await _open(code="9137")
        await _walk(vid, {TG_GATEWAY: tg_carrier.carrier(
            vid, app_id="app1", token=TOKEN, callback_url="")})
        db = await get_db()
        async with db.execute(
            "SELECT code FROM verifications WHERE id = ?", (vid,)
        ) as cur:
            return vid, (await cur.fetchone())[0]

    vid, code_after = _run(body)

    assert alerts, "the operator was not alerted; the guard asserted over nothing"
    assert any("Telegram" in a or "tg" in a.lower() for a in alerts), alerts
    assert [a for a in alerts if "9137" in a] == []
    lines = [r.getMessage() for r in caplog.records]
    assert [line for line in lines if "9137" in line] == []
    assert code_after is None, "a failed verification kept a usable secret"


def test_every_terminal_ending_takes_the_secret_with_it():
    """All four endings in one run, because the claim is about the set rather than about
    any one of them: a verification stops holding a usable secret the moment it stops
    being confirmable, whichever way it stopped.

    The rung-failure ending is the one the inherited guards miss — confirmation and
    exhaustion were both covered and this one was not, though it is the ending every
    walked ladder arrives at when nothing carried the code.

    🔴 **The sweep was the fourth and it was missing until 22.09.2026**, found by
    `bite-code.py`: dropping `code = NULL` from `expire_due_verifications` turned nothing
    red. Counting endings by *writer* is what hid it — `check_verification` holds two of
    them, so "all three writers" and "all three endings" are different sets and the prose
    that named three meant the first. It is also the ending that happens to **the person
    who never got the call**, which is the commonest of the four and the one nobody comes
    back to.
    """
    async def body():
        confirmed = await _open(code="1111")
        await queries.check_verification(confirmed, "app1", code="1111",
                                         max_attempts=LIMIT)

        exhausted = await _open(code="2222")
        for _ in range(LIMIT):
            await queries.check_verification(exhausted, "app1", code="0000",
                                             max_attempts=LIMIT)

        by_its_rung = await _open(code="3333")
        ended = await queries.fail_verification(by_its_rung, reason="route_unavailable")

        # The sweep's own ending: opened already past its deadline, then swept.
        await _open(code="4444", ttl=-1)
        await queries.expire_due_verifications()

        db = await get_db()
        async with db.execute(
            "SELECT id, status, code FROM verifications ORDER BY id"
        ) as cur:
            return ended, [tuple(r)[1:] for r in await cur.fetchall()]

    ended, rows = _run(body)
    assert ended is True
    assert rows == [("confirmed", None), ("failed", None), ("failed", None),
                    ("expired", None)], rows


def test_the_rung_row_is_written_through_the_same_border(): 
    """The third writer of verification-scoped free text, guarded directly because no
    caller reaches it with a reason today.

    `ladder.walk` writes this row before it contacts the rung, and at that moment it has
    nothing to say — so the scrub here is for the writer that is not written yet, and an
    unreachable scrub with no guard on it is the shape that gets deleted as dead code.
    The border is the function, so the guard calls the function.
    """
    async def body():
        vid = await _open(code="9137")
        await queries.record_verification_rung(
            vid, route=TG_GATEWAY, outcome="attempting",
            reason="the vendor answered: code 9137 is not acceptable")
        db = await get_db()
        async with db.execute(
            "SELECT reason FROM verification_rungs WHERE verification_id = ?", (vid,)
        ) as cur:
            return (await cur.fetchone())[0]

    stored = _run(body)
    assert "9137" not in stored, stored
    assert "is not acceptable" in stored, stored


def test_a_vendors_words_do_not_carry_the_code_out_to_the_application():
    """🔴 Found by mutation on 21.09.2026, and it cost a mechanism — task 4.22a.

    `reason` is free text, and it is not ours: it is filled from a vendor's error string
    and from an exception's message. A reason carrying the code reached
    `GET /verifications/{id}` and the console's expanded row with the whole suite green,
    because every guard on this requirement watched the **fields**, and a field of type
    `str` says nothing about what is inside it.

    The vendor echoing a rejected code is the ordinary shape of this: the samples captured
    from the live Gateway show no echo today, which is exactly why a guard written against
    today's samples would be a guard held up by somebody else's habit.
    """
    sends = []
    import app.verification.tg_gateway as tgg

    async def body():
        vid = await _open(code="9137")

        async def check(phone, *, token, timeout=5.0, client=None):
            return _able()

        async def send(phone, *, code, ttl, token, request_id=None, callback_url="",
                       payload="", sender_username="", timeout=10.0, client=None):
            sends.append(code)
            # The vendor quoting back what it was given, which is the whole hazard.
            return tgg.Sent(ok=False, error=f"MESSAGE_BODY_REJECTED: code {code}")

        original = (tgg.check_send_ability, tgg.send_verification_message)
        tgg.check_send_ability, tgg.send_verification_message = check, send
        try:
            await _walk(vid, {TG_GATEWAY: tg_carrier.carrier(
                vid, app_id="app1", token=TOKEN, callback_url="")})
        finally:
            tgg.check_send_ability, tgg.send_verification_message = original

        row = dict(await queries.get_verification(vid, "app1"))
        db = await get_db()
        async with db.execute(
            "SELECT reason FROM verification_rungs WHERE verification_id = ?", (vid,)
        ) as cur:
            rungs = [r[0] for r in await cur.fetchall()]
        return row["reason"], rungs

    reason, rungs = _run(body)

    assert sends == ["9137"], "the code never reached the vendor; nothing was proved"
    assert "9137" not in (reason or ""), reason
    assert all("9137" not in (r or "") for r in rungs), rungs
    # The positive control: what the vendor actually said is still there. A reason blanked
    # wholesale would satisfy the line above and tell an operator nothing.
    assert "MESSAGE_BODY_REJECTED" in (reason or ""), reason
