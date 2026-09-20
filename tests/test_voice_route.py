"""The voice route's episode state machine, away from the modem.

Two conditions, alerted separately, and only one of them gated on registration. The
third is the one that catches the other two having gone quiet.
"""

from app.modem.voice_route import VoiceRouteWatch, ROUTE, CONFIG, STALE


def _reading(conf=1, cap=1):
    from app.modem.diag import decode_qcfg_ims
    return decode_qcfg_ims(f'+QCFG: "ims",{conf},{cap}')


def _kinds(alerts):
    return [(a.event, a.state) for a in alerts]


def test_a_healthy_module_says_nothing():
    w = VoiceRouteWatch()
    assert w.observe(registered=True, parsed=_reading(1, 1), now=0.0) == []


def test_losing_the_route_alerts_once_per_episode():
    w = VoiceRouteWatch()
    w.observe(registered=True, parsed=_reading(1, 1), now=0.0)
    first = w.observe(registered=True, parsed=_reading(1, 0), now=60.0)
    assert _kinds(first) == [(ROUTE, "lost")]
    for tick in range(2, 10):
        assert w.observe(registered=True, parsed=_reading(1, 0), now=60.0 * tick) == []


def test_the_route_alert_names_the_observation_and_no_cause():
    """`outbound-send` forbids naming a cause the gateway did not observe, and the
    vendor's own reference does not say this field is the network's verdict."""
    w = VoiceRouteWatch()
    text = w.observe(registered=True, parsed=_reading(1, 0), now=0.0)[0].text.lower()
    assert "carrier" not in text and "operator" not in text
    assert "refus" not in text and "reject" not in text


def test_an_unregistered_module_raises_no_availability_alert():
    """That reading is negative on an unregistered module whether or not the route would
    otherwise be available. A watcher without this gate announces a lost voice route
    after every modem reset, every radio cycle and every recovery."""
    w = VoiceRouteWatch()
    for tick in range(10):
        alerts = w.observe(registered=False, parsed=_reading(1, 0), now=60.0 * tick)
        assert [a for a in alerts if a.event == ROUTE] == []


def test_the_route_returning_says_so_and_re_arms():
    w = VoiceRouteWatch()
    w.observe(registered=True, parsed=_reading(1, 0), now=0.0)
    back = w.observe(registered=True, parsed=_reading(1, 1), now=60.0)
    assert _kinds(back) == [(ROUTE, "restored")]
    again = w.observe(registered=True, parsed=_reading(1, 0), now=120.0)
    assert _kinds(again) == [(ROUTE, "lost")]


def test_a_route_already_lost_at_startup_alerts_on_the_first_reading():
    """Episode state dies with the process, and the process exits itself on the ladder's
    top rung and on every deploy. This is the 2026-09-18 state exactly."""
    w = VoiceRouteWatch()
    assert _kinds(w.observe(registered=True, parsed=_reading(1, 0), now=0.0)) == [
        (ROUTE, "lost")]


# ------------------------------------------------------------ the configuration digit

def test_the_configuration_is_alerted_while_off_the_network():
    """Every state that moves the configuration arises while the module is rebooting and
    off the network. Gating this one would silence it in the scenario that generates it."""
    w = VoiceRouteWatch()
    alerts = w.observe(registered=False, parsed=_reading(0, 0), now=0.0)
    assert _kinds(alerts) == [(CONFIG, "drifted")]


def test_the_configuration_is_alerted_while_the_route_still_works():
    """`0,1` — the factory position with an MBN that happens to enable VoLTE. A working
    voice route, and no longer the state this gateway asked for."""
    w = VoiceRouteWatch()
    alerts = w.observe(registered=True, parsed=_reading(0, 1), now=0.0)
    assert _kinds(alerts) == [(CONFIG, "drifted")]
    assert [a for a in alerts if a.event == ROUTE] == []
    # And it is not called a disabled route on the way past: `0,1` IS a working voice
    # route, supplied by the module's own carrier profile.
    assert "disabled" not in alerts[0].text.lower()


def test_zero_is_not_reported_as_somebody_disabling_it():
    """🔴 The bug this change exists to avoid. `0` is the factory position; `2` is the
    explicit disable, and they got there by different routes."""
    w = VoiceRouteWatch()
    deferred = w.observe(registered=True, parsed=_reading(0, 1), now=0.0)[0].text
    assert "profile" in deferred.lower()
    off = VoiceRouteWatch().observe(registered=True, parsed=_reading(2, 0), now=0.0)
    drift = [a for a in off if a.event == CONFIG][0].text.lower()
    assert "disabled" in drift and "profile" not in drift


