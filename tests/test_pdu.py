import pytest

from app.modem.pdu import ConcatInfo, decode_deliver


def test_ucs2_single_part():
    # SMSC len 0; fo=04 (DELIVER); sender +79161234567; DCS=08 (UCS2);
    # SCTS 2026-06-10 09:19:42+03; text "Привет"
    pdu = (
        "0004"
        "0B919761214365F7"
        "0008"
        "62600190912421"
        "0C"
        "041F04400438043204350442"
    )
    d = decode_deliver(pdu)
    assert d.sender == "+79161234567"
    assert d.text == "Привет"
    assert d.scts == "2026-06-10 09:19:42"
    assert d.concat is None


def test_smsc_prefix_is_skipped():
    # Same PDU but with a real 7-byte SMSC field in front
    pdu = (
        "07919730071111F1"
        "04"
        "0B919761214365F7"
        "0008"
        "62600190912421"
        "0C"
        "041F04400438043204350442"
    )
    d = decode_deliver(pdu)
    assert d.sender == "+79161234567"
    assert d.text == "Привет"


def test_non_deliver_raises():
    # fo=01 → SMS-SUBMIT, we only handle DELIVER
    with pytest.raises(ValueError, match="not SMS-DELIVER"):
        decode_deliver("000100")


def test_gsm7_single_part():
    # DCS=00 (GSM7), text "hello" = E8329BFD06 (canonical packing)
    pdu = (
        "0004"
        "0B919761214365F7"
        "0000"
        "62600190912421"
        "05"
        "E8329BFD06"
    )
    d = decode_deliver(pdu)
    assert d.text == "hello"
    assert d.concat is None


def test_alphanumeric_sender():
    # addr_type=D0 (alphanumeric), addr "T2" GSM7-packed = 5419, addr_len=4 nibbles
    pdu = (
        "0004"
        "04D05419"
        "0008"
        "62600190912421"
        "04"
        "00480049"
    )
    d = decode_deliver(pdu)
    assert d.sender == "T2"
    assert d.text == "HI"


@pytest.mark.parametrize("bad", ["", "000", "zz"])
def test_malformed_input_raises(bad):
    with pytest.raises(ValueError):
        decode_deliver(bad)


def test_ucs2_multipart_8bit_ref():
    # fo=44 (DELIVER+UDHI); UDH 0500038C0201 → ref=140 total=2 seq=1; текст "AB"
    pdu = (
        "0044"
        "0B919761214365F7"
        "0008"
        "62600190912421"
        "0A"
        "0500038C020100410042"
    )
    d = decode_deliver(pdu)
    assert d.concat == ConcatInfo(ref=140, total=2, seq=1)
    assert d.text == "AB"


def test_gsm7_multipart_udh_septet_alignment():
    # GSM7 + 6-октетный UDH: текст начинается с бита 49 (7 септетов смещения),
    # UDL=12 септетов всего, текст "hello"
    pdu = (
        "0044"
        "0B919761214365F7"
        "0000"
        "62600190912421"
        "0C"
        "0500038C0201D06536FB0D"
    )
    d = decode_deliver(pdu)
    assert d.concat == ConcatInfo(ref=140, total=2, seq=1)
    assert d.text == "hello"


def test_multipart_16bit_ref():
    # IEI=08: UDH 060804040002 02 → ref=0x0400=1024 total=2 seq=2; текст "B"
    pdu = (
        "0044"
        "0B919761214365F7"
        "0008"
        "62600190912421"
        "09"
        "060804040002020042"
    )
    d = decode_deliver(pdu)
    assert d.concat == ConcatInfo(ref=1024, total=2, seq=2)
    assert d.text == "B"


def test_udh_unknown_ie_skipped():
    # UDH из двух IE: неизвестный (IEI=24, len=1) + concat 8-bit;
    # парсер должен пропустить первый и найти второй
    # UDH = 1 (UDHL) + 8 = 9 октетов; текст = 4 октета → UDL = 13 = 0D
    pdu = (
        "0044"
        "0B919761214365F7"
        "0008"
        "62600190912421"
        "0D"
        "08240105000380020100410042"
    )
    d = decode_deliver(pdu)
    assert d.concat == ConcatInfo(ref=128, total=2, seq=1)
    assert d.text == "AB"


def test_gsm7_extension_char():
    # "€" = септеты 1B 65 (escape + 0x65), упаковано 9B32
    pdu = (
        "0004"
        "0B919761214365F7"
        "0000"
        "62600190912421"
        "02"
        "9B32"
    )
    assert decode_deliver(pdu).text == "€"


def test_ucs2_truncated_ud_raises():
    # UDL заявляет 12 октетов, в UD только 2
    pdu = (
        "0004"
        "0B919761214365F7"
        "0008"
        "62600190912421"
        "0C"
        "0410"
    )
    with pytest.raises(ValueError, match="truncated"):
        decode_deliver(pdu)


def test_alphanumeric_sender_7_chars_no_fill_at():
    # "UNKNOWN" = 7 GSM7-символов = 7 октетов (addr_len=14) — fill-биты не должны дать '@'
    pdu = (
        "0004"
        "0ED055E7D2F9BC3A01"
        "0008"
        "62600190912421"
        "04"
        "00480049"
    )
    d = decode_deliver(pdu)
    assert d.sender == "UNKNOWN"
    assert d.text == "HI"
