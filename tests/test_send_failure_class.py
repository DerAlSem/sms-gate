"""Transient vs permanent classification of a send failure.

Drives whether the gateway re-attempts a message or gives up on it. The default is
deliberately asymmetric: an unrecognised failure counts as transient, because a wasted
retry costs seconds inside a bounded budget while a missed one loses the message.
"""

import pytest

from app.modem.errors import is_permanent_failure


@pytest.mark.parametrize("error", [
    "+CMS ERROR 1 (unassigned number)",
    "+CMS ERROR 21 (short message transfer rejected)",
    "+CMS ERROR 28 (unidentified subscriber)",
    "+CMS ERROR 50 (operation barred)",
    "+CMS ERROR 69 (requested facility not implemented)",
    "+CMS ERROR 96 (invalid mandatory information)",
    "+CMS ERROR 301 (SMS service reserved)",
    "+CMS ERROR 304 (invalid PDU mode parameter)",
    "+CMS ERROR 305 (invalid text mode parameter)",
    "+CMS ERROR 321 (invalid memory index)",
    "+CMS ERROR 330 (SMSC address unknown)",
    "+CMS ERROR 310 (SIM not inserted)",
    "+CMS ERROR 311 (SIM PIN required)",
    "+CMS ERROR 313 (SIM failure)",
    "+CME ERROR 10 (SIM not inserted)",
    "+CME ERROR 11 (SIM PIN required)",
    "+CME ERROR 13 (SIM failure)",
])
def test_permanent_failures_are_not_retried(error):
    assert is_permanent_failure(error) is True


@pytest.mark.parametrize("error", [
    "no response from modem (timeout)",
    "timeout waiting for '> ', got: 'OK'",
    "modem returned ERROR",
    "+CMS ERROR 38 (network out of order)",
    "+CMS ERROR 41 (temporary failure)",
    "+CMS ERROR 42 (congestion)",
    "+CMS ERROR 331 (no network service)",
    "+CMS ERROR 332 (network timeout)",
    "+CMS ERROR 350 (network/SMSC rejected the message)",
    "+CMS ERROR 500 (unknown error)",
    "+CME ERROR 30 (no network service)",
    "+CME ERROR 31 (network timeout)",
    "Could not parse +CMGS ref from: '\\r\\nweird\\r\\n'",
])
def test_transient_failures_are_retried(error):
    assert is_permanent_failure(error) is False


def test_an_unlisted_code_defaults_to_transient():
    assert is_permanent_failure("+CMS ERROR 477 (vendor specific)") is False


def test_a_code_is_recognised_inside_a_wrapped_message():
    """Callers wrap the modem's text — `command()` prefixes the AT command, and the
    CMGF helper prefixes its own label."""
    assert is_permanent_failure("AT+CMGS=23: +CMS ERROR 305 (invalid text mode parameter)") is True
    assert is_permanent_failure("CMGF=0 failed: +CMS ERROR: 331") is False


def test_a_message_over_the_part_budget_is_permanent():
    assert is_permanent_failure("message too long: 8 parts > max 6") is True


def test_an_empty_or_unknown_error_is_transient():
    assert is_permanent_failure("") is False
    assert is_permanent_failure("something nobody has seen before") is False
