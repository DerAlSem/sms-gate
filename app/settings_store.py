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
                       # | "oproutes" | "templates" | "region" | "delays"
    default: object
    section: str
    is_secret: bool
    description: str
    route_key: str = ""   # "routes" only: the field identifying a route


def _shipped_rule() -> str:
    """The rule's shipped content, fetched late.

    `app.verification.rule` reads this store, so importing it at module scope would close
    a cycle. The default is wanted here all the same: a spec whose default lived anywhere
    else would let `seed_from_env` write a rule nobody wrote.
    """
    from app.verification import rule
    return rule.SHIPPED


def _shipped_templates() -> str:
    """The templates' shipped content, fetched late, for the reason above."""
    from app.verification import template
    return template.SHIPPED


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
    # On by default, unlike `notify_send_errors`. What it reports is not a send failing
    # but a way out being refused or skipped — and the skip is the one that shows up
    # only as a bill on the rung below it.
    Spec("notify_routing_errors", "bool", True, "Alerting", False,
         "Notify when a route is refused, unreadable or cannot be attempted"),
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
    # The ladder's acceptance bound, and it covers the ladder **as a whole** rather than
    # each rung: otherwise two rungs on a slow day take twice the time the application was
    # promised, and the application is holding a person at a barrier for all of it. Its own
    # setting rather than a share of `verification_probe_timeout`, because the two bound
    # different things — that one bounds asking whether a rung *could* carry, this one
    # bounds actually carrying, and only this one has money behind it.
    #
    # 🔴 Ten seconds is a ceiling rather than an expectation, and the two numbers behind it
    # are measured. The Gateway answers in 178–285 ms over the wired path (task 1.7, read
    # 20.09.2026), so a ladder of two rungs each doing a check and a send is about a second
    # — roughly tenfold headroom. What the ceiling is actually for is the other measurement:
    # on a failed-over uplink `gatewayapi.telegram.org` times out at **fifteen** seconds
    # (18.09.2026, task 1.12), which is longer than any answer an application should be made
    # to wait for. Cutting at ten is what makes that case bounded rather than a hang, and it
    # is the one case where this setting decides anything at all.
    Spec("verification_ladder_bound", "float", 10.0, "Verification", False,
         "Bound on the whole ladder once a rung is selected (s) — one bound for every "
         "rung together, never one each"),
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
    # The Telegram Gateway rung's access token. Secret on the same terms as
    # `alert_bot_token`, and blank by default because blank is the honest state of an
    # unconfigured estate: the rung is then never offered, which is a refusal rather
    # than a rung that fails at the vendor after the gates have been spent.
    Spec("tg_gateway_token", "str", "", "Verification", True,
         "Telegram Gateway API access token (blank = the tg_gateway rung is never offered)"),
    # How far a signed callback's own timestamp may be from ours before it is refused as
    # a replay. `posint` because zero would refuse every callback the vendor ever sends
    # and present as a vendor that stopped reporting deliveries.
    Spec("tg_gateway_callback_tolerance_seconds", "posint", 300, "Verification", False,
         "Refuse a signed Gateway callback whose timestamp is further than this from "
         "now (s)"),
    # The row holds a subscriber's number beside a code. Retention is why it does not hold
    # it for ever; `posint` because zero would delete verifications as fast as they are
    # made and present as a gateway that answers 404 to everyone.
    Spec("verification_retention_days", "posint", 30, "Verification", False,
         "Delete finished verifications after N days"),
    # The vendor's numbers, not ours, and therefore settings: uCaller allows four
    # authorisations per number per minute with at least fifteen seconds between them and
    # thirty per number per day, and a number that exceeds them is blocked **for ten
    # hours**. Being told to wait fifteen seconds costs a person fifteen seconds; being
    # blocked at the vendor costs them a working day of not being able to log in.
    #
    # They bound the ladder as a whole rather than the call rung alone. Telegram's
    # reference publishes no rate limits at all, and silence is the absence of a
    # statement rather than a statement of absence — a rung whose block conditions are
    # unpublished is the one to be more careful with.
    Spec("verification_min_gap_seconds", "posint", 15, "Verification", False,
         "Least time between two paid attempts on one number (s)"),
    Spec("verification_per_minute", "posint", 4, "Verification", False,
         "Paid attempts allowed on one number per rolling minute"),
    Spec("verification_per_day", "posint", 30, "Verification", False,
         "Paid attempts allowed on one number per rolling day"),
    # Rolling, and stated rather than implied. This database stores naive UTC and the
    # vendor is Russian: a calendar day read in the wrong zone resets three hours early,
    # and in those three hours the gateway confidently places the call that costs the
    # subscriber ten hours. A rolling window is the stricter reading of any calendar day.
    Spec("verification_day_window_hours", "posint", 24, "Verification", False,
         "The window the daily ceiling counts in, rolling backwards from now (h)"),
    # The spend ceiling: how many paid rungs this gateway may attempt in total, across
    # every number, every application and both paid routes together. A different
    # instrument from the per-number limits above, which are the vendors' and are per
    # number — a loop over five hundred numbers violates none of them while spending four
    # hundred roubles.
    #
    # 🔴 The shipped numbers are measured rather than chosen, on this gateway's own live
    # traffic: 2391 messages between 17.04.2026 and 20.09.2026, of which 601 went to
    # МегаФон — the operator whose traffic the paid ladder carries. Read on 20.09.2026
    # with both spellings matched by hand, because `upper()` is ASCII-only here and would
    # have counted 397 of the 601. The busiest МегаФон hour in five months held 20
    # messages and the busiest day 47; a verification may consume **two** paid rungs by
    # advancing from Telegram to the call, so the worst honest load ever seen is about 40
    # attempts an hour and 94 a day.
    #
    # So: a ceiling that does not refuse the busiest real hour this gateway has ever had,
    # even doubled, and still stops a runaway loop within minutes rather than at the
    # four-hundred-rouble bill the requirement is written against.
    Spec("verification_paid_per_hour", "posint", 100, "Verification", False,
         "Paid rungs this gateway may attempt per rolling hour, across all numbers, "
         "applications and both paid routes together"),
    Spec("verification_paid_per_day", "posint", 300, "Verification", False,
         "Paid rungs this gateway may attempt per rolling day, across all numbers, "
         "applications and both paid routes together"),
    # The balance floors: one per prepaid vendor, never a floor over the sum. A single
    # floor over the total would be satisfied by one funded account while the other is
    # empty, and the empty one is a rung of the same ladder.
    #
    # 🔴 Telegram's balance cannot be polled: `remaining_balance` is the account's
    # balance only in the answer to a **confirming** ability check, which is the billed
    # call (measured 20.09.2026 — the same request answered 99.99 on the check and 0 on
    # the send that followed). So the floor is held against the reading that arrives with
    # ordinary traffic, and the shipped value is stated in the vendor's own units rather
    # than in a currency this gateway has never been told: one confirmation cost 0.01 in
    # those units, so a floor of 10 is about a thousand verifications of warning.
    Spec("tg_gateway_balance_floor", "float", 10.0, "Verification", False,
         "Alert when the Telegram Gateway balance last reported falls below this "
         "(in the vendor's own units; read from confirming ability checks, never polled)"),
    # Zero, and deliberately: this rung has no account yet (task 1.1) and no observed
    # cost, so any number here would be a guess dressed as a setting. Zero is not read as
    # "the balance is fine" — a balance arriving for a rung with no floor is logged as a
    # vendor nobody is watching, which is what it is until the account exists.
    Spec("flash_call_balance_floor", "float", 0.0, "Verification", False,
         "Alert when the uCaller balance falls below this (0 = not configured; the "
         "account does not exist yet, and a reading with no floor is reported as such)"),
    # The routing rule, as data. Its shipped content and every norm about reading it live
    # in `app/verification/rule.py`; what belongs here is that it is a setting at all —
    # `.env` would need a restart to change, and a restart drops sending sessions, which
    # is the deploy the rule exists to avoid, merely spelled differently. Not carried by
    # `delivery_dispatch`, which requires a webhook URL on every entry and would reject
    # this rule outright.
    # How long the **sender** may wait for an operator it has no row for, before the
    # rule's unknown-operator entry answers instead. Its own setting rather than a share
    # of `voxlink_timeout`, because the two bound different decisions: that one is how
    # patient one HTTP call is, this one is how long a message may sit in a single-file
    # queue while the gateway works out which way out it takes. Spent only on a number
    # with no operator at all — a stale row still names one, and refreshing it changes
    # no route.
    Spec("operator_lookup_bound", "float", 5.0, "Routing", False,
         "How long the sender waits for an unknown recipient's operator before routing "
         "by the rule's \"?\" entry (seconds; the lookup keeps running either way)"),
    Spec("operator_routes", "oproutes", _shipped_rule(), "Routing", False,
         'Which way out each operator\'s traffic takes: JSON list, e.g. '
         '[{"operator":"МегаФон","routes":["tg_gateway","flash_call"]},'
         '{"operator":"*","routes":["sms_out"]},{"operator":"?","routes":["sms_out"]}] '
         "— \"*\" answers for an operator with no entry, \"?\" for one that could not "
         "be resolved, and \"refuse\" is a way of declining rather than a way out"),
    # The text an `sms_out`-carried code arrives in, per application. Its norms and its
    # save-time validation live in `app/verification/template.py`; what belongs here is
    # that it is a setting at all, and that its default is **empty**. An estate with no
    # templates refuses every `sms_out`-carried code, which is the honest state: the
    # alternative is wording nobody chose going out under somebody's name. Not carried by
    # `delivery_dispatch`, which requires a webhook URL on every entry.
    Spec("verification_templates", "templates", _shipped_templates(), "Verification", False,
         'The text of an sms_out-carried code, per application: JSON list, e.g. '
         '[{"app_id":"sp_app","template":"SokolParking: {code}"}] — exactly one '
         "{code} per template, and an application with no entry is refused an "
         "sms_out-carried code rather than given wording of the gateway's own"),
    # How long an entry of the routing rule may stay in force before the gateway says it
    # has not been revisited. The rule's own requirement asks for a way to observe
    # recovery, and this is the half that costs nothing: the other — a rate-bounded probe
    # send over the withdrawn route — puts a real message in front of a real person.
    #
    # Thirty days because the event the rule exists for is an operator's withdrawal, and
    # those are settled or escalated on the scale of a month, not of a week. `posint`
    # because zero would report every entry on every tick from the moment it was written,
    # which is the shape that teaches an operator to ignore the channel.
    Spec("operator_route_review_days", "posint", 30, "Routing", False,
         "Report a routing-rule entry that has been in force this many days without "
         "being revisited — a rule set during an outage outlives the outage"),
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
    if type_ == "oproutes":
        from app.verification import rule
        rule.validate(raw)
        return
    if type_ == "templates":
        from app.verification import template
        template.validate(raw)
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
    """Canonical stored form of `raw`. Two types are rewritten: "routes" has its route
    fields stripped, so a pasted " https://…" cannot reach httpx, and "oproutes" has its
    operator names and route names stripped, so a pasted name is stored as it will be
    matched rather than matched around for ever."""
    if type_ == "oproutes":
        from app.verification import rule
        return rule.normalize(raw)
    if type_ == "templates":
        from app.verification import template
        return template.normalize(raw)
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
