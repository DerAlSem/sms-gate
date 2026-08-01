"""Rolling time windows shared by the SMS view and the statistics view.

The options are named after the window they actually apply. A control labelled
"month" over a rolling 30 days would answer a different question from the one it
appears to answer — and the operator would compare the card against what they
expected "August" to be and conclude the counter is broken.

Calendar anchors were the alternative. They lose on the default: a view bounded to
"since the 1st" is near-empty on the 1st, and a default that shows nothing is a
worse default.
"""

DEFAULT = "30d"

# period key -> sqlite datetime() modifier for the lower bound; None = unbounded
_BOUNDS: dict[str, str | None] = {
    "24h": "-1 day",
    "7d": "-7 days",
    "30d": "-30 days",
    "1y": "-365 days",
    "all": None,
}

PERIODS: tuple[str, ...] = tuple(_BOUNDS)


def resolve(raw: str | None) -> str:
    """The period to render for a raw query value. Anything unrecognised — missing,
    empty, or a stale bookmark from before this vocabulary — falls back to the
    default rather than failing."""
    return raw if raw in _BOUNDS else DEFAULT


def bound(period: str) -> str | None:
    """The sqlite `datetime('now', ?)` modifier bounding the period, or None when
    the period is unbounded."""
    return _BOUNDS[resolve(period)]


def bucket_expr(column: str, period: str) -> str:
    """SQL bucketing `column` for the statistics breakdown, sized to the period and
    computed in MSK (as the rest of the console is).

    Hourly over a day, daily over a week or a month, monthly over a year or all
    time — a 365-row daily table is not a breakdown anyone reads.
    """
    resolved = resolve(period)
    if resolved == "24h":
        return f"strftime('%Y-%m-%d %H:00', {column}, '+3 hours')"
    if resolved in ("7d", "30d"):
        return f"DATE({column}, '+3 hours')"
    return f"strftime('%Y-%m', {column}, '+3 hours')"
