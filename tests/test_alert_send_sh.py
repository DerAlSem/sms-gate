"""The shared alert sender, driven end to end with a fake curl.

These cover a shell script rather than the app, and they exist because the defect they guard
against was not a logic error anybody could have spotted by reading: the relay was wired into
two of the three scripts that raise alerts, and the third — the one whose alert had actually
been lost — kept posting directly. Three copies of a delivery path is the bug. One copy with
tests is the fix, and the tests are what stop the next fix from reaching two thirds of it.
"""
import os
import subprocess
import time
from pathlib import Path

import pytest

SENDER = Path(__file__).resolve().parent.parent / "deploy" / "alert-send.sh"

RELAY = "http://relay.invalid"
DIRECT = "https://api.telegram.org"


@pytest.fixture
def env(tmp_path):
    """A fake curl on PATH, plus the paths the sender writes to."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "curl-calls"
    sent = tmp_path / "curl-args"
    fail_list = tmp_path / "curl-fails"
    fail_list.write_text("")

    # Records every invocation — the URL separately from the whole argument list, so a test can
    # count attempts without the payload, and read the payload when that is the point. Written
    # as a script rather than mocked, because what is under test is the shell's own control flow.
    (bin_dir / "curl").write_text(
        "#!/bin/sh\n"
        f'for a in "$@"; do case "$a" in http*) echo "$a" >> {calls} ;; esac; done\n'
        f'echo "$*" >> {sent}\n'
        f'while read -r bad; do [ -n "$bad" ] || continue\n'
        f'  for a in "$@"; do case "$a" in *"$bad"*) exit 7 ;; esac; done\n'
        f'done < {fail_list}\n'
        "exit 0\n"
    )
    (bin_dir / "curl").chmod(0o755)

    return {
        "bin": bin_dir,
        "calls": calls,
        "sent": sent,
        "fail_list": fail_list,
        "spool": tmp_path / "spool",
        "tmp": tmp_path,
    }


def run(env, *args, **overrides):
    e = dict(os.environ)
    e["PATH"] = f"{env['bin']}:{e['PATH']}"
    e.update(
        ALERT_BOT_TOKEN="TOK",
        ALERT_CHAT_ID="CHAT",
        ALERT_RELAY_BASE=RELAY,
        ALERT_ENV_FILE=str(env["tmp"] / "nonexistent.env"),
        ALERT_SPOOL=str(env["spool"]),
    )
    e.update({k: str(v) for k, v in overrides.items()})
    return subprocess.run(
        ["sh", str(SENDER), *args], env=e, capture_output=True, text=True, timeout=30
    )


def urls(env):
    if not env["calls"].exists():
        return []
    return [line for line in env["calls"].read_text().splitlines() if line]


def fail(env, *bases):
    env["fail_list"].write_text("".join(f"{b}\n" for b in bases))


def payloads(env):
    return env["sent"].read_text() if env["sent"].exists() else ""


def spool_lines(env):
    if not env["spool"].exists():
        return []
    return [line for line in env["spool"].read_text().splitlines() if line]


# --- the ordinary path ---


def test_relay_is_tried_before_the_direct_route(env):
    """Deliberate: the relay is the route that survives the outage the alert reports."""
    r = run(env, "hello")
    assert r.returncode == 0, r.stderr
    assert urls(env)[0].startswith(RELAY)
    assert len(urls(env)) == 1, "the direct route should not be touched once the relay works"


def test_direct_route_is_the_fallback(env):
    fail(env, "relay.invalid")
    r = run(env, "hello")
    assert r.returncode == 0, r.stderr
    assert [u.split("/bot")[0] for u in urls(env)] == [RELAY, DIRECT]


def test_no_credentials_is_not_an_error_and_spools_nothing(env):
    r = run(env, "hello", ALERT_BOT_TOKEN="", ALERT_CHAT_ID="")
    assert r.returncode == 0
    assert urls(env) == []
    assert spool_lines(env) == [], "there is nobody to deliver it to later either"


# --- when nothing can carry it ---


def test_message_is_retained_when_no_route_answers(env):
    fail(env, "relay.invalid", "api.telegram.org")
    r = run(env, "the wire is down")
    assert r.returncode != 0
    assert len(spool_lines(env)) == 1
    assert "the wire is down" in env["spool"].read_text()


def test_retained_message_is_delivered_once_a_route_returns(env):
    fail(env, "relay.invalid", "api.telegram.org")
    run(env, "raised during the outage")
    env["calls"].write_text("")
    env["sent"].write_text("")

    fail(env)  # a route comes back
    r = run(env, "raised after it ended")
    assert r.returncode == 0, r.stderr

    body = payloads(env)
    assert "raised during the outage" in body, "the held alert goes out"
    assert "raised after it ended" in body, "and so does the new one"
    assert body.index("raised during the outage") < body.index("raised after it ended"), (
        "in the order they were raised — reordering an incident is worse than delaying it"
    )
    assert spool_lines(env) == [], "the spool is emptied by a successful drain"


def test_a_late_message_says_how_late_it_is(env):
    """A delayed alert read without its age is read as current, and sends the operator after
    a fault that has already ended."""
    fail(env, "relay.invalid", "api.telegram.org")
    run(env, "began at the start of the outage")

    # Age the record rather than sleeping through it.
    line = env["spool"].read_text().rstrip("\n")
    stamp, rest = line.split(" ", 1)
    env["spool"].write_text(f"{int(stamp) - 3600} {rest}\n")

    fail(env)
    r = run(env, "--drain")
    assert r.returncode == 0, r.stderr
    assert "delayed 60 min" in payloads(env)
    assert "began at the start of the outage" in payloads(env)


def test_the_spool_is_bounded(env):
    """A spool that grows without limit is a second fault: on a long outage it becomes the
    thing that fills the disk the gateway writes its database to."""
    fail(env, "relay.invalid", "api.telegram.org")
    for i in range(8):
        run(env, f"message {i}", ALERT_SPOOL_MAX=3)
    lines = spool_lines(env)
    assert len(lines) == 3
    assert "message 7" in lines[-1], "the newest is kept"
    assert not any("message 0" in ln for ln in lines), "the oldest is dropped"


# --- draining on its own ---


def test_drain_with_an_empty_spool_sends_nothing(env):
    r = run(env, "--drain")
    assert r.returncode == 0
    assert urls(env) == [], "the every-30s heartbeat must cost nothing when there is nothing to do"


def test_drain_leaves_the_spool_alone_when_no_route_answers(env):
    fail(env, "relay.invalid", "api.telegram.org")
    run(env, "kept")
    r = run(env, "--drain")
    assert r.returncode != 0
    assert len(spool_lines(env)) == 1, "a failed drain must not discard what it could not send"


def test_multiline_text_survives_the_spool(env):
    """systemd's notifier sends a traceback; a spool that flattens it loses the alert's point."""
    fail(env, "relay.invalid", "api.telegram.org")
    run(env, "line one\nline two\nline three")
    assert len(spool_lines(env)) == 1, "one record, however many lines the message has"

    fail(env)
    r = run(env, "--drain")
    assert r.returncode == 0, r.stderr
    assert spool_lines(env) == []
