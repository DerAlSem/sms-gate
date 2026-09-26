"""Tasks 1.2–1.4 — the typed settings the ladder reads, and the refusals they owe.

Every rule here is refused **at save time**, with the offending part named, in the manner
every other structured setting in this gateway is. The alternative — accept now, alert
later — puts a malformed rule in front of live customer traffic and asks an operator to
notice an alert while messages are already going the wrong way.

Two refusals here are not about shape but about meaning, and both were bought:

- **An empty route order means the modem alone**, never "no routes". Settings are seeded
  from code defaults for any key with no row (`seed_from_env`), so an empty default that
  meant "no routes" would fail every message on the first restart after deployment, on a
  host carrying live customer traffic.

- **One account may not be bound to two brands.** Without it the non-substitution rule is
  satisfied and vacuous: a parking code would arrive from the GM+ account with every
  SHALL obeyed.
"""
from __future__ import annotations

import json

from app.phone import normalize_e164
from app.routing.classes import CLASS_NAMES
from app.routing.introduction import MAX_LENGTH as INTRODUCTION_MAX_LENGTH
from app.routing.routes import (
    APP_BOT,
    LADDER_ROUTES,
    MESSENGER_OF,
    MESSENGER_ROUTES,
    MODEM,
)


def _as_object(raw: str, what: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{what} must be a JSON object")
    return data


# --------------------------------------------------------------------------- route order


def validate_route_order(raw: str) -> None:
    if raw.strip() == "":
        return                                  # the modem alone; the shipped default
    data = _as_object(raw, "the route order")

    for class_name, routes in data.items():
        if class_name not in CLASS_NAMES:
            raise ValueError(
                f"unknown message class {class_name!r} — "
                f"known classes are {', '.join(CLASS_NAMES)}"
            )
        if not isinstance(routes, list):
            raise ValueError(f"{class_name}: the route order must be a list")
        if not routes:
            continue                            # empty for this class: the modem alone

        seen: set[str] = set()
        for name in routes:
            name = str(name)
            if name == APP_BOT:
                raise ValueError(
                    f"{class_name}: {APP_BOT!r} is not a rung this gateway offers — "
                    "the application owns that step and tries it before calling here"
                )
            if name not in LADDER_ROUTES:
                raise ValueError(
                    f"{class_name}: unknown route {name!r} — "
                    f"known routes are {', '.join(LADDER_ROUTES)}"
                )
            if name in seen:
                raise ValueError(f"{class_name}: route {name!r} is listed twice")
            seen.add(name)

        # "The modem is last" needs only this one check: a modem appearing anywhere else
        # as well is already refused as a duplicate above, so a second guard for
        # `MODEM in routes[:-1]` would be unreachable — a rule that cannot fire reads
        # like protection and is none.
        if routes[-1] != MODEM:
            raise ValueError(
                f"{class_name}: the modem must be the last route, and the list ends at "
                f"{routes[-1]!r} — every rule of the modem path applies to a message no "
                "earlier rung accepted"
            )


def parse_route_order(raw: str) -> dict[str, list[str]]:
    """The stored order, per class. Unusable or absent means the modem alone.

    Never raises: it is read on the send path. A rule that does not parse was refused at
    save time, so reaching here means a row older than this setting.
    """
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for class_name, routes in data.items():
        if class_name in CLASS_NAMES and isinstance(routes, list):
            out[class_name] = [str(r) for r in routes if str(r) in LADDER_ROUTES]
    return out


# --------------------------------------------------------------------------- deadlines


def validate_route_deadlines(raw: str) -> None:
    if raw.strip() == "":
        return
    data = _as_object(raw, "the rung deadlines")
    for name, seconds in data.items():
        if name == MODEM:
            raise ValueError(
                f"{MODEM!r} takes no rung deadline — the modem path is bounded by its own "
                "retry budget and hold rules, not by the ladder"
            )
        if name not in MESSENGER_ROUTES:
            raise ValueError(
                f"unknown route {name!r} — deadlines are set for "
                f"{', '.join(MESSENGER_ROUTES)}"
            )
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds <= 0:
            raise ValueError(f"{name}: deadline must be a positive number of seconds, got {seconds!r}")


def parse_route_deadlines(raw: str) -> dict[str, float]:
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k): float(v)
        for k, v in data.items()
        if str(k) in MESSENGER_ROUTES
        and isinstance(v, (int, float))
        and not isinstance(v, bool)
        and v > 0
    }


