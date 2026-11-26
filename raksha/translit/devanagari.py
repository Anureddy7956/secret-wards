"""Devanagari -> Latin transliteration tuned for Indian personal and place names.

Implements inherent-schwa handling with the standard Hindi schwa-deletion heuristics
(word-final schwa dropped; medial schwa dropped in a V C _ C V context), so that
सुनीता -> sunita, कमला -> kamla, मोहम्मद -> mohammad, पांडे -> pande.
"""
from __future__ import annotations

import unicodedata

VOWELS = {
    "अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u", "ऋ": "ri", "ए": "e", "ऐ": "ai",
    "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e", "ॐ": "om",
}
MATRAS = {
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o",
    "ौ": "au", "ॉ": "o", "ॅ": "e", "ॆ": "e", "ॊ": "o",
}
CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh",
    "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d",
    "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r",
    "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h", "ळ": "l",
    "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f", "य़": "y",
}
NUKTA_BASE = {"क": "क़", "ख": "ख़", "ग": "ग़", "ज": "ज़", "ड": "ड़", "ढ": "ढ़", "फ": "फ़", "य": "य़"}
NUKTA = "़"
HALANT = "्"
ANUSVARA = "ं"
CHANDRABINDU = "ँ"
VISARGA = "ः"
DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
LABIALS = {"p", "ph", "b", "bh", "m"}


def is_devanagari_char(ch: str) -> bool:
    return "ऀ" <= ch <= "ॿ"


def has_devanagari(s: str) -> bool:
    return any(is_devanagari_char(c) for c in s)


def deva_digits_to_ascii(s: str) -> str:
    return "".join(DIGITS.get(c, c) for c in s)


def _units(word: str):
    """Split a word into units: ('C', consonant, vowel|None|'') or ('V', vowel) or ('M', mark)."""
    chars = list(unicodedata.normalize("NFC", word))
    # Fold base+nukta pairs into precomposed consonants.
    merged = []
    for ch in chars:
        if ch == NUKTA and merged and merged[-1] in NUKTA_BASE:
            merged[-1] = NUKTA_BASE[merged[-1]]
        else:
            merged.append(ch)
    units = []
    i = 0
    while i < len(merged):
        ch = merged[i]
        if ch in CONSONANTS:
            vowel = None  # inherent schwa candidate
            if i + 1 < len(merged):
                nxt = merged[i + 1]
                if nxt in MATRAS:
                    vowel = MATRAS[nxt]
                    i += 1
                elif nxt == HALANT:
                    vowel = ""
                    i += 1
            units.append(["C", CONSONANTS[ch], vowel])
        elif ch in VOWELS:
            units.append(["V", VOWELS[ch]])
        elif ch in (ANUSVARA, CHANDRABINDU):
            units.append(["N"])
        elif ch == VISARGA:
            units.append(["V", "h"])
        elif ch in DIGITS:
            units.append(["V", DIGITS[ch]])
        elif ch in MATRAS:  # stray matra
            units.append(["V", MATRAS[ch]])
        else:
            if not is_devanagari_char(ch):
                units.append(["X", ch])
        i += 1
    return units


def _has_vowel(u) -> bool:
    if u[0] == "V":
        return True
    if u[0] == "C":
        return u[2] is None or bool(u[2])
    return False


def transliterate_word(word: str) -> str:
    units = _units(word)
    n = len(units)
    # Decide schwa realisation for consonants with vowel None.
    keep = [True] * n
    cons_idx = [i for i, u in enumerate(units) if u[0] == "C"]
    if cons_idx:
        last = cons_idx[-1]
        # word-final schwa deletion (only if the consonant is the last letter-bearing unit)
        if units[last][2] is None and all(units[j][0] in ("N", "X") for j in range(last + 1, n)) and len(cons_idx) > 1:
            keep[last] = False
    def sounded(j: int) -> bool:
        u = units[j]
        if u[0] == "V":
            return True
        if u[0] == "C":
            return bool(u[2]) or (u[2] is None and keep[j])
        return False

    # medial deletion, right to left: V C [a] C V  ->  V C C V
    for i in range(n - 1, 0, -1):
        u = units[i]
        if u[0] != "C" or u[2] is not None or not keep[i]:
            continue
        nxt = i + 1
        if nxt >= n or units[nxt][0] != "C" or not sounded(nxt):
            continue
        prev = i - 1
        if units[prev][0] in ("C", "V") and sounded(prev):
            keep[i] = False
    out = []
    for i, u in enumerate(units):
        kind = u[0]
        if kind == "C":
            out.append(u[1])
            if u[2] is None:
                if keep[i]:
                    out.append("a")
            else:
                out.append(u[2])
        elif kind == "V":
            out.append(u[1])
        elif kind == "N":
            nxt = units[i + 1] if i + 1 < n else None
            out.append("m" if nxt is not None and nxt[0] == "C" and nxt[1] in LABIALS else "n")
        elif kind == "X":
            out.append(u[1])
    return "".join(out)


def transliterate(text: str) -> str:
    """Transliterate every Devanagari run in text; other characters pass through."""
    out, buf = [], []
    for ch in text:
        if is_devanagari_char(ch) and ch not in "।॥":
            buf.append(ch)
        else:
            if buf:
                out.append(transliterate_word("".join(buf)))
                buf = []
            out.append(" " if ch in "।॥" else ch)
    if buf:
        out.append(transliterate_word("".join(buf)))
    return "".join(out)
