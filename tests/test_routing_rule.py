"""The routing rule: which way out an operator's traffic takes, as data.

Task 4.16 and its guards. The rule is a typed setting rather than a branch, and the
order inside an entry is the thing being configured — which paid way out is tried first
is a money decision that changes as vendors' prices and reachability change.

Three of these tests fail on the implementation everyone writes first:

- matching by `==` or by SQLite's `upper()` passes the first spelling and silently drops
  the other, and production holds both (`МЕГАФОН` for 120 numbers, `МегаФон` for 57 on
  08.09.2026);
- an order held in the code satisfies "the rule says Telegram first" while defeating it —
  the entry is rewritten and nothing changes;
- a stored rule that cannot be parsed, read as an empty rule, sends the whole of an
  operator's traffic back to the route that is rejecting it, with no line in the log.
"""

import asyncio

import pytest

from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import rule
from app.verification.routes import FLASH_CALL, SMS_OUT, TG_GATEWAY


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await store.load()
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


def _entries(*pairs):
    import json
    return json.dumps([{"operator": op, "routes": routes} for op, routes in pairs],
                      ensure_ascii=False)


# --- what the rule ships with ---------------------------------------------------------

def test_the_shipped_rule_routes_megafon_to_telegram_first_and_everything_else_to_the_modem():
    """The initial content is data, and it is the owner's decision of 18.09.2026."""
    async def body():
        assert rule.route_for("МегаФон") == [TG_GATEWAY, FLASH_CALL]
        assert rule.route_for("МТС") == [SMS_OUT]

    _run(body)


# --- the spelling the data actually holds ---------------------------------------------

@pytest.mark.parametrize("stored", ["МЕГАФОН", "МегаФон", "  МегаФон  ", "мегафон"])
def test_every_stored_spelling_of_one_operator_takes_the_same_route(stored):
    """`upper()` and `==` each pass one spelling and drop the other, and the drop is
    silent. Production held both spellings of МегаФон on 08.09.2026."""
    async def body():
        assert rule.route_for(stored) == [TG_GATEWAY, FLASH_CALL]

    _run(body)


def test_an_operator_named_with_whitespace_in_the_rule_still_matches():
    async def body():
        await store.set_many({"operator_routes": _entries(
            ("  Билайн  ", [SMS_OUT]), ("*", [SMS_OUT]), ("?", [SMS_OUT]))})
        assert rule.route_for("билайн") == [SMS_OUT]

    _run(body)


# --- the order is data, not code ------------------------------------------------------

def test_rewriting_the_entry_reverses_which_rung_is_tried_first_with_no_restart():
    """Task 4.32's half that belongs to the rule. An implementation that tries Telegram
    first because the code says so satisfies the letter of 4.16 and defeats it."""
    async def body():
        assert rule.route_for("МегаФон") == [TG_GATEWAY, FLASH_CALL]
        await store.set_many({"operator_routes": _entries(
            ("МегаФон", [FLASH_CALL, TG_GATEWAY]), ("*", [SMS_OUT]), ("?", [SMS_OUT]))})
        assert rule.route_for("МегаФон") == [FLASH_CALL, TG_GATEWAY]

    _run(body)


def test_a_second_operator_added_while_running_takes_the_new_route():
    async def body():
        await store.set_many({"operator_routes": _entries(
            ("МегаФон", [TG_GATEWAY, FLASH_CALL]), ("Билайн", [FLASH_CALL]),
            ("*", [SMS_OUT]), ("?", [SMS_OUT]))})
        assert rule.route_for("Билайн") == [FLASH_CALL]

    _run(body)


# --- the two entries that are not operators -------------------------------------------

def test_an_operator_with_no_entry_takes_the_default_entry_of_the_same_rule():
    """A default compiled into the sending path is the hard-coding the rule forbids,
    spelled differently."""
    async def body():
        await store.set_many({"operator_routes": _entries(
            ("МегаФон", [TG_GATEWAY]), ("*", [FLASH_CALL]), ("?", [SMS_OUT]))})
        assert rule.route_for("Т2 Мобайл") == [FLASH_CALL]

    _run(body)


def test_an_unresolved_operator_takes_its_own_entry_and_not_the_default():
    """Task 4.4. The numbers most likely to lack an operator row are the ones never
    messaged before, and a first-time recipient is exactly who a code is usually for —
    so "unknown" is a case the owner configures, not the default arrived at by accident.
    """
    async def body():
        await store.set_many({"operator_routes": _entries(
            ("*", [FLASH_CALL]), ("?", [SMS_OUT]))})
        assert rule.route_for(None) == [SMS_OUT]
        assert rule.route_for("") == [SMS_OUT]

    _run(body)


