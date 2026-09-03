"""Attributing a +CDS: a filter chain that fails open.

The rule that matters most is the one about what the new evidence may *not* do. An empty
recipient address, an `scts` that will not parse, a part whose submit time is unknown —
each leaves attribution exactly where it was before this change. The new fields may
eliminate a candidate they contradict or order candidates they can separate; they may
never be required before an attribution is made. A rule that turned deliveries into
expiries on a formatting difference would be worse than the defect it replaces.
"""
from datetime import datetime, timedelta, timezone

from app.modem.attribution import attribute, significant_digits
from app.modem.parser import DeliveryReport

NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)


def _row(message_id, seq=1, *, phone="+79031680015", msg_status="sent",
         part_status="sent", sent_at="2026-09-02 11:00:00"):
    return {
        "message_id": message_id, "seq": seq, "phone": phone,
        "msg_status": msg_status, "part_status": part_status, "sent_at": sent_at,
    }


def _report(*, recipient="+79031680015", submitted_at=None, status_code=0, ref=42):
    return DeliveryReport(
        modem_ref=ref, delivered=(status_code == 0), status_code=status_code,
        recipient=recipient, submitted_at=submitted_at,
        raw_line=f"+CDS: 6,{ref},...",
    )


def _decide(report, rows, *, window_hours=168, strict=False):
    return attribute(report, rows, window_hours=window_hours, strict=strict, now=NOW)


def _outcomes(decision):
    return {(c["message_id"], c["seq"]): c["outcome"] for c in decision.candidates}


# --- the positive obligation ---------------------------------------------------


def test_one_qualifying_uncontradicted_candidate_is_chosen():
    """Task 4.1 — without this, attributing nothing at all satisfies every other rule."""
    d = _decide(_report(), [_row(7)])
    assert d.outcome == "attributed"
    assert (d.message_id, d.seq) == (7, 1)
    assert d.decided_by == "sole"


def test_two_candidates_and_the_selected_one_is_chosen():
    """Task 4.2 — choosing is not applying. A chain that selects and writes nothing
    satisfies every "SHALL prefer"."""
    d = _decide(
        _report(submitted_at=datetime(2026, 9, 2, 11, 50, tzinfo=timezone.utc)),
        [_row(7, sent_at="2026-09-02 09:00:00"), _row(9, sent_at="2026-09-02 11:45:00")],
    )
    assert d.outcome == "attributed"
    assert d.message_id == 9
    assert d.decided_by == "nearest"


# --- failing open --------------------------------------------------------------


def test_a_part_with_no_recorded_submit_time_qualifies():
    """Task 4.3 — unknown is not old. A NULL compared in SQL silently answers "does not
    qualify", which is fail-closed in a rule that must fail open."""
    d = _decide(_report(), [_row(7, sent_at=None)])
    assert d.outcome == "attributed" and d.message_id == 7


def test_an_absent_or_short_address_eliminates_nothing():
    """Task 4.4 — a length difference is not a disagreement. Under strict, so a rule
    that quietly eliminated would show."""
    for report, rows, why in [
        (_report(recipient=None), [_row(7)], "the network sent no address"),
        (_report(recipient=""), [_row(7)], "an empty address"),
        (_report(recipient="123456"), [_row(7)], "an address of six digits"),
        (_report(), [_row(7, phone="12345")], "a stored number of five digits"),
    ]:
        d = _decide(report, rows, strict=True)
        assert d.outcome == "attributed", why
        assert d.message_id == 7, why


def test_a_national_address_agrees_with_an_international_one():
    """Task 4.5 — `89031680015` and `+79031680015` share their last ten digits.

    Not compared by canonicalizing: `validate_and_normalize` needs a region and raises on
    what it dislikes, and a national-format address parsed against our region can
    canonicalize into a *different valid* number and eliminate the correct sole candidate.
    """
    d = _decide(_report(recipient="89031680015"),
                [_row(7, phone="+79031680015")], strict=True)
    assert d.outcome == "attributed" and d.message_id == 7


def test_clocks_hours_apart_do_not_stop_the_update():
    """Task 4.6 — the distance between the two clocks orders candidates; it never
    eliminates one, however large it is."""
    d = _decide(
        _report(submitted_at=datetime(2026, 9, 2, 3, 0, tzinfo=timezone.utc)),
        [_row(7, sent_at="2026-09-02 11:00:00")], strict=True,
    )
    assert d.outcome == "attributed" and d.message_id == 7


