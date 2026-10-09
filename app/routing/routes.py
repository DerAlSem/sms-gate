"""The route vocabulary — one list, because task 1.1 holds these values provisional.

The names are normative values exposed to an application whose contract is already sent,
and the direction axis (`outbound`/`inbound`) of `verify-by-inbound-code` is the other
half of the same vocabulary. Until the owner settles them jointly, every module reads
them from here, so settling them is an edit to one file rather than a grep.
"""
from __future__ import annotations

# The application's own bot. It is a route a message can have *been carried by* — the
# application tries it before calling the gateway at all — but never a rung this gateway
# offers, because the gateway holds no third-party bot token and no `chat_id`.
APP_BOT = "app_bot"

TG_USER = "tg_user"
MAX_USER = "max_user"
MODEM = "modem"

#: Every value the `route` field may ever carry, in ladder order with `app_bot` first.
ROUTE_NAMES: tuple[str, ...] = (APP_BOT, TG_USER, MAX_USER, MODEM)

#: The routes this gateway itself can offer a message to. `app_bot` is excluded by
#: ownership, not by capability.
LADDER_ROUTES: tuple[str, ...] = (TG_USER, MAX_USER, MODEM)

#: Rungs that reach into a messenger. The modem is the existing send path and is handed
#: to rather than offered, so it is not one of these.
MESSENGER_ROUTES: tuple[str, ...] = (TG_USER, MAX_USER)

#: Which messenger a rung speaks, for the brand-account map.
MESSENGER_OF: dict[str, str] = {TG_USER: "telegram", MAX_USER: "max"}

#: The stable intent an application names to force the modem, so that the request keeps
#: working when routes are added or reordered.
FORCE_SMS = "force_sms"
