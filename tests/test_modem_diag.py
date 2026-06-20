from app.modem.diag import (
    decode_cpin, decode_reg, decode_csq, decode_cops,
    decode_csca, decode_qnwinfo, decode_qcsq,
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
