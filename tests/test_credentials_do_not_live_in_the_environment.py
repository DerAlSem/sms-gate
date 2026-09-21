"""Task 4.49 — a vendor credential placed in `.env` after the first run is read by nobody.

The requirement says `.env` is not where such a value lives, and calls that "a fact about
the code rather than a preference". A fact about the code is exactly what is asserted here,
and it has two halves that fail differently.

The first half is precedence, and it is the half a reader expects: `seed_from_env()` copies
an environment variable into `settings` only for a key with no row yet, so a credential put
into `.env` afterwards loses to the row that is already there. Asserted at the value the
code feeds **directly** — the `Authorization` header that leaves for the vendor — rather
than at `store.tg_gateway_token`, because what the requirement forbids is the environment's
value reaching the vendor, and an attribute agreeing with the settings row while something
downstream re-read the environment would satisfy a weaker guard.

The second half is the one precedence cannot hold. "The gateway SHALL NOT read a vendor
credential from the environment at send time" is a claim about **every** line in `app/`,
not about `seed_from_env`, and a guard that drove the seeder alone would stay green on the
day somebody adds `os.getenv("TG_GATEWAY_TOKEN")` to the carrier as a convenience. A census
of readers is never complete when it is taken by eye; this one is taken off the syntax tree.

🔴 **There are two environment surfaces and the obvious census sees only one.** Measured
while writing this file: a census of `os.environ` in `app/` reports a single reader and a
clean bill, while `app/config.py` reads `.env` on every start through
`BaseSettings(env_file=".env")` — no `os.environ` anywhere in it, because pydantic does the
reading. A credential declared there is the whole defect in its purest form: read from
`.env` at every start, invisible to the settings page, and unchangeable without a restart.
So the boundary is asserted twice, once per surface.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import httpx

from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations
from app.settings_store import seed_from_env, store
from app.verification import tg_gateway as tg

KEY = "tg_gateway_token"
ENV_NAME = KEY.upper()

APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _run(body):
    async def go():
        await init_db(":memory:")
        await run_migrations()
        return await body()

    try:
        return asyncio.run(go())
    finally:
        asyncio.run(close_db())


def _bearer_seen(token: str) -> str:
    """The `Authorization` header of a real send, made with `token`.

    The send rather than the ability check, because the send is the call that carries the
    code: if the wrong credential travels anywhere, this is the call where it costs a
    person their login rather than a request that answers nothing.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {
            "request_id": "1", "phone_number": "79990000001",
            "request_cost": 0.01, "delivery_status": {"status": "sent"},
        }})

    async def send():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await tg.send_verification_message(
                "+79990000001", code="1234", ttl=300, token=token, client=client)
        finally:
            await client.aclose()

    asyncio.run(send())
    return seen[0].headers["Authorization"]


# --- precedence ------------------------------------------------------------------------

def test_an_env_credential_does_not_displace_the_row_that_is_already_there(monkeypatch):
    """The scenario, driven the way it actually happens: the gateway has been configured
    through the console, somebody later writes the key into `.env`, and the process is
    restarted — which is when `seed_from_env` runs and would be the only chance for the
    environment to win.
    """
    monkeypatch.setenv(ENV_NAME, "env-token-please-do-not-use-me")

    async def body():
        await seed_from_env()       # first start
        await store.load()
        await store.set_many({KEY: "the-token-the-operator-entered"})
        # The restart: seeding runs again over a database that already has the row.
        await seed_from_env()
        await store.load()
        return getattr(store, KEY)

    stored = _run(body)
    assert stored == "the-token-the-operator-entered"
    assert _bearer_seen(stored) == "Bearer the-token-the-operator-entered", (
        "the value that reached the vendor is not the one the operator configured"
    )


def test_a_row_that_exists_is_not_rewritten_even_when_it_is_blank(monkeypatch):
    """Blank is a configured state rather than an absent one, and it is the state every
    estate ships in: `tg_gateway_token` defaults to empty on purpose, so that the rung is
    never offered rather than failing at the vendor after the gates have been spent. The
    first start writes that blank row, so from the second start onwards the environment
    has already lost — even on a gateway nobody has configured.

    This is the case the precedence rule is hardest on and the one it must get right. An
    implementation that treated blank as "no value yet" would let `.env` take over exactly
    the estates whose operator has made no decision, and who are therefore least likely to
    notice one made for them.
    """
    async def body():
        await seed_from_env()       # first start, no environment: the row is written blank
        monkeypatch.setenv(ENV_NAME, "env-token-arriving-later")
        await seed_from_env()       # second start, the key now in `.env`
        await store.load()
        return getattr(store, KEY)

    assert _run(body) == ""


def test_the_environment_is_used_for_a_key_that_has_no_row_yet(monkeypatch):
    """The control without which both guards above are empty.

    A `seed_from_env` that ignored the environment entirely — or read the wrong variable
    name — would satisfy them perfectly, and the one-time seed the requirement describes
    would be gone with nothing saying so. This is the placement the requirement calls
    sanctioned: before the first run, copied once, and living in `settings` afterwards.
    """
    monkeypatch.setenv(ENV_NAME, "the-token-from-the-env-file")

    async def body():
        await seed_from_env()       # a virgin database: no row for this key
        await store.load()
        return getattr(store, KEY)

    seeded = _run(body)
    assert seeded == "the-token-from-the-env-file"
    assert _bearer_seen(seeded) == "Bearer the-token-from-the-env-file"


