from app.modem.diag import (
    decode_cpin, decode_reg, decode_csq, decode_cops,
    decode_csca, decode_qnwinfo, decode_qcsq, decode_clip, decode_clip_test,
)


def test_cpin():
    assert decode_cpin("\r\n+CPIN: READY\r\n\r\nOK\r\n") == {"state": "READY"}
    assert decode_cpin("OK") == {}


def test_reg_home_and_none():
    assert decode_reg("+CEREG: 0,1") == {"stat": 1, "status": "registered (home)"}
    assert decode_reg("+CREG: 0,0") == {"stat": 0, "status": "not registered"}
    assert decode_reg("+CGREG: 2,5") == {"stat": 5, "status": "registered (roaming)"}
    assert decode_reg("OK") == {}


def test_csq():
    assert decode_csq("+CSQ: 17,99") == {"rssi": 17, "dbm": -79, "ber": 99}
    assert decode_csq("+CSQ: 99,99") == {"rssi": 99, "dbm": None, "ber": 99}
    assert decode_csq("OK") == {}


def test_cops():
    assert decode_cops('+COPS: 0,0,"Tele2",7') == {
        "operator": "Tele2", "act": 7, "rat": "LTE (E-UTRAN)"}
    assert decode_cops("+COPS: 0") == {}


def test_csca():
    assert decode_csca('+CSCA: "+79262000331",145') == {"smsc": "+79262000331"}
    assert decode_csca("OK") == {}


def test_qnwinfo():
    assert decode_qnwinfo('+QNWINFO: "FDD LTE","25001","LTE BAND 7",3100') == {
        "act": "FDD LTE", "operator": "25001", "band": "LTE BAND 7", "channel": 3100}
    assert decode_qnwinfo("+QNWINFO: No Service") == {}


def test_qcsq_lte():
    out = decode_qcsq('+QCSQ: "LTE",-65,-95,150,-12')
    assert out["sysmode"] == "LTE"
    assert out["values"] == [-65, -95, 150, -12]
    assert out["rssi"] == -65 and out["rsrp"] == -95
    assert out["sinr"] == 150 and out["rsrq"] == -12
    assert decode_qcsq("OK") == {}


# ---------------------------------------------------------------- alert summary

from app.modem.diag import summarise_for_alert


def _diag(**parsed):
    """A collect_diagnostics() result carrying the four readings the alert uses."""
    keys = {"sim": "AT+CPIN?", "cs_reg": "AT+CREG?", "signal": "AT+CSQ",
            "operator": "AT+COPS?"}
    return [{"key": "gateway", "cmd": "—", "parsed": {"modem_detected": True}}] + [
        {"key": k, "cmd": c, "parsed": parsed.get(k, {})} for k, c in keys.items()
    ]


def test_summary_names_the_four_readings():
    line = summarise_for_alert(_diag(
        sim={"state": "READY"},
        cs_reg={"stat": 2, "status": "searching"},
        signal={"rssi": 21, "dbm": -71, "ber": 99},
        operator={"operator": "MTS", "act": 7, "rat": "LTE"},
    ))
    assert "SIM=READY" in line
    assert "searching" in line
    assert "-71" in line
    assert "MTS" in line


def test_summary_does_not_claim_an_antenna_fault():
    """The whole point. On 2026-09-06 the text said 'check antenna/operator' while the
    signal was never read; a summary must report, not conclude."""
    line = summarise_for_alert(_diag(
        sim={"state": "READY"},
        cs_reg={"stat": 2, "status": "searching"},
        signal={"rssi": 21, "dbm": -71, "ber": 99},
        operator={},
    ))
    assert "antenna" not in line.lower()


def test_summary_says_so_when_the_modem_did_not_answer():
    diag = [{"key": "gateway", "cmd": "—", "parsed": {}},
            {"key": "alive", "cmd": "AT",
             "error": "modem not responding: TimeoutError: "}]
    line = summarise_for_alert(diag)
    assert "unavailable" in line.lower()
    assert "not responding" in line


def test_summary_marks_a_missing_reading_rather_than_inventing_one():
    line = summarise_for_alert(_diag(sim={"state": "READY"}))
    assert "SIM=READY" in line
    assert line.count("?") >= 3


def test_summary_fits_the_alert_budget():
    """`_bounded(record.getMessage(), 500)` truncates the delivered text; a summary that
    needs truncating is a summary that loses the reading it was added for."""
    line = summarise_for_alert(_diag(
        sim={"state": "SIM PIN"},
        cs_reg={"stat": 3, "status": "registration denied"},
        signal={"rssi": 99, "dbm": None, "ber": 99},
        operator={"operator": "MegaFon-Long-Name", "act": 7, "rat": "LTE"},
    ))
    assert len(line) < 200


# --- CLIP: the caller-ID question, asked of the firmware and of the network ---------
# `AT+CLIP?` answers two different things in one line, and only the second is about us:
# `+CLIP: <n>,<m>` — `n` is our own URC subscription, `m` is whether the NETWORK
# provisions calling-line identification on this subscription. `m` is the reading that
# would otherwise cost a phone call to the operator.

def test_clip_reports_network_provisioning_not_just_our_setting():
    assert decode_clip("\r\n+CLIP: 0,1\r\n\r\nOK\r\n") == {
        "urc": 0, "provision": 1, "network": "provisioned",
    }
    assert decode_clip("+CLIP: 1,0") == {
        "urc": 1, "provision": 0, "network": "not provisioned",
    }
    assert decode_clip("+CLIP: 0,2") == {
        "urc": 0, "provision": 2, "network": "unknown",
    }


def test_clip_unparseable_is_empty_not_a_guess():
    # A firmware without the command answers ERROR. That must not decode into a
    # confident-looking zero — "not provisioned" and "never asked" are different facts.
    assert decode_clip("ERROR") == {}
    assert decode_clip("OK") == {}


def test_clip_test_query_reports_whether_the_firmware_knows_the_command():
    assert decode_clip_test("\r\n+CLIP: (0,1)\r\n\r\nOK\r\n") == {"supported": True}
    assert decode_clip_test("+CLIP: (0-1)") == {"supported": True}
    assert decode_clip_test("ERROR") == {}


# --- A query whose answer comes from the network needs longer than a local one -------

def test_the_diagnostic_sweep_gives_each_query_its_own_budget():
    """`AT+CLIP?` timed out on the live modem on 2026-09-14 while `AT+CLIP=?` answered
    instantly. That is the shape of the difference: the test query is answered out of
    the firmware, the read query reports `<m>` — the *network's* provisioning of caller
    ID — and the modem interrogates the network to learn it. One flat timeout across a
    sweep of local queries and network queries can only be wrong for one of them.
    """
    from app.modem.manager import _DIAG_QUERIES

    budgets = {key: timeout for key, _cmd, _dec, timeout in _DIAG_QUERIES}
    assert budgets["clip"] > budgets["signal"], (
        "the network round-trip must get more than a local register read")
    assert budgets["clip_caps"] == budgets["signal"], (
        "the capability query is answered locally and must stay cheap")


def test_no_diagnostic_query_may_hold_the_serial_lock_indefinitely():
    """The sweep runs on the alert path too (`_alert_observations`), so it holds the
    command port during an incident — exactly when an outgoing SMS is least able to
    wait. Every budget is bounded, and the bound is stated here rather than left to
    whoever adds the next row."""
    from app.modem.manager import _DIAG_QUERIES

    for key, cmd, _dec, timeout in _DIAG_QUERIES:
        assert 0 < timeout <= 10.0, f"{key} ({cmd}) may stall the lock for {timeout}s"
