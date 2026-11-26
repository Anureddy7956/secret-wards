"""PII in file names: detect on each path component; rename deterministically (keyed HMAC suffix)."""
from __future__ import annotations

import hashlib
import hmac
import re

from ..detect.combine import LOCATION_TYPES, NAME_TYPES
from ..detect.text_detector import Context, detect
from ..translit.canonical import canon_token

PII_TYPES = NAME_TYPES | {"PHONE", "MRN", "AADHAAR", "ABHA_NUMBER", "EMAIL", "PAN", "INSURANCE_ID", "AADHAAR_MASKED",
                          "ABHA_ADDRESS", "DOB"} | (LOCATION_TYPES - {"DISTRICT"})


def component_has_pii(name: str, ctx: Context, known_tokens: set) -> bool:
    stem = name.rsplit(".", 1)[0] if "." in name else name
    words = re.split(r"[_\s.()\[\]]+", stem)
    text = " ".join(w for w in words if w)
    # Title-case lower-case tokens so the name rules can see them ('anita_sharma' -> 'Anita Sharma')
    titled = " ".join(w.capitalize() if w.isalpha() else w for w in text.split())
    for t in (text, titled):
        for sp in detect(t, ctx):
            if sp.etype in PII_TYPES and sp.conf >= 0.6:
                return True
    for w in re.split(r"[_\s.\-()]+", stem):
        if not w:
            continue
        if re.fullmatch(r"\+?\d{10,14}", w):
            return True
        if w.isalpha() and len(w) > 2 and canon_token(w) in known_tokens:
            return True
    return False


def safe_name(name: str, key: bytes, rel: str) -> str:
    """Keep only ordinary vocabulary words and short numbers from the old stem, then add a keyed tag."""
    from ..detect.lexicon import get_lexicon
    lex = get_lexicon()
    ext = ""
    if "." in name:
        stem, ext = name.rsplit(".", 1)
        ext = "." + ext
    else:
        stem = name
    keep = []
    for w in re.split(r"[_\s.()\[\]]+", stem):
        if not w:
            continue
        if re.fullmatch(r"\d{1,5}", w):
            keep.append(w)
        elif w.isalpha() and lex.is_vocab(w) and not lex.is_name_gaz(w) and len(w) > 1:
            keep.append(w)
    tag = hmac.new(key, ("file|" + rel).encode("utf-8"), hashlib.sha256).hexdigest()[:10]
    return "_".join(keep[:6] + [tag]) + ext
