"""Run the notifier's shell smoke test as part of the suite.

It existed as a standalone script and therefore ran when somebody remembered, which is to say
it did not run — it went on passing for months while the thing it covers drifted. A test
outside the suite is documentation with a shebang.
"""
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "test_notify_telegram.sh"


def test_notify_telegram_smoke():
    r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
