"""The routing rule: which way out an operator's traffic takes.

Data, not a branch. The capability exists because the modem route has been withdrawn by
operators before, at whole-estate scale, and the replacement has to be reachable by
configuration during the outage rather than by deploying code into it. Three properties
follow from that, and each of them is a norm rather than a convenience:

- **No operator name appears in the sending path.** The initial content — МегаФон to the
  paid ladder, everything else to the modem — is a row in `settings`, because the event
  this rule exists for is the *next* withdrawal rather than this one.
- **An entry's value is an ordered list**, and the order is the thing being configured.
  Which paid way out is tried first is a money decision that moves with vendors' prices
  and reachability. An implementation that tries Telegram first because the code says so
  satisfies the letter of the requirement and defeats it.
- **Names are matched normalised.** `number_operators` holds МегаФон under two spellings
  — `МЕГАФОН` for 120 numbers and `МегаФон` for 57, read on 08.09.2026 — written by the
  same lookup at different times. A rule comparing by `==` would route a third of the
  subscribers correctly and the rest to the route that has been rejecting them, silently.
  SQLite's `upper()`, `lower()` and `LIKE` are no remedy: they are ASCII-only in the
  shipped build and leave Cyrillic untouched, and a measurement taken with `upper()` on
  08.09.2026 undercounted МегаФон traffic by half before the mistake was caught. The
  folding is therefore done here, in Python, and never in SQL.

Two entries are not operators. `*` answers for an operator the rule does not mention, and
`?` for an operator that could not be resolved at all — separate because the numbers most
likely to lack an operator row are the ones never messaged before, and a first-time
recipient is exactly who a confirmation code is usually for. Either may be set to
`refuse`, because an unknown operator on a network being refused is a coin toss with a
person's login on it, and that coin toss must be the owner's to decline.

A rule that cannot be read is never read as an empty one. Empty, a broken rule sends the
whole of an operator's traffic back to the route that is rejecting it, without a line in
the log — the one failure of this capability that is both total and silent.
"""

from __future__ import annotations

import json
import logging
import unicodedata

from app.verification.routes import ALL_ROUTES

logger = logging.getLogger(__name__)

KEY = "operator_routes"

# The two entries that name no operator, spelled as characters an operator name cannot
# contain, so that neither can ever be shadowed by a real network.
DEFAULT = "*"
UNKNOWN = "?"

# Not a way out but the absence of one, and expressible for the same reason the rule is
# configuration at all: refusing is sometimes the correct answer and must not need a
# deploy either. It stands alone in an entry — a ladder that continues past a refusal is
# not a refusal.
REFUSE = "refuse"

_ALLOWED = ALL_ROUTES | {REFUSE}

# The shipped content, and the owner's decision of 18.09.2026 reconciled that evening:
# Telegram's Gateway goes *in front* of the flash call, because an unreachable subscriber
# costs nothing there and a call is charged for having been placed.
SHIPPED = json.dumps(
    [
        {"operator": "МегаФон", "routes": ["tg_gateway", "flash_call"]},
        {"operator": DEFAULT, "routes": ["sms_out"]},
        {"operator": UNKNOWN, "routes": ["sms_out"]},
    ],
    ensure_ascii=False,
)


class UnreadableRule(Exception):
    """The stored rule is not a rule. Never an empty rule — see the module docstring."""


def fold(name: str) -> str:
    """The form two spellings of one operator have in common.

    NFKC first so that compatibility forms do not survive the comparison, then the
    surrounding whitespace (pasted names carry it), then `casefold`, which unlike
    `lower()` is defined over Cyrillic.
    """
    return unicodedata.normalize("NFKC", name or "").strip().casefold()


