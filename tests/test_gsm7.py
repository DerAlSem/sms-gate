import pytest
from app.modem.gsm7 import is_gsm7, to_septets, pack_septets


def test_plain_ascii_is_gsm7():
    assert is_gsm7("Hello") is True
    assert is_gsm7("Привет") is False


def test_extension_char_is_gsm7():
    assert is_gsm7("price 5€ {x}") is True


def test_to_septets_basic_and_extension():
    assert to_septets("A") == [0x41]
    assert to_septets("{") == [0x1B, 0x28]


def test_pack_septets_roundtrip_via_decoder():
    from app.modem.pdu import _unpack_septets, _gsm7_to_str
    text = "Hello, world!"
    septets = to_septets(text)
    packed = pack_septets(septets)
    out = _gsm7_to_str(_unpack_septets(packed, len(septets), 0))
    assert out == text


def test_pack_septets_with_fill_bits_roundtrip():
    from app.modem.pdu import _unpack_septets, _gsm7_to_str
    text = "ABCDEFG"
    septets = to_septets(text)
    packed = pack_septets(septets, fill_bits=1)
    out = _gsm7_to_str(_unpack_septets(packed, len(septets) + 1, 1))
    assert out == text
