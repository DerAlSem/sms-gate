#!/usr/bin/env python3
"""Sign a session file in, once, by hand — the step `capture_telegram.py` refuses to do.

The capture harness will not create a session, on purpose: `SQLiteStorage` mints a
database when the file is absent, so a mistyped path would quietly produce a fresh
unauthorised session and then report "not signed in" — a lie about the file the owner
believes in. Creating one is therefore a separate, deliberate act, and this is it.

**This is an operator tool, not the production login.** Task 3.2 owns the login that
lives behind the route interface; this exists because a session file has to be minted by
a human at least once per host, and will be again on the production host (task 3.5).

It lives in `deploy/` rather than beside the capture harness that first needed it, moved
there on 22.09.2026: `messenger-delivery` requires a sender session to be **replaceable**,
and the only procedure that replaces one is this file. Left in `changes/.../captures/` it
would have been carried into `changes/archive/` the day the change is reaped — still in
the repository, but filed as history, which is not where an operator looks for the tool
that gets a locked-out brand account writing again.

Three things it was built to get right, each paid for on 22.09.2026:

1. **One connection.** A split version that asked for the code, disconnected, and signed
   in on a fresh connection was refused with `PHONE_CODE_EXPIRED`, whose own text says
   why: "use the code on the same connection". Telegram binds the code to the live auth
   session. That mistake costs a code, and codes are rate-limited.
2. **The code does not arrive by SMS.** It came as `SentCodeType.APP`, inside the
   account's own Telegram app, with `next_type=None` — no SMS fallback at all. An
   account that is not already open somewhere cannot be signed in again.
3. **Secrets arrive as files, never through the operator.** With no terminal attached,
   the code and (if two-step verification is on) the cloud password are polled for from
   files while the connection is held open, so the owner can write them by his own hand.
   The api credentials come from the environment for the same reason: this pair cannot be
   reissued while my.telegram.org is unreachable, which makes disclosure permanent.

    export TG_API_ID=... TG_API_HASH=...      # from ~/.config/sms-gate/tg.env
    export TG_SESSION=/secure/path/gmplus.session
    export TG_LOGIN_PHONE=+7...               # the account's own number
    export TG_CODE_FILE=/tmp/code.txt TG_PASSWORD_FILE=/tmp/password.txt
    python deploy/tg-sign-in.py               # then write the code into TG_CODE_FILE
"""
import asyncio, os, sys, time
from pathlib import Path

from pyrogram import Client, errors

SESSION = Path(os.environ["TG_SESSION"])
PHONE = os.environ["TG_LOGIN_PHONE"]
CODE_FILE = Path(os.environ["TG_CODE_FILE"])
PASS_FILE = Path(os.environ["TG_PASSWORD_FILE"])
WAIT = int(os.environ.get("TG_WAIT_SECONDS", "900"))


def say(*a):
    print(*a, flush=True)


async def await_file(path: Path, what: str) -> str:
    """Poll, holding the connection open. Absent or empty both mean 'not yet'."""
    path.unlink(missing_ok=True)
    say(f"WAITING FOR {what}: write it into {path}")
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                path.unlink(missing_ok=True)
                return value
        await asyncio.sleep(2)
    sys.exit(f"gave up waiting {WAIT}s for {what}")


async def main() -> None:
    SESSION.parent.mkdir(parents=True, exist_ok=True)
    client = Client(name=SESSION.stem, workdir=SESSION.parent,
                    api_id=int(os.environ["TG_API_ID"]),
                    api_hash=os.environ["TG_API_HASH"],
                    sleep_threshold=0)
    if await client.connect():
        me = await client.get_me()
        await client.disconnect()
        sys.exit(f"already signed in as id={me.id} @{me.username}")

    sent = await client.send_code(PHONE)
    say(f"code sent to {PHONE[:4]}…{PHONE[-2:]} via {sent.type}; next_type={sent.next_type}")

    result = None
    for attempt in range(1, 4):
        code = (await await_file(CODE_FILE, f"LOGIN CODE (attempt {attempt}/3)")
                ).replace(" ", "").replace("-", "")
        try:
            result = await client.sign_in(PHONE, sent.phone_code_hash, code)
            break
        except errors.SessionPasswordNeeded:
            # The password is retried like the code is, and for the same reason. Exiting
            # on the first refusal used to cost a fresh login code for every typo — the
            # code has already been spent by the time this branch is reached, and it is
            # the rate-limited half. Paid for on 22.09.2026, on the rehearsal that task
            # 3.5 exists to make routine.
            say("two-step verification is ON — the cloud password is needed")
            for pw_attempt in range(1, 4):
                password = await await_file(
                    PASS_FILE, f"CLOUD PASSWORD (attempt {pw_attempt}/3)"
                )
                try:
                    result = await client.check_password(password)
                    break
                except errors.PasswordHashInvalid:
                    say(f"that password is refused ({len(password)} characters read) — "
                        "the connection is still open, write it again")
                    continue
                except Exception as exc:  # noqa: BLE001
                    await client.disconnect()
                    sys.exit(f"password refused — {type(exc).__name__}: {exc}")
            else:
                await client.disconnect()
                sys.exit("three refused passwords — stopping rather than burning a code")
            break
        except errors.PhoneCodeInvalid:
            say("that code is wrong — read it again, same connection is still open")
            continue
        except Exception as exc:  # noqa: BLE001
            await client.disconnect()
            sys.exit(f"{type(exc).__name__}: {exc}")
    else:
        await client.disconnect()
        sys.exit("three wrong codes — stopping rather than burning another send")

    if not hasattr(result, "id"):
        await client.disconnect()
        sys.exit(f"sign_in returned {result!r} — no account to sign in to")
    client.me = result
    await client.disconnect()
    os.chmod(SESSION, 0o600)
    say(f"SIGNED IN as id={result.id} @{result.username}; session saved: {SESSION}")


asyncio.run(main())
