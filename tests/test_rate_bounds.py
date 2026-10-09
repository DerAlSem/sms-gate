"""Task 3.4 — the rule that decides, above the claim that records.

Two refusals here are the whole point of the layer, and neither may read as "no bound":

- an account the limit rule does not mention has **no** allowance, not an unlimited one.
  The save-time rule already refuses that configuration; this is what happens when one
  reaches the reader anyway, and it must not be the reading that costs the account;
- a rule that does not parse raises an alert and refuses. The delta names both wrong
  readings — absent and zero — and `parse_limits` answers a malformed rule with an empty
  mapping, which is exactly the first of them. Reusing the save-time validator here is
  what keeps the two sides from drifting apart.
"""

import asyncio
import logging

from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.routing.rate import DurableBounds
from app.routing.routes import TG_USER
from app.settings_store import store

PHONE = "+79851600019"
ACCOUNT = "@sokol_tech"
GOOD = ('{"accounts": {"@sokol_tech": {"per_hour": 2, "per_day": 5}, '
        '"@gmplus_tech": {"per_hour": 2, "per_day": 5}}, '
        '"recipient_window_seconds": 600}')


def _with_settings(raw: str, coro):
    """Write the limit rule **past** `set_many` and run `coro`.

    Deliberately not through the setting API: the malformed case is refused there, and a
    reader tested only against values the writer permits is a reader whose refusal has
    never run.
    """
    async def run():
        await init_db(":memory:")
        await run_migrations()
        db = await get_db()
        await db.execute(
            "INSERT INTO settings (key, value) VALUES ('messenger_limits', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (raw,),
        )
        await db.commit()
        await store.load()
        return await coro()

    try:
        return asyncio.run(run())
    finally:
        asyncio.run(close_db())


def _claim(message_id=1, account=ACCOUNT, phone=PHONE):
    return DurableBounds().claim(
        message_id=message_id, route=TG_USER, account=account, phone=phone,
    )


def test_an_account_the_rule_names_is_granted_its_first_send():
    claim = _with_settings(GOOD, lambda: _claim())
    assert claim.granted is True


def test_the_hourly_bound_from_the_rule_is_the_one_enforced():
    async def body():
        return [(await _claim(i)).granted for i in (1, 2, 3)]

    assert _with_settings(GOOD, body) == [True, True, False]


def test_an_account_with_no_bound_in_the_rule_may_not_send():
    claim = _with_settings(GOOD, lambda: _claim(account="@nobody_configured"))
    assert claim.granted is False
    assert "@nobody_configured" in claim.reason


def test_an_empty_limit_rule_is_no_allowance_rather_than_no_bound():
    claim = _with_settings("", lambda: _claim())
    assert claim.granted is False


def test_a_rule_that_does_not_parse_refuses_the_send(caplog):
    claim = _with_settings("{not json at all", lambda: _claim())
    assert claim.granted is False
    assert "parse" in claim.reason


def test_a_rule_that_does_not_parse_raises_an_alert(caplog):
    """`logger.error` is the alert: the operator channel is a handler on the root logger
    at ERROR. A refusal nobody hears about is a route that has silently stopped."""
    with caplog.at_level(logging.ERROR):
        _with_settings("{not json at all", lambda: _claim())
    assert [r for r in caplog.records if r.levelno >= logging.ERROR], caplog.text


def test_a_rule_whose_bounds_are_zero_is_refused_rather_than_read_as_zero(caplog):
    """The second wrong reading the delta names. A zero bound is not a working limit of
    none; it is a rule the save-time validator refuses, and the reader says so too."""
    raw = '{"accounts": {"@sokol_tech": {"per_hour": 0, "per_day": 0}}}'
    with caplog.at_level(logging.ERROR):
        claim = _with_settings(raw, lambda: _claim())
    assert claim.granted is False
    assert [r for r in caplog.records if r.levelno >= logging.ERROR], caplog.text


def test_settling_a_claim_as_reaching_nobody_frees_the_person():
    """The second brand's account may address the number the first one found nobody at.

    Without the settlement the window would hold it, and the layer would be enforcing a
    bound on *asking* where the delta writes one on *receiving*.
    """
    async def body():
        blocked = await _claim(1, account="@sokol_tech")
        held = await _claim(2, account="@gmplus_tech")
        await DurableBounds().settle(
            message_id=1, route=TG_USER, may_have_reached=False,
        )
        freed = await _claim(3, account="@gmplus_tech")
        return blocked.granted, held.granted, freed.granted

    assert _with_settings(GOOD, body) == (True, False, True)
