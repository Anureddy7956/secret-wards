"""Pre-detection normalisation so disguised PII cannot slip through.

* NFC, Devanagari digits -> ASCII digits (९८७६ -> 9876)
* zero-width / soft-hyphen characters removed
* Cyrillic / Greek homoglyphs folded to Latin, but only inside otherwise-Latin words
  (so a real Greek 'µ' in 'µg' is never touched)
* hidden payloads decoded: literal \\uXXXX escapes, HTML entities, %-encoding (when it encodes text)
The sanitised output is written in this normalised form, which the evaluator normalises the same way.
"""
from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import unquote

_ZW = dict.fromkeys(map(ord, "​‌‍⁠﻿­᠎"), None)
_DEVA_DIGITS = {0x0966 + i: str(i) for i in range(10)}
_HOMO = {
    # Cyrillic
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "һ": "h",
    "ԁ": "d", "ӏ": "l", "Ѕ": "S", "І": "I", "Ј": "J",
    # Greek
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P",
    "Τ": "T", "Υ": "Y", "Χ": "X", "ο": "o", "ν": "v", "ι": "i", "κ": "k", "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
    "α": "a",
}
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_UESC = re.compile(r"\\u([0-9a-fA-F]{4})")
_ENTITY = re.compile(r"&(?:#\d{2,6}|#x[0-9a-fA-F]{2,6}|[a-zA-Z]{2,8});")
_PCT = re.compile(r"(?:%[0-9A-Fa-f]{2}){1,}")


def _fold_word(m: re.Match) -> str:
    w = m.group(0)
    if not any(c in _HOMO for c in w):
        return w
    latin = sum(1 for c in w if "a" <= c.lower() <= "z")
    if latin == 0 and len(w) > 1 and all(c in _HOMO for c in w) is False:
        return w
    if latin > 0 or all(c in _HOMO for c in w):
        return "".join(_HOMO.get(c, c) for c in w)
    return w


def normalize_text(s: str) -> str:
    if not s:
        return s
    if "\\u" in s:
        s = _UESC.sub(lambda m: chr(int(m.group(1), 16)), s)
    if "&" in s and _ENTITY.search(s):
        s = html.unescape(s)
    if "%" in s and _PCT.search(s):
        # only decode when it hides letters / non-ASCII (e.g. %E0%A4.. or %20 between words)
        dec = unquote(s)
        if dec != s and re.search(r"%(?:[2-7][0-9A-Fa-f]|[CDE][0-9A-Fa-f])", s):
            s = dec
    s = unicodedata.normalize("NFC", s)
    s = s.translate(_ZW).translate(_DEVA_DIGITS)
    if any(c in _HOMO for c in s):
        s = _WORD.sub(_fold_word, s)
    return s
