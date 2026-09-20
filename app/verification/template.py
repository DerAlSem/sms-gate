"""The text an SMS-carried code arrives in, configured per application.

There is no built-in default and the gateway composes no wording of its own. That is the
owner's decision of 18.09.2026, and the reason is that a default is a wording decision
taken silently on behalf of applications that do not share a voice: `sp_app` signs every
message `SokolParking:` — 446 of 448 since 01.08 — while the others are free text under
other names. A person reading a code signed by something they do not recognise treats it
as the fraud it resembles.

Configured in the manner `delivery_dispatch` configures a dispatch route per application:
a typed `settings` entry holding a list keyed on `app_id`, changeable without a restart.
Not carried *by* `delivery_dispatch`, which requires a `webhook_url` on every entry and
would reject a template outright.

Three norms, and each is here rather than at compose time:

**Exactly one placeholder, and it is the code.** A template carrying none sends a person
a message with nothing in it to type; carrying it twice shows them two numbers and no way
to tell which; carrying an unknown one is a typo that survives until someone reads a
message. All three are knowable when the value is saved, and by compose time the request
has passed the entitlement and the ceiling and may already have bought a rung.

**An application named twice is refused.** Which of the two entries wins would otherwise
be decided by the order of the list, invisibly — the same argument the routing rule makes
about two spellings of one operator.

**An unreadable setting is never read as an absent template.** Absent refuses the
application, which is loud and recoverable. Read as empty it would send the code into
whatever the compose step does with an empty string, which is neither.

This governs the `sms_out` route only. `tg_gateway` takes a `code` and no text of ours,
and `flash_call` carries no text at all, so an application with no template is still
served by those rungs: the refusal follows the rung, not the application.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

KEY = "verification_templates"

# The one thing a template may interpolate, spelled as `str.format` spells it.
CODE = "code"

# Every `{...}` in the text, including the empty and the misspelled ones, so that an
# unknown placeholder is *named* in the refusal rather than counted as absent.
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")

# The shipped content: none. An estate with no templates configured is an estate whose
# applications are refused an `sms_out`-carried code, and that is the honest state — the
# alternative is wording nobody chose going out under somebody's name.
SHIPPED = ""


class UnreadableTemplates(Exception):
    """The stored setting is not a list of templates. Never an absence of templates."""


def _entry(item: object, index: int) -> tuple[str, str]:
    """One validated entry, or ValueError naming which one and why."""
    where = f"template #{index + 1}"
    if not isinstance(item, dict):
        raise ValueError(f"{where}: must be an object")
    app_id = str(item.get("app_id", "")).strip()
    if not app_id:
        raise ValueError(f"{where}: app_id is required")
    text = str(item.get("template", ""))
    if not text.strip():
        raise ValueError(
            f"{where} ({app_id}): template is required — an application with no text is "
            f"configured by having no entry, not by having a blank one")
    found = _PLACEHOLDER.findall(text)
    unknown = [name for name in found if name.strip() != CODE]
    if unknown:
        raise ValueError(
            f"{where} ({app_id}): unknown placeholder "
            f"{', '.join(repr('{' + n + '}') for n in unknown)} — the only one a template "
            f"may carry is {'{' + CODE + '}'}")
    if len(found) == 0:
        raise ValueError(
            f"{where} ({app_id}): the template carries no {'{' + CODE + '}'} — it would "
            f"send a person a message with nothing in it to type")
    if len(found) > 1:
        raise ValueError(
            f"{where} ({app_id}): {'{' + CODE + '}'} appears {len(found)} times and may "
            f"appear once — two copies show a person two numbers and no way to tell which")
    return app_id, text


def validate(raw: str) -> None:
    """Refuse at save time what would otherwise be discovered at compose time."""
    if raw is None or raw.strip() == "":
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("must be a JSON list of templates")
    seen: set[str] = set()
    for i, item in enumerate(data):
        app_id, _ = _entry(item, i)
        if app_id in seen:
            raise ValueError(
                f"template #{i + 1} ({app_id}): this application already has a template, "
                f"and which of the two wins would be decided by the order of the list")
        seen.add(app_id)


def normalize(raw: str) -> str:
    """The canonical stored form: `app_id` stripped, the text left exactly as written.

    The text is never stripped. Leading or trailing space in a message body is a wording
    decision, and one this gateway has no standing to take.
    """
    if raw is None or raw.strip() == "":
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
        if "app_id" in entry:
            entry["app_id"] = str(entry["app_id"]).strip()
        cleaned.append(entry)
    return json.dumps(cleaned, ensure_ascii=False)


def parse(raw: str) -> dict[str, str]:
    """The templates as a lookup keyed on `app_id`.

    Raises `UnreadableTemplates` rather than answering with none — see the module
    docstring.
    """
    if raw is None or raw.strip() == "":
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UnreadableTemplates(
            f"the stored verification templates are not JSON: {exc}") from exc
    if not isinstance(data, list):
        raise UnreadableTemplates("the stored verification templates are not a list")
    parsed: dict[str, str] = {}
    for i, item in enumerate(data):
        try:
            app_id, text = _entry(item, i)
        except ValueError as exc:
            raise UnreadableTemplates(str(exc)) from exc
        parsed[app_id] = text
    return parsed


def for_app(app_id: str) -> str | None:
    """This application's template as configured right now, or `None` if it has none.

    Read per call rather than held, because a change must take effect without a restart —
    a restart drops sending sessions, which is the deploy configuration exists to avoid.
    """
    from app.settings_store import store

    try:
        templates = parse(store.get(KEY))
    except UnreadableTemplates:
        # Raised here so it is raised once per read wherever the read happens, rather than
        # once per caller that remembered. The read still answers "no template", which
        # refuses the application — loud and recoverable, unlike composing around it.
        from app.alerting import notify
        notify("routing", "the stored verification templates cannot be read; every "
                          "application is being refused an sms_out-carried code until it "
                          "is fixed", dedup_extra=KEY)
        logger.warning("verification templates unreadable; %s is refused", app_id)
        return None
    return templates.get(app_id)


def compose(text: str, code: str) -> str:
    """The message body for this code.

    `replace` rather than `str.format`: a template is operator-supplied text, and
    `format` would read any other brace in it as a field — including `{0}`, which reaches
    into the arguments, and `{a.b}`, which reaches into attributes.
    """
    return text.replace("{" + CODE + "}", code)
