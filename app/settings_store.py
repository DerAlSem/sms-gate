from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Callable

from app.db.connection import get_db

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Spec:
    key: str
    type: str          # "bool" | "int" | "posint" | "float" | "str" | "routes"
                       # | "region" | "delays"
    default: object
    section: str
    is_secret: bool
    description: str
    route_key: str = ""   # "routes" only: the field identifying a route


SETTINGS_SPEC: list[Spec] = [
    Spec("voxlink_enabled", "bool", True, "Voxlink", False, "Enable operator/region lookup"),
    Spec("voxlink_url", "str", "https://num.voxlink.ru/get/", "Voxlink", False, "Lookup endpoint"),
    Spec("voxlink_timeout", "float", 5.0, "Voxlink", False, "Per-request timeout (s)"),
    Spec("voxlink_cache_ttl_days", "int", 7, "Voxlink", False, "Re-lookup after N days"),
    Spec("alert_bot_token", "str", "", "Alerting", True, "Telegram bot token (blank = disabled)"),
    Spec("alert_chat_id", "str", "", "Alerting", False, "Telegram chat id"),
    Spec("alert_dedup_window", "float", 300.0, "Alerting", False, "Suppress identical alerts for N seconds"),
    # Tried before the direct route, not instead of it. The mobile carrier the backup uplink
    # runs on cannot reach Telegram at all, so during a wired outage every alert raised on
    # this host is lost — observed on 2026-07-29, where the failover alert never arrived and
    # the restore alert eight minutes later did. Being told an outage ended and never that it
    # began is the worst shape available.
    Spec("alert_relay_base", "str", "", "Alerting", False,
         "Base URL of a relay that can reach Telegram when this host cannot "
         "(e.g. a relay on the far end of a tunnel). Tried first; the direct route is the fallback"),
    Spec("notify_system_errors", "bool", True, "Alerting", False,
         "Send ERROR-level log records (crashes, exceptions) to Telegram"),
    Spec("notify_send_errors", "bool", False, "Alerting", False,
         "Notify when an outbound SMS fails to send"),
    Spec("notify_delivery_errors", "bool", False, "Alerting", False,
         "Notify on delivery failure or when a number is blacklisted"),
    # Its own switch rather than a share of the one above, which defaults to off: this
    # guarantee would then be empty on every existing install — and every existing
    # install is one that has the defect.
    Spec("notify_unplaced_reports", "bool", True, "Alerting", False,
         "Notify when a delivery report could not be attributed to any message "
         "(the report is recorded either way)"),
    Spec("notify_inbound", "bool", False, "Alerting", False,
         "Notify on every inbound SMS received"),
    Spec("notify_dispatch_errors", "bool", True, "Alerting", False,
         "Notify when an inbound webhook fails — otherwise the drop is silent"),
    Spec("telegram_replies_enabled", "bool", False, "Alerting", False,
         "Allow replying to a notification in Telegram to send an SMS back (takes effect after restart)"),
    Spec("instance_name", "str", "", "Alerting", False,
         "Label shown in notifications (blank = server hostname)"),
    Spec("inbound_dispatch", "routes", "", "Dispatch", False,
         'Inbound routes: JSON list, e.g. '
         '[{"prefix":"X","webhook_url":"https://...","bearer":"..."}]',
         route_key="prefix"),
    Spec("delivery_dispatch", "routes", "", "Dispatch", False,
         'Outbound status routes: JSON list, e.g. '
         '[{"app_id":"X","webhook_url":"https://...","bearer":"..."}]',
         route_key="app_id"),
    Spec("inbound_dispatch_retries", "int", 3, "Dispatch", False, "POST retries"),
    Spec("inbound_dispatch_timeout", "float", 10.0, "Dispatch", False, "POST timeout (s)"),
    # Both numbers coincide with ones the gateway already holds, by the owner's decision
    # of 18.09.2026, and the coincidence is the argument. Five minutes is
    # `delivery_timeout_seconds`: a verification that outlived the message carrying it
    # would sit open waiting on an outcome the sender had already abandoned. Five attempts
    # is `blacklist_threshold`: two different numbers for "enough" is two support answers
    # to one question.
    Spec("verification_ttl_seconds", "posint", 300, "Verification", False,
         "How long a verification stays open (s)"),
    # The ladder: which rungs are offered and in what order. Configuration rather than
    # compiled-in behaviour, because prices move, vendors are added and dropped, and an
    # operator that refuses delivery today may accept it next month — none of which should
    # need a deployment. The shipped order is the owner's decision of 18.09.2026 and is
    # recorded as a decision rather than a measurement. Changing it changes nothing about
    # what a route proves.
    Spec("verification_route_order", "str",
         "call_in,sms_out,flash_call,tg_gateway,sms_in", "Verification", False,
         "Rungs offered, cheapest first (comma-separated). A rung nothing can prove is "
         "never offered, whatever its place here"),
    # Bounds the precondition probes **as a whole**, not one by one: otherwise a slow day
    # at one vendor spends the budget the whole answer was promised in.
    Spec("verification_probe_timeout", "float", 5.0, "Verification", False,
         "Bound on the whole set of precondition probes (s)"),
    # How stale a proof may be before a person is sent down a route that no longer works.
    # Without a bound, "current evidence" is undefined: a reading taken once at boot would
    # satisfy the norm for ever, which is precisely the failure it exists to prevent.
    Spec("verification_proof_max_age_seconds", "posint", 300, "Verification", False,
         "Refuse a route whose precondition was last proven longer ago than this (s)"),
    # The `call_in` rung's own window, separately configurable and never longer than the
    # ladder's. Shorter is the point: the rung's residual risk scales with the window,
    # because an attacker can open a verification on a victim's number and, inside it,
    # give the victim a reason to call. The number itself is open — task 1.5 — so the
    # shipped value is the ladder's rather than an unmeasured guess.
    Spec("verification_call_in_ttl_seconds", "posint", 300, "Verification", False,
         "How long a call_in verification stays open (s); clamped to the ladder's"),
    # The number a subscriber calls or texts. The gateway does not otherwise hold its own
    # MSISDN anywhere, and both rungs this change adds have to tell the person where to
    # reach it — blank means neither rung can be offered, which is the honest answer.
    Spec("gateway_msisdn", "str", "", "Verification", False,
         "The gateway's own number, as the subscriber must dial or text it"),
    Spec("verification_max_attempts", "posint", 5, "Verification", False,
         "Wrong codes tolerated before a verification stops accepting any"),
    # The row holds a subscriber's number beside a code. Retention is why it does not hold
    # it for ever; `posint` because zero would delete verifications as fast as they are
    # made and present as a gateway that answers 404 to everyone.
    Spec("verification_retention_days", "posint", 30, "Verification", False,
         "Delete finished verifications after N days"),
    Spec("blacklist_threshold", "int", 5, "Limits", False, "Block a number after N permanent fails"),
    Spec("delivery_timeout_seconds", "int", 300, "Limits", False, "Mark 'sent' as 'expired' after N seconds"),
    # Measured, not guessed: over 1544 reported deliveries the mean report arrived 93
    # seconds after submission and the slowest took 13 hours, none over a day. The
    # negative verdict that prompted this change took 27 hours — what a permanent failure
    # costs while the network exhausts its retries first. Seven days is six times the
    # worst verdict this gateway has ever seen.
    #
    # `posint` rather than `int`, because zero discards every report the gateway receives
    # and would announce itself only as every message expiring. A setting whose worst
    # value looks like a network outage is one the settings layer refuses.
    Spec("delivery_report_max_age_hours", "posint", 168, "Limits", False,
         "Stop considering a delivery report once the part it names is older than N "
         "hours (the report is still recorded)"),
    # The only rule in this gateway that can refuse a delivery, so the only one with a
    # switch. Off, a contradicting recipient address is recorded and the report is
    # attributed as it would have been before; on, it eliminates. Flipped as a separate
    # decision against the ledger's own evidence, because turning a real delivery into an
    # expiry is worse than the defect it replaces.
    Spec("delivery_report_strict_attribution", "bool", False, "Limits", False,
         "Refuse a delivery report whose recipient address contradicts the only "
         "candidate (off = record the contradiction and attribute anyway)"),
    Spec("max_sms_parts", "int", 6, "Sending", False,
         "Max parts for a multipart SMS; longer text fails before sending"),
    Spec("send_retry_backoff", "delays", "30,120,300", "Sending", False,
         "Seconds to wait before each retry of a transient send failure; the number of "
         "delays sets the number of retries (blank = no retry, one attempt only)"),
    Spec("modem_watchdog_enabled", "bool", True, "Sending", False,
         "Auto-recover the modem when it loses network registration"),
    Spec("send_stall_recovery_enabled", "bool", True, "Sending", False,
         "Also treat repeated send failures as a reason to recover the modem "
         "(off = only lost registration triggers recovery)"),
    Spec("phone_region", "region", "RU", "Sending", False,
         "ISO country code for phone validation (e.g. RU, US, GB)"),
]

