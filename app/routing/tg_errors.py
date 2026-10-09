"""Task 3.3 — the mapping from a Telegram failure to one of the four outcomes, with the
evidence for each row.

`messenger-delivery` states the rule this file exists to obey: the mapping "SHALL be
written against a named vendor error or a captured live sample, and SHALL cite it. A
verdict recognised by a string match invented by us SHALL NOT be written." This gateway
has paid for it once, in the modem's `+CMS`/`+CME` table, where 96 was filed as permanent
when it is not.

**Every row is keyed on the exception class's `ID`** — the server's own string, carried by
the library as a class attribute (`PHONE_NOT_OCCUPIED`, `FLOOD_WAIT_X`). Never on the
formatted message: the library builds that by interpolation and does not promise it, and
matching on it is the invented verdict the delta forbids. A test checks every key against
the installed library, so a renamed error fails a second-long test rather than a send.

**What is deliberately absent is as load-bearing as what is here.** There is no catch-all.
An error the library itself cannot name arrives as `UnknownError`, and an error we cannot
name is what `indeterminate` is for — the caller's own floor answers it. Adding a row that
guessed would be the thing this file exists to prevent.

**Two rows are the live capture; the rest are the vendor's own words.** The delta accepts
a named vendor error in place of a sample, and each of these carries Telegram's own
description as its docstring in the library — that description is the citation.

*The one the capture changed:* `PHONE_NOT_OCCUPIED` came back **identically** for a number
with no Telegram account and for a number that has one but hides from lookup by phone —
same id, same code, same formatted message, and `ImportContacts` equally empty for both.
So this row reports a miss and says no more than that. A classifier that told them apart
would be inventing; there is no key, `ID` included, that separates them.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.routing.route import Attempt, Outcome


@dataclass(frozen=True)
class Row:
    """One named failure: what it means for the ladder, in words, and on whose authority.

    `limits_us` marks the failures that say *our sender account* is limited, revoked or
    gone, as against the ordinary unavailability of a route. Task 5.5 owes an alert naming
    the brand and the messenger, and this is where that fact is knowable; it lives on the
    row rather than in a second list so it cannot drift away from the mapping it describes.
    """
    outcome: Outcome
    means: str
    cites: str
    limits_us: bool = False


#: Keyed on the exception class's `ID`.
TABLE: dict[str, Row] = {
    # ------------------------------------------------------------------ about the recipient
    "PHONE_NOT_OCCUPIED": Row(
        Outcome.MISS,
        "the number did not resolve to a Telegram account — it has none, or it is hidden "
        "from lookup by phone; the wire does not say which",
        "captured live 22.09.2026, probes resolve_phone.no_account and "
        "resolve_phone.hidden — identical in every recorded field",
    ),
    "USER_PRIVACY_RESTRICTED": Row(
        Outcome.MISS,
        "the recipient's privacy settings do not allow this",
        "pyrogram.errors.UserPrivacyRestricted, 403: \"The user's privacy settings do not "
        "allow you to do this.\"",
    ),
    "USER_IS_BLOCKED": Row(
        Outcome.MISS,
        "the recipient has blocked this account",
        "pyrogram.errors.UserIsBlocked, 400: \"You were blocked by this user.\"",
    ),
    "INPUT_USER_DEACTIVATED": Row(
        Outcome.MISS,
        "the recipient's account has been deleted",
        "pyrogram.errors.InputUserDeactivated, 400: \"The target user has been "
        "deleted/deactivated.\"",
    ),
    "PHONE_NUMBER_INVALID": Row(
        Outcome.MISS,
        "Telegram does not accept this number as a phone number",
        "pyrogram.errors.PhoneNumberInvalid, 400: \"The phone number is invalid.\"",
    ),

    # ------------------------------------------------------------------------- about us
    "FLOOD_WAIT_X": Row(
        Outcome.UNAVAILABLE,
        "Telegram is asking this account to wait",
        "pyrogram.errors.FloodWait, 420, carrying .value and .seconds — named vendor "
        "error, deliberately not produced: probe flood_wait says why",
    ),
    "PEER_FLOOD": Row(
        Outcome.UNAVAILABLE,
        "this account is limited and cannot write to people it has not met — check "
        "@spambot",
        "pyrogram.errors.PeerFlood, 400: \"The current account is limited, you cannot "
        "execute this action, check @spambot for more info.\"",
        limits_us=True,
    ),
    "AUTH_KEY_UNREGISTERED": Row(
        Outcome.UNAVAILABLE,
        "this session is no longer registered and has to be signed in again by hand",
        "pyrogram.errors.AuthKeyUnregistered, 401",
        limits_us=True,
    ),
    "SESSION_REVOKED": Row(
        Outcome.UNAVAILABLE,
        "somebody terminated this session from the account's own Telegram",
        "pyrogram.errors.SessionRevoked, 401",
        limits_us=True,
    ),
    "SESSION_EXPIRED": Row(
        Outcome.UNAVAILABLE,
        "this session has expired and has to be signed in again by hand",
        "pyrogram.errors.SessionExpired, 401",
        limits_us=True,
    ),
    "USER_DEACTIVATED": Row(
        Outcome.UNAVAILABLE,
        "this sender account has been deleted",
        "pyrogram.errors.UserDeactivated, 401",
        limits_us=True,
    ),
    "USER_DEACTIVATED_BAN": Row(
        Outcome.UNAVAILABLE,
        "this sender account was banned by Telegram's antispam — the permanent one",
        "pyrogram.errors.UserDeactivatedBan, 401",
        limits_us=True,
    ),
    "MESSAGE_TOO_LONG": Row(
        Outcome.UNAVAILABLE,
        "Telegram refused the text as too long",
        "pyrogram.errors.MessageTooLong, 400",
    ),
}


def outcome_for(exc: BaseException) -> Attempt | None:
    """The outcome this named failure carries, or None when it is not one we can name.

    None is an answer, not a gap: the caller's floor turns it into the delta's own rule —
    what cannot be named after the request left is indeterminate.

    Every row here is also a **positive statement that nothing was sent**: each is the
    server's answer refusing the request, which is why a `FLOOD_WAIT_X` interrupting the
    send leaves the ladder free to reach the modem instead of stopping it. That is the one
    exception the delta anticipates, and it is the difference between a rate-limited
    account costing a person nothing and costing them their code.

    Whether the row says our own sender account is limited or gone travels **on the
    attempt**, as `limits_account`. Task 5.5 owes an alert naming the brand and the
    messenger, and this is the only place the fact is knowable: downstream it could be
    recovered only by matching on the reason text, which is the invented verdict the delta
    forbids. It is carried here rather than by a second predicate over the same table —
    there used to be one, `says_the_account_is_limited`, and it had no caller in `app/` at
    all. Two statements of one invariant mean nobody can tell which is load-bearing, and
    the one the alert does not read is the one that would have drifted.

    It is deliberately **not** the only thing between a dead account and silence: 5.5's
    aggregate alert — N consecutive non-acceptances — is the load-bearing one, because an
    alert conditioned on recognising "limited" is satisfied by an implementation that never
    recognises it while the degradation continues.
    """
    row = TABLE.get(getattr(type(exc), "ID", None) or "")
    if row is None:
        return None
    return Attempt(row.outcome, reason=_reason(row, exc), limits_account=row.limits_us)


def _reason(row: Row, exc: BaseException) -> str:
    wait = getattr(exc, "value", None)
    if wait is None:
        wait = getattr(exc, "seconds", None)
    if isinstance(wait, int):
        return f"{row.means} ({wait}s)"
    return row.means
