"""Rendering: turn detected spans / field classes into the sanitised value for one record."""
from __future__ import annotations

import base64
import datetime as dt
import re

from ..detect.combine import NAME_TYPES
from ..detect.lexicon import get_lexicon
from ..privacy.age_band import band_for, render as render_band
from ..privacy.dates import find_dates
from ..privacy.location import generalize_district, pin_out
from ..translit.canonical import name_tokens, token_match

TAGS = {
    "RELATIVE_NAME": "[RELATIVE]", "OTHER_NAME": "[NAME]", "PHONE": "[PHONE]", "EMAIL": "[EMAIL]",
    "AADHAAR": "[AADHAAR]", "AADHAAR_MASKED": "[AADHAAR]", "ABHA_NUMBER": "[ABHA]", "ABHA_ADDRESS": "[ABHA]",
    "PAN": "[PAN]", "INSURANCE_ID": "[INSURANCE-ID]", "HOUSE": "[HOUSE]", "LOCALITY": "[LOCALITY]",
    "LANDMARK": "[LANDMARK]", "VILLAGE": "[VILLAGE]", "TEHSIL": "[TEHSIL]", "MRN": "[ID]",
}


class RecordView:
    """What the renderer needs to know about the record being written."""

    def __init__(self, pid, shift, band, order, level, policy, patient_names, counter, ref_year=2026):
        self.pid = pid
        self.shift = shift
        self.band = band              # (lo, hi) or None
        self.order = order
        self.level = level
        self.policy = policy
        self.patient_names = patient_names  # list of canonical token tuples
        self.counter = counter        # Counter of entity types written
        self.ref_year = ref_year
        self.generalized = False

    def age_text(self, age: int) -> str:
        top = int(self.policy.get("age.top_code", 80))
        width = int(self.policy.get("_chosen.width", self.policy.get("age.band_width", 10)))
        b = self.band if self.band is not None else band_for([age], width, top)
        lo, hi = b
        if not (lo <= age and (hi is None or age <= hi)):
            b = band_for([age], width, top)
        self.generalized = True
        return render_band(b)

    def is_patient_name(self, raw: str) -> bool:
        toks = name_tokens(raw)
        if not toks or not self.patient_names:
            return False
        for n in self.patient_names:
            if any(token_match(t, u) for t in toks for u in n if len(t) > 2 and len(u) > 2):
                return True
        return False

    def name_tag(self, etype: str, role: str, raw: str) -> str:
        if etype == "PATIENT_NAME" and (role == "patient" or self.is_patient_name(raw)):
            return self.pid or "[PATIENT]"
        if etype == "RELATIVE_NAME":
            return "[RELATIVE]"
        if etype == "PATIENT_NAME" and role == "unknown":
            return "[NAME]"
        return "[NAME]" if etype == "OTHER_NAME" else (self.pid or "[PATIENT]")

    def address_text(self, info: dict) -> str:
        self.generalized = True
        d = info.get("district")
        if d and self.level in ("district", "tehsil", "village"):
            return f"[ADDRESS], Distt. {_title(d)}"
        return "[ADDRESS]"

    def district_text(self, raw: str) -> str:
        self.generalized = True
        return generalize_district(raw, self.level)

    def pin_text(self, raw: str) -> str:
        self.generalized = True
        return pin_out(raw, self.level, self.policy)


def _title(s: str) -> str:
    return " ".join(w.capitalize() for w in s.split())


def render_text(text: str, spans, view: RecordView, shift_dates: bool = True) -> str:
    reps = []  # (start, end, replacement)
    for sp in spans:
        t = sp.etype
        raw = text[sp.start:sp.end]
        if t == "AGE":
            try:
                reps.append((sp.start, sp.end, view.age_text(int(sp.value or raw))))
            except ValueError:
                pass
            continue
        if t == "DOB":
            continue  # shifted with all other dates below
        view.counter[t] += 1
        if t in NAME_TYPES:
            rep = view.name_tag(t, sp.role, raw)
        elif t == "MRN":
            rep = view.pid or "[ID]"
        elif t == "ADDRESS":
            rep = view.address_text(sp.meta)
        elif t == "DISTRICT":
            m = re.match(r"(?i)(Distt?\.?|District|Zila|Jila|जिला|ज़िला|जनपद)\s*[:\-]?\s*", raw)
            name = raw[m.end():] if m else raw
            gen = view.district_text(name)
            if m and gen == name:
                rep = raw
            elif m:
                rep = m.group(0) + gen if gen != "[DISTRICT]" else "[DISTRICT]"
            else:
                rep = gen if not raw.isupper() else gen.upper()
        elif t == "PIN":
            rep = view.pin_text(raw)
        else:
            rep = TAGS.get(t, "[REDACTED]")
        reps.append((sp.start, sp.end, rep))
    if shift_dates:
        for h in find_dates(text):
            if any(h.start < e and s < h.end for s, e, _ in reps):
                continue
            d = h.parse(view.order, view.ref_year)
            if d is None:
                continue
            reps.append((h.start, h.end, h.render(d + dt.timedelta(days=view.shift), view.order)))
    reps.sort()
    out, last = [], 0
    for s, e, r in reps:
        if s < last:
            continue
        out.append(text[last:s])
        out.append(r)
        last = e
    out.append(text[last:])
    return "".join(out)


def shift_date_value(value: str, view: RecordView, order: str | None = None) -> str:
    hits = find_dates(value)
    if not hits:
        return value
    out, last = [], 0
    for h in hits:
        d = h.parse(order or view.order, view.ref_year)
        if d is None:
            continue
        out.append(value[last:h.start])
        out.append(h.render(d + dt.timedelta(days=view.shift), order or view.order))
        last = h.end
    out.append(value[last:])
    return "".join(out)


def maybe_b64_text(s: str) -> str | None:
    if len(s) < 16 or not re.fullmatch(r"[A-Za-z0-9+/=\s]+", s):
        return None
    try:
        raw = base64.b64decode(re.sub(r"\s", "", s) + "=" * (-len(re.sub(r"\s", "", s)) % 4), validate=False)
        txt = raw.decode("utf-8")
    except Exception:
        return None
    printable = sum(1 for c in txt if c.isprintable() or c in "\n\r\t")
    if not txt or printable / len(txt) < 0.95:
        return None
    return txt
