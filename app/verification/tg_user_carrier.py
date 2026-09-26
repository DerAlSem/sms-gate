"""The Telegram user-account rung, as the verification ladder calls it.

`app/routing/tg_user.py` knows the wire and reports four outcomes; this knows what the
verification ladder does with each of them, and which account an application may write as.
It is the slice of the messengers branch that the owner's decision of 25.09.2026 brought to
master ahead of that branch's own ladder: after the flash call was withdrawn (SG-31), a GM+
code goes as a message from GM+'s own Telegram account before it falls to SMS.

Five decisions live here, and each of them is a norm rather than a detail.

**The account is the application's, read from the brand map and never chosen here.** The
verification rule is keyed on the operator, not on the application, so "only GM+ writes
from @gmplus_support" cannot be said by the rule at all. It is said by `messenger_brands` —
application → brand → one account per messenger — the same map, read by the same
functions, that the messengers branch reads, so the invariant that the Sokol account cannot
write to GM+ recipients is one statement across both ladders. An application with no
account there is `INCAPABLE`: a statement about the application, and the reason the rung
is quiet for HRM rather than alerting on every one of its verifications.

**Everything that can refuse without Telegram refuses before Telegram.** Resolving a number
discloses it to the vendor before any verdict exists, and the claim spends the account's
allowance whatever the vendor answers. So no template, a withheld number and an
introduction that is owed but not recorded are all decided first, and none of them touch
either the vendor or the allowance.

**The ids in the messenger ledgers are this verification's id, negated.** `rung_ledger`,
`messenger_rate_claims` (whose key is `(message_id, route)`) and Telegram's own `random_id`
are all derived from a message id, and verification ids overlap message ids from the first
row of each table. Shared, a verification would find its claim already taken by a message
of the same number — `ON CONFLICT DO NOTHING`, read as a limit — or Telegram would
deduplicate one against the other and deliver neither. Negated, the two spaces cannot meet
and the tables keep the shape the messengers branch gives them, so that branch merges
without touching them.

**`unavailable` is a refusal of us, and it is loud and names the account.** A dead
session, a ban, a flood wait or our own bound: the person may well be reachable, we are
not. By the owner's decision of 25.09.2026 this does **not** withhold the modem the way a
paid vendor's refusal does (`ladder.walk`) — one support account somebody forgot to renew
must not be able to silence every GM+ code.

**`indeterminate` advances, and that is the opposite of the messengers branch on
purpose.** There the ladder stops dead on a send that may have left, so that nobody gets
two codes. Here a verification carries one code whichever rung carries it, so a second copy
of it is harmless, while a code that never arrived is a person locked out — the owner's
decision of 25.09.2026, point В.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.config import settings
from app.db import queries
from app.routing import brands, introduction
from app.routing.rate import DurableBounds
from app.routing.route import Attempt as RouteAttempt
from app.routing.route import Outcome
from app.routing.tg_user import TelegramUserRoute
from app.verification import ladder, template
from app.verification.routes import TG_USER

logger = logging.getLogger(__name__)

# What the wire's outcome means to the verification ladder. `ACCEPTED` is here like the
# rest: unlike the paid rung, nothing is spent between the verdict and the send.
_OUTCOME = {
    Outcome.ACCEPTED: ladder.CARRIED,
    Outcome.MISS: ladder.DECLINED,
    Outcome.UNAVAILABLE: ladder.REFUSED,
    Outcome.INDETERMINATE: ladder.UNANSWERED,
}

# Not a class the verification ladder has: the route interface asks for one because the
# messengers branch routes by it. `TelegramUserRoute.carries` answers yes to every class.
_MESSAGE_CLASS = "verification"


# ------------------------------------------------------------------------------ the route

#: The one route object this process owns, and the credentials it was built from.
#:
#: **One per process, and that is the mechanism rather than a cache.** A kurigram session
#: file is a SQLite database, and a second `Client` opened over it answers `database is
#: locked` — found by the live run of task 3.2 on the messengers branch and by no test. A
#: carrier built per verification would therefore lose the rung from the second
#: verification onwards and report it as `unavailable`, which reads as Telegram's answer
#: rather than ours. The key exists for tests that set credentials; in production they are
#: read once at import and cannot change.
_wired: tuple[tuple, TelegramUserRoute | None] | None = None


def route() -> TelegramUserRoute | None:
    """The process's route, or None when the three environment values are not all set."""
    global _wired
    key = (settings.tg_api_id, settings.tg_api_hash, settings.tg_session_dir)
    if _wired is None or _wired[0] != key:
        built = TelegramUserRoute(api_id=settings.tg_api_id, api_hash=settings.tg_api_hash,
                                  session_dir=settings.tg_session_dir)
        _wired = (key, built if built.configured() else None)
    return _wired[1]


