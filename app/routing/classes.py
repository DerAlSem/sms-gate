"""Task 2.1 — what kind of message this is, decided at acceptance and recorded.

Three classes, not two. The split that matters is not "code versus prose": it is what
draws a spam report and what a person is sitting there waiting for.

- `code4`      — a four-digit code. The only class a flash call can carry, and the one
                 whose recipient is waiting for it at this second, so a link-borne
                 complaint risk barely applies to it.
- `code_long`  — a five-to-eight-digit code. Awaited exactly like `code4`, but it fits in
                 no flash call and reaches no uCaller route, so a messenger rung is the
                 only path it has other than SMS.
- `free_text`  — anything carrying a link, and the named default. This is the class the
                 messenger path is most valuable for and most dangerous in: Telegram
                 names links among the grounds for losing the ability to write to
                 strangers, and one complaint is enough.

The rule is a setting rather than a branch in code, so that a template change on the
application's side is not a deployment here. What ships is the rule this change's
specification states.

⚠️ The trap the specification names by hand: the parking template is `SokolParking: 1234`,
so a rule keyed on the text being *nothing but* four digits is wrong for 446 of the 448
messages this change was measured on. The shipped pattern therefore looks for an isolated
run of digits anywhere in the text, not for the whole text.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

CODE_FOUR = "code4"
CODE_LONG = "code_long"
FREE_TEXT = "free_text"

CLASS_NAMES: tuple[str, ...] = (CODE_FOUR, CODE_LONG, FREE_TEXT)

#: A text matching no rule takes this class. It is `free_text` deliberately: the default
#: must be the class with the *most* conservative route list, because an unrecognised
#: template is the case we know least about.
DEFAULT_CLASS = FREE_TEXT

# A link is decided first, so that a code-shaped number sitting next to one does not pull
# the message into a code class and past the free-text pacing.
_LINK = r"https?://|\bwww\."
# `(?<!\d)` / `(?!\d)` isolate the run: without them `84721` would match the four-digit
# pattern on its first four characters and the third class would never be reached.
_FOUR = r"(?<!\d)\d{4}(?!\d)"
_LONG = r"(?<!\d)\d{5,8}(?!\d)"

DEFAULT_RULE: dict = {
    "default": DEFAULT_CLASS,
    "rules": [
        {"class": FREE_TEXT, "matches": _LINK},
        {"class": CODE_FOUR, "matches": _FOUR},
        {"class": CODE_LONG, "matches": _LONG},
    ],
}

DEFAULT_RULE_JSON = json.dumps(DEFAULT_RULE, ensure_ascii=False)


def validate_rule(raw: str) -> None:
    """Raise ValueError if `raw` is not a usable class rule, naming the offending part.

    Refused at save time rather than alerted about mid-traffic: an unparsable rule that
    reaches the classifier has no safe reading — "no class" is not a class, and guessing
    one silently routes a payment link down a code's route list.
    """
    if raw.strip() == "":
        return
    try:
        rule = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(rule, dict):
        raise ValueError("must be a JSON object with 'default' and 'rules'")

    default = str(rule.get("default", "")).strip()
    if default not in CLASS_NAMES:
        raise ValueError(
            f"default class {default!r} is not one of {', '.join(CLASS_NAMES)}"
        )

    rules = rule.get("rules", [])
    if not isinstance(rules, list):
        raise ValueError("'rules' must be a list")
    for i, item in enumerate(rules):
        if not isinstance(item, dict):
            raise ValueError(f"rule #{i + 1}: must be an object")
        name = str(item.get("class", "")).strip()
        pattern = str(item.get("matches", ""))
        if name not in CLASS_NAMES:
            raise ValueError(
                f"rule #{i + 1}: class {name!r} is not one of {', '.join(CLASS_NAMES)}"
            )
        if not pattern:
            raise ValueError(f"rule #{i + 1} ({name}): 'matches' is required")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"rule #{i + 1} ({name}): {pattern!r} does not compile: {exc}") from exc


def _current_rule() -> dict:
    from app.settings_store import store

    raw = store.get("message_class_rule") or ""
    if not raw.strip():
        return DEFAULT_RULE
    try:
        rule = json.loads(raw)
        validate_rule(raw)
    except ValueError:
        # Refused at save time, so reaching here means a row written before this setting
        # existed or edited underneath us. The shipped rule is the safe reading; treating
        # it as "no rule" would leave every message without a route list.
        logger.warning(
            "message_class_rule is unusable; classifying with the shipped default"
        )
        return DEFAULT_RULE
    return rule


def classify(text: str, rule: dict | None = None) -> str:
    """The class of `text`. Never raises and never returns something that is not a class."""
    rule = rule if rule is not None else _current_rule()
    for item in rule.get("rules", []):
        pattern = item.get("matches")
        name = item.get("class")
        if not pattern or name not in CLASS_NAMES:
            continue
        try:
            if re.search(pattern, text or ""):
                return name
        except re.error:
            continue
    default = rule.get("default")
    return default if default in CLASS_NAMES else DEFAULT_CLASS