SPEC_BY_KEY: dict[str, Spec] = {s.key: s for s in SETTINGS_SPEC}

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off", ""}


def cast_value(type_: str, raw: str):
    """Convert a stored string to its typed value. Assumes `raw` already validated."""
    if type_ == "bool":
        return raw.strip().lower() in _TRUE
    if type_ == "int":
        return int(raw)
    if type_ == "posint":
        value = int(raw)
        if value <= 0:
            raise ValueError(f"must be a positive number: {value}")
        return value
    if type_ == "float":
        return float(raw)
    if type_ == "region":
        return raw.strip().upper()
    return raw


def validate_raw(type_: str, raw: str, route_key: str = "") -> None:
    """Raise ValueError if `raw` is not a valid value for `type_`.

    `route_key` names the field that identifies a route ("prefix" for inbound,
    "app_id" for delivery); it is required for the "routes" type.
    """
    if type_ == "bool":
        if raw.strip().lower() not in (_TRUE | _FALSE):
            raise ValueError(f"not a boolean: {raw!r}")
        return
    if type_ == "int":
        int(raw)
        return
    if type_ == "posint":
        if int(raw) <= 0:
            raise ValueError(f"must be a positive number: {raw!r}")
        return
    if type_ == "float":
        float(raw)
        return
    if type_ == "routes":
        if not route_key:
            raise ValueError("internal: route_key is required to validate routes")
        if raw.strip() == "":
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError("must be a JSON list of routes")
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                raise ValueError(f"route #{i + 1}: must be an object")
            key = str(item.get(route_key, "")).strip()
            url = str(item.get("webhook_url", "")).strip()
            if not key:
                raise ValueError(f"route #{i + 1}: {route_key} is required")
            if not url:
                raise ValueError(f"route #{i + 1} ({key}): webhook_url is required")
            # A url without a scheme (or with stray whitespace that hides one) is rejected
            # by httpx at POST time — i.e. silently, hours later. Catch it at save time.
            if not url.startswith(("http://", "https://")):
                raise ValueError(
                    f"route #{i + 1} ({key}): webhook_url must start with "
                    f"http:// or https:// — got {url!r}"
                )
        return
    if type_ == "delays":
        for part in raw.split(","):
            text = part.strip()
            if not text:            # a trailing or doubled comma is a typo, not an error
                continue
            try:
                seconds = int(text)
            except ValueError as exc:
                raise ValueError(
                    f"not a whole number of seconds: {text!r}"
                ) from exc
            if seconds <= 0:
                raise ValueError(f"delay must be positive: {seconds}")
        return
    if type_ == "region":
        import phonenumbers
        if raw.strip().upper() not in phonenumbers.SUPPORTED_REGIONS:
            raise ValueError(f"unknown region: {raw!r}")
        return
    return


