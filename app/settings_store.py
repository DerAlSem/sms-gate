from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable

from app.db.connection import get_db


@dataclass(frozen=True)
class Spec:
    key: str
    type: str          # "bool" | "int" | "float" | "str" | "routes" | "region"
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
    Spec("notify_system_errors", "bool", True, "Alerting", False,
         "Send ERROR-level log records (crashes, exceptions) to Telegram"),
    Spec("notify_send_errors", "bool", False, "Alerting", False,
         "Notify when an outbound SMS fails to send"),
    Spec("notify_delivery_errors", "bool", False, "Alerting", False,
         "Notify on delivery failure or when a number is blacklisted"),
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
    Spec("blacklist_threshold", "int", 5, "Limits", False, "Block a number after N permanent fails"),
    Spec("delivery_timeout_seconds", "int", 300, "Limits", False, "Mark 'sent' as 'expired' after N seconds"),
    Spec("max_sms_parts", "int", 6, "Sending", False,
         "Max parts for a multipart SMS; longer text fails before sending"),
    Spec("modem_watchdog_enabled", "bool", True, "Sending", False,
         "Auto-recover the modem when it loses network registration"),
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
            return cast_value(spec.type, self._cache[key])
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
