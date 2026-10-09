# tests/test_the_call_outcome_that_arrives_late.py
"""Task 4.17e: what became of a call the vendor had not decided in time.

The ladder waits ten seconds because a person is standing in front of a synchronous
request. uCaller takes "от 1 сек до 1 минуты" to set `call_status`. Those two numbers do
not overlap, so the rung's ordinary ending is `unresolved` — and until this sweep existed
that ending was permanent: a subscriber the vendor could not reach watched the
verification expire instead of being told the call failed, and the call's `cost` was
never recorded against the rung that incurred it, which is the number the weekly spend is
reconciled against.

Three properties, and each is a way the sweep could look like it works:

- **it runs from the one pass that announces every ending**, so an ending it creates is
  announced in the same pass rather than by a second announcer nobody added;
- **it settles the money whether or not anybody is still waiting.** A verification that
  expired meanwhile still owes its rung a cost;
- **it gives up rather than telling a story.** A rung the vendor never resolves stops
  being chased and keeps saying `unresolved`, which is the truthful record.
"""

from __future__ import annotations

import asyncio

from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import dispatch, flash_carrier, ladder, ucaller
from app.verification.routes import FLASH_CALL

PHONE = "+79851600019"


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        await store.set_many({"ucaller_key": "SECRET", "ucaller_service_id": "747277"})
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


async def _unresolved(code="1234", ttl=300, vendor_ref="57251313"):
    """A verification whose call rung is exactly where the ladder left it."""
    vid = await queries.create_verification("app1", PHONE, code=code, ttl_seconds=ttl)
    rung_id = await queries.record_verification_rung(
        vid, route=FLASH_CALL, outcome=ladder.ATTEMPTING)
    await queries.set_rung_outcome(rung_id, outcome=ladder.UNRESOLVED,
                                   vendor_ref=vendor_ref)
    await queries.select_route(vid, "app1", route=FLASH_CALL)
    return vid, rung_id


def _answer(monkeypatch, *, call_status, code="1234", cost=0.8, balance=100.8,
            asked=None):
    async def get_info(uid, *, bearer, timeout=10.0, client=None):
        if asked is not None:
            asked.append((uid, bearer))
        return ucaller.Fetched(kind=ucaller.ACCEPTED, info=ucaller.Info(
            ucaller_id=uid, call_status=call_status, code=code, cost=cost,
            balance_before=balance))
    monkeypatch.setattr(ucaller, "get_info", get_info)


# --- the ending the person was owed -------------------------------------------------------

def test_a_call_that_could_not_connect_fails_the_verification_when_it_finally_says_so(
        monkeypatch):
    def body():
        async def run():
            vid, rung_id = await _unresolved()
            asked: list = []
            _answer(monkeypatch, call_status=ucaller.NOT_CONNECTED, asked=asked)

            settled = await flash_carrier.resolve_outstanding()
            assert settled == 1
            assert asked == [(57251313, "SECRET.747277")]

            row = await queries.get_verification(vid, "app1")
            assert row["status"] == "failed", (
                "the person waited out the window for a call that had already failed")
            assert "connect" in (row["reason"] or "")
            rungs = await queries.verification_rungs(vid)
            assert rungs[0]["outcome"] == ladder.FAILED
            assert rungs[0]["cost"] == 0.8
            return True
        return run()
    assert _run(body)


def test_a_call_that_was_placed_settles_the_rung_and_leaves_the_person_time(monkeypatch):
    def body():
        async def run():
            vid, _ = await _unresolved()
            _answer(monkeypatch, call_status=ucaller.PLACED)

            assert await flash_carrier.resolve_outstanding() == 1
            row = await queries.get_verification(vid, "app1")
            assert row["status"] == "pending", (
                "a placed call was read as a confirmed code")
            rungs = await queries.verification_rungs(vid)
            assert rungs[0]["outcome"] == ladder.CARRIED
            assert rungs[0]["cost"] == 0.8
            return True
        return run()
    assert _run(body)


def test_the_money_is_recorded_even_when_nobody_is_waiting_any_more(monkeypatch):
    """A verification that expired while the vendor was thinking still owes its rung a
    cost: the weekly reconciliation compares what was recorded against what the balance
    fell by, and a charge with no row is exactly the disagreement it exists to find."""
    def body():
        async def run():
            vid, _ = await _unresolved()
            await queries.fail_verification(vid, reason="expired under us")
            _answer(monkeypatch, call_status=ucaller.NOT_CONNECTED)

            assert await flash_carrier.resolve_outstanding() == 1
            rungs = await queries.verification_rungs(vid)
            assert rungs[0]["cost"] == 0.8, "a charge was left attributable to nothing"
            row = await queries.get_verification(vid, "app1")
            assert row["reason"] == "expired under us", (
                "the ending the person already had was overwritten a minute later")
            return True
        return run()
    assert _run(body)