# --------------------------------------------------------------------------- brands


def validate_brands(raw: str) -> None:
    if raw.strip() == "":
        return
    data = _as_object(raw, "the brand map")

    brands = data.get("brands", {})
    if not isinstance(brands, dict):
        raise ValueError("'brands' must be a JSON object of brand → accounts")

    # One account, one brand. Checked across every brand and every messenger, because
    # the substitution this forbids is exactly the cross-brand one.
    owner_of: dict[tuple[str, str], str] = {}
    # And the same rule on the axis that numbers opened. A messenger account *is* a phone
    # number, so two brands recorded on one number are two brands on one account —
    # spelled so that no account id repeats and nothing above catches it.
    number_owner: dict[tuple[str, str], str] = {}
    for brand, accounts in brands.items():
        if not isinstance(accounts, dict):
            raise ValueError(f"brand {brand!r}: accounts must be a JSON object")
        for route, entry in accounts.items():
            if route not in MESSENGER_ROUTES:
                raise ValueError(
                    f"brand {brand!r}: unknown messenger route {route!r} — "
                    f"known routes are {', '.join(MESSENGER_ROUTES)} "
                    f"(for {', '.join(sorted(set(MESSENGER_OF.values())))})"
                )
            if not isinstance(entry, dict):
                raise ValueError(
                    f"brand {brand!r}: the {route} account must be recorded as an object "
                    f'with "account" and "number", e.g. {{"account": "@name", '
                    f'"number": "+79990000000"}} — the number an account lives on is what '
                    "its re-login code arrives on, and a number written only in prose "
                    "cannot be recognised in order to be withheld"
                )
            account = str(entry.get("account", "") or "").strip()
            if not account:
                raise ValueError(f"brand {brand!r}: {route} account is required")
            written = str(entry.get("number", "") or "").strip()
            if not written:
                raise ValueError(
                    f"brand {brand!r}: the {route} account must record the number it "
                    "lives on"
                )
            try:
                number = normalize_e164(written)
            except ValueError as exc:
                raise ValueError(f"brand {brand!r}: {route} {exc}") from exc
            intro = str(entry.get("intro", "") or "").strip()
            if not intro:
                raise ValueError(
                    f"brand {brand!r}: the {route} account must record the "
                    '"intro" it sends as its first message to a number — who is '
                    "writing and why. A personal account that writes a stranger a "
                    "code with nothing to identify it is correctly read as fraud, "
                    "and the report that follows costs the account permanently"
                )
            if len(intro) > INTRODUCTION_MAX_LENGTH:
                raise ValueError(
                    f"brand {brand!r}: the {route} introduction is {len(intro)} "
                    f"characters and at most {INTRODUCTION_MAX_LENGTH} are accepted — "
                    "it is prefixed to every first message, and one long enough to "
                    "push the code off a phone screen defeats what it is there for"
                )
            key = (route, account)
            if key in owner_of and owner_of[key] != brand:
                raise ValueError(
                    f"account {account!r} is bound to both {owner_of[key]!r} and "
                    f"{brand!r} — one account may carry one brand only, or the rule that "
                    "forbids substituting another brand's account is vacuous"
                )
            owner_of[key] = brand
            number_key = (route, number)
            if number_key in number_owner and number_owner[number_key] != brand:
                raise ValueError(
                    f"number {number} carries both {number_owner[number_key]!r} and "
                    f"{brand!r} on {MESSENGER_OF[route]} — one number is one "
                    f"{MESSENGER_OF[route]} account, so this binds one account to two "
                    "brands without repeating an account id"
                )
            number_owner[number_key] = brand

    apps = data.get("apps", {})
    if not isinstance(apps, dict):
        raise ValueError("'apps' must be a JSON object of app_id → permitted brands")
    for app_id, entry in apps.items():
        if not isinstance(entry, dict):
            raise ValueError(f"application {app_id!r}: must be a JSON object")
        permitted = entry.get("brands", [])
        if not isinstance(permitted, list) or not all(isinstance(b, str) for b in permitted):
            raise ValueError(f"application {app_id!r}: 'brands' must be a list of names")
        for brand in permitted:
            if brand not in brands:
                raise ValueError(
                    f"application {app_id!r} is permitted brand {brand!r}, which has no "
                    "configured account"
                )
        default = str(entry.get("default", "")).strip()
        if permitted and not default:
            raise ValueError(
                f"application {app_id!r} has permitted brands but no default — a send "
                "that names no brand would have to be refused, and the messenger rungs "
                "must not be silently skipped for it"
            )
        if default and default not in permitted:
            raise ValueError(
                f"application {app_id!r}: default brand {default!r} is not in its "
                f"permitted set ({', '.join(permitted) or 'empty'})"
            )


