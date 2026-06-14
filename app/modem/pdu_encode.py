"""SMS-SUBMIT PDU encoder (AT+CMGF=0).

Mirror of app/modem/pdu.py's decoder. Auto-selects GSM 7-bit or UCS2, splits
long messages into UDH-concatenated parts. SMSC length octet is always 00
(the modem uses its stored SMSC), so PDUs start with "00".
"""

from __future__ import annotations

from app.modem.gsm7 import is_gsm7, to_septets, septet_groups, pack_septets

GSM7_SINGLE = 160
GSM7_MULTI = 153          # 160 - 7 septets consumed by the concat UDH
UCS2_SINGLE = 70          # 140 octets / 2
UCS2_MULTI = 67           # 134 octets / 2 (140 - 6 UDH octets)

_FO_SUBMIT = 0x31         # MTI=SUBMIT, VPF=relative, SRR=1 (mirror of CSMP=49)
_FO_UDHI = 0x40
_VP_RELATIVE = 167        # 24h, parity with CSMP=49,167


def _encode_address(phone: str) -> bytes:
    """Destination address field: [addr_len][toa][swapped BCD digits]."""
    intl = phone.startswith("+")
    digits = phone[1:] if intl else phone
    toa = 0x91 if intl else 0x81
    addr_len = len(digits)
    padded = digits if len(digits) % 2 == 0 else digits + "F"
    swapped = bytearray()
    for i in range(0, len(padded), 2):
        swapped.append((int(padded[i + 1], 16) << 4) | int(padded[i], 16))
    return bytes([addr_len, toa]) + bytes(swapped)


def _concat_udh(ref: int, total: int, seq: int) -> bytes:
    """6-octet concatenation UDH (8-bit reference, IEI 0x00)."""
    return bytes([0x05, 0x00, 0x03, ref & 0xFF, total, seq])


def _build_pdu(addr: bytes, dcs: int, ud: bytes, udl: int, udhi: bool) -> str:
    fo = _FO_SUBMIT | (_FO_UDHI if udhi else 0)
    pdu = bytearray()
    pdu.append(0x00)                 # SMSC length: use stored SMSC
    pdu.append(fo)
    pdu.append(0x00)                 # MR: modem assigns
    pdu += addr
    pdu.append(0x00)                 # PID
    pdu.append(dcs)
    pdu.append(_VP_RELATIVE)         # VP (relative)
    pdu.append(udl)
    pdu += ud
    return pdu.hex().upper()


def _split_gsm7(text: str, limit: int) -> list[str]:
    parts: list[str] = []
    cur_chars: list[str] = []
    cur_septets = 0
    for ch, group in zip(text, septet_groups(text)):
        if cur_septets + len(group) > limit:
            parts.append("".join(cur_chars))
            cur_chars, cur_septets = [], 0
        cur_chars.append(ch)
        cur_septets += len(group)
    if cur_chars:
        parts.append("".join(cur_chars))
    return parts


def _split_ucs2(text: str, limit_units: int) -> list[str]:
    """Split by UTF-16 code units without severing a surrogate pair."""
    parts: list[str] = []
    cur: list[str] = []
    units = 0
    for ch in text:
        w = 2 if ord(ch) > 0xFFFF else 1   # astral chars take 2 UTF-16 units
        if units + w > limit_units:
            parts.append("".join(cur))
            cur, units = [], 0
        cur.append(ch)
        units += w
    if cur:
        parts.append("".join(cur))
    return parts


def _encode_gsm7_part(addr, text, concat):
    septets = to_septets(text)
    if concat is None:
        ud = pack_septets(septets)
        return _build_pdu(addr, 0x00, ud, len(septets), udhi=False)
    udh = _concat_udh(*concat)
    udh_bits = len(udh) * 8
    fill_bits = (7 - udh_bits % 7) % 7
    udh_septets = (udh_bits + fill_bits) // 7
    ud = udh + pack_septets(septets, fill_bits=fill_bits)
    return _build_pdu(addr, 0x00, ud, udh_septets + len(septets), udhi=True)


def _encode_ucs2_part(addr, text, concat):
    body = text.encode("utf-16-be")
    if concat is None:
        return _build_pdu(addr, 0x08, body, len(body), udhi=False)
    udh = _concat_udh(*concat)
    ud = udh + body
    return _build_pdu(addr, 0x08, ud, len(ud), udhi=True)


def encode_submit(phone: str, text: str, *, ref: int) -> list[str]:
    """Encode text into one or more SMS-SUBMIT PDUs (hex strings)."""
    addr = _encode_address(phone)
    gsm7 = is_gsm7(text)

    if gsm7:
        if len(to_septets(text)) <= GSM7_SINGLE:
            return [_encode_gsm7_part(addr, text, None)]
        chunks = _split_gsm7(text, GSM7_MULTI)
        total = len(chunks)
        return [
            _encode_gsm7_part(addr, c, (ref, total, i + 1))
            for i, c in enumerate(chunks)
        ]

    if len(text.encode("utf-16-be")) <= UCS2_SINGLE * 2:
        return [_encode_ucs2_part(addr, text, None)]
    chunks = _split_ucs2(text, UCS2_MULTI)
    total = len(chunks)
    return [
        _encode_ucs2_part(addr, c, (ref, total, i + 1))
        for i, c in enumerate(chunks)
    ]


def tpdu_length(pdu_hex: str) -> int:
    """Octet count of the TPDU excluding the leading SMSC length octet — the
    value AT+CMGS=<n> expects in PDU mode."""
    return len(bytes.fromhex(pdu_hex)) - 1
