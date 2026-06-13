from datetime import datetime, timedelta

# Moscow is a fixed UTC+3 (no DST in Russia since 2014), so a constant offset
# is safe. sqlite's CURRENT_TIMESTAMP is stored UTC; we shift only for display.
_MSK_OFFSET = timedelta(hours=3)


def to_msk(value: str | None) -> str:
    """Render a sqlite UTC timestamp ('YYYY-MM-DD HH:MM:SS') as Moscow time.
    None/empty → ''. Unparseable input is returned unchanged (fail-safe)."""
    if not value:
        return ""
    try:
        ts = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    return (ts + _MSK_OFFSET).strftime("%Y-%m-%d %H:%M:%S")
