import asyncio
import inspect
import os
import sys

# Make `import app.*` work when pytest is run from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.db import connection


class FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def fake_webhook_client(monkeypatch, handler):
    """Patch the shared webhook transport's httpx so `handler(url, json, headers)`
    decides the outcome. Returns the list of (url, payload, headers) posted.

    Both dispatch directions POST through `app.modem.webhook`, so this is where the
    patch belongs — patching a caller module's `httpx` would miss it.
    """
    import app.modem.webhook as webhook

    posted = []

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            posted.append((url, json, headers))
            result = handler(url, json, headers)
            # an async handler lets a test make one POST slow, to prove another is
            # not queued behind it
            if inspect.isawaitable(result):
                result = await result
            return result

    monkeypatch.setattr(webhook.httpx, "AsyncClient", FakeClient)
    return posted


@pytest.fixture(autouse=True)
def _no_real_operator_lookup(monkeypatch):
    """The operator lookup never reaches the network from a test.

    🔴 **This became necessary the day the sender started resolving operators**
    (task 4.4a): before it, `record_operator` was awaited only at the API door, which
    most tests bypass. Now every send of a number with no `number_operators` row would
    make a real HTTP call — slow on a machine with no route to voxlink, and worse than
    slow on one that has it, where the answer decides which way out the message takes
    and the test's outcome depends on somebody else's database.

    Patched at the transport rather than over `voxlink.lookup`, deliberately:
    `tests/test_voxlink.py` exercises `lookup` itself and passes its own client, so it
    never constructs this class and stays untouched; `tests/test_record_operator.py`
    replaces `voxlink.lookup` inside the test body, which runs after this fixture and
    therefore wins. What everything else gets is `lookup`'s own fail-open path with a
    deterministic answer: unreachable, so nobody is resolved.

    ⚠️ **The patch replaces the name `httpx` inside `app.lookup.voxlink`, never an
    attribute of the `httpx` module.** A module object is shared by every importer, and
    setting `AsyncClient` on it took the Gateway adapter's transport down with it —
    measured, in nine red tests, rather than reasoned about.

    A test that needs an operator writes the row (`queries.save_number_operator`) or
    replaces `record_operator` where it is called from. Neither is an accident — the
    lookup being arranged is the thing such a test is about.
    """
    import types

    import httpx

    import app.lookup.voxlink as voxlink

    class _NoNetwork:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            raise httpx.ConnectError("the test suite does not reach the network")

        async def aclose(self):
            return None

    # Everything `voxlink` reads off `httpx` — the client it builds and the error class
    # it fails open on — and nothing else.
    shim = types.SimpleNamespace(AsyncClient=_NoNetwork, HTTPError=httpx.HTTPError)
    monkeypatch.setattr(voxlink, "httpx", shim)


@pytest.fixture(autouse=True)
def _close_db_after_each_test():
    """Safety net: close any DB connection a test left open.

    Tests open an in-memory DB via init_db(); aiosqlite runs the connection on a
    background thread. A leaked (never-closed) connection leaves that thread alive,
    which can block interpreter exit and hang the whole run (seen in CI). Each test
    should still close its own connection in-loop; this is belt-and-suspenders.
    """
    yield
    if connection._db is not None:
        try:
            asyncio.run(connection.close_db())
        except Exception:
            pass
