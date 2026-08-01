import pytest

from app import periods


@pytest.mark.parametrize(
    "period,expected",
    [
        ("24h", "-1 day"),
        ("7d", "-7 days"),
        ("30d", "-30 days"),
        ("1y", "-365 days"),
    ],
)
def test_each_period_yields_its_bound(period, expected):
    assert periods.resolve(period) == period
    assert periods.bound(period) == expected


def test_all_time_is_unbounded():
    assert periods.bound("all") is None


@pytest.mark.parametrize("raw", [None, "", "month", "14d", "  ", "30D"])
def test_unrecognised_period_falls_back_to_default(raw):
    """A stale bookmark or a typo renders the default view rather than failing."""
    assert periods.resolve(raw) == "30d"
    assert periods.bound(raw) == "-30 days"


def test_default_is_thirty_days():
    assert periods.DEFAULT == "30d"
    assert periods.PERIODS == ("24h", "7d", "30d", "1y", "all")


@pytest.mark.parametrize(
    "period,fragment",
    [
        ("24h", "%Y-%m-%d %H:00"),
        ("7d", "DATE("),
        ("30d", "DATE("),
        ("1y", "%Y-%m"),
        ("all", "%Y-%m"),
    ],
)
def test_bucket_expression_is_sized_to_the_period(period, fragment):
    expr = periods.bucket_expr("created_at", period)
    assert fragment in expr
    assert "+3 hours" in expr, "buckets fall on MSK days, as the rest of the console does"
