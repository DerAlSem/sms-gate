"""What the production unit must keep saying.

The unit file is not code, so nothing else here would notice it drifting — and two of its
lines are decisions rather than defaults. Both were made because of what a tunnel changed:
the application became reachable from further away than it had ever been, and nothing
recorded who was reaching it.
"""

from pathlib import Path

import pytest

UNIT = Path("deploy/sms-gate.service").read_text(encoding="utf-8")
EXEC = " ".join(
    line.strip().rstrip("\\").strip()
    for line in UNIT.splitlines()
    if line.startswith("ExecStart=") or line.strip().startswith("--")
)


def test_the_application_listens_only_on_the_loopback():
    """nginx is the only thing that should reach it, and it reaches it over the loopback.

    Bound wider, the application answered from the home network directly — and once a tunnel
    gave the host another address, from the far end of that too. A machine hosting eleven
    public sites could talk to it.
    """
    assert "--host 127.0.0.1" in EXEC
    assert "--host 0.0.0.0" not in EXEC


def test_the_callers_own_address_reaches_the_access_log():
    """With one public entrance and long-lived tokens behind it, a token used from somewhere
    it has never been used from must not look like an ordinary call. Without this the log
    records the proxy, which is the same address every time and says nothing."""
    assert "--proxy-headers" in EXEC


def test_the_forwarding_header_is_trusted_only_from_the_loopback():
    """Trusting it from anywhere would let a caller name its own address. The loopback is the
    only place it can arrive from once the bind above holds, which is what makes the trust
    safe rather than merely narrow."""
    assert "--forwarded-allow-ips=127.0.0.1" in EXEC


@pytest.mark.parametrize("setting", ["StartLimitIntervalSec", "StartLimitBurst", "OnFailure"])
def test_the_restart_bound_and_its_alert_stay_together(setting):
    """A restart bound without an alert is a service that gives up quietly; an alert without a
    bound never fires, because a unit that restarts for ever never enters failure."""
    assert setting in UNIT