# --- choosing between candidates -----------------------------------------------


def test_the_nearest_submit_time_wins_and_every_candidate_is_recorded():
    """Task 4.7."""
    d = _decide(
        _report(submitted_at=datetime(2026, 9, 2, 10, 5, tzinfo=timezone.utc)),
        [_row(7, sent_at="2026-09-02 10:00:00"), _row(9, sent_at="2026-09-02 11:30:00")],
    )
    assert d.message_id == 7 and d.decided_by == "nearest"
    assert _outcomes(d) == {(7, 1): "chosen", (9, 1): "eligible"}


def test_without_a_usable_report_timestamp_the_most_recent_wins():
    """Task 4.8 — and the record says so, because the guess carries a consequence."""
    d = _decide(
        _report(submitted_at=None),
        [_row(7, sent_at="2026-09-02 10:00:00"), _row(9, sent_at="2026-09-02 11:30:00")],
    )
    assert d.message_id == 9
    assert d.decided_by == "recency"


def test_a_tie_nothing_separates_falls_to_recency():
    """Task 4.9 — the same instant on both candidates. The blacklist carve-out that
    hangs off this is wired in `_handle_cds` and tested there."""
    d = _decide(
        _report(submitted_at=datetime(2026, 9, 2, 11, 0, tzinfo=timezone.utc),
                status_code=64),
        [_row(7, sent_at="2026-09-02 11:00:00"), _row(9, sent_at="2026-09-02 11:00:00")],
    )
    assert d.decided_by == "recency"
    assert d.message_id in (7, 9)


def test_an_already_reported_part_does_not_shadow_an_unreported_one():
    """Task 4.10."""
    d = _decide(_report(), [
        _row(7, part_status="delivered", msg_status="delivered"),
        _row(9, part_status="sent"),
    ])
    assert d.outcome == "attributed" and d.message_id == 9
    assert _outcomes(d)[(7, 1)] == "superseded"


# --- the three outcomes --------------------------------------------------------


def test_a_second_report_for_an_already_reported_part_is_superseded():
    """Task 4.11 — ordinary network behaviour, recorded and silent: a multipart message
    completed at the timeout still receives its remaining reports."""
    d = _decide(_report(), [_row(7, part_status="delivered", msg_status="delivered")])
    assert d.outcome == "superseded"
    assert (d.message_id, d.seq) == (7, 1), "it names the part it was superseded by"


def test_a_match_past_the_window_is_unplaced_and_names_the_part():
    """Tasks 4.12 and 2.6a — not "nothing matched".

    Collecting the matches BEFORE the window and status filters is what makes this
    possible. A `WHERE` clause that filters first cannot name what it discarded, and it
    also makes every superseded report look unplaced — which starts waking an operator on
    ordinary traffic.
    """
    d = _decide(_report(), [_row(7, sent_at="2026-01-01 10:00:00")], window_hours=168)
    assert d.outcome == "unplaced"
    assert _outcomes(d) == {(7, 1): "outside_window"}
    assert d.reason and "window" in d.reason.lower()


def test_nothing_matched_at_all_is_unplaced():
    d = _decide(_report(), [])
    assert d.outcome == "unplaced"
    assert d.candidates == []
    assert d.message_id is None


def test_a_superseded_match_keeps_an_unplaceable_report_quiet():
    """A completed message is an ordinary explanation for a report that cannot be
    applied, and the operator must not be woken by ordinary traffic."""
    d = _decide(_report(), [
        _row(7, part_status="delivered", msg_status="delivered"),
        _row(9, sent_at="2026-01-01 10:00:00"),
    ])
    assert d.outcome == "superseded"


# --- the digit comparison itself ------------------------------------------------


def test_significant_digits():
    assert significant_digits("+79031680015") == "9031680015"
    assert significant_digits("89031680015") == "9031680015"
    assert significant_digits("7 903 168-00-15") == "9031680015"
    assert significant_digits("123456") is None, "fewer than ten digits is not comparable"
    assert significant_digits("") is None
    assert significant_digits(None) is None
