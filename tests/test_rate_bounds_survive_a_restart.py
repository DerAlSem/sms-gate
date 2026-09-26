"""Task 3.4 — the allowance is still spent after the service restarts.

**Restarted, not simulated.** The obvious form of this test — close the connection,
reopen it, ask again — proves nothing about the thing the delta is afraid of. A window
held in a module-level dict survives `close_db()` exactly as well as it survives anything
else inside one interpreter, so that test stays green against the implementation it
exists to forbid. Only a second process starts with the memory actually empty.

The delta spells out why it matters here rather than leaving it to taste: this process
exits **by design** — the modem's hard recovery rung calls `os._exit(1)`, and every push
to `master` restarts the service — so an in-memory hour would hand the account a fresh
allowance several times inside the same hour, which is how an account gets limited.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: One claim, printed as `granted=True` or `granted=False`. The bound is one an hour, so
#: the first run consumes the account's whole hourly allowance.
SCRIPT = """
import asyncio, sys
from app.db import queries
from app.db.connection import close_db, init_db
from app.db.migrate import run_migrations

async def main(path, message_id):
    await init_db(path)
    await run_migrations()
    granted = await queries.claim_rate_allowance(
        message_id=int(message_id), route="tg_user", account="@sokol_tech",
        phone="+79851600019", per_hour=1, per_day=10, recipient_window_seconds=0,
    )
    await close_db()
    print("granted=%s" % granted)

asyncio.run(main(sys.argv[1], sys.argv[2]))
"""


def _claim_in_a_fresh_process(db_path: Path, message_id: int) -> str:
    done = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(db_path), str(message_id)],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip().splitlines()[-1]


def test_an_allowance_spent_before_a_restart_is_still_spent_after_one(tmp_path):
    db = tmp_path / "gateway.db"

    assert _claim_in_a_fresh_process(db, 1) == "granted=True"
    assert _claim_in_a_fresh_process(db, 2) == "granted=False", (
        "the restart handed the account a second hourly allowance inside the same hour"
    )
