"""Name canonicalisation for cross-script / cross-spelling matching.

canon("Reena") == canon("Rina") == canon("रीना") == "rina"
canon("Pandey") == canon("पांडे") == "pande"
skeleton() keeps the first letter plus consonants, so Fatma/Fatima and Brijesh/Brajesh collide.
Mohammad / Mohd / Md. / Muhammad / मोहम्मद all map to "mohamad".
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from .devanagari import has_devanagari, transliterate

MOHAMMAD = {"mohammad", "mohammed", "muhammad", "mohamad", "mohamed", "muhammed", "mohd", "md", "mohmad",
            "mahmad", "mohammod", "mohummad"}

HONORIFICS = {
    # suffix / prefix honorifics and kinship terms used with names (Hinglish + Hindi transliterated)
    "ji", "jee", "sahab", "saheb", "sahib", "saab", "sab", "bhai", "bhaiya", "bhaiyya", "bhaiyaa", "behenji", "behen",
    "bahen", "bahenji", "didi", "amma", "ammi", "ammaji", "chacha", "chachu", "chachi", "mama", "mami", "mausi", "bua",
    "dada", "dadi", "nana", "nani", "baba", "bhabhi", "bhabi", "uncle", "aunty", "auntie", "madam", "sir", "shri", "sri",
    "shree", "smt", "shrimati", "kumari", "kum", "mr", "mrs", "ms", "miss", "master", "baby", "late", "sushri", "begum",
    "janab", "maulana", "babu", "bhaiyaa", "baba ji", "sardar", "seth", "pandit", "chaudhary_title",
}

_NONLETTER = re.compile(r"[^a-z]")


def fold(s: str) -> str:
    """NFKC, strip Latin diacritics, casefold, transliterate Devanagari."""
    s = unicodedata.normalize("NFKC", s)
    if has_devanagari(s):
        s = transliterate(s)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return s.casefold()


@lru_cache(maxsize=65536)
def canon_token(tok: str) -> str:
    t = _NONLETTER.sub("", fold(tok))
    if not t:
        return ""
    if t in MOHAMMAD:
        return "mohamad"
    # digraphs / aspirates
    t = t.replace("chh", "c").replace("ch", "c").replace("sh", "s").replace("ph", "f")
    for a, b in (("bh", "b"), ("dh", "d"), ("th", "t"), ("kh", "k"), ("gh", "g"), ("jh", "j"), ("rh", "r")):
        t = t.replace(a, b)
    t = t.replace("ck", "k").replace("q", "k").replace("x", "ks").replace("w", "v").replace("z", "j")
    # vowel length and diphthongs
    t = t.replace("ee", "i").replace("ii", "i").replace("oo", "u").replace("uu", "u").replace("aa", "a")
    t = t.replace("ou", "o").replace("au", "o").replace("ai", "e")
    t = re.sub(r"(?<=[aeiou])y$", "", t)       # pandey -> pande, sanjay -> sanja
    t = re.sub(r"y$", "i", t)                   # sunny -> suni
    t = re.sub(r"(.)\1+", r"\1", t)             # double letters
    return t


@lru_cache(maxsize=65536)
def skeleton(tok: str) -> str:
    c = canon_token(tok)
    if not c:
        return ""
    rest = re.sub(r"[aeiouh]", "", c[1:])
    return c[0] + rest


def name_tokens(name: str, generic: frozenset = frozenset()) -> list[str]:
    """Split a raw name into canonical tokens, dropping honorifics and (optionally) generic tokens.
    Initials ("R." / "K") are kept as single letters."""
    s = fold(name)
    s = re.sub(r"[_.,/\\\-]", " ", s)
    out = []
    for raw in s.split():
        raw = _NONLETTER.sub("", raw)
        if not raw or raw in HONORIFICS:
            continue
        c = canon_token(raw)
        if not c or c in generic:
            continue
        out.append(c)
    return out


def jaro_winkler(a: str, b: str) -> float:
    try:
        from rapidfuzz.distance import JaroWinkler
        return JaroWinkler.similarity(a, b)
    except Exception:  # pragma: no cover - fallback when rapidfuzz is unavailable
        return _jw(a, b)


def _jw(s1: str, s2: str) -> float:
    if s1 == s2:
        return 1.0
    l1, l2 = len(s1), len(s2)
    if not l1 or not l2:
        return 0.0
    rng = max(l1, l2) // 2 - 1
    m1, m2 = [False] * l1, [False] * l2
    m = 0
    for i in range(l1):
        for j in range(max(0, i - rng), min(l2, i + rng + 1)):
            if not m2[j] and s1[i] == s2[j]:
                m1[i] = m2[j] = True
                m += 1
                break
    if not m:
        return 0.0
    t, k = 0, 0
    for i in range(l1):
        if m1[i]:
            while not m2[k]:
                k += 1
            if s1[i] != s2[k]:
                t += 1
            k += 1
    j = (m / l1 + m / l2 + (m - t / 2) / m) / 3
    p = 0
    for a, b in zip(s1[:4], s2[:4]):
        if a != b:
            break
        p += 1
    return j + p * 0.1 * (1 - j)


def token_match(a: str, b: str, jw: float = 0.9) -> bool:
    """Two canonical tokens refer to the same name part."""
    if a == b:
        return True
    if len(a) == 1 or len(b) == 1:  # initial vs full token
        return a[0] == b[0]
    if skeleton(a) == skeleton(b) and a[0] == b[0]:
        return True
    return jaro_winkler(a, b) >= jw and a[0] == b[0]
