"""The balance floor, held against each prepaid vendor separately.

A prepaid vendor fails by running out, and it fails at the worst moment: the balance is
fine until it is not, and the first symptom is every verification failing at once. The
floor exists so that the symptom arrives as a sentence with a vendor's name in it rather
than as an outage.

🔴 **The balance cannot be polled for free, and that shapes the whole of this module.**
Measured 20.09.2026 within one request: `checkSendAbility` answered
`remaining_balance: 99.99`, and the send that followed it answered `remaining_balance: 0`
with nothing in between that could have spent it. So on the Telegram rung the balance is
the account's balance **only in the answer to a confirming ability check** — and a
confirming ability check is the billed call. A gateway that polled it would be buying a
reading it gets for nothing from the next real verification, and on an idle rung it would
be spending exactly when nobody is being verified.

Hence: nothing here asks a vendor anything. The floor is held against the balance that
arrives with ordinary traffic, and a balance late by one verification is the cheaper
error.

**Two accounts, two floors, and never a sum.** A single floor over the total would be
satisfied by one funded account while the other is empty, and the empty one is a rung of
the same ladder. Every alert names which vendor it is about: with one paid route "the
vendor is out of credit" was unambiguous, and with two it is the question the operator has
to answer before they can act.

⚠️ **A route with no floor configured is said out loud rather than read as "fine".** A
zero floor is how a floor silently stops existing, and a floor that never fires is
indistinguishable from a vendor that never runs out.

🔴 **And "out loud" means `notify`, at the same volume as the floor itself — plus a check
that does not wait for an event.** Both unwatched states used to leave through
`logger.warning` while the floor they belong to woke the operator; a log line is read when
somebody already suspects something, which is never the case for a floor nobody set. Worse,
`observe` runs only once a balance has arrived — that is, only once the rung is already
carrying — so the rung nobody has used yet, which is exactly the rung this norm was written
about, said nothing at all. `report_unwatched_rungs` is the answer to that half and runs at
startup. Found by the critic circle of 22.09.2026 (task 4.65); the channel is the owner's
decision of the same day.
"""

from __future__ import annotations

import logging

from app.settings_store import store
from app.verification.routes import FLASH_CALL, TG_GATEWAY

logger = logging.getLogger(__name__)

# What each paid rung's account is called when an operator is woken about it. Not the
# route name: "flash_call is out of credit" names our word for a rung, and the person
# reading it has to top up an account at a company.
VENDOR = {
    TG_GATEWAY: "Telegram Gateway",
    FLASH_CALL: "uCaller",
}

# Which setting holds each rung's floor. A mapping rather than a formatted key, so that a
# route with no floor is a missing entry rather than a lookup that quietly returns the
# default of a setting that does not exist.
_FLOOR_SETTING = {
    TG_GATEWAY: "tg_gateway_balance_floor",
    FLASH_CALL: "flash_call_balance_floor",
}


def observe(route: str, balance: float | None) -> None:
    """Record what a vendor just said its balance was, and alert if it is under the floor.

    Called from the carrier on the one answer where the number means the account's
    balance, and never anywhere else. `None` is the ordinary case rather than an error:
    the vendor omits the field from most answers, and its absence says nothing about the
    account.
    """
    if balance is None:
        return

    floor_key = _FLOOR_SETTING.get(route)
    if floor_key is None:
        # A paid rung was added and its floor was not. Loud, because the alternative is a
        # vendor nobody is watching the balance of — and loud means the operator's
        # channel, not the log: this is the state in which the floor cannot fire at all.
        from app.alerting import notify

        logger.warning("a balance of %s arrived for the route %s and no balance floor is "
                       "configured for it", balance, route)
        notify("routing",
               f"a balance of {balance} arrived for the route {route} and this gateway "
               f"holds no balance floor setting for it at all — nobody is watching this "
               f"vendor's credit, and the first symptom of it running out will be every "
               f"verification on that rung failing at once",
               dedup_extra=f"balance_unwatched:{route}")
        return

    floor = store.get(floor_key)
    vendor = VENDOR.get(route, route)
    if not floor:
        from app.alerting import notify

        logger.warning("%s reported a balance of %s and %s is not set — this vendor's "
                       "balance is not being watched", vendor, balance, floor_key)
        notify("routing", _unwatched_text(vendor, floor_key),
               dedup_extra=f"balance_unwatched:{route}")
        return

    if balance >= float(floor):
        logger.info("%s reported a balance of %s, above the floor of %s",
                    vendor, balance, floor)
        return

    from app.alerting import notify

    logger.warning("%s reported a balance of %s, below the floor of %s",
                   vendor, balance, floor)
    notify("routing",
           f"{vendor} is running out: the balance it last reported is {balance}, below "
           f"the configured floor of {floor}. This is one of two prepaid accounts behind "
           f"the verification ladder and only this one needs topping up. The reading "
           f"arrived with ordinary traffic — it is not polled, so it is as fresh as the "
           f"last verification this rung carried and no fresher",
           dedup_extra=f"balance_floor:{route}")


def _unwatched_text(vendor: str, floor_key: str) -> str:
    """The one sentence both unwatched paths say, so they cannot drift apart.

    It names the setting rather than only the vendor, because the reader's next action is
    to set it and a message that does not say which key sends them looking.
    """
    return (f"nobody is watching {vendor}'s balance: {floor_key} is not set, so the floor "
            f"cannot fire for this vendor at all. This is one of two prepaid accounts "
            f"behind the verification ladder, and a prepaid vendor fails by running out — "
            f"the first symptom is every verification on that rung failing at once")


def _configured(route: str) -> bool:
    """Whether this rung holds the credential that lets it carry anything.

    Asked because a rung with no credential is never offered — the registry refuses it at
    the probe and `placement.carriers_for` leaves it out of the map — so it spends nothing
    and its missing floor costs nothing. Reporting it on every start would teach an
    operator to ignore the channel that also carries "this vendor is running out", which
    is the same argument `refusals` makes for leaving `*` and `?` out of its report.
    """
    if route == TG_GATEWAY:
        return bool(store.tg_gateway_token)
    if route == FLASH_CALL:
        from app.verification import ucaller
        return bool(ucaller.configured_bearer())
    return False


async def report_unwatched_rungs() -> None:
    """Say, at startup, which configured paid rung nobody is watching the balance of.

    `observe` cannot answer this: it runs only when a balance has arrived, and a balance
    arrives only once the rung has carried something. The rung that has carried nothing
    yet is the one the norm is about — and on a fresh estate that is every rung.

    Asynchronous and awaited rather than a task, because it reads settings already loaded
    and must have spoken before the first verification is accepted.
    """
    from app.alerting import notify

    for route, floor_key in _FLOOR_SETTING.items():
        if not _configured(route):
            continue
        if store.get(floor_key):
            continue
        vendor = VENDOR.get(route, route)
        logger.warning("%s is configured and %s is not set; nobody is watching its "
                       "balance", vendor, floor_key)
        notify("routing", _unwatched_text(vendor, floor_key),
               dedup_extra=f"balance_unwatched:{route}")