def _brand_and_account(app_id: str) -> tuple[str, str | None]:
    """The brand this application sends under and its one Telegram account, if any.

    Read per call, because the map is a setting and a change must not need a restart.
    """
    from app.settings_store import store

    cfg = store.messenger_brands_parsed
    try:
        brand = brands.resolve(app_id, None, cfg)
    except brands.BrandRefused:
        return "", None
    return brand, brands.account_for(brand, TG_USER, cfg)


def account_for_app(app_id: str) -> str | None:
    """The Telegram account this application may write as, or None."""
    return _brand_and_account(app_id)[1]


def _session_file(account: str) -> Path:
    return Path(settings.tg_session_dir) / f"{account.strip().lstrip('@')}.session"


def unwired_reason(app_id: str) -> str | None:
    """Why this application's rung cannot be wired, or None when it can.

    `""` — the empty string — when the application simply has no account: that is not a
    configuration gap but the ordinary state of every application that is not GM+, and the
    caller says nothing about it. Anything else names what is missing, for the one line an
    operator reads when they configured the rung and nothing happens.

    The session file is asked for here rather than left to the route, and that is 3.6's
    invariant rather than tidiness: the route would answer `unavailable` for a missing
    file, but only after the ladder had claimed the account's allowance for it.
    """
    account = account_for_app(app_id)
    if not account:
        return ""
    if route() is None:
        return (f"{app_id} writes as {account}, and tg_api_id, tg_api_hash and "
                f"tg_session_dir are not all set")
    session = _session_file(account)
    if not session.is_file():
        return f"{app_id} writes as {account}, and there is no session file at {session}"
    return None


def wired(app_id: str) -> bool:
    """Whether this application's Telegram rung can be put on the ladder at all."""
    return unwired_reason(app_id) is None


# ---------------------------------------------------------------------------- the carrier


def ledger_id(verification_id: int) -> int:
    """The id this verification goes by in the messenger ledgers. See the module docstring."""
    return -verification_id


