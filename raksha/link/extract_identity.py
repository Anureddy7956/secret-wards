"""Per-record identity evidence used for linkage. Holds canonical / normalised values only."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from ..translit.canonical import canon_token, name_tokens
from ..detect.lexicon import get_lexicon

STRONG_TYPES = ("MRN", "AADHAAR", "ABHA_NUMBER", "ABHA_ADDRESS", "EMAIL", "PAN", "INSURANCE_ID", "PHONE")


@dataclass
class Identity:
    names: list = field(default_factory=list)       # list[tuple[str, ...]] canonical tokens, patient role
    weak_names: list = field(default_factory=list)  # first-name-only mentions (honorific / fragment)
    ids: set = field(default_factory=set)           # {(type, normalised value)}
    relatives: list = field(default_factory=list)   # list[tuple[str, ...]]
    genders: set = field(default_factory=set)
    ages: list = field(default_factory=list)        # [(age, reference date or None)]
    dobs: set = field(default_factory=set)          # {date}
    villages: set = field(default_factory=set)      # canonical village keys
    districts: set = field(default_factory=set)
    pins: set = field(default_factory=set)
    hospital: str | None = None
    dates: list = field(default_factory=list)       # event dates (true)

    def add_name(self, raw: str):
        lex = get_lexicon()
        toks = tuple(name_tokens(raw))
        if not toks:
            return
        core = tuple(t for t in toks if t not in lex.generic)
        if len(core) >= 2 or (len(toks) >= 2 and core):
            self.names.append(toks)
        elif core:
            self.weak_names.append(core)

    def add_relative(self, raw: str):
        raw = re.sub(r"(?i)^\s*(?:s|d|w|c|h)\s*/\s*o\.?\s*", "", raw)
        toks = tuple(name_tokens(raw))
        if toks:
            self.relatives.append(toks)

    def add_gender(self, raw: str):
        g = normalize_gender(raw)
        if g:
            self.genders.add(g)

    def birth_years(self) -> list[int]:
        out = [d.year for d in self.dobs]
        for age, ref in self.ages:
            if ref is not None:
                out.append(ref.year - age)
        return out

    def has_patient_evidence(self) -> bool:
        # hospital IDs, Aadhaar and ABHA belong to exactly one person; a phone may be a relative's
        return bool(self.names or any(t in ("MRN", "AADHAAR", "ABHA_NUMBER", "ABHA_ADDRESS") for t, _ in self.ids))


def normalize_gender(raw: str) -> str | None:
    v = str(raw).strip().lower()
    if v in ("m", "male", "man", "boy", "पुरुष", "mard", "purush"):
        return "M"
    if v in ("f", "female", "woman", "girl", "महिला", "स्त्री", "aurat", "mahila"):
        return "F"
    return None


def village_key(raw: str) -> str:
    toks = name_tokens(raw)
    return " ".join(toks)
