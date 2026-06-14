from app.modem.pdu import decode_deliver, ConcatInfo
from app.modem.pdu_encode import encode_submit, tpdu_length


def _submit_to_deliver(submit_hex: str) -> str:
    """Rewrite a SUBMIT PDU into a DELIVER PDU so the existing decoder can read
    its address/DCS/UDH/payload back. SUBMIT and DELIVER share UD layout; we
    only need to swap the header so decode_deliver accepts it.

    SUBMIT (no SMSC): [00][fo][mr][addr_len][toa][addr...][pid][dcs][vp][udl][ud...]
    DELIVER wanted:   [00][fo'][addr_len][toa][addr...][pid][dcs][scts(7)][udl][ud...]
    """
    b = bytearray.fromhex(submit_hex)
    assert b[0] == 0x00  # SMSC length octet
    b = b[1:]
    fo = b[0]
    udhi = 0x40 if (fo & 0x40) else 0x00
    i = 1   # skip fo
    i += 1  # skip mr
    addr_len = b[i]
    addr_bytes = (addr_len + 1) // 2
    addr = b[i:i + 2 + addr_bytes]
    i += 2 + addr_bytes
    pid = b[i]; i += 1
    dcs = b[i]; i += 1
    i += 1  # skip vp
    rest = b[i:]  # udl + ud
    deliver = bytearray()
    deliver.append(0x00)            # SMSC length 0
    deliver.append(0x04 | udhi)     # DELIVER first octet (+ UDHI)
    deliver += addr
    deliver.append(pid)
    deliver.append(dcs)
    deliver += bytes.fromhex("00000000000000")  # dummy SCTS
    deliver += rest
    return deliver.hex().upper()


def test_single_part_ascii_is_gsm7():
    parts = encode_submit("+79161234567", "Hello", ref=7)
    assert len(parts) == 1
    d = decode_deliver(_submit_to_deliver(parts[0]))
    assert d.sender == "+79161234567"
    assert d.text == "Hello"
    assert d.concat is None


def test_single_part_cyrillic_is_ucs2_no_udh():
    parts = encode_submit("+79161234567", "Привет", ref=7)
    assert len(parts) == 1
    b = bytes.fromhex(parts[0])
    assert b[0] == 0x00 and b[1] == 0x31  # SMSC len, fo (no UDHI)
    d = decode_deliver(_submit_to_deliver(parts[0]))
    assert d.text == "Привет"
    assert d.concat is None


def test_tpdu_length_excludes_smsc_octet():
    parts = encode_submit("+79161234567", "Hi", ref=1)
    assert tpdu_length(parts[0]) == len(bytes.fromhex(parts[0])) - 1


def test_multipart_ucs2_concat_metadata():
    text = "Ы" * 100  # > 70 -> 2 parts (67 + 33)
    parts = encode_submit("+79161234567", text, ref=42)
    assert len(parts) == 2
    decoded = [decode_deliver(_submit_to_deliver(p)) for p in parts]
    assert decoded[0].concat == ConcatInfo(ref=42, total=2, seq=1)
    assert decoded[1].concat == ConcatInfo(ref=42, total=2, seq=2)
    assert decoded[0].text + decoded[1].text == text


def test_multipart_gsm7_concat_roundtrip():
    text = "A" * 200  # > 160 -> 2 parts (153 + 47)
    parts = encode_submit("+79161234567", text, ref=9)
    assert len(parts) == 2
    decoded = [decode_deliver(_submit_to_deliver(p)) for p in parts]
    assert decoded[0].concat == ConcatInfo(ref=9, total=2, seq=1)
    assert decoded[0].text + decoded[1].text == text


def test_emoji_not_split_across_parts():
    text = "😀" * 34  # 68 UTF-16 units > 67 -> must split at char boundary
    parts = encode_submit("+79161234567", text, ref=5)
    decoded = [decode_deliver(_submit_to_deliver(p)) for p in parts]
    joined = "".join(d.text for d in decoded)
    assert joined == text
    assert "�" not in joined


def test_boundary_gsm7_160_is_single_161_is_multipart():
    assert len(encode_submit("+79161234567", "A" * 160, ref=1)) == 1
    assert len(encode_submit("+79161234567", "A" * 161, ref=1)) == 2


def test_boundary_ucs2_70_is_single_71_is_multipart():
    assert len(encode_submit("+79161234567", "Ы" * 70, ref=1)) == 1
    assert len(encode_submit("+79161234567", "Ы" * 71, ref=1)) == 2
