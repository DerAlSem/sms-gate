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
