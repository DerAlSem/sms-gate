"""Task 2.5 — who the message is sent as, and from which account.

The owner's requirement, written as an invariant rather than as a convention: the Sokol
account must not be able to write to GM+ recipients, and the GM+ account must not be able
to write to HRM's. Mechanically, not "not done".

**The invariant is placed on the border, not written as a census of rungs.** These two
functions are the only place an account is read, and `dispatch` is the only caller. A rung
receives one account — the one its brand owns — and receives nothing else, ever: it is
never handed the map, so substitution is not a rule it obeys but a sentence it cannot say.

A census ("every route checks its brand before sending") reads better and ages silently.
The route written next year would be written by someone reading the other routes, and
every one of them would look correct.

A brand that owns no account on a messenger yields `None`, and `dispatch` then does not
offer that rung at all. Offering it with an empty account and letting it refuse is not the
same thing: resolving a phone number discloses it to the vendor **before** any verdict is
reached, so a rung that cannot send would still have told Telegram who we were looking
for.
"""
from __future__ import annotations

from app.routing.config import parse_brands as parse
from app.routing.routes import MESSENGER_ROUTES

__all__ = [
    "BrandRefused", "parse", "resolve", "account_for", "number_for",
    "introduction_for", "messenger_rungs_in",
]


class BrandRefused(Exception):
    """A brand that cannot be resolved for this caller.

    Carries its own `key` because the API door puts it in the `{"error": …}` body, and a
    blacklisted number, a foreign brand, an unknown route name and an emptied ladder have
    four different remedies. One shared key would make them indistinguishable to a client
    that already has the contract.
    """

    def __init__(self, key: str, message: str, **detail):
        super().__init__(message)
        self.key = key
        self.detail = detail


def resolve(app_id: str, requested: str | None, cfg: dict) -> str:
    """The brand this application may send under, or `""` when it has none configured.

    The permitted set is derived from the authenticated `app_id` — never from the request
    — and a brand named in the request is accepted only after it is confirmed to be a
    member of that set.

    `""` is not an error here on purpose. Whether having no brand is fatal depends on
    whether a messenger rung would be offered at all, and that is the border's question,
    not this function's: this gateway carries every one of today's messages under no
    brand, by the modem, and must keep doing so on the day this change deploys.
    """
    entry = (cfg.get("apps") or {}).get(app_id) or {}
    permitted = [b for b in (entry.get("brands") or []) if isinstance(b, str)]
    default = str(entry.get("default", "") or "").strip()

    requested = (requested or "").strip()
    if requested:
        if requested not in permitted:
            raise BrandRefused(
                "brand_not_permitted",
                f"application {app_id!r} may not send under brand {requested!r} "
                f"(permitted: {', '.join(permitted) or 'none'})",
                brand=requested,
                permitted=permitted,
            )
        return requested

    return default


def _record(brand: str, route: str, cfg: dict) -> dict:
    """The stored record for one brand on one route, normalised by `parse`.

    Reads a single brand's entry. It cannot return another brand's, and these are the only
    readers of the account map — which is what makes non-substitution a property of the
    code's shape rather than of a check somebody has to remember to write.
    """
    if not brand:
        return {}
    accounts = (cfg.get("brands") or {}).get(brand) or {}
    if not isinstance(accounts, dict):
        return {}
    entry = accounts.get(route) or {}
    return entry if isinstance(entry, dict) else {}


def account_for(brand: str, route: str, cfg: dict) -> str | None:
    """The one account `brand` owns on `route`, or None.

    A rung is handed this and nothing else. Handing it the record instead would hand it
    the number of our own SIM along with the account it is allowed to send as.
    """
    account = str(_record(brand, route, cfg).get("account", "") or "").strip()
    return account or None


def number_for(brand: str, route: str, cfg: dict) -> str | None:
    """The number that account lives on, or None when it was never recorded (task 5.1).

    Nothing sends to this number: it is ours. It is read to recognise our own traffic —
    the re-login code of a sender account arrives on it, and `messenger-delivery` requires
    that such a code be withheld from every application's webhook and from the operator
    alert channel. An account whose number is unknown cannot have its code recognised, and
    that is why the number is refused at save time rather than merely allowed.

    🔴 No caller in `app/` yet. The named consumer is task 3.5; it lives here rather than
    in the inbound path so that `brands.py` stays the only reader of the account map.
    """
    number = str(_record(brand, route, cfg).get("number", "") or "").strip()
    return number or None


def introduction_for(brand: str, route: str, cfg: dict) -> str | None:
    """What this brand's account says the first time it writes to a number (task 5.3).

    A third reader of the same record, and here rather than anywhere else for the reason
    the other two are here: this file is the only place a brand's entry is read, so a rung
    receiving another brand's introduction is not a rule anybody has to remember but a
    sentence the code cannot say. A rung is handed its own introduction and never the map.

    Per route rather than per brand. The same words are usually right on both messengers,
    but they are not guaranteed to be — MAX and Telegram are different products with
    different expectations of a stranger — and the record that already holds one account
    per messenger is where a difference would have to live.

    `None` when the brand records none. Read time is lenient here, as everywhere in this
    file; the refusal that holds is the ladder's, which declines to offer a rung that
    would have to open a conversation without saying who it is.
    """
    text = str(_record(brand, route, cfg).get("intro", "") or "").strip()
    return text or None


def messenger_rungs_in(order) -> list[str]:
    """The rungs in `order` that would reach into a messenger.

    The modem is handed to, not offered, and reaches nobody's servers under any brand.
    """
    return [name for name in (order or ()) if name in MESSENGER_ROUTES]