def test_an_unrecognised_configuration_is_a_drift_named_as_unrecognised():
    w = VoiceRouteWatch()
    alerts = w.observe(registered=True, parsed=_reading(7, 1), now=0.0)
    assert _kinds(alerts) == [(CONFIG, "drifted")]
    assert "7" in alerts[0].text


def test_the_configuration_coming_back_re_arms():
    w = VoiceRouteWatch()
    w.observe(registered=True, parsed=_reading(2, 0), now=0.0)
    back = [a for a in w.observe(registered=True, parsed=_reading(1, 1), now=60.0)
            if a.event == CONFIG]
    assert _kinds(back) == [(CONFIG, "restored")]


def test_the_two_conditions_are_separate_alerts():
    """Distinct events, so neither hides behind the other in a dedup window."""
    w = VoiceRouteWatch()
    alerts = w.observe(registered=True, parsed=_reading(2, 0), now=0.0)
    assert {a.event for a in alerts} == {CONFIG, ROUTE}
    texts = {a.event: a.text for a in alerts}
    assert texts[CONFIG] != texts[ROUTE]


# ------------------------------------------------------------------------ staleness

def test_a_watcher_gone_silent_says_so():
    """Every mechanism this change installs fails silent, and a watcher that has gone
    permanently silent is otherwise indistinguishable from a route that is fine."""
    w = VoiceRouteWatch(stale_after=600.0)
    w.observe(registered=True, parsed=_reading(1, 1), now=0.0)
    assert w.observe(registered=True, parsed=None, now=300.0) == []
    alerts = w.observe(registered=True, parsed=None, now=601.0)
    assert _kinds(alerts) == [(STALE, "unknown")]
    assert w.observe(registered=True, parsed=None, now=900.0) == []


def test_staleness_counts_from_startup_when_nothing_was_ever_measured():
    """An unanswerable modem returns `False` from the registration poll for ever, so the
    gate never opens and no reading is ever taken."""
    w = VoiceRouteWatch(stale_after=600.0)
    w.observe(registered=False, parsed=None, now=0.0)
    assert _kinds(w.observe(registered=False, parsed=None, now=601.0)) == [
        (STALE, "unknown")]


def test_an_unparseable_reading_is_not_measured_and_feeds_staleness():
    """A firmware change that alters the response format must not read as a value."""
    w = VoiceRouteWatch(stale_after=600.0)
    w.observe(registered=True, parsed=_reading(1, 1), now=0.0)
    assert _kinds(w.observe(registered=True, parsed={}, now=601.0)) == [(STALE, "unknown")]


def test_an_unregistered_module_is_not_a_measurement_of_the_route():
    """The gate is shut, so nothing about the route was learned — which is the silencing
    mechanism this alert exists to catch."""
    w = VoiceRouteWatch(stale_after=600.0)
    w.observe(registered=True, parsed=_reading(1, 1), now=0.0)
    assert _kinds(w.observe(registered=False, parsed=_reading(1, 1), now=601.0)) == [
        (STALE, "unknown")]


def test_measuring_again_clears_the_staleness_and_says_so():
    w = VoiceRouteWatch(stale_after=600.0)
    w.observe(registered=True, parsed=None, now=0.0)
    assert _kinds(w.observe(registered=True, parsed=None, now=601.0)) == [
        (STALE, "unknown")]
    back = w.observe(registered=True, parsed=_reading(1, 1), now=700.0)
    assert _kinds(back) == [(STALE, "known")]


# -------------------------------------------------------------------- the page's view

def test_the_snapshot_carries_the_state_and_when_it_was_measured():
    w = VoiceRouteWatch()
    w.observe(registered=True, parsed=_reading(1, 1), now=1_758_000_000.0)
    snap = w.snapshot()
    assert snap["voice_route"] == "available"
    assert snap["voice_route_config"] == "enabled compulsorily"
    assert snap["voice_route_measured"].startswith("2025-09-16")


def test_the_snapshot_does_not_show_a_stale_value_as_current():
    """The page says so rather than showing the last known value as if it were current."""
    w = VoiceRouteWatch(stale_after=600.0)
    w.observe(registered=True, parsed=_reading(1, 1), now=0.0)
    w.observe(registered=False, parsed=None, now=601.0)
    assert w.snapshot()["voice_route"] == "not measured"


def test_the_snapshot_before_anything_was_read():
    assert VoiceRouteWatch().snapshot()["voice_route"] == "not measured"
