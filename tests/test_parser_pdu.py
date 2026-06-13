from app.modem.parser import parse_cmgr_pdu, parse_cmgl_pdu

PDU1 = "00040B919761214365F70008626001909124210C041F04400438043204350442"
PDU2 = "00040B919761214365F700006260019091242105E8329BFD06"


def test_parse_cmgr_pdu():
    resp = f'\r\n+CMGR: 1,,32\r\n{PDU1}\r\n\r\nOK\r\n'
    assert parse_cmgr_pdu(resp) == PDU1


def test_parse_cmgr_pdu_no_match():
    assert parse_cmgr_pdu('\r\nOK\r\n') is None


def test_parse_cmgl_pdu_multiple():
    resp = (
        f'\r\n+CMGL: 1,1,,32\r\n{PDU1}\r\n'
        f'+CMGL: 5,1,,24\r\n{PDU2}\r\n\r\nOK\r\n'
    )
    assert parse_cmgl_pdu(resp) == [(1, PDU1), (5, PDU2)]


def test_parse_cmgl_pdu_empty():
    assert parse_cmgl_pdu('\r\nOK\r\n') == []
