import phonenumbers
from babel import Locale, UnknownLocaleError


def validate_and_normalize(phone: str, region: str, *, restrict_region: bool = True) -> str:
    """Return the E.164 form of `phone` if it is a valid number, else raise ValueError.

    Accepts national-format or E.164 input. With restrict_region=True (default), the
    number must also BELONG to `region` (region_code_for_number == region) — used by the
    public send API. restrict_region=False accepts any valid number (dialog replies to an
    existing conversation).
    """
    region = region.upper()
    try:
        parsed = phonenumbers.parse(phone, region)
    except phonenumbers.NumberParseException:
        raise ValueError(f"Invalid phone number for region {region}")
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError(f"Invalid phone number for region {region}")
    if restrict_region and phonenumbers.region_code_for_number(parsed) != region:
        raise ValueError(f"Invalid phone number for region {region}")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def is_dialable(value: str, region: str) -> bool:
    """Whether `value` is something we could actually send to.

    An inbound sender is stored as the network delivered it and need not be a number
    at all — a service sender arrives as a name like `Tinkoff`. Offering a reply or a
    blacklist entry for one of those would fail at send time, or write a non-number
    into the blacklist.
    """
    if not value:
        return False
    try:
        validate_and_normalize(value, region, restrict_region=False)
    except ValueError:
        return False
    return True


def country_choices(locale: str) -> list[tuple[str, str]]:
    """(code, "Localized Name (CODE)") for every phonenumbers region, sorted by label.
    Names are localized to `locale` (the admin UI language); unknown codes/locales
    fall back gracefully so the picker never crashes."""
    try:
        loc = Locale.parse(locale)
    except (UnknownLocaleError, ValueError):
        loc = Locale("en")
    out = []
    for code in phonenumbers.SUPPORTED_REGIONS:
        name = loc.territories.get(code) or code
        out.append((code, f"{name} ({code})"))
    return sorted(out, key=lambda t: t[1].lower())


# --- Ported from the messengers branch (reach-people-in-messengers) for SG-32.
# `app/routing/config.py` imports this at module scope for validating a brand's own
# account number, and is otherwise unchanged from that branch — flagged in the task
# report as a dependency outside the file list in ТЗ section 1, since `app/phone.py`
# itself was not named there. ---
def normalize_e164(value: str) -> str:
    """Return the E.164 form of an already-international number, else raise ValueError.

    Used where the number is **ours** rather than a recipient's — a sender account's own
    number, written once by hand into configuration. There is deliberately no region to
    default to: `validate_and_normalize` takes one from `store.phone_region`, and a
    settings validator that read the store would be reading the very thing it guards.

    The `+` is required rather than guessed at for a second reason. Two spellings of one
    number are two numbers to any check that compares them, and the check that one number
    carries one brand would be evaded by spacing alone.
    """
    text = (value or "").strip()
    if not text.startswith("+"):
        raise ValueError(
            f"{value!r} is not in E.164 form — write it as +<country code><number>"
        )
    try:
        parsed = phonenumbers.parse(text, None)
    except phonenumbers.NumberParseException:
        raise ValueError(f"{value!r} is not a valid phone number")
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError(f"{value!r} is not a valid phone number")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
