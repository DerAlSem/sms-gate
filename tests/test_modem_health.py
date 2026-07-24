"""The escalation ladder as a table of histories.

This is what extracting `ModemHealth` bought. `decide()` touches no serial port, no
filesystem and no clock, so the rung reached by a given history of observations can be
asserted directly — including the histories that are awkward to stage against a live
modem, which is where this feature's sharpest bug lived: a soft recovery performed for a
lost registration letting the next send stall open with a hard reset.
"""

import pytest

from app.modem.health import (
    ModemHealth, COOLDOWN, HARD, OK, REGISTRATION, SOFT, STALL, WAIT,
)

THRESHOLD = 3


def _health():
    return ModemHealth(THRESHOLD, THRESHOLD)


def _run(health, observations, hard_reset_allowed=True):
    """Feed (registered, stalled) pairs and collect the rungs reached."""
    return [
        health.decide(registered=r, stalled=s, hard_reset_allowed=hard_reset_allowed)
        for r, s in observations
    ]


def test_a_healthy_modem_stays_on_the_ground():
    h = _health()
    assert _run(h, [(True, False)] * 5) == [OK] * 5
    assert h.cause is None


def test_three_strikes_reach_a_soft_recovery():
    h = _health()
    assert _run(h, [(False, False)] * 3) == [WAIT, WAIT, SOFT]
    assert h.cause == REGISTRATION


def test_a_good_observation_resets_the_climb():
    """A flapping signal must not accumulate its way to a recovery."""
    h = _health()
    assert _run(h, [(False, False), (False, False), (True, False), (False, False)]) == [
        WAIT, WAIT, OK, WAIT]


def test_the_ladder_continues_to_a_hard_reset():
    h = _health()
    rungs = _run(h, [(False, False)] * 6)
    assert rungs == [WAIT, WAIT, SOFT, WAIT, WAIT, HARD]


def test_the_cooldown_substitutes_another_soft_recovery():
    h = _health()
    rungs = _run(h, [(False, False)] * 6, hard_reset_allowed=False)
    assert rungs == [WAIT, WAIT, SOFT, WAIT, WAIT, COOLDOWN]
    assert h.fails == 0, "the cooldown rung must not leave the counter armed"


def test_a_stall_climbs_its_own_ladder_while_registration_is_fine():
    h = _health()
    assert _run(h, [(True, True)] * 3) == [WAIT, WAIT, SOFT]
    assert h.cause == STALL


def test_a_stall_does_not_inherit_the_registration_ladder():
    """The bug this extraction exists to prevent: one 'have we tried the gentle thing'
    bit answering for two different problems."""
    h = _health()
    assert _run(h, [(False, False)] * 3) == [WAIT, WAIT, SOFT]
    assert h.soft_tried is True

    # Registration is back; the sends that failed during the outage declare a stall.
    rungs = _run(h, [(True, True)] * 3)
    assert rungs == [WAIT, WAIT, SOFT], "the stall must earn its own soft recovery"
    assert HARD not in rungs


def test_a_registration_outage_does_not_inherit_the_stall_ladder():
    """Symmetric, and just as easy to get wrong."""
    h = _health()
    assert _run(h, [(True, True)] * 3) == [WAIT, WAIT, SOFT]
    assert _run(h, [(False, False)] * 3) == [WAIT, WAIT, SOFT]


def test_a_persistent_single_problem_still_escalates_all_the_way():
    """Separating the ladders must not make either toothless."""
    h = _health()
    assert _run(h, [(True, True)] * 6) == [WAIT, WAIT, SOFT, WAIT, WAIT, HARD]


# ------------------------------------------------------------------------ evidence


def test_distinct_messages_are_the_unit_of_evidence():
    h = _health()
    for _ in range(5):
        h.note_send_failure(1, "no response from modem (timeout)", exhausted=False)
    assert h.stalled() is False, "one message's attempts describe one destination"

    h.note_send_failure(2, "no response from modem (timeout)", exhausted=False)
    h.note_send_failure(3, "no response from modem (timeout)", exhausted=False)
    assert h.stalled() is True


def test_an_exhausted_budget_is_evidence_on_its_own():
    h = _health()
    h.note_send_failure(1, "no response from modem (timeout)", exhausted=True)
    assert h.stalled() is True


@pytest.mark.parametrize("error", [
    "+CMS ERROR 1 (unassigned number)",
    "message too long: 8 parts > max 6",
])
def test_failures_that_describe_the_destination_are_neutral(error):
    h = _health()
    for i in (1, 2, 3, 4):
        h.note_send_failure(i, error, exhausted=True)
    assert h.stalled() is False


def test_a_success_wipes_the_slate():
    h = _health()
    h.note_send_failure(1, "no response from modem (timeout)", exhausted=True)
    h.note_send_success()
    assert h.stalled() is False


def test_the_signal_can_be_switched_off():
    h = _health()
    h.note_send_failure(1, "no response from modem (timeout)", exhausted=True)
    assert h.stalled(enabled=False) is False


def test_forgetting_drops_both_the_evidence_and_the_climb():
    h = _health()
    _run(h, [(False, False)] * 3)
    h.note_send_failure(1, "no response from modem (timeout)", exhausted=True)
    h.forget()
    assert (h.fails, h.soft_tried, h.cause) == (0, False, None)
    assert h.stalled() is False


def test_the_gate_starts_open():
    """A gateway that boots unable to send would be a silent outage."""
    assert _health().gate.is_set() is True
