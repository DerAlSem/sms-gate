"""Task 3.2 — the Telegram user account behind the route interface.

Nothing of kurigram's — no type, no exception, no session object — leaves this module.
That containment is what makes a change of client one file, and it is the answer to the
fork being small: kurigram is the one Python MTProto client still being pushed to, and
the day it stops, this module is the whole of the work.

**Three things the live capture of 3.1 bought, each of which is here rather than in a
comment somewhere.** The capture is
`openspec/changes/reach-people-in-messengers/captures/kurigram-2.2.26.json`.

1. **The library's own give-up is 160 s.** Measured, not guessed: `seconds_to_answer =
   160.03`, exactly `MAX_RETRIES(10) × (WAIT_TIMEOUT(15) + RETRY_DELAY(1))`. The rung's
   deadline is 8 s, so in production our own timer always fires first and the library's
   `TimeoutError` is a thing this gateway will *never* see. Two consequences, and both
   are load-bearing: the library is handed an explicit retry budget that ends inside our
   window, and a call that outlives it is **cancelled outright**. A wrapper that merely
   awaits with a deadline leaves the library retrying for another ~152 s per severed
   call, against an account whose second limiting is permanent.
2. **`sleep_threshold=0`.** `Session.invoke` swallows a `FloodWait` at or below the
   threshold — 10 s by default — sleeps it off and retries. Our whole rung is 8 s, so at
   the default the rung is spent inside the library and reports nothing at all.
3. **A miss is not "this person has no Telegram".** `PhoneNotOccupied` came back
   identically for a number with no account and for a number that has one but hides from
   lookup by phone — the same id, code and formatted message. No key separates them, `ID`
   included, so nothing here claims to.

**Resolution adds no contact, and therefore none is undone.** `messenger-delivery` allows
a contact entry only "where resolution is impossible without it"; the capture showed
`contacts.ResolvePhone` resolves without one, while `contacts.ImportContacts` answers an
absent number and a hidden one with the same empty `users` — it buys nothing and leaves an
entry on the account to be removed. So the undo named by task 3.2 is discharged by never
creating the thing. MAX is the route that will need the import; Telegram does not.

**Where a failure happens decides whether the ladder stops.** A failure while *resolving*
cannot have delivered anything — no send was invoked — so the route is `unavailable` and
the message drops to the modem. A failure while *sending* may have left the frame, so it
is `indeterminate` and the ladder stops dead. Getting this backwards is the difference
between a Telegram outage costing us the messenger route and a Telegram outage costing
people their codes.

**This route is wired — task 3.6 — and only where its credentials are.**
`dispatch._live_registry()` builds one instance of this class per process, from
`TG_API_ID`, `TG_API_HASH` and `TG_SESSION_DIR`, and leaves the rung out of the registry
entirely when any of the three is missing. One instance is not an optimisation: two
`Client` objects over one session file answer `database is locked`. Leaving it out is not
tidiness either — the ladder charges the account for a rung it reaches, so a route wired
without credentials would spend a real allowance to say `unavailable`.

The mapping from a named Telegram failure to an outcome is `tg_errors`; what it cannot
name falls to the floor below, which is the delta's own rule.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from dataclasses import replace
from enum import Enum
from pathlib import Path
from typing import Callable

from app.routing import tg_errors
from app.routing.route import Attempt, Outcome
from app.routing.routes import TG_USER

logger = logging.getLogger(__name__)

#: Telegram's own ceiling for the text of one message.
MAX_TEXT_LENGTH = 4096

#: What the library may do on its own before it has to answer us.
#:
#: One attempt, no delay. Retrying inside the library is retrying where neither the ladder
#: nor the ledger can see it, on a window too short to hold a second attempt anyway — and
#: this gateway already has a retry that is visible and durable: the next rung, and after
#: it the modem path's own budget.
VENDOR_RETRIES = 1
VENDOR_RETRY_DELAY = 0

#: The shipped `route_deadlines` entry for this rung, repeated here only as the fallback
#: for a store that has not been read yet. The setting is the source of truth.
DEFAULT_DEADLINE_SECONDS = 8.0

#: How much of the rung's deadline is left to the ladder rather than spent on the vendor.
#:
#: The ladder applies the deadline from outside with `asyncio.wait_for`, and what it
#: concludes when its own timer fires is `indeterminate` — correct, because from out there
#: a hung rung may have sent. Inside, we know which step we were on. The margin is what
#: buys that knowledge: our timer fires first, so the classification is ours to make.
DEFAULT_MARGIN_SECONDS = 1.5

#: The floor on what any single vendor call is given, so that a rung already near its
#: deadline still asks a real question instead of a zero-second one.
MIN_CALL_SECONDS = 0.2


class _Step(Enum):
    """Which call we were in when it went wrong. It decides the outcome."""
    CONNECT = "connect"
    RESOLVE = "resolve"
    SEND = "send"


class _Unavailable(Exception):
    """This route cannot be used right now, and the reason is the message.

    Private on purpose: it never crosses `offer`, which returns an `Attempt`.
    """


# --------------------------------------------------------------------------- cancellation

#: Calls we cancelled and did not wait for. The event loop keeps only a weak reference to
#: a task, so without this a cancelled call could be collected before it has unwound.
_abandoned: set[asyncio.Task] = set()


def _abandon(task: asyncio.Task) -> None:
    """Cancel a call and walk away from it.

    The walking away is the point. `asyncio.wait_for` cancels and then *awaits* the
    cancellation, so a library that takes its time dying holds the rung past its own
    deadline and past the ladder's — which is the shape the capture measured at 160 s.
    Here the cancel is issued and the rung returns; whatever the task does afterwards is
    logged, not waited on.
    """
    if task.done():
        # Retrieve whatever it ended with, so a finished call does not surface later as
        # "Task exception was never retrieved" from a rung that reported cleanly.
        with contextlib.suppress(BaseException):
            task.exception()
        return
    task.cancel()
    _abandoned.add(task)
    task.add_done_callback(_forget)


def _forget(task: asyncio.Task) -> None:
    _abandoned.discard(task)
    if task.cancelled():
        return
    with contextlib.suppress(BaseException):
        failure = task.exception()
        if failure is not None:
            logger.warning("an abandoned tg_user call ended in %r", failure)


async def _bounded(awaitable, seconds: float):
    """Await something for at most `seconds`, then cancel it and stop caring.

    Raises `TimeoutError` when the time is spent — which since Python 3.11 is the same
    class as `asyncio.TimeoutError`, and is also what the library itself raises when it
    gives up. They are indistinguishable by type, and here that costs nothing: both mean
    "no answer inside our window", and the step we were on decides the rest.
    """
    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.wait_for(asyncio.shield(task), seconds)
    finally:
        _abandon(task)


# -------------------------------------------------------------------------------- the route


class TelegramUserRoute:
    """The `tg_user` rung. One instance serves every brand; one client per account.

    `account` arrives on each call and is never looked up here — task 2.5. A route that
    resolved its own account would hold the whole map, and holding the map is what makes
    sending under another brand expressible at all.
    """

    name = TG_USER

    def __init__(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_dir: str,
        client_factory: Callable[..., object] | None = None,
        margin_seconds: float = DEFAULT_MARGIN_SECONDS,
    ) -> None:
        self._api_id = int(api_id or 0)
        self._api_hash = api_hash or ""
        self._session_dir = session_dir or ""
        self._factory = client_factory or _kurigram_client
        self._margin = float(margin_seconds)
        self._clients: dict[str, object] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ the interface

    def carries(self, message_class: str) -> bool:
        """Every class, because which classes go to Telegram is `route_order`.

        Said once and in one place. A second statement here would be the weaker of the
        two — the ladder never offers a route the configured order left out — and two
        statements of one invariant mean nobody can tell which one is load-bearing. The
        first rollout puts this rung in `code_long` alone, and that is a row in the
        admin settings, not a branch in this file.
        """
        return True

    async def offer(
        self,
        *,
        message_id: int,
        phone: str,
        text: str,
        message_class: str,
        brand: str,
        account: str,
    ) -> Attempt:
        if not self.configured():
            return Attempt(
                Outcome.UNAVAILABLE,
                reason="tg_user is not configured: tg_api_id, tg_api_hash and "
                       "tg_session_dir must all be set",
            )
        if len(text) > MAX_TEXT_LENGTH:
            # Ahead of resolution, because resolution *is* the disclosure: a number sent
            # to Telegram for a message that cannot be delivered is a disclosure spent
            # for nothing.
            return Attempt(
                Outcome.UNAVAILABLE,
                reason=f"the text is {len(text)} characters and Telegram accepts "
                       f"{MAX_TEXT_LENGTH}",
            )

        ends_at = asyncio.get_running_loop().time() + self._budget()

        try:
            client = await self._client_for(account, ends_at)
        except _Unavailable as refusal:
            return Attempt(Outcome.UNAVAILABLE, reason=str(refusal))
        except Exception as exc:
            return self._outcome_for(exc, step=_Step.CONNECT, account=account)

        raw = _raw()

        try:
            resolved = await self._invoke(
                client, raw.functions.contacts.ResolvePhone(phone=phone), ends_at)
        except Exception as exc:
            self._drop_if_broken(account, exc)
            return self._outcome_for(exc, step=_Step.RESOLVE, account=account)

        peer = _peer_of(resolved)
        if peer is None:
            # Never "this person has no Telegram". The capture proved the wire gives one
            # answer for an absent account and for a hidden one, and an operator reading
            # this line is entitled to a statement we can actually support.
            return Attempt(
                Outcome.MISS,
                reason="the number did not resolve to a Telegram account — it has none, "
                       "or it is hidden from lookup by phone; the wire does not say which",
            )

        try:
            await self._invoke(
                client,
                raw.functions.messages.SendMessage(
                    peer=peer,
                    message=text,
                    random_id=_random_id(account, message_id),
                    no_webpage=True,
                ),
                ends_at,
            )
        except Exception as exc:
            self._drop_if_broken(account, exc)
            return self._outcome_for(exc, step=_Step.SEND, account=account)

        return Attempt(Outcome.ACCEPTED, reason=f"telegram accepted it from {account}")

    # ------------------------------------------------------------------- classification

    def _outcome_for(self, exc: BaseException, *, step: _Step, account: str) -> Attempt:
        """What a failure means, by what the library said and then by where it happened.

        The vendor table of task 3.3 gets first say, because a named error knows more than
        a step does — `FloodWait` is a positive statement that nothing was sent, whatever
        call it interrupted. Where it says nothing, the step decides, and the delta's own
        floor applies: what we cannot name is indeterminate.
        """
        named = tg_errors.outcome_for(exc)
        if named is not None:
            # The account is carried in the reason as well as in its own ledger column:
            # with two brands configured, "this account is limited" names neither of them,
            # and the line an operator reads is the one that has to be unambiguous.
            #
            # `replace` rather than a fresh `Attempt`: the only thing being changed here
            # is the wording. Rebuilding the attempt field by field drops whatever the
            # classifier decided and did not get restated — `limits_account` today, and
            # silently, since a dropped `False` is indistinguishable from a route whose
            # account is fine. That is the whole alert of task 5.5 going quiet in the one
            # place that knows the account is dead.
            return replace(named, reason=f"{named.reason} — account {account}")

        described = _describe(exc)
        if step is not _Step.SEND:
            # Nothing can have been delivered by a connect or a lookup — no send was
            # invoked. That is a stronger statement than the "positive statement that
            # nothing was sent" the delta asks of the library, and it is what keeps a
            # Telegram outage costing us this route rather than costing people their
            # codes: `unavailable` lets the ladder reach the modem, `indeterminate`
            # stops it dead.
            return Attempt(
                Outcome.UNAVAILABLE,
                reason=f"{step.value} failed before anything was sent from {account}: "
                       f"{described}",
            )
        return Attempt(
            Outcome.INDETERMINATE,
            reason=f"the send from {account} may already have happened: {described}",
        )

    # ------------------------------------------------------------------------ the client

    def configured(self) -> bool:
        """All three of the environment-borne values are present.

        Public because `dispatch._live_registry` asks it before wiring the rung at all.
        A registry that restated the rule would be the weaker of two statements of one
        invariant, and the day a fourth value is needed here only one of them would
        learn about it.
        """
        return bool(self._api_id and self._api_hash and self._session_dir)

    def _budget(self) -> float:
        """Our own window: the rung's configured deadline, less the ladder's margin."""
        deadline = DEFAULT_DEADLINE_SECONDS
        try:
            from app.settings_store import store

            deadline = float(store.route_deadlines_parsed.get(TG_USER, deadline))
        except Exception:                      # a store not yet initialised, in a test
            pass
        return max(MIN_CALL_SECONDS, deadline - self._margin)

    def _session_path(self, account: str) -> Path:
        stem = (account or "").strip().lstrip("@")
        if not stem or "/" in stem or stem in (".", ".."):
            raise _Unavailable(f"{account!r} is not a usable account name")
        return Path(self._session_dir) / f"{stem}.session"

    async def _client_for(self, account: str, ends_at: float):
        lock = self._locks.setdefault(account, asyncio.Lock())
        async with lock:
            client = self._clients.get(account)
            if client is not None:
                return client

            session = self._session_path(account)
            if not session.is_file():
                # Refused rather than opened. `SQLiteStorage` creates the database when
                # the file is absent, so a mistyped path would not fail — it would mint a
                # fresh unauthorised session beside the typo and then report "not signed
                # in", which is a lie about the file the operator believes in.
                raise _Unavailable(
                    f"no session file for account {account!r} at {session} — a session "
                    "is signed in once, by hand, and kept"
                )

            client = self._factory(
                name=session.stem,
                workdir=str(session.parent),
                api_id=self._api_id,
                api_hash=self._api_hash,
                # Every flood-wait must reach us as an error; see the module docstring.
                sleep_threshold=0,
            )

            try:
                signed_in = await _bounded(client.connect(), self._left(ends_at))
            except Exception:
                await _shut(client)
                raise
            if not signed_in:
                await _shut(client)
                raise _Unavailable(
                    f"the session for account {account!r} is not signed in — the login "
                    "code arrives in that account's own Telegram app, so no unattended "
                    "run can do it"
                )

            try:
                me = await _bounded(client.get_me(), self._left(ends_at))
            except Exception:
                await _shut(client)
                raise
            if not _is_account(me, account):
                # Task 2.5 at the wire. The brand-to-account map already keeps a rung from
                # being handed another brand's account; this catches the other direction,
                # a session file holding an account nobody configured, which no amount of
                # configuration can see.
                await _shut(client)
                raise _Unavailable(
                    f"the session at {session} is signed in as "
                    f"{_name_of(me)}, not as {account!r} — refusing to send under an "
                    "account this message's brand does not own"
                )

            self._clients[account] = client
            return client

    def _drop_if_broken(self, account: str, exc: BaseException) -> None:
        """A transport-level failure means the connection is gone; the next offer rebuilds.

        `TimeoutError` is an `OSError`, and so is every connection error the library lets
        through, so this one test covers both the severed transport and our own expired
        budget — after which the socket is in no state to be reused anyway.
        """
        if not isinstance(exc, OSError):
            return
        client = self._clients.pop(account, None)
        if client is not None:
            _abandon(asyncio.ensure_future(_shut(client)))

    async def _invoke(self, client, query, ends_at: float):
        left = self._left(ends_at)
        return await _bounded(
            client.invoke(
                query,
                retries=VENDOR_RETRIES,
                timeout=left,
                retry_delay=VENDOR_RETRY_DELAY,
            ),
            left,
        )

    def _left(self, ends_at: float) -> float:
        return max(MIN_CALL_SECONDS, ends_at - asyncio.get_running_loop().time())


# ------------------------------------------------------------------------------- helpers


def _peer_of(resolved):
    """The `InputPeerUser` for the first resolved user, or None.

    Built explicitly rather than by handing the phone number to the high-level
    `send_message`: that call answers from the session file's peer cache first, so the
    send would depend on a side effect of the resolve, and a stale entry would decide who
    receives a code.
    """
    raw = _raw()
    for user in getattr(resolved, "users", None) or ():
        user_id = getattr(user, "id", None)
        access_hash = getattr(user, "access_hash", None)
        if user_id is not None and access_hash is not None:
            return raw.types.InputPeerUser(user_id=user_id, access_hash=access_hash)
    return None


def _random_id(account: str, message_id: int) -> int:
    """Telegram's deduplication key, derived rather than drawn.

    Nothing in this gateway resends a message a messenger rung may already have carried —
    that is what `indeterminate` is for — but a door that costs three lines to close is
    closed: the same message offered twice from the same account cannot arrive twice.
    """
    digest = hashlib.blake2b(f"{account}:{message_id}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def _is_account(me, account: str) -> bool:
    wanted = (account or "").strip().lstrip("@").casefold()
    known = {
        str(getattr(me, "id", "") or "").casefold(),
        str(getattr(me, "username", "") or "").casefold(),
    }
    return bool(wanted) and wanted in known


def _name_of(me) -> str:
    username = getattr(me, "username", None)
    return f"{getattr(me, 'id', '?')}" + (f" (@{username})" if username else "")


def _describe(exc: BaseException) -> str:
    """The vendor's failure as evidence, never as an object.

    An operator reads this to tell "our account is dead" from "these recipients have no
    messenger account", so the class name earns its place. The identity stays here.
    """
    return f"{type(exc).__name__}: {exc}"[:300]


async def _shut(client) -> None:
    with contextlib.suppress(Exception):
        await client.disconnect()


def _raw():
    """kurigram's raw layer, imported on use.

    Imported here rather than at module scope, and that matters more since 3.6 than it
    did before: `dispatch` now imports this module unconditionally, at import, on every
    host. A module-level `from pyrogram import raw` would therefore turn a missing
    kurigram into a service that does not start — on a host whose route order names no
    messenger rung and needs the library for nothing.
    """
    try:
        from pyrogram import raw
    except ImportError as exc:                 # pragma: no cover — declared in requirements
        raise _Unavailable(f"the kurigram client is not installed: {exc}") from exc
    return raw


def _kurigram_client(**kwargs):
    """The real client. kurigram installs under the import name `pyrogram`: it is the live
    fork, not the archived original."""
    try:
        from pyrogram import Client
    except ImportError as exc:                 # pragma: no cover — declared in requirements
        raise _Unavailable(f"the kurigram client is not installed: {exc}") from exc
    return Client(**kwargs)
