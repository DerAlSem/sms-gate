import asyncio
import os
import sys

# Make `import app.*` work when pytest is run from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.db import connection


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