# --- the boundary: who may read the environment at all ---------------------------------

# The one function allowed to read the environment, and the reason the rule is a census
# rather than a review: every other reader is a send-time read of a credential, which is
# what the requirement forbids in the same breath as it permits this one.
_SANCTIONED_ENV_READER = "seed_from_env"


def _environment_readers() -> dict[str, list[str]]:
    """Every function in `app/` that reads the process environment, by name.

    Taken off the syntax tree rather than by grepping the text, for the reason the
    verification writers' census is: a read spelled `environ.get`, or reached through a
    module alias, is the same read and a pattern over source lines sees only the spelling
    it was written against.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text())
        enclosing = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for sub in ast.walk(node):
                    enclosing.setdefault(sub, node.name)
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
                name = node.attr
            elif isinstance(node, ast.Name) and node.id in ("environ", "getenv"):
                name = node.id
            if name is None:
                continue
            where = enclosing.get(node, "<module level>")
            found.setdefault(where, []).append(
                f"{path.relative_to(APP_DIR.parent)}:{node.lineno}")
    return found


def test_the_environment_is_read_in_one_place_and_it_is_the_seeder():
    """"The gateway SHALL NOT read a vendor credential from the environment at send time"
    is a claim about every line in `app/`, and this is the only form in which it can be
    made: one sanctioned reader, everything else an offender by construction.

    Written as a whitelist of *one* rather than as a search for credential-shaped variable
    names, because the name a convenience read is given is the author's choice and the
    rule is not. A second reader arriving here is not necessarily a leak — but it is
    necessarily a decision, and this is what makes somebody take it.
    """
    readers = _environment_readers()
    offenders = {k: v for k, v in readers.items() if k != _SANCTIONED_ENV_READER}
    assert offenders == {}, (
        f"these read the process environment, and only {_SANCTIONED_ENV_READER!r} may: "
        f"{offenders}. A credential read here is one the operator cannot change without "
        f"a restart and cannot see on the settings page — and one `.env` can override "
        f"behind their back, which is exactly what this capability forbids"
    )
    assert _SANCTIONED_ENV_READER in readers, (
        "the seeder no longer reads the environment at all — the one-time seed the "
        "requirement sanctions is gone, and the census above now passes vacuously"
    )


def test_the_census_above_can_actually_fail():
    """Its own bite, inline, because a guard over source structure passes loudly against a
    file it has stopped reading correctly.

    Both spellings are exercised: the attribute access the code uses today, and the
    `from os import getenv` form a convenience read is at least as likely to take.
    """
    import tempfile

    source = (
        "from os import getenv\n"
        "import os\n"
        "def a_convenience_read():\n"
        "    return getenv('TG_GATEWAY_TOKEN')\n"
        "def another_one():\n"
        "    return os.environ['TG_GATEWAY_TOKEN']\n"
    )
    with tempfile.TemporaryDirectory() as d:
        probe = Path(d) / "probe.py"
        probe.write_text(source)
        tree = ast.parse(probe.read_text())
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "getenv" in names and "environ" in names, (
        "the census no longer recognises an environment read in either spelling"
    )


# The `.env`-backed settings object, and what it is allowed to hold. `admin_password` is
# there deliberately and the comment beside it says why: it is the console's own door, and
# keeping it in the database would let a bad settings write lock the operator out of the
# page they would fix it from. It is not a vendor's credential, and the distinction is the
# whole rule — a vendor credential belongs in `settings`, where it can be changed without a
# restart and reported as configured without being shown.
_CREDENTIAL_SUFFIXES = ("_token", "_key", "_secret", "_password")
_SANCTIONED_ENV_FILE_CREDENTIALS = {"admin_password"}


def test_no_vendor_credential_is_declared_in_the_env_backed_settings_object():
    """The second surface, which the `os.environ` census above cannot see.

    `app/config.py` declares `env_file=".env"` and pydantic reads it on every start, so a
    field added there is read from `.env` for the life of the process — precisely the
    placement the requirement calls "a fact about the code rather than a preference", and
    reached without a single `os.environ` for a census to find.

    A whitelist rather than a ban, because one credential-shaped field is there on purpose
    and removing it would lock an operator out of the console. What this makes impossible
    is adding the *next* one without saying so.
    """
    from app.config import Settings

    declared = {name for name in Settings.model_fields
                if name.endswith(_CREDENTIAL_SUFFIXES)}
    unsanctioned = declared - _SANCTIONED_ENV_FILE_CREDENTIALS
    assert unsanctioned == set(), (
        f"these credentials are declared in the `.env`-backed settings object and are "
        f"therefore read from `.env` on every start: {sorted(unsanctioned)}. A vendor "
        f"credential belongs in the `settings` table, where the console can report it as "
        f"configured without rendering it and an operator can change it without a restart"
    )
    assert _SANCTIONED_ENV_FILE_CREDENTIALS <= declared, (
        f"{sorted(_SANCTIONED_ENV_FILE_CREDENTIALS - declared)} is no longer declared in "
        f"app/config.py — if the console's own password moved into `settings`, this "
        f"whitelist is now wrong rather than satisfied, and a bad settings write can lock "
        f"the operator out of the page they would fix it from"
    )
