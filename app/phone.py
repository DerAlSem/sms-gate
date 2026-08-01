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
