"""A refusal, a silence and a fault are three different readings.

The axis this pins is the one that produced a standing verdict that this module had no
voice path at all: `AT+CIREG?` answers `ERROR` on this build, and reading that as "not
registered to IMS" reports the negative of a fact never obtained.
"""

from app.modem.parser import classify_at_outcome, REFUSAL, SILENCE, FAILURE


def test_a_bare_error_is_a_refusal():
    """What the live module answers to `AT+CIREG?`. The modem would not carry out the
    command; that is all it says, and all we may record."""
    assert classify_at_outcome("\r\nERROR\r\n") == REFUSAL


def test_the_codes_that_mean_not_supported_are_refusals_too():
    """The manual promises only that `+CME ERROR` is "similar to the ERROR result code",
    so a build that answers a missing command with a code is not ruled out."""
    assert classify_at_outcome("+CME ERROR: 3") == REFUSAL    # operation not allowed
    assert classify_at_outcome("+CME ERROR: 4") == REFUSAL    # operation not supported
    assert classify_at_outcome("+CMS ERROR: 302") == REFUSAL
    assert classify_at_outcome("+CMS ERROR: 303") == REFUSAL


def test_an_error_about_the_modems_own_state_is_a_fault():
    """The positive control, and the fault of the 2026-09-06 outage: `AT+CPIN?` answered
    `+CME ERROR: 13` is a failed SIM. Rendering it as "nothing was measured" would hide
    the one reading that names the cause."""
    assert classify_at_outcome("+CME ERROR: 13") == FAILURE
    for code in (10, 11, 14, 15):
        assert classify_at_outcome(f"+CME ERROR: {code}") == FAILURE
    assert classify_at_outcome("+CMS ERROR: 331") == FAILURE


def test_nothing_at_all_is_a_silence():
    """`AT+CLIP?` on this module: given two seconds it spends two, given eight it spends
    eight. It never refused — it never answered."""
    assert classify_at_outcome("") == SILENCE
    assert classify_at_outcome("   \r\n") == SILENCE


def test_a_reply_that_never_terminated_is_a_silence_not_a_refusal():
    """Bytes arrived and the terminator did not. The modem did not refuse anything."""
    assert classify_at_outcome("\r\n+CLIP: 1,") == SILENCE


def test_classification_is_not_a_list_of_commands_believed_absent():
    """The same response classifies the same way whichever command produced it — which
    is what lets a command that used to be refused be reported from its answer, with no
    edit to the gateway."""
    assert classify_at_outcome("ERROR") == classify_at_outcome("\r\nERROR\r\n\r\n")


def test_a_textual_cme_error_about_state_is_a_fault():
    """The spec draws the line at "an error the modem raises about its own state", not at
    "an error carrying a number". A verbose firmware saying it in words is saying the
    same thing, and a refusal is only ever the two meanings the vendor gives it."""
    assert classify_at_outcome("+CME ERROR: SIM failure") == FAILURE
    assert classify_at_outcome("+CME ERROR: operation not supported") == REFUSAL
    assert classify_at_outcome("+CME ERROR: Operation not allowed") == REFUSAL
