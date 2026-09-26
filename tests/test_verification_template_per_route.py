# tests/test_verification_template_per_route.py
"""SG-34: a template per (application, rung), and the code spelled out in words.

The owner's decision of 26.09.2026: the words a person reads in Telegram and in an SMS
differ, and in an SMS the code goes as capitals, one word per digit — `ОДИН ДВА ТРИ
ЧЕТЫРЕ`. An entry with no `route` stands in for every rung of its application, so the
entries written before this change keep working.
"""

import asyncio
import json

import pytest

from app.db import queries
from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import store
from app.verification import ladder, placement, template
from app.verification.routes import SMS_OUT, TG_USER

PHONE = "+79851600019"


def _set(entries):
    return json.dumps(entries, ensure_ascii=False)


def _with(entries, body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        await queries.create_app("app1", "token-app1")
        await store.load()
        await store.set_many({template.KEY: _set(entries)})
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


# ---- the words ------------------------------------------------------------------

def test_the_code_is_spelled_as_capitals_one_word_per_digit():
    assert template.spell("1204") == "ОДИН ДВА НОЛЬ ЧЕТЫРЕ"
    assert template.spell("5678") == "ПЯТЬ ШЕСТЬ СЕМЬ ВОСЕМЬ"
    assert template.spell("9310") == "ДЕВЯТЬ ТРИ ОДИН НОЛЬ"


def test_code_words_is_composed_and_code_still_is():
    assert template.compose("Код GM+: {code_words}", "1234") == \
        "Код GM+: ОДИН ДВА ТРИ ЧЕТЫРЕ"
    assert template.compose("s-g: {code}", "1234") == "s-g: 1234"


# ---- which entry a rung reads ---------------------------------------------------

def test_the_entry_naming_the_rung_wins_and_the_bare_one_stands_in():
    entries = [
        {"app_id": "app1", "template": "общий {code}"},
        {"app_id": "app1", "route": SMS_OUT, "template": "смс {code_words}"},
    ]

    async def body():
        return (template.for_app("app1", SMS_OUT), template.for_app("app1", TG_USER),
                template.for_app("app1"))

    sms, tg, bare = _with(entries, body)
    assert sms == "смс {code_words}"
    assert tg == "общий {code}", "a rung with no entry of its own must fall back"
    assert bare == "общий {code}"


def test_without_a_bare_entry_another_rung_has_no_template():
    entries = [{"app_id": "app1", "route": TG_USER, "template": "тг {code}"}]

    async def body():
        return template.for_app("app1", SMS_OUT), template.for_app("app1", TG_USER)

    assert _with(entries, body) == (None, "тг {code}")


# ---- what the save refuses ------------------------------------------------------

def test_one_pair_named_twice_is_refused_but_a_route_beside_the_bare_one_is_not():
    template.validate(_set([
        {"app_id": "app1", "template": "a {code}"},
        {"app_id": "app1", "route": SMS_OUT, "template": "b {code_words}"},
        {"app_id": "app1", "route": TG_USER, "template": "c {code}"},
    ]))
    with pytest.raises(ValueError, match="already has a template"):
        template.validate(_set([
            {"app_id": "app1", "route": SMS_OUT, "template": "a {code}"},
            {"app_id": "app1", "route": " sms_out ", "template": "b {code}"},
        ]))


@pytest.mark.parametrize("route", ["flash_call", "tg_gateway", "pigeon"])
def test_a_route_that_carries_no_words_of_ours_is_refused(route):
    with pytest.raises(ValueError, match="carries no words of ours"):
        template.validate(_set([{"app_id": "app1", "route": route,
                                 "template": "x {code}"}]))


def test_the_code_as_digits_and_as_words_together_is_refused():
    with pytest.raises(ValueError, match="appears 2 times"):
        template.validate(_set([{"app_id": "app1",
                                 "template": "{code} ({code_words})"}]))


def test_a_pasted_route_is_stored_as_it_will_be_read():
    stored = json.loads(template.normalize(
        _set([{"app_id": " app1 ", "route": " sms_out ", "template": "x {code}"},
              {"app_id": "app1", "route": "", "template": "y {code}"}])))
    assert stored[0]["route"] == "sms_out"
    assert "route" not in stored[1]


# ---- the rungs write their own words --------------------------------------------

class _Modem:
    def __init__(self):
        self.queued = []

    async def enqueue(self, message_id, phone, text, app_id=""):
        self.queued.append(text)


def test_the_modem_rung_sends_its_own_template_with_the_code_in_words():
    entries = [
        {"app_id": "app1", "route": TG_USER, "template": "тг {code}"},
        {"app_id": "app1", "route": SMS_OUT, "template": "Код GM+: {code_words}"},
    ]
    modem = _Modem()

    async def body():
        vid = await queries.create_verification("app1", PHONE, code="1204",
                                                ttl_seconds=300)
        rung_id = await queries.record_verification_rung(
            vid, route=SMS_OUT, outcome=ladder.ATTEMPTING)
        carriers = placement.carriers_for(vid, app_id="app1", modem=modem,
                                          operator="МегаФон")
        attempt = await carriers[SMS_OUT](PHONE, seconds_left=5.0, rung_id=rung_id)
        db = await get_db()
        async with db.execute("SELECT text FROM messages") as cur:
            texts = [r["text"] for r in await cur.fetchall()]
        return attempt, texts

    attempt, texts = _with(entries, body)
    assert attempt.outcome == ladder.CARRIED, attempt.reason
    assert texts == ["Код GM+: ОДИН ДВА НОЛЬ ЧЕТЫРЕ"]
    assert modem.queued == texts
