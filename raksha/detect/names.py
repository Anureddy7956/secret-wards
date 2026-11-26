"""Name tokens: shape features, gazetteer lookup (Latin + Devanagari via transliteration) and
span grabbing after a context cue."""
from __future__ import annotations

import re

from ..translit.canonical import HONORIFICS, canon_token
from ..translit.devanagari import transliterate
from .lexicon import get_lexicon

TOKEN_RX = re.compile(r"[A-Za-z][A-Za-z'’]*\.?|[ऀ-ॣॱ-ॿ]+")
DEVA_RX = re.compile(r"[ऀ-ॿ]")

# Hindi words (Devanagari) that are never names; used to stop name grabbing / gazetteer runs.
HINDI_STOP = set("""
का की के को से ने है हैं था थी थे में पर और या भी तो नहीं जी श्री श्रीमती कुमारी आयु उम्र वर्ष साल महिला पुरुष
पिता पति माता पुत्र पुत्री पत्नी बेटा बेटी नाम मरीज़ मरीज रोगी पता मकान नं नंबर मोहल्ला ग्राम गांव गाँव तहसील जिला ज़िला
मोबाइल फोन फ़ोन तारीख तिथि दिनांक भर्ती छुट्टी निदान डिस्चार्ज सारांश पंजीकरण सं आईपीडी ओपीडी पर्चा दिन हफ़्ते हफ्ते महीने
बुखार खांसी दर्द पेट सिर उल्टी दस्त कमजोरी चक्कर दवा दवाई डॉ डॉक्टर अस्पताल वार्ड बेड पास पीछे सामने निकट
निमोनिया मलेरिया टाइफाइड डेंगू मधुमेह शुगर टीबी काला अज़ार सीओपीडी लिए लिया दिया गया गई रहे रहा रही ठीक
""".split())

LABEL_WORDS = {
    "age", "sex", "gender", "uhid", "mrn", "reg", "regn", "registration", "no", "mob", "mobile", "phone", "ph", "tel",
    "date", "dob", "address", "addr", "ipd", "opd", "ward", "bed", "consultant", "diagnosis", "village", "vill", "gram",
    "tehsil", "distt", "district", "pin", "aadhaar", "aadhar", "abha", "pan", "email", "relation", "attendant", "visit",
    "doctor", "dept", "department", "hospital", "patient", "name", "years", "yrs", "y", "male", "female", "c", "k", "h",
}


def tokens(text: str):
    """(start, end, token) for Latin / Devanagari word tokens."""
    return [(m.start(), m.end(), m.group(0)) for m in TOKEN_RX.finditer(text)]


def is_deva(tok: str) -> bool:
    return bool(DEVA_RX.match(tok))


def deva_canon(tok: str) -> str:
    return canon_token(transliterate(tok))


def tok_core(tok: str) -> str:
    t = tok.rstrip(".")
    if t.endswith(("'s", "’s")):
        t = t[:-2]
    return t.rstrip("'’")


def is_cap(tok: str) -> bool:
    t = tok_core(tok)
    return bool(t) and t[0].isupper()


def is_gaz(tok: str) -> bool:
    lex = get_lexicon()
    if is_deva(tok):
        c = deva_canon(tok)
        return c in lex.first or c in lex.sur
    return lex.is_name_gaz(tok_core(tok))


def is_first_gaz(tok: str) -> bool:
    lex = get_lexicon()
    c = deva_canon(tok) if is_deva(tok) else canon_token(tok_core(tok))
    return c in lex.first


def is_honorific(tok: str) -> bool:
    t = tok_core(tok).lower()
    return t in HONORIFICS or tok in ("जी", "श्री", "श्रीमती", "कुमारी", "साहब", "बहनजी", "दीदी")


def is_vocab(tok: str) -> bool:
    if is_deva(tok):
        return tok in HINDI_STOP
    return get_lexicon().is_vocab(tok_core(tok))


def name_like(tok: str, strict: bool) -> bool:
    """Could this token be part of a person's name?"""
    core = tok_core(tok)
    if not core:
        return False
    if is_deva(tok):
        return tok not in HINDI_STOP
    if len(core) == 1:
        return core.isupper()  # initial
    if core.lower() in LABEL_WORDS and not is_gaz(core):
        return False
    if not (core[0].isupper()):
        return is_gaz(core) and strict
    if strict:
        return True
    return is_gaz(core) or not is_vocab(core)


def grab_forward(text: str, pos: int, strict: bool = True, max_tokens: int = 4, allow_lower: bool = False):
    """Collect a name starting at pos (after a label / relation marker).
    Returns (start, end, honorific_end) or None. Stops at punctuation, double spaces, labels, digits."""
    i = pos
    n = len(text)
    while i < n and text[i] in " \t:-–.":
        if text[i] == "\n":
            break
        i += 1
    start = None
    end = None
    count = 0
    j = i
    while j < n and count < max_tokens:
        m = TOKEN_RX.match(text, j)
        if not m:
            break
        tok = m.group(0)
        after = text[m.end(): m.end() + 2]
        if is_honorific(tok):
            if start is None:
                # leading honorific (Shri, Smt.): skip it
                j = m.end()
                while j < n and text[j] == " ":
                    j += 1
                continue
            end = m.end()
            break
        ok = name_like(tok, strict) or (allow_lower and is_gaz(tok))
        if not ok:
            break
        if after.startswith(":"):
            break
        if start is None:
            start = m.start()
        end = m.end()
        count += 1
        j = m.end()
        # continue only across a single space
        if text[j:j + 1] == " " and text[j + 1:j + 2] not in (" ", "\n", "") :
            j += 1
            continue
        break
    if start is None:
        return None
    # don't end on a trailing period that belongs to the sentence (keep initials like 'R.')
    if text[end - 1] == "." and end - start > 2 and not re.search(r"\b[A-Z]\.$", text[start:end]):
        end -= 1
    return start, end


def grab_backward(text: str, pos: int, max_tokens: int = 3):
    """Collect a name that ends right before pos (skipping ', ' and spaces)."""
    j = pos
    while j > 0 and text[j - 1] in " ,":
        j -= 1
    end = j
    toks = []
    while j > 0 and len(toks) < max_tokens:
        k = j
        while k > 0 and (text[k - 1].isalpha() or text[k - 1] in "'’." or DEVA_RX.match(text[k - 1])):
            k -= 1
        tok = text[k:j]
        if not tok or not name_like(tok, strict=False) or is_honorific(tok):
            break
        toks.append((k, j))
        j = k
        if j > 0 and text[j - 1] == " " and j > 1 and text[j - 2] not in " \n":
            j -= 1
        else:
            break
    if not toks:
        return None
    return toks[-1][0], end