def parse_brands(raw: str) -> dict:
    if not raw or not raw.strip():
        return {"apps": {}, "brands": {}}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"apps": {}, "brands": {}}
    if not isinstance(data, dict):
        return {"apps": {}, "brands": {}}
    return {
        "apps": data.get("apps", {}) if isinstance(data.get("apps"), dict) else {},
        "brands": _brand_records(data.get("brands")),
    }


def _brand_records(raw_brands) -> dict:
    """One shape for every reader: brand \u2192 route \u2192 {"account", "number", "intro"}.

    Read time is lenient where save time is strict, as every parser in this file is. A
    brand map stored before the number was recorded names the account as a bare string,
    and refusing it here would take the messenger rungs away from a running gateway at the
    next restart \u2014 a far worse answer to an old configuration than carrying it with the
    number unknown.

    The number is canonicalised on the way in, not left as written. A consumer comparing a
    recorded number against one that arrived from the network compares two spellings
    otherwise, and that is the same defect the save-time refusal exists to prevent.
    """
    out: dict[str, dict] = {}
    if not isinstance(raw_brands, dict):
        return out
    for brand, accounts in raw_brands.items():
        if not isinstance(accounts, dict):
            continue
        record: dict[str, dict] = {}
        for route, entry in accounts.items():
            if isinstance(entry, dict):
                account = str(entry.get("account", "") or "").strip()
                number = _read_number(entry.get("number"))
                intro = str(entry.get("intro", "") or "").strip()
            else:
                account = str(entry or "").strip()
                number = ""
                intro = ""
            if not account:
                continue
            record[route] = {"account": account, "number": number, "intro": intro}
        out[brand] = record
    return out


