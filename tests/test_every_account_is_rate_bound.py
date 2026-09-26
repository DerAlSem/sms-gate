# tests/test_every_account_is_rate_bound.py
"""`messenger-delivery`: "Each sender account SHALL have a configured maximum number of
sends per rolling hour and per rolling day."

The setting holding those maxima was built and validated for shape. Nothing checked that the
accounts actually configured to send **have** one, and the two settings are separate rows: a
brand added without its bounds is an account with no ceiling, saved green.

The reader is what makes this a save-time refusal rather than a rung's responsibility.
Sections 3 and 4 will ask "what is this account's hourly bound?" and a missing answer has
only two readings — unbounded, which risks the account permanently on the second complaint,
or zero, which disables a working route in silence. The delta forbids exactly that pair of
readings for a rule that does not parse ("SHALL NOT be read as absent or as zero"); a rule
that is simply absent deserves no gentler treatment. Refused at the border, every later
reader may assume a bound exists.

It becomes worth its cost with the owner's decision of 14.09.2026 — a number per production
centre, so a brand map with many accounts, where the forgotten one is the likely mistake
rather than the exotic one.
"""
import asyncio
import json

import pytest

from app.db.connection import close_db, get_db, init_db
from app.db.migrate import run_migrations
from app.routing.routes import MAX_USER, TG_USER
from app.settings_store import store

A, B = "+79851600019", "+79851600020"


def _brands(*entries) -> str:
    """`entries` are (brand, number, {route: account}) triples."""
    brands = {
        brand: {route: {"account": account, "number": number, "intro": "Это наш сервисный аккаунт, вы запросили код."}
                for route, account in accounts.items()}
        for brand, number, accounts in entries
    }
    apps = {f"{brand}_app": {"brands": [brand], "default": brand} for brand in brands}
    return json.dumps({"brands": brands, "apps": apps})


def _limits(*accounts) -> str:
    return json.dumps({
        "accounts": {a: {"per_hour": 5, "per_day": 20} for a in accounts},
        "recipient_window_seconds": 600,
    })


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


def test_a_configured_account_with_no_bound_is_refused():
    def body():
        async def go():
            with pytest.raises(ValueError, match="sokol_tg"):
                await store.set_many({
                    "messenger_brands": _brands(("sokol", A, {TG_USER: "sokol_tg"})),
                    "messenger_limits": _limits("someone_else"),
                })
        return go()

    _run(body)


def test_the_account_is_named_whichever_setting_is_being_saved():
    """The relation spans two settings, so either side can be the one that breaks it.

    Bounds removed from a stored rule while the brand map still names the account is the
    same state as the account never having had them, reached through the other door.
    """
    def body():
        async def go():
            await store.set_many({
                "messenger_brands": _brands(("sokol", A, {TG_USER: "sokol_tg"})),
                "messenger_limits": _limits("sokol_tg"),
            })
            with pytest.raises(ValueError, match="sokol_tg"):
                await store.set_many({"messenger_limits": _limits("someone_else")})
        return go()

    _run(body)


def test_every_account_of_every_brand_is_checked():
    """Not only the first. With a number per production centre the map is long, and a check
    that stopped at the first brand would pass the one account nobody bounded."""
    def body():
        async def go():
            with pytest.raises(ValueError, match="gmplus_max"):
                await store.set_many({
                    "messenger_brands": _brands(
                        ("sokol", A, {TG_USER: "sokol_tg", MAX_USER: "sokol_max"}),
                        ("gmplus", B, {TG_USER: "gmplus_tg", MAX_USER: "gmplus_max"}),
                    ),
                    "messenger_limits": _limits("sokol_tg", "sokol_max", "gmplus_tg"),
                })
        return go()

    _run(body)


def test_a_fully_bounded_map_is_accepted():
    def body():
        async def go():
            await store.set_many({
                "messenger_brands": _brands(
                    ("sokol", A, {TG_USER: "sokol_tg", MAX_USER: "sokol_max"}),
                    ("gmplus", B, {TG_USER: "gmplus_tg", MAX_USER: "gmplus_max"}),
                ),
                "messenger_limits": _limits(
                    "sokol_tg", "sokol_max", "gmplus_tg", "gmplus_max"
                ),
            })
            return store.messenger_limits_parsed["accounts"]["gmplus_max"]["per_hour"]
        return go()

    assert _run(body) == 5


def test_a_gateway_with_no_brands_needs_no_bounds():
    """The shipped state, and the one this refusal must not touch: no brand map, no limit
    rule, every message carried by the modem. A refusal firing here would stop an operator
    from saving any routing setting on the day this deploys."""
    def body():
        async def go():
            await store.set_many({"messenger_brands": "", "messenger_limits": ""})
            # `route_deadlines` on the messengers branch; any routing setting will do here.
            await store.set_many({"operator_route_review_days": "30"})
            return True
        return go()

    assert _run(body)
