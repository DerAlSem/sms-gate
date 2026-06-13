"""SMS-DELIVER PDU decoder (AT+CMGF=0).

PDU mode is required for UDH: only there are multipart metadata
(ref/total/seq) available, which are inaccessible in text mode.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConcatInfo:
    ref: int
    total: int
    seq: int


@dataclass
class DeliverPdu:
    sender: str
    text: str
    scts: str  # "YYYY-MM-DD HH:MM:SS" by the SMSC clock
    concat: ConcatInfo | None


_GSM7_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ"
    " !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
    "¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM7_EXT = {
    0x0A: "\f", 0x14: "^", 0x28: "{", 0x29: "}", 0x2F: "\\",
    0x3C: "[", 0x3D: "~", 0x3E: "]", 0x40: "|", 0x65: "€",
}


def _unpack_septets(data: bytes, total_septets: int, start_bit: int) -> list[int]:
    """GSM7 bits are packed LSB-first; total_septets is the count of ALL septets
    (including those occupied by UDH), start_bit is where the text begins."""
    septets = []
    for i in range(total_septets - start_bit // 7):
        bitpos = start_bit + i * 7
        byte_i, shift = divmod(bitpos, 8)
        if byte_i >= len(data):
            break
        val = data[byte_i] >> shift
        if shift > 1 and byte_i + 1 < len(data):
            val |= data[byte_i + 1] << (8 - shift)
        septets.append(val & 0x7F)
    return septets


def _gsm7_to_str(septets: list[int]) -> str:
    out: list[str] = []
    esc = False
    for s in septets:
        if esc:
            out.append(_GSM7_EXT.get(s, " "))
            esc = False
        elif s == 0x1B:
            esc = True
        else:
            out.append(_GSM7_BASIC[s])
    return "".join(out)


def _alphabet(dcs: int) -> str:
    if dcs & 0x80 == 0x00:  # general / auto-deletion groups — same alphabet bits
        return {0: "gsm7", 1: "8bit", 2: "ucs2", 3: "gsm7"}[(dcs >> 2) & 0x03]
    if dcs & 0xF0 == 0xE0:  # message waiting, UCS2
        return "ucs2"
    if dcs & 0xF0 == 0xF0:  # data coding / message class
        return "8bit" if dcs & 0x04 else "gsm7"
    return "gsm7"


def _swap_nibbles(data: bytes) -> str:
    return "".join(f"{b & 0x0F:X}{b >> 4:X}" for b in data)


def _decode_address(addr_len: int, addr_type: int, addr: bytes) -> str:
    if addr_type & 0x70 == 0x50:  # alphanumeric, GSM7-packed
        name = _gsm7_to_str(_unpack_septets(addr, addr_len * 4 // 7, 0))
        # 7 characters → 8th septet is zero fill-bits, decoded as '@'
        return name[:-1] if name.endswith("@") else name
    digits = _swap_nibbles(addr)[:addr_len]
    return ("+" + digits) if addr_type & 0x70 == 0x10 else digits


def _decode_scts(data: bytes) -> str:
    s = _swap_nibbles(data)
    return f"20{s[0:2]}-{s[2:4]}-{s[4:6]} {s[6:8]}:{s[8:10]}:{s[10:12]}"


def decode_deliver(pdu_hex: str) -> DeliverPdu:
    """Parse SMS-DELIVER. ValueError — if this is not a DELIVER or the PDU is corrupt."""
    try:
        return _decode_deliver(bytes.fromhex(pdu_hex.strip()))
    except (IndexError, ValueError) as e:
        raise ValueError(f"bad PDU: {e}") from e


def _decode_deliver(b: bytes) -> DeliverPdu:
    pos = 0
    smsc_len = b[pos]
    pos += 1 + smsc_len
    fo = b[pos]
    pos += 1
    if fo & 0x03 != 0x00:
        raise ValueError(f"not SMS-DELIVER: first octet 0x{fo:02X}")
    udhi = bool(fo & 0x40)

    addr_len = b[pos]
    addr_type = b[pos + 1]
    addr_bytes = (addr_len + 1) // 2
    sender = _decode_address(addr_len, addr_type, b[pos + 2:pos + 2 + addr_bytes])
    pos += 2 + addr_bytes

    pos += 1  # PID
    dcs = b[pos]
    pos += 1
    scts = _decode_scts(b[pos:pos + 7])
    pos += 7
    udl = b[pos]
    ud = b[pos + 1:]

    concat, udh_octets = _parse_udh(ud) if udhi else (None, 0)
    alphabet = _alphabet(dcs)
    if alphabet in ("ucs2", "8bit") and len(ud) < udl:
        # UDL is in octets for ucs2/8bit; for gsm7 UDL is in septets, handled separately
        raise ValueError(f"UD truncated: {len(ud)} < {udl}")
    if alphabet == "ucs2":
        text = ud[udh_octets:udl].decode("utf-16-be", errors="replace")
    elif alphabet == "8bit":
        text = ud[udh_octets:udl].decode("latin-1", errors="replace")
    else:  # gsm7: udl is in septets; UDH is padded to a septet boundary
        udh_bits = udh_octets * 8
        start_bit = udh_bits + (7 - udh_bits % 7) % 7 if udh_octets else 0
        text = _gsm7_to_str(_unpack_septets(ud, udl, start_bit))
    return DeliverPdu(sender=sender, text=text, scts=scts, concat=concat)


def _parse_udh(ud: bytes) -> tuple[ConcatInfo | None, int]:
    """UDH at the start of UD → (concat info if present, length of UDH in octets)."""
    udhl = ud[0]
    udh_octets = 1 + udhl
    concat = None
    i = 1
    while i + 1 < udh_octets:
        iei, ielen = ud[i], ud[i + 1]
        data = ud[i + 2:i + 2 + ielen]
        if iei == 0x00 and ielen == 3:
            concat = ConcatInfo(ref=data[0], total=data[1], seq=data[2])
        elif iei == 0x08 and ielen == 4:
            concat = ConcatInfo(ref=(data[0] << 8) | data[1], total=data[2], seq=data[3])
        i += 2 + ielen
    return concat, udh_octets
