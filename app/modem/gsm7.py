"""Shared GSM 7-bit default alphabet: tables (used by the decoder) plus the
encode/pack helpers used by the SMS-SUBMIT encoder."""

from __future__ import annotations

GSM7_BASIC = (
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ"
    " !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
    "¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXT = {
    0x0A: "\f", 0x14: "^", 0x28: "{", 0x29: "}", 0x2F: "\\",
    0x3C: "[", 0x3D: "~", 0x3E: "]", 0x40: "|", 0x65: "€",
}

_BASIC_REV = {ch: i for i, ch in enumerate(GSM7_BASIC)}
_EXT_REV = {ch: code for code, ch in GSM7_EXT.items()}


def is_gsm7(text: str) -> bool:
    """True if every char is representable in the GSM 7-bit alphabet."""
    return all(ch in _BASIC_REV or ch in _EXT_REV for ch in text)


def to_septets(text: str) -> list[int]:
    """Encode text to a flat list of septet values. Extension chars expand to
    [0x1B, <ext code>]. Assumes is_gsm7(text) is True."""
    out: list[int] = []
    for ch in text:
        if ch in _BASIC_REV:
            out.append(_BASIC_REV[ch])
        else:
            out.append(0x1B)
            out.append(_EXT_REV[ch])
    return out


def septet_groups(text: str) -> list[list[int]]:
    """Per-character septet groups (1 or 2 septets each) — used to split
    multipart messages without severing an escape sequence."""
    groups: list[list[int]] = []
    for ch in text:
        if ch in _BASIC_REV:
            groups.append([_BASIC_REV[ch]])
        else:
            groups.append([0x1B, _EXT_REV[ch]])
    return groups


def pack_septets(septets: list[int], fill_bits: int = 0) -> bytes:
    """Pack septets LSB-first into octets. `fill_bits` zero bits are inserted
    before the first septet (used to align text after a byte-aligned UDH)."""
    acc = 0
    nbits = fill_bits
    out = bytearray()
    for s in septets:
        acc |= (s & 0x7F) << nbits
        nbits += 7
        while nbits >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            nbits -= 8
    if nbits > 0:
        out.append(acc & 0xFF)
    return bytes(out)
