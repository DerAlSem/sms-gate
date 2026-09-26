"""How the settings screen groups `SETTINGS_SPEC` for display — SG-33.2.

`Spec.section` (in `app/settings_store.py`) is never touched by this module: it is what
`store.set_many` reads to fire a change hook (e.g. reconfiguring alerting), and two
settings that must be reconfigured together can legitimately belong on two different
pages of this screen. This module is a pure display grouping on top of it — the owner's
own tasks ("set up alerting", "check the money limits") rather than the code's internal
sections.

`N_` marks a string for extraction without translating it now: `babel.cfg` already walks
`app/admin/**.py` for Python strings, and `N_` is one of pybabel's default keywords. The
English text is the msgid; its Russian goes into `messages.po`, filled by hand (see
`docs/i18n.md`). Every label and help string here is `N_`-wrapped for that reason, and
none of them is translated in this module — only where a template calls `_()` on it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.settings_store import Spec, SPEC_BY_KEY, cast_value, to_str, store
from app.verification.routes import (
    APP_BOT, CALL_IN, FLASH_CALL, MAX_USER, SMS_IN, SMS_OUT, TG_GATEWAY, TG_USER,
)

N_ = lambda s: s  # noqa: E731 — a marker for pybabel, not a real translation call

# The rungs a form-mode picker offers, in the shipped ladder's own order (see
# `verification_route_order`'s default and `app.verification.routes.ALL_ROUTES`) — not
# alphabetical, so that "cheapest first" is legible in the picker too, not only in the
# comma-separated value it edits. The label is `N_`-wrapped for the same reason every
# other label in this module is: the template translates it, this module never does.
RUNGS: tuple[tuple[str, str], ...] = (
    (CALL_IN, N_("Subscriber's call to our number")),
    (SMS_IN, N_("Subscriber's SMS to our number")),
    (SMS_OUT, N_("SMS carrying the code")),
    (FLASH_CALL, N_("Flash call (uCaller)")),
    (TG_GATEWAY, N_("Telegram Gateway")),
    (TG_USER, N_("Telegram account")),
    (MAX_USER, N_("MAX account")),
    (APP_BOT, N_("Application's bot")),
)


@dataclass(frozen=True)
class FieldLayout:
    key: str
    label: str          # N_(...) msgid
    help: str           # N_(...) msgid
    # SG-33.4: this key still lives in SETTINGS_SPEC and is still counted by the
    # "every key in exactly one section" sentry, but the owner edits it on the
    # application's own page (`/admin/apps/<id>`), not here. The settings screen
    # renders a pointer instead of an input, and never puts the key in its POST.
    app_owned: bool = False


@dataclass(frozen=True)
class Section:
    id: str              # latin, used as the anchor and as `_section` on save
    title: str           # N_(...) msgid
    collapsed: bool
    fields: tuple[FieldLayout, ...] = field(default_factory=tuple)


def _f(key: str, label: str, help_: str, app_owned: bool = False) -> FieldLayout:
    return FieldLayout(key=key, label=label, help=help_, app_owned=app_owned)


SECTIONS: tuple[Section, ...] = (
    Section("sending", N_("Modem and sending"), False, (
        _f("max_sms_parts", N_("Max parts per multipart SMS"),
           N_("How many parts one SMS may be split into. Longer text is refused before "
              "sending, rather than sent cut short.")),
        _f("send_retry_backoff", N_("Retry delays for a failed send"),
           N_("How many seconds to wait before each retry after a transient send failure. "
              "As many delays as retries. None at all means one attempt only, no "
              "retry.")),
        _f("modem_watchdog_enabled", N_("Auto-recover the modem"),
           N_("Automatically recover the modem when it loses network registration.")),
        _f("send_stall_recovery_enabled", N_("Recover on repeated send failures too"),
           N_("Also treat repeated send failures as a reason to recover the modem. Off "
              "means only lost registration triggers recovery.")),
        _f("phone_region", N_("Default country for phone numbers"),
           N_("ISO country code used to validate phone numbers, e.g. RU, US, GB.")),
        _f("delivery_timeout_seconds", N_("Give up waiting for delivery after"),
           N_("Seconds after which a message stuck as \"sent\" is marked \"expired\".")),
        _f("blacklist_threshold", N_("Block a number after this many failures"),
           N_("How many permanent failures in a row before a number is blocked.")),
    )),
    Section("alerts", N_("Telegram alerts"), False, (
        _f("alert_bot_token", N_("Telegram bot token"),
           N_("The alerting bot's own API token. Blank disables Telegram alerting "
              "entirely.")),
        _f("alert_chat_id", N_("Where alerts go — the Telegram chat"),
           N_("The chat id alerts are sent to.")),
        _f("instance_name", N_("Name shown in notifications"),
           N_("Label shown in every notification, so alerts from several gateways can be "
              "told apart. Blank uses the server's hostname.")),
        _f("notify_system_errors", N_("Notify on system errors"),
           N_("Send crashes and exceptions (error-level log records) to Telegram.")),
        _f("notify_send_errors", N_("Notify when a send fails"),
           N_("Notify when an outbound SMS fails to send.")),
        _f("notify_delivery_errors", N_("Notify on delivery failure"),
           N_("Notify on a delivery failure, or when a number is blacklisted.")),
        _f("notify_unplaced_reports", N_("Notify on an unmatched delivery report"),
           N_("Notify when a delivery report could not be matched to any message. The "
              "report itself is recorded either way.")),
        _f("notify_inbound", N_("Notify on every inbound SMS"),
           N_("Notify on every inbound SMS received. Can be noisy on a busy gateway.")),
        _f("notify_dispatch_errors", N_("Notify when an inbound webhook fails"),
           N_("Notify when delivering an inbound SMS to the application's webhook fails "
              "— otherwise the drop is silent.")),
        _f("notify_routing_errors", N_("Notify when a route is refused"),
           N_("Notify when a route is refused, unreadable, or cannot be attempted at "
              "all.")),
        _f("telegram_replies_enabled", N_("Allow replying to alerts to send an SMS"),
           N_("Reply to a notification in Telegram to send an SMS back. Takes effect "
              "after a restart.")),
    )),
    Section("verification", N_("Number verification"), False, (
        _f("verification_route_order", N_("Order of verification rungs"),
           N_("Rungs are tried top to bottom, cheapest first. A rung nothing can prove "
              "is never offered, wherever it stands.")),
        _f("gateway_msisdn", N_("The gateway's own phone number"),
           N_("The number a subscriber must call or text. Blank means the rungs that "
              "need it are never offered.")),
        _f("verification_ttl_seconds", N_("How long a verification stays open"),
           N_("Seconds before an open verification expires.")),
        _f("verification_call_in_ttl_seconds", N_("How long the call-in rung stays open"),
           N_("Seconds a call_in verification stays open; capped by how long the "
              "verification itself stays open, above.")),
        _f("verification_max_attempts", N_("Wrong codes allowed"),
           N_("How many wrong codes are tolerated before a verification stops accepting "
              "any.")),
        _f("verification_templates", N_("SMS wording for verification codes"),
           N_("Set on each application's own page (Apps), not here — an application "
              "with no template there never gets a code by SMS."), app_owned=True),
    )),
    Section("routing", N_("Routes by operator"), False, (
        _f("operator_routes", N_("Which way out each operator takes"),
           N_("Rungs are tried top to bottom for each operator. \"Any other operator\" "
              "answers for one with no row of its own; \"Not resolved\" answers when the "
              "operator could not be told at all; \"Refuse\" means not sending at "
              "all.")),
        _f("operator_route_review_days", N_("Flag a routing rule after this many days"),
           N_("Report a routing-rule entry that has stood this many days without being "
              "revisited — a rule set during an outage can outlive it.")),
        _f("voxlink_enabled", N_("Look up the operator for a number"),
           N_("Enable looking up a number's operator and region.")),
    )),
    Section("vendors", N_("Vendors"), False, (
        _f("tg_gateway_token", N_("Telegram Gateway API token"),
           N_("Access token for the Telegram Gateway verification rung. Blank means "
              "that rung is never offered.")),
        _f("tg_gateway_sender_username", N_("Telegram Gateway sender channel"),
           N_("Username of the verified Telegram channel codes are sent from. Blank "
              "uses the vendor's own sender.")),
        _f("tg_gateway_callback_base", N_("This gateway's public address for delivery "
                                          "reports"),
           N_("This gateway's own public HTTPS address, so the Telegram Gateway can "
              "report deliveries back to it, e.g. https://sms.example.org. Blank means "
              "no delivery reports and no refunds are ever recorded.")),
        _f("ucaller_key", N_("uCaller secret key"),
           N_("The secret key half of the uCaller credential, from the cabinet under "
              "\"Мои сервисы\". Blank means the flash_call rung is never offered.")),
        _f("ucaller_service_id", N_("uCaller service id"),
           N_("The service id half of the uCaller credential, the second half of the "
              "pair above.")),
        _f("messenger_brands", N_("Messenger accounts and brands"),
           N_("JSON: the account each brand owns on each messenger. Which application "
              "may send under which brand is set on that application's own page "
              "(Apps), not here.")),
        _f("messenger_limits", N_("Messenger sending limits"),
           N_("JSON: hourly and daily sending maxima per account, and the minimum time "
              "between two messages to the same recipient.")),
    )),
    Section("money", N_("Money limits and protection"), False, (
        _f("verification_paid_per_hour", N_("Paid verifications allowed per hour"),
           N_("How many paid rungs (call or Telegram) this gateway may attempt per "
              "rolling hour, across every number and application together.")),
        _f("verification_paid_per_day", N_("Paid verifications allowed per day"),
           N_("How many paid rungs this gateway may attempt per rolling day, across "
              "every number and application together.")),
        _f("tg_gateway_balance_floor", N_("Alert below this Telegram Gateway balance"),
           N_("Alert when the last-seen Telegram Gateway balance falls below this, in "
              "the vendor's own units.")),
        _f("flash_call_balance_floor", N_("Alert below this uCaller balance"),
           N_("Alert when the uCaller balance falls below this. 0 means not configured "
              "— there is no account to watch yet.")),
        _f("verification_min_gap_seconds", N_("Minimum time between two paid attempts"),
           N_("Seconds that must pass between two paid verification attempts on the "
              "same number.")),
        _f("verification_per_minute", N_("Paid attempts per number per minute"),
           N_("How many paid attempts one number may have within a rolling minute.")),
        _f("verification_per_day", N_("Paid attempts per number per day"),
           N_("How many paid attempts one number may have within a rolling day.")),
    )),
    Section("webhooks", N_("Webhooks"), False, (
        _f("inbound_dispatch", N_("Inbound SMS webhooks"),
           N_("Where an inbound SMS goes: by the text's prefix, to an application's "
              "webhook.")),
        _f("delivery_dispatch", N_("Delivery status webhooks"),
           N_("Set on each application's own page (Apps), not here."), app_owned=True),
    )),
    Section("advanced", N_("Advanced"), True, (
        _f("alert_dedup_window", N_("Suppress repeated identical alerts for"),
           N_("Seconds during which an identical alert is not sent again.")),
        _f("alert_relay_base", N_("Backup relay for alerts"),
           N_("Base URL of a relay that can reach Telegram when this host cannot. "
              "Tried first; the direct route is the fallback. Blank disables the "
              "relay.")),
        _f("inbound_dispatch_retries", N_("Webhook POST retries"),
           N_("How many times delivery of an inbound webhook is retried.")),
        _f("inbound_dispatch_timeout", N_("Webhook POST timeout"),
           N_("Seconds to wait for a webhook POST to answer.")),
        _f("verification_probe_timeout", N_("Precondition probe budget"),
           N_("Seconds allowed for the whole set of precondition probes together, "
              "before offering a rung.")),
        _f("verification_ladder_bound", N_("Verification ladder time budget"),
           N_("Seconds allowed for the whole ladder once a rung has been selected — "
              "one bound for every rung together, never one each.")),
        _f("verification_proof_max_age_seconds", N_("How stale a proof may be"),
           N_("Refuse a route whose precondition was last proven longer ago than this, "
              "in seconds.")),
        _f("verification_retention_days", N_("Keep finished verifications for"),
           N_("Delete finished verifications after this many days.")),
        _f("verification_day_window_hours", N_("Length of the daily ceiling window"),
           N_("The window the daily paid-attempt ceilings count in, rolling backwards "
              "from now, in hours.")),
        _f("tg_gateway_callback_tolerance_seconds",
           N_("Callback signature time tolerance"),
           N_("Refuse a signed Telegram Gateway callback whose timestamp is further "
              "than this from now, in seconds — guards against replay.")),
        _f("operator_lookup_bound", N_("Operator lookup time budget"),
           N_("How long the sender waits for an unknown recipient's operator before "
              "routing by the rule's \"?\" entry, in seconds. The lookup itself keeps "
              "running either way.")),
        _f("voxlink_url", N_("Operator lookup endpoint"),
           N_("The URL used to look up a number's operator and region.")),
        _f("voxlink_timeout", N_("Operator lookup timeout"),
           N_("Seconds allowed for one operator-lookup request.")),
        _f("voxlink_cache_ttl_days", N_("Re-check an operator after"),
           N_("Days after which a cached operator/region lookup is refreshed.")),
        _f("delivery_report_max_age_hours", N_("Ignore delivery reports older than"),
           N_("Stop considering a delivery report once the message it names is older "
              "than this many hours. The report is still recorded.")),
        _f("delivery_report_strict_attribution",
           N_("Refuse contradicting delivery reports"),
           N_("Refuse a delivery report whose recipient address contradicts the only "
              "candidate message, instead of recording the contradiction and "
              "attributing it anyway.")),
    )),
)

FIELD_BY_KEY: dict[str, FieldLayout] = {
    f.key: f for section in SECTIONS for f in section.fields
}
# Keys the settings screen shows as a pointer rather than an input — see
# `FieldLayout.app_owned`.
APP_OWNED_KEYS: frozenset[str] = frozenset(
    f.key for section in SECTIONS for f in section.fields if f.app_owned
)
SECTION_BY_ID: dict[str, Section] = {s.id: s for s in SECTIONS}
SECTION_ID_OF_KEY: dict[str, str] = {
    f.key: s.id for s in SECTIONS for f in s.fields
}


def is_changed(spec: Spec) -> bool:
    """Whether `spec`'s stored value differs from its shipped default.

    A secret is "changed" if it is set at all — its value is never compared, never
    even read into this process's memory for that purpose; `store.get` on a secret
    already answers whether one is configured. Every other type is compared through
    `cast_value`, the same normaliser `SettingsStore.get` itself uses, so a stored
    value spelled differently from the default (e.g. "TRUE" vs "true") still reads as
    unchanged when it means the same thing; the JSON-carrying types fall through to a
    plain string and are compared stripped, which is the type they are held as either
    way.
    """
    if spec.is_secret:
        return bool(store.get(spec.key))
    current = store.get(spec.key)
    default = cast_value(spec.type, to_str(spec.type, spec.default))
    if isinstance(current, str) and isinstance(default, str):
        return current.strip() != default.strip()
    return current != default


def tg_account_overview() -> dict:
    """What the settings screen's "Telegram account" card needs, read live.

    Never returns a credential's value — only whether the three environment variables
    are set, and free-text reasons from `tg_user_carrier.unwired_reason`, which may
    name a session file path (not a secret) but never a token or hash. Any failure
    while reading this is caught here: the settings page must render even when brands,
    the store or the carrier cannot be read, which is the one thing this card must
    never cost the rest of the screen.
    """
    from app.config import settings

    result: dict = {
        "api_id_set": bool(settings.tg_api_id),
        "api_hash_set": bool(settings.tg_api_hash),
        "session_dir_set": bool(settings.tg_session_dir),
        "route_order_has_tg_user": False,
        "apps": [],          # [{"app_id": ..., "reason": str | None}], reason=None -> wired
        "wired_count": 0,
        "ok": False,
        # Raw, untranslated reason text (from `unwired_reason`, or None): the fixed part
        # of the sentence around it is translated in the template; this is not, because
        # it is a diagnostic sentence composed at read time, not a fixed msgid.
        "blocking_reason": None,
        "no_apps": False,
        "error": None,
    }
    try:
        from app.verification.tg_user_carrier import unwired_reason

        order = [r.strip() for r in (store.verification_route_order or "").split(",")]
        result["route_order_has_tg_user"] = "tg_user" in order

        cfg = store.messenger_brands_parsed
        app_ids = sorted((cfg.get("apps") or {}).keys())
        for app_id in app_ids:
            reason = unwired_reason(app_id)
            if reason == "":
                continue        # no account at all for this app — not this card's business
            result["apps"].append({"app_id": app_id, "reason": reason})

        # The rung is per application: one wired application is enough for it to be on,
        # and an unwired one beside it is a partial state, not an off one — the per-app
        # rows name which. A reason is the headline only when no application is wired.
        result["wired_count"] = sum(1 for a in result["apps"] if a["reason"] is None)
        result["blocking_reason"] = next(
            (a["reason"] for a in result["apps"] if a["reason"]), None)
        result["no_apps"] = not result["apps"]
        result["ok"] = result["route_order_has_tg_user"] and result["wired_count"] > 0
    except Exception as exc:  # the card must not take the settings page down with it
        result["error"] = str(exc)
    return result
