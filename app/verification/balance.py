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
        # vendor nobody is watching the balance of.
        logger.warning("a balance of %s arrived for the route %s and no balance floor is "
                       "configured for it", balance, route)
        return

    floor = store.get(floor_key)
    vendor = VENDOR.get(route, route)
    if not floor:
        logger.warning("%s reported a balance of %s and %s is not set — this vendor's "
                       "balance is not being watched", vendor, balance, floor_key)
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