_ROUTE_FIELDS = ("prefix", "app_id", "webhook_url", "bearer")


def _clean_route(item: dict) -> dict:
    """Strip surrounding whitespace off every route field (pasted values carry it)."""
    cleaned = dict(item)
    for field in _ROUTE_FIELDS:
        if field in cleaned:
            cleaned[field] = str(cleaned[field]).strip()
    return cleaned


def normalize_raw(type_: str, raw: str) -> str:
    """Canonical stored form of `raw`. Only "routes" is rewritten: route fields are
    stripped, so a pasted " https://…" cannot reach httpx."""
    if type_ != "routes" or raw.strip() == "":
        return raw
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw                              # validate_raw reports it
    if not isinstance(data, list):
        return raw
    cleaned = [_clean_route(i) if isinstance(i, dict) else i for i in data]
    return json.dumps(cleaned, ensure_ascii=False)


def to_str(type_: str, value) -> str:
    """Serialize a typed default to its stored-string form."""
    if type_ == "bool":
        return "true" if value else "false"
    return str(value)

class SettingsStore:
    """In-memory cache over the `settings` table with typed accessors.

    Getters are synchronous cache reads. `load()` is awaited once at startup;
    `set_many()` writes all changes in one transaction, then updates the cache and
    fires change hooks. A missing key falls back to its SETTINGS_SPEC default.
    """

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self._hooks: dict[str, list[Callable[[], None]]] = {}

    async def load(self) -> None:
        db = await get_db()
        new_cache: dict[str, str] = {}
        async with db.execute("SELECT key, value FROM settings") as cur:
            async for row in cur:
                new_cache[row["key"]] = row["value"]
        self._cache = new_cache

    def on_change(self, section: str, callback: Callable[[], None]) -> None:
        self._hooks.setdefault(section, []).append(callback)

    def get(self, key: str):
        if key not in SPEC_BY_KEY:
            raise KeyError(f"unknown setting key: {key!r}")
        spec = SPEC_BY_KEY[key]
        if key in self._cache and self._cache[key] is not None:
            try:
                return cast_value(spec.type, self._cache[key])
            except (ValueError, TypeError):
                # Only "posint" degrades rather than raising. A stored value that cannot
                # be read as a positive integer must not be taken literally: the one such
                # setting bounds which delivery reports are considered, and reading a
                # broken row as zero would discard every report the gateway receives.
                if spec.type != "posint":
                    raise
                logger.warning(
                    "Setting %s holds %r, which is not a positive integer; using the "
                    "default of %s", key, self._cache[key], spec.default,
                )
                return spec.default
        return spec.default

    def __getattr__(self, name: str):
        if name in SPEC_BY_KEY:
            return self.get(name)
        raise AttributeError(name)

    def _routes(self, key: str) -> list[dict]:
        """Usable routes for a "routes" setting: stripped, and missing the identifying
        field or the url means dropped. Stripping happens on read as well as on write,
        so rows stored before normalization existed still route."""
        spec = SPEC_BY_KEY[key]
        raw = self.get(key)
        if not raw or not raw.strip():
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        routes = [_clean_route(item) for item in data if isinstance(item, dict)]
        return [r for r in routes if r.get(spec.route_key) and r.get("webhook_url")]

    @property
    def inbound_dispatch_parsed(self) -> list[dict]:
        return self._routes("inbound_dispatch")

    @property
    def delivery_dispatch_parsed(self) -> list[dict]:
        return self._routes("delivery_dispatch")

    @property
    def send_retry_backoff_parsed(self) -> list[int]:
        """Delays before each retry. Empty means a message gets a single attempt."""
        raw = self.get("send_retry_backoff") or ""
        return [int(t) for t in (p.strip() for p in raw.split(",")) if t]

    async def set_many(self, changes: dict[str, str]) -> None:
        for key in changes:
            if key not in SPEC_BY_KEY:
                raise ValueError(f"unknown setting: {key}")
        changes = {k: normalize_raw(SPEC_BY_KEY[k].type, v) for k, v in changes.items()}
        for key, raw in changes.items():
            spec = SPEC_BY_KEY[key]
            validate_raw(spec.type, raw, spec.route_key)
        db = await get_db()
        try:
            for key, raw in changes.items():
                await db.execute(
                    """
                    INSERT INTO settings (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value, updated_at = CURRENT_TIMESTAMP
                    """,
                    (key, raw),
                )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        for key, raw in changes.items():
            self._cache[key] = raw
        sections = {SPEC_BY_KEY[k].section for k in changes}
        for section in sections:
            for cb in self._hooks.get(section, []):
                cb()


store = SettingsStore()


async def seed_from_env() -> None:
    """One-time migration: for each spec key with no row yet, insert the env value
    (UPPERCASE name) if set, else the code default. Existing rows are never touched."""
    db = await get_db()
    async with db.execute("SELECT key FROM settings") as cur:
        existing = {row["key"] async for row in cur}
    to_insert = []
    for spec in SETTINGS_SPEC:
        if spec.key in existing:
            continue
        env_val = os.environ.get(spec.key.upper())
        raw = env_val if env_val is not None else to_str(spec.type, spec.default)
        to_insert.append((spec.key, raw))
    for key, raw in to_insert:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)", (key, raw)
        )
    await db.commit()