def test_the_unknown_operator_entry_can_be_set_to_a_refusal():
    """An unknown operator on a network being refused is a coin toss with a person's
    login on it, so refusing SHALL be expressible."""
    async def body():
        await store.set_many({"operator_routes": _entries(
            ("*", [SMS_OUT]), ("?", [rule.REFUSE]))})
        assert rule.route_for(None) == [rule.REFUSE]
        assert rule.refuses(rule.route_for(None))

    _run(body)


# --- what is refused at save time -----------------------------------------------------

def test_an_entry_naming_an_unknown_route_is_refused_at_save_time():
    """Task 4.24. Refused at save rather than discovered at send: at send time the
    discovery is a person standing at a barrier."""
    async def body():
        before = rule.route_for("МегаФон")
        with pytest.raises(ValueError, match="grimm"):
            await store.set_many({"operator_routes": _entries(("МегаФон", ["grimm"]))})
        assert rule.route_for("МегаФон") == before

    _run(body)


def test_an_entry_naming_the_same_route_twice_is_refused():
    async def body():
        with pytest.raises(ValueError):
            await store.set_many({"operator_routes": _entries(
                ("МегаФон", [TG_GATEWAY, TG_GATEWAY]))})

    _run(body)


def test_an_empty_route_list_is_refused():
    async def body():
        with pytest.raises(ValueError):
            await store.set_many({"operator_routes": _entries(("МегаФон", []))})

    _run(body)


def test_two_entries_for_one_operator_are_refused_however_they_are_spelled():
    """Otherwise which of the two wins is decided by list order, invisibly."""
    async def body():
        with pytest.raises(ValueError):
            await store.set_many({"operator_routes": _entries(
                ("МегаФон", [TG_GATEWAY]), ("МЕГАФОН", [FLASH_CALL]))})

    _run(body)


def test_a_refusal_may_not_share_an_entry_with_a_route():
    """A ladder that continues past a refusal is not a refusal."""
    async def body():
        with pytest.raises(ValueError):
            await store.set_many({"operator_routes": _entries(
                ("МегаФон", [rule.REFUSE, FLASH_CALL]))})

    _run(body)


def test_an_entry_keyed_on_the_originating_application_is_refused():
    """The rule SHALL NOT be keyed on the application: that is the same hard-coding
    moved into configuration, routing by who is asking rather than by what is reachable.
    """
    import json

    async def body():
        raw = json.dumps([{"operator": "МегаФон", "app_id": "gmp_app",
                           "routes": [TG_GATEWAY]}], ensure_ascii=False)
        with pytest.raises(ValueError, match="app_id"):
            await store.set_many({"operator_routes": raw})

    _run(body)


def test_the_stored_rule_is_stripped_on_write_as_well_as_on_read():
    async def body():
        await store.set_many({"operator_routes": _entries(
            (" МегаФон ", [" tg_gateway ", "flash_call"]), ("*", [SMS_OUT]),
            ("?", [SMS_OUT]))})
        assert '" МегаФон "' not in store.operator_routes
        assert rule.route_for("МегаФон") == [TG_GATEWAY, FLASH_CALL]

    _run(body)


# --- the rule that cannot be read -----------------------------------------------------

def test_a_stored_rule_that_cannot_be_parsed_is_not_read_as_an_empty_rule():
    """Read as empty, a broken rule sends the whole of an operator's traffic back to the
    route that is rejecting it — the one failure of this capability that is both total
    and silent. It raises instead, and the caller refuses loudly."""
    async def body():
        # Written past the setting's own validation, as a hand-edited row would be.
        # Inserted rather than updated: an in-memory database has no row for this key
        # until something seeds one, and an UPDATE that matched nothing would leave the
        # shipped default in force and this test green for the wrong reason.
        from app.db.connection import get_db
        db = await get_db()
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("operator_routes", "{not json at all"))
        await db.commit()
        await store.load()
        assert store.get("operator_routes") == "{not json at all"
        with pytest.raises(rule.UnreadableRule):
            rule.route_for("МегаФон")

    _run(body)


def test_a_rule_with_no_default_entry_refuses_rather_than_guessing():
    """A parseable rule that cannot answer for this operator is a configuration gap, and
    the gap is loud. Guessing the modem here is the silent failover the capability
    refuses."""
    async def body():
        await store.set_many({"operator_routes": _entries(("МегаФон", [TG_GATEWAY]))})
        assert rule.refuses(rule.route_for("Билайн"))

    _run(body)