def test_the_balance_this_sweep_watches_is_the_one_after_the_charge(monkeypatch):
    """The same subtraction the carrier makes, and it has to be made here too: this pass
    is the only reading the gateway gets for a call the ladder stopped waiting for, and
    `getInfo`'s `balance` is the balance **before** this operation is charged."""
    seen: list = []
    monkeypatch.setattr("app.verification.balance.observe",
                        lambda route, value: seen.append((route, value)))

    def body():
        async def run():
            await _unresolved()
            _answer(monkeypatch, call_status=ucaller.NOT_CONNECTED, cost=0.8,
                    balance=100.8)
            await flash_carrier.resolve_outstanding()
            assert seen == [(FLASH_CALL, 100.0)], seen
            return True
        return run()
    assert _run(body)


# --- the spent code and the honest echo -----------------------------------------------------

def test_the_sweep_does_not_rewrite_the_rung_of_a_verification_our_own_code_confirmed(
        monkeypatch):
    """Verification 118, 08.10: confirmed at 16:43:06, rung failed at 16:43:12. The
    person confirmed within seconds, the vendor reports within a minute — so the sweep
    always arrives after the confirmation, and the code it would compare the report
    against is already spent. Confirmation at `/check` is this gateway's own evidence,
    and it outranks whatever the vendor says a minute later."""
    def body():
        async def run():
            vid, _ = await _unresolved(code="1234")
            assert await queries.check_verification(
                vid, "app1", code="1234", max_attempts=3) == "confirmed"
            _answer(monkeypatch, call_status=ucaller.PLACED, code="9876")

            assert await flash_carrier.resolve_outstanding() == 1
            row = await queries.get_verification(vid, "app1")
            assert row["status"] == "confirmed", "a confirmed verification was re-ended"
            rungs = await queries.verification_rungs(vid)
            assert rungs[0]["outcome"] == ladder.CARRIED, (
                "the vendor's late report outranked this gateway's own confirmation")
            assert rungs[0]["cost"] == 0.8
            assert "confirmed" in (rungs[0]["reason"] or ""), (
                f"the confirmation was not named: {rungs[0]['reason']!r}")
            return True
        return run()
    assert _run(body)


def test_a_genuine_disagreement_on_a_live_code_fails_the_rung_when_the_sweep_settles(
        monkeypatch):
    """The report is an honest echo (control probes v121/v122), so a disagreement the
    sweep sees while the verification still holds its code is real: the vendor dialled
    digits the person cannot be matched against, and the rung fails for that reason —
    the same branch the carrier takes, a minute later."""
    def body():
        async def run():
            vid, _ = await _unresolved(code="1234")
            _answer(monkeypatch, call_status=ucaller.PLACED, code="9876")

            assert await flash_carrier.resolve_outstanding() == 1
            row = await queries.get_verification(vid, "app1")
            assert row["status"] == "failed", (
                "a live-code disagreement left nobody-waiting pending")
            assert "digits" in (row["reason"] or "")
            rungs = await queries.verification_rungs(vid)
            assert rungs[0]["outcome"] == ladder.FAILED
            assert rungs[0]["cost"] == 0.8
            return True
        return run()
    assert _run(body)


def test_an_ended_verification_spending_its_code_is_not_read_as_a_disagreement(
        monkeypatch):
    """Every ending spends the verification's code, and the sweep reads rungs of ended
    verifications too — for their cost. A spent code read as a disagreement
    manufactured a false "different digits" out of an honest echo: all six production
    rungs with that reason were exactly this, each on a verification this gateway's own
    code had already confirmed."""
    def body():
        async def run():
            vid, _ = await _unresolved(code="1234")
            await queries.fail_verification(vid, reason="expired under us")
            # Even a report that had disagreed could not be told apart now — the code
            # to compare against is gone.
            _answer(monkeypatch, call_status=ucaller.PLACED, code="1234")

            assert await flash_carrier.resolve_outstanding() == 1
            rungs = await queries.verification_rungs(vid)
            assert rungs[0]["outcome"] == ladder.CARRIED
            assert rungs[0]["reason"] == ("the verification ended before the vendor "
                                          "reported; its code is spent, so the digits "
                                          "are not comparable"), (
                f"a spent code was read as a disagreement: {rungs[0]['reason']!r}")
            return True
        return run()
    assert _run(body)


def test_a_vendor_denying_the_call_under_a_confirmation_is_kept_as_evidence(
        monkeypatch):
    """The rarest and the most valuable line for the claim against the vendor: this
    gateway's own code check confirmed the person saw the digits, and the vendor's
    report says the call was never connected. The rung still records ours — and the
    contradiction is written down rather than folded into a neutral reason."""
    def body():
        async def run():
            vid, _ = await _unresolved(code="1234")
            assert await queries.check_verification(
                vid, "app1", code="1234", max_attempts=3) == "confirmed"
            _answer(monkeypatch, call_status=ucaller.NOT_CONNECTED, code="1234")

            assert await flash_carrier.resolve_outstanding() == 1
            row = await queries.get_verification(vid, "app1")
            assert row["status"] == "confirmed", "a confirmed verification was re-ended"
            rungs = await queries.verification_rungs(vid)
            assert rungs[0]["outcome"] == ladder.CARRIED
            assert "not connected" in (rungs[0]["reason"] or ""), (
                f"the vendor's contradiction was folded away: {rungs[0]['reason']!r}")
            return True
        return run()
    assert _run(body)


