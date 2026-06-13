# tests/test_timefmt.py
from app.admin.timefmt import to_msk


def test_converts_utc_to_msk():
    assert to_msk("2026-06-03 04:09:27") == "2026-06-03 07:09:27"


def test_crosses_midnight():
    assert to_msk("2026-06-02 23:30:00") == "2026-06-03 02:30:00"


def test_none_and_empty_render_blank():
    assert to_msk(None) == ""
    assert to_msk("") == ""


def test_unparseable_returned_unchanged():
    assert to_msk("not-a-date") == "not-a-date"
