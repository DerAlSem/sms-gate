"""The +CDS line carries more than a reference, and reading it must not move the old fields.

`_CDS_PATTERN` captures by position and `parse_cds` reads `group(1)` as the reference and
`group(2)` as the status. Capturing the recipient address and the submit timestamp inserts
groups *ahead* of the status — an implementation that forgets to re-index reads the status
out of a timestamp, `delivered` becomes "a timestamp is not the string 0", and every
delivery in the system silently turns into a failure. No test that builds a DeliveryReport
by hand can see that. These do.
"""
from datetime import datetime, timedelta, timezone

from app.modem.parser import parse_cds

# docs/modem.md:103 — the captured sample, `+CDS: fo,mr,ra,tora,scts,dt,st`.
SAMPLE = '+CDS: 6,42,"+79991234567",145,"26/04/17,12:00:01+12","26/04/17,12:00:03+12",0'


def test_captured_sample_still_yields_reference_and_status():
    """Task 1.1 — the guard. Passes before the new captures exist and after."""
    report = parse_cds(SAMPLE)
    assert report is not None
    assert report.modem_ref == 42
    assert report.status_code == 0
    assert report.delivered is True


def test_a_failure_line_yields_its_status():
    """Task 1.2 — shaped like the report that prompted this change (st=64, permanent)."""
    line = '+CDS: 6,75,"+79031680015",145,"26/09/01,12:37:02+12","26/09/02,15:37:44+12",64'
    report = parse_cds(line)
    assert report is not None
    assert report.modem_ref == 75
    assert report.status_code == 64
    assert report.delivered is False


def test_an_empty_recipient_address_is_absent_not_an_empty_number():
    """Task 1.3 — `""` is the network saying nothing, not a number of zero digits."""
    line = '+CDS: 6,42,"",145,"26/04/17,12:00:01+12","26/04/17,12:00:03+12",0'
    report = parse_cds(line)
    assert report is not None, "an empty address does not make the line unreadable"
    assert report.recipient is None
    assert report.modem_ref == 42 and report.status_code == 0


def test_the_recipient_address_is_carried_through():
    report = parse_cds(SAMPLE)
    assert report.recipient == "+79991234567"


def test_an_unreadable_submit_timestamp_leaves_the_report_usable():
    """Task 1.4 — absent, never rejected and never epoch zero."""
    line = '+CDS: 6,42,"+79991234567",145,"not a timestamp","26/04/17,12:00:03+12",0'
    report = parse_cds(line)
    assert report is not None, "an unreadable timestamp does not reject the report"
    assert report.submitted_at is None
    assert report.modem_ref == 42 and report.status_code == 0


def test_the_offset_is_quarter_hours_and_the_year_is_this_century():
    """Task 1.6 — `+12` is UTC+03:00, not UTC+12:00, and `26` is 2026."""
    report = parse_cds(SAMPLE)
    assert report.submitted_at is not None
    assert report.submitted_at.utcoffset() == timedelta(hours=3)
    assert report.submitted_at == datetime(
        2026, 4, 17, 12, 0, 1, tzinfo=timezone(timedelta(hours=3))
    )
    # the same instant, said the other way, so a nine-hour error cannot hide behind
    # a naive comparison
    assert report.submitted_at.astimezone(timezone.utc) == datetime(
        2026, 4, 17, 9, 0, 1, tzinfo=timezone.utc
    )


def test_a_negative_offset_is_also_quarter_hours():
    line = '+CDS: 6,42,"+79991234567",145,"26/04/17,12:00:01-08","26/04/17,12:00:03-08",0'
    report = parse_cds(line)
    assert report.submitted_at.utcoffset() == timedelta(hours=-2)


def test_the_discharge_time_is_read_too():
    report = parse_cds(SAMPLE)
    assert report.discharged_at == datetime(
        2026, 4, 17, 12, 0, 3, tzinfo=timezone(timedelta(hours=3))
    )


def test_the_report_carries_the_line_it_came_from():
    """The ledger records the raw line for every report, including attributed ones."""
    assert parse_cds(SAMPLE).raw_line == SAMPLE


def test_a_line_that_is_not_a_report_is_still_rejected():
    assert parse_cds("+CDS: garbage") is None