# --- giving up rather than telling a story --------------------------------------------------

def test_a_vendor_that_still_will_not_say_leaves_the_rung_alone(monkeypatch):
    def body():
        async def run():
            vid, _ = await _unresolved()
            _answer(monkeypatch, call_status=ucaller.PENDING)

            assert await flash_carrier.resolve_outstanding() == 0
            rungs = await queries.verification_rungs(vid)
            assert rungs[0]["outcome"] == ladder.UNRESOLVED
            assert (await queries.get_verification(vid, "app1"))["status"] == "pending"
            return True
        return run()
    assert _run(body)


def test_a_rung_older_than_the_verifications_own_lifetime_stops_being_chased(monkeypatch):
    """The give-up is an age, and it lives in the query. Past the verification's lifetime
    the answer can change nothing a person sees, and chasing it is one request per sweep
    for ever against a vendor that rate-limits per IP."""
    def body():
        async def run():
            vid, rung_id = await _unresolved()
            db = await queries.get_db()
            await db.execute(
                "UPDATE verification_rungs SET started_at = datetime('now', '-2 hours') "
                " WHERE id = ?", (rung_id,))
            await db.commit()

            asked: list = []
            _answer(monkeypatch, call_status=ucaller.NOT_CONNECTED, asked=asked)
            assert await flash_carrier.resolve_outstanding() == 0
            assert asked == [], "an answer that can change nothing was paid a request for"
            return True
        return run()
    assert _run(body)


def test_a_blank_credential_asks_nobody_anything(monkeypatch):
    def body():
        async def run():
            await _unresolved()
            await store.set_many({"ucaller_key": ""})
            asked: list = []
            _answer(monkeypatch, call_status=ucaller.NOT_CONNECTED, asked=asked)
            assert await flash_carrier.resolve_outstanding() == 0
            assert asked == []
            return True
        return run()
    assert _run(body)


def test_a_vendor_that_raises_does_not_stop_the_sweep(monkeypatch):
    """This runs inside the pass that announces every other ending. A vendor's mood must
    not be able to leave an application untold how its verification ended."""
    def body():
        async def run():
            await _unresolved()

            async def boom(uid, *, bearer, timeout=10.0, client=None):
                raise RuntimeError("no route to host")
            monkeypatch.setattr(ucaller, "get_info", boom)

            assert await flash_carrier.resolve_outstanding() == 0
            return True
        return run()
    assert _run(body)


# --- it runs from the one pass that announces every ending -----------------------------------

def test_the_late_failure_is_announced_by_the_pass_that_announces_everything_else(
        monkeypatch):
    """Not a second announcer. An ending learned in a pass of its own is an ending
    somebody has to remember to announce — which is the defect the single announcer and
    its writer census (task 4.28) exist to make impossible."""
    pushed: list = []

    async def push(verification_id, app_id, status, *, method=None, reason=None):
        pushed.append((verification_id, status, reason))
        return True

    def body():
        async def run():
            vid, _ = await _unresolved()
            _answer(monkeypatch, call_status=ucaller.NOT_CONNECTED)
            monkeypatch.setattr(dispatch, "push_verification", push)

            announced = await dispatch.announce_verification_outcomes()
            assert announced == 1, "the ending this sweep created was announced by nobody"
            assert pushed and pushed[0][0] == vid and pushed[0][1] == "failed"
            assert "connect" in (pushed[0][2] or "")
            return True
        return run()
    assert _run(body)


def test_the_sweep_runs_before_the_expiry_it_would_otherwise_be_beaten_by(monkeypatch):
    """Ordering, and it is the whole point of the task. A verification whose window ran
    out in the same interval would otherwise be expired first and report the one thing
    that did not happen — the window did not run out on the person, the call failed."""
    def body():
        async def run():
            vid, _ = await _unresolved(ttl=-1)
            _answer(monkeypatch, call_status=ucaller.NOT_CONNECTED)
            monkeypatch.setattr(dispatch, "push_verification",
                                lambda *a, **kw: _true())

            await dispatch.announce_verification_outcomes()
            row = await queries.get_verification(vid, "app1")
            assert row["status"] == "failed", row["status"]
            assert "connect" in (row["reason"] or ""), (
                f"expired beat the vendor's answer: {row['reason']!r}")
            return True
        return run()
    assert _run(body)


async def _true():
    return True
