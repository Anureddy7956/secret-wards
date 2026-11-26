"""Byte decoding: BOM-aware UTF-8 / UTF-16 / UTF-32, BOM-less UTF-16 detection, UTF-8, cp1252 fallback."""
from __future__ import annotations


def decode(raw: bytes) -> tuple[str | None, str]:
    """Return (text, encoding_name) or (None, '') if the bytes are not plausible text."""
    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            return raw[3:].decode("utf-8"), "utf-8-sig"
        except UnicodeDecodeError:
            return raw[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    for bom, enc in ((b"\xff\xfe\x00\x00", "utf-32-le"), (b"\x00\x00\xfe\xff", "utf-32-be"),
                     (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")):
        if raw.startswith(bom):
            try:
                return raw[len(bom):].decode(enc), enc
            except UnicodeDecodeError:
                return None, ""
    # BOM-less UTF-16: lots of NUL bytes in alternating positions
    if len(raw) >= 4:
        even_nul = raw[0::2].count(0) / max(1, len(raw[0::2]))
        odd_nul = raw[1::2].count(0) / max(1, len(raw[1::2]))
        if odd_nul > 0.3 and even_nul < 0.05:
            try:
                return raw.decode("utf-16-le"), "utf-16-le"
            except UnicodeDecodeError:
                pass
        if even_nul > 0.3 and odd_nul < 0.05:
            try:
                return raw.decode("utf-16-be"), "utf-16-be"
            except UnicodeDecodeError:
                pass
    if b"\x00" in raw:
        return None, ""
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    text = raw.decode("cp1252", errors="replace")
    return text, "cp1252"


def looks_binary(text: str) -> bool:
    if not text:
        return False
    sample = text[:20000]
    ctrl = sum(1 for c in sample if (ord(c) < 32 and c not in "\r\n\t\f") or c == "�")
    return ctrl / len(sample) > 0.05