def carrier(verification_id: int, *, app_id: str):
    """A carrier the ladder can call for this verification.

    The code is read from the store at the moment of sending rather than handed in, so that
    a verification which ended while the ladder walked cannot have its code sent afterwards.
    """
    async def carry(phone: str, *, seconds_left: float, rung_id: int) -> ladder.Attempt:
        brand, account = _brand_and_account(app_id)
        rung = route()
        if not account or rung is None:
            # The assembly checked this; the map is a setting and may have changed since.
            return _incapable(f"{app_id} has no Telegram account to write from")

        wording = template.for_app(app_id)
        if not wording:
            return _incapable(f"no verification template is available for {app_id}, and "
                              f"this gateway composes no wording of its own")

        if await queries.is_withheld_from_messengers(phone):
            return _incapable("the number is withheld from messenger lookup")

        from app.settings_store import store
        written = await queries.accounts_that_have_written_to(phone)
        intro = introduction.decide(
            recorded=brands.introduction_for(brand, TG_USER, store.messenger_brands_parsed)
            or "",
            already_written=(TG_USER, account) in written,
        )
        if intro.unrecorded:
            # A personal account writing a code to a stranger without saying who it is gets
            # reported, and the second report costs the account permanently.
            logger.warning("verification %d: %s owes this number an introduction and "
                           "brand %r records none for tg_user; the rung is not offered",
                           verification_id, account, brand)
            return _incapable(f"brand {brand!r} records no introduction for tg_user, and "
                              f"{account} has never written to this number")

        lid = ledger_id(verification_id)
        bounds = DurableBounds()
        claim = await bounds.claim(message_id=lid, route=TG_USER, account=account,
                                   phone=phone)
        if not claim.granted:
            _alert(account, claim.reason)
            return ladder.Attempt(outcome=ladder.REFUSED, route=TG_USER,
                                  reason=f"{claim.reason} — account {account}")

        row = await queries.get_verification(verification_id, app_id)
        code = row["code"] if row is not None else None
        if not code:
            await bounds.settle(message_id=lid, route=TG_USER, may_have_reached=False)
            logger.warning("verification %d ended before the Telegram rung could compose "
                           "its code; nothing was sent", verification_id)
            return ladder.Attempt(
                outcome=ladder.FAILED, route=TG_USER,
                reason="the verification ended before its code could be sent")

        text = introduction.compose(intro, template.compose(wording, code))
        attempt = await _offer(rung, seconds_left=seconds_left, message_id=lid,
                               phone=phone, text=text, brand=brand, account=account)

        await bounds.settle(
            message_id=lid, route=TG_USER,
            may_have_reached=attempt.outcome in (Outcome.ACCEPTED, Outcome.INDETERMINATE))
        await _record(lid, phone=phone, brand=brand, account=account, attempt=attempt)

        if attempt.outcome is Outcome.UNAVAILABLE:
            _alert(account, attempt.reason)
        return ladder.Attempt(outcome=_OUTCOME[attempt.outcome], route=TG_USER,
                              reason=attempt.reason)

    return carry


async def _offer(rung, *, seconds_left: float, **kw) -> RouteAttempt:
    """One offer, bounded by what is left of the ladder and contained in failure.

    A deadline that expires is `indeterminate`: the send may have left the process. A
    failure raised by the route is `unavailable`, as on the messengers branch — the route
    classifies everything it can name itself, and what escapes it happened on our side.
    """
    try:
        return await asyncio.wait_for(
            rung.offer(message_class=_MESSAGE_CLASS, **kw),
            timeout=max(0.1, seconds_left))
    except asyncio.TimeoutError:
        return RouteAttempt(Outcome.INDETERMINATE,
                            reason=f"tg_user did not answer within {seconds_left:.1f}s; "
                                   f"the send may have happened")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("tg_user raised: %s", exc)
        return RouteAttempt(Outcome.UNAVAILABLE, reason=f"{type(exc).__name__}: {exc}")


async def _record(lid: int, *, phone: str, brand: str, account: str,
                  attempt: RouteAttempt) -> None:
    """The rung ledger and the disclosure ledger, as the messengers branch writes them.

    The rung ledger's `accepted` rows are what the next introduction is decided on, so
    they are written for verifications too: the person saw the account, whichever ladder
    put it there. Evidence, not a gate — a failure here must not cost the person the code
    that has already been sent.
    """
    try:
        await queries.record_rung(message_id=lid, phone=phone, route=TG_USER,
                                  outcome=attempt.outcome.value, reason=attempt.reason,
                                  brand=brand, account=account, offered=True)
        await queries.record_disclosure(phone=phone, route=TG_USER, account=account)
    except Exception:
        logger.warning("could not record the tg_user rung for %s", lid, exc_info=True)


def _incapable(reason: str) -> ladder.Attempt:
    return ladder.Attempt(outcome=ladder.INCAPABLE, route=TG_USER, reason=reason)


def _alert(account: str, reason: str) -> None:
    from app.alerting import notify

    notify("routing",
           f"Telegram refused the account {account} rather than the subscriber "
           f"({reason}) — verification codes are going to the rung below it until the "
           f"account is restored",
           dedup_extra=f"tg_user:{account}")
