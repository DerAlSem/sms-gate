# tests/test_ucaller_credentials.py
"""Where uCaller's credential lives, and what a bearer for it is made of.

The vendor takes the same two values — a per-service secret key and a service id — in
three interchangeable ways, and the header form joins them with a dot:
`Authorization: Bearer <key>.<service_id>` (reference read 22.09.2026, captured in
`openspec/changes/route-sends-by-operator/captures/ucaller-reference-2026-09-22.md`).

The spec used to call that "a single bearer string" and would have had the owner paste the
joined value. Two halves are stored instead, and the reason is a failure mode rather than
tidiness: a bearer whose dot is missing or doubled is *indistinguishable from configured*
on the settings page, and announces itself as a `401` on the first live call — which on
this rung is a call somebody paid for. Two rows can each be pasted verbatim, and a missing
half reads as "not set".
"""

import asyncio

import pytest

from app.db.connection import init_db, close_db
from app.db.migrate import run_migrations
from app.settings_store import SPEC_BY_KEY, store
from app.verification import ucaller


@pytest.fixture
def db():
    async def up():
        await init_db(":memory:")
        await run_migrations()
        await store.load()
    asyncio.run(up())
    yield
    asyncio.run(close_db())


def test_both_halves_have_a_home_in_settings():
    """The owner holds a key with nowhere to put it until these two rows exist."""
    for key in ("ucaller_key", "ucaller_service_id"):
        assert key in SPEC_BY_KEY, f"{key}: uCaller's credential has no home in settings"
        assert SPEC_BY_KEY[key].default == "", (
            f"{key}: ships with a value, and an unconfigured estate would look configured")


def test_the_secret_half_is_declared_secret():
    """`tests/test_vendor_credentials.py` enumerates credentials by the shape of the key
    and so covers this one by itself; asserted here too because that guard's reach is the
    thing being relied on, and a rename of the half would quietly leave both silent."""
    assert SPEC_BY_KEY["ucaller_key"].is_secret is True


def test_the_bearer_joins_the_two_halves_with_a_dot():
    """The vendor's header form, verbatim from the reference."""
    assert ucaller.bearer("SECRET", "1692") == "SECRET.1692"


def test_either_half_missing_is_no_credential_at_all():
    """Written from the opposite side: nothing is a credential unless both halves say so.

    Whitespace counts as missing because a row holding a stray newline is the state a
    paste leaves behind, and a bearer built from it is refused by the vendor as a wrong
    key rather than reported as an unconfigured rung."""
    assert ucaller.bearer("SECRET", "") is None
    assert ucaller.bearer("", "1692") is None
    assert ucaller.bearer("", "") is None
    assert ucaller.bearer(None, None) is None
    assert ucaller.bearer("SECRET", "   ") is None
    assert ucaller.bearer("  \n", "1692") is None
    # the positive control, without which every line above is satisfied by returning None
    assert ucaller.bearer("SECRET", "1692") == "SECRET.1692"


def test_pasted_whitespace_never_reaches_the_vendor():
    assert ucaller.bearer("  SECRET\n", "\t1692 ") == "SECRET.1692"


def test_the_configured_bearer_is_read_from_settings(db):
    """The wiring, not the arithmetic: these two rows are what the adapter will read."""
    assert ucaller.configured_bearer() is None, "blank settings are not a credential"

    asyncio.run(store.set_many({"ucaller_key": "SECRET", "ucaller_service_id": "1692"}))
    assert ucaller.configured_bearer() == "SECRET.1692"

    asyncio.run(store.set_many({"ucaller_service_id": ""}))
    assert ucaller.configured_bearer() is None, (
        "half a credential is offered to the vendor as a whole one")