def _read_number(value) -> str:
    """The recorded number in E.164, or as written when it does not parse at all.

    Dropping an unparsable value would hide it from the operator reading the settings;
    reporting it as written keeps it visible to whoever has to fix it. Nothing sends to
    this number \u2014 it is ours, and it is read to recognise our own traffic.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return normalize_e164(text)
    except ValueError:
        return text


# --------------------------------------------------------------------------- limits


def validate_limits(raw: str) -> None:
    if raw.strip() == "":
        return
    data = _as_object(raw, "the limit rule")

    accounts = data.get("accounts", {})
    if not isinstance(accounts, dict):
        raise ValueError("'accounts' must be a JSON object of account → bounds")
    for account, bounds in accounts.items():
        if not isinstance(bounds, dict):
            raise ValueError(f"account {account!r}: bounds must be a JSON object")
        values = {}
        for field in ("per_hour", "per_day"):
            value = bounds.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(
                    f"account {account!r}: {field} must be a positive whole number, "
                    f"got {value!r} — a bound read as zero disables the account silently"
                )
            values[field] = value
        if values["per_day"] < values["per_hour"]:
            raise ValueError(
                f"account {account!r}: per_day ({values['per_day']}) is below per_hour "
                f"({values['per_hour']}) — a day that cannot hold an hour is a typo, and "
                "it reads as a working limit"
            )

    window = data.get("recipient_window_seconds", 0)
    if not isinstance(window, int) or isinstance(window, bool) or window < 0:
        raise ValueError(
            f"recipient_window_seconds must be a whole number of seconds, got {window!r}"
        )


def parse_limits(raw: str) -> dict:
    if not raw or not raw.strip():
        return {"accounts": {}, "recipient_window_seconds": 0}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"accounts": {}, "recipient_window_seconds": 0}
    if not isinstance(data, dict):
        return {"accounts": {}, "recipient_window_seconds": 0}
    accounts = data.get("accounts")
    return {
        "accounts": accounts if isinstance(accounts, dict) else {},
        "recipient_window_seconds": data.get("recipient_window_seconds", 0) or 0,
    }


# ------------------------------------------------------- the rule that spans settings


def check_every_account_is_rate_bound(brands_raw: str, limits_raw: str) -> None:
    """Every account configured to send has an hourly and a daily maximum.

    `messenger-delivery` states it as a SHALL — "each sender account SHALL have a configured
    maximum number of sends per rolling hour and per rolling day" — and the two settings are
    separate rows, so a brand added without its bounds is an account with no ceiling saved
    green. Like the deadline rule below this spans settings and either side can be the one
    being saved, which is why it lives at `set_many` and not in `validate_raw`.

    Refused rather than defaulted. The reader in sections 3 and 4 asks an account for its
    bound, and a missing answer has two readings, both wrong: unbounded risks the account
    permanently on the second complaint, and zero disables a working route in silence. The
    delta forbids that pair for a rule that does not parse; an absent one is no better.
    """
    brands = parse_brands(brands_raw)
    bounded = set((parse_limits(limits_raw).get("accounts") or {}).keys())

    for brand, accounts in (brands.get("brands") or {}).items():
        for route, entry in (accounts or {}).items():
            account = str((entry or {}).get("account", "") or "").strip()
            if account and account not in bounded:
                raise ValueError(
                    f"account {account!r} ({brand} on {route}) has no rate bound — every "
                    "sender account needs a maximum per rolling hour and per rolling day "
                    "in the limit rule before it may send. An account with none would be "
                    "read either as unbounded, which is what costs an account permanently, "
                    "or as zero, which turns a working route off without saying so"
                )


def check_ladder_fits_the_retry_interval(
    order_raw: str, deadlines_raw: str, backoff_raw: str
) -> None:
    """The ladder must finish before the modem path's first retry becomes due.

    Two mechanisms already act on a message on a timer and know nothing of rungs: the
    retry scheduler becomes due at `next_attempt_at`, and the pending sweep fails a
    message older than the retry deadline. A ladder that can outlive either produces a
    message sent twice, or a `failed` webhook for a message a rung is still sending.

    This cannot live in `validate_raw`: it is a relation between three settings, and any
    one of them can be the one being saved.
    """
    order = parse_route_order(order_raw)
    deadlines = parse_route_deadlines(deadlines_raw)

    rungs: set[str] = set()
    for class_name, routes in order.items():
        for name in routes:
            if name == MODEM:
                continue
            if name not in deadlines:
                raise ValueError(
                    f"{class_name}: route {name!r} has no configured deadline — every "
                    "route call must be bounded, so a rung without one cannot be offered"
                )
            rungs.add(name)

    if not rungs:
        return

    # The worst case is one class using every configured rung, which is what the sum
    # over the distinct rungs measures.
    total = sum(deadlines[name] for name in rungs)

    delays = [int(p.strip()) for p in (backoff_raw or "").split(",") if p.strip()]
    if not delays:
        # No retry to race. The pending sweep still bounds the message, but that bound is
        # the modem's deadline and is far longer; nothing here is contradicted.
        return

    first_retry = delays[0]
    if total >= first_retry:
        raise ValueError(
            f"the rung deadlines sum to {total:g}s, which is not shorter than the first "
            f"retry interval of {first_retry}s — a ladder that outlives it sends the "
            "message twice, or reports a failure for a message a rung is still sending"
        )