def _entry(item: object, index: int) -> tuple[str, list[str]]:
    """One validated entry, or ValueError naming which one and why."""
    where = f"entry #{index + 1}"
    if not isinstance(item, dict):
        raise ValueError(f"{where}: must be an object")
    if "app_id" in item:
        # The same hard-coding moved into configuration: it would route by who is asking
        # rather than by what is reachable. Who may spend on a paid route is a separate
        # question, answered by the application's entitlement.
        raise ValueError(f"{where}: app_id does not belong in the routing rule — the "
                         f"rule is keyed on the operator, never on the application")
    operator = str(item.get("operator", "")).strip()
    if not operator:
        raise ValueError(f"{where}: operator is required")
    raw_routes = item.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ValueError(f"{where} ({operator}): routes must be a non-empty ordered list")
    routes = [str(r).strip() for r in raw_routes]
    for route in routes:
        if route not in _ALLOWED:
            raise ValueError(
                f"{where} ({operator}): unknown route {route!r} — "
                f"known routes are {', '.join(sorted(_ALLOWED))}")
    if len(set(routes)) != len(routes):
        raise ValueError(f"{where} ({operator}): a route is named twice; a rung is "
                         f"attempted at most once")
    if REFUSE in routes and len(routes) > 1:
        raise ValueError(f"{where} ({operator}): {REFUSE!r} stands alone — a ladder that "
                         f"continues past a refusal is not a refusal")
    return operator, routes


def validate(raw: str) -> None:
    """Refuse at save time what would otherwise be discovered at send time.

    At send time the discovery is a person standing at a barrier, and on the paid rungs it
    is a person standing at a barrier after money has been spent.
    """
    if raw.strip() == "":
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("must be a JSON list of entries")
    seen: dict[str, str] = {}
    for i, item in enumerate(data):
        operator, _ = _entry(item, i)
        key = fold(operator)
        if key in seen:
            raise ValueError(
                f"entry #{i + 1} ({operator}): {seen[key]!r} is the same operator by "
                f"another spelling, and which of the two wins would be decided by the "
                f"order of the list")
        seen[key] = operator


def normalize(raw: str) -> str:
    """The canonical stored form: every operator and route stripped.

    On write as well as on read, so that a pasted value is stored as it will be matched
    rather than matched around for ever.
    """
    if raw.strip() == "":
        return raw
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw                                  # `validate` reports it
    if not isinstance(data, list):
        return raw
    cleaned = []
    for item in data:
        if not isinstance(item, dict):
            return raw
        entry = dict(item)
        if "operator" in entry:
            entry["operator"] = str(entry["operator"]).strip()
        if isinstance(entry.get("routes"), list):
            entry["routes"] = [str(r).strip() for r in entry["routes"]]
        cleaned.append(entry)
    return json.dumps(cleaned, ensure_ascii=False)


def parse(raw: str) -> dict[str, list[str]]:
    """The rule as a lookup keyed on the folded operator name.

    Raises `UnreadableRule` rather than answering with an empty rule.
    """
    if raw is None or raw.strip() == "":
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UnreadableRule(f"the stored routing rule is not JSON: {exc}") from exc
    if not isinstance(data, list):
        raise UnreadableRule("the stored routing rule is not a list of entries")
    parsed: dict[str, list[str]] = {}
    for i, item in enumerate(data):
        try:
            operator, routes = _entry(item, i)
        except ValueError as exc:
            raise UnreadableRule(str(exc)) from exc
        parsed[fold(operator)] = routes
    return parsed


def route_for(operator: str | None) -> list[str]:
    """The ordered rungs for this operator, read from the rule in force right now.

    Read per call rather than held, because a change to the rule must take effect without
    a restart — a restart drops sending sessions, which is the deploy the rule exists to
    avoid, merely spelled differently.

    A rule that answers nothing for this operator refuses rather than guessing: a default
    arrived at by accident is the silent failover this capability refuses by name.
    """
    # Imported here rather than at module scope: the store holds this rule's shipped
    # content as its default, so the two modules would otherwise import each other.
    from app.settings_store import store

    try:
        rule = parse(store.get(KEY))
    except UnreadableRule:
        # Re-raised for the caller to refuse loudly with. The alert is raised here so that
        # it is raised once per read wherever the read happens, rather than once per
        # caller that remembered.
        from app.alerting import notify
        notify("routing", "the stored routing rule cannot be read; nothing is being "
                          "routed by it until it is fixed", dedup_extra=KEY)
        raise
    if not rule:
        return [REFUSE]
    key = fold(operator) if operator else ""
    if key and key in rule:
        return list(rule[key])
    fallback = UNKNOWN if not key else DEFAULT
    if fallback in rule:
        return list(rule[fallback])
    return [REFUSE]


def refuses(routes: list[str]) -> bool:
    """Whether this answer is a refusal rather than a ladder."""
    return not routes or routes == [REFUSE]
