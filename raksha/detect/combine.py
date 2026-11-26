"""Span model and overlap resolution."""
from __future__ import annotations

from dataclasses import dataclass, field

# Higher = wins an overlap first (then confidence, then length).
PRIORITY = {
    "EMAIL": 9, "ABHA_ADDRESS": 9, "ABHA_NUMBER": 8, "AADHAAR": 8, "AADHAAR_MASKED": 8, "PAN": 8, "INSURANCE_ID": 8,
    "PHONE": 7, "MRN": 7, "ADDRESS": 6, "DOB": 6, "PATIENT_NAME": 5, "RELATIVE_NAME": 5, "OTHER_NAME": 5,
    "HOUSE": 4, "LOCALITY": 4, "LANDMARK": 4, "VILLAGE": 4, "TEHSIL": 3, "DISTRICT": 3, "PIN": 3, "AGE": 2,
}
NAME_TYPES = {"PATIENT_NAME", "RELATIVE_NAME", "OTHER_NAME"}
LOCATION_TYPES = {"ADDRESS", "HOUSE", "LOCALITY", "LANDMARK", "VILLAGE", "TEHSIL", "DISTRICT", "PIN"}


@dataclass
class Span:
    start: int
    end: int
    etype: str
    conf: float = 0.8
    value: str = ""          # normalised value (digits for phones, canonical text for names...)
    role: str = "patient"    # patient | relative | other
    meta: dict = field(default_factory=dict)

    @property
    def length(self) -> int:
        return self.end - self.start


def resolve(spans: list[Span]) -> list[Span]:
    """Greedy non-overlapping selection: priority, then confidence, then length."""
    order = sorted(spans, key=lambda s: (-PRIORITY.get(s.etype, 1), -s.conf, -s.length, s.start))
    chosen: list[Span] = []
    for s in order:
        if s.end <= s.start:
            continue
        clash = False
        for c in chosen:
            if s.start < c.end and c.start < s.end:
                clash = True
                break
        if not clash:
            chosen.append(s)
    # A longer lower-priority span (e.g. ADDRESS) swallowing smaller ones is handled by priority already.
    return sorted(chosen, key=lambda s: s.start)


def merge_adjacent_names(text: str, spans: list[Span]) -> list[Span]:
    """Join name spans separated only by a space (e.g. 'Brajesh' + 'Yadav')."""
    out: list[Span] = []
    for s in sorted(spans, key=lambda x: x.start):
        if out and s.etype in NAME_TYPES and out[-1].etype == s.etype and out[-1].role == s.role \
                and text[out[-1].end:s.start] in (" ", "") and s.start >= out[-1].end:
            prev = out[-1]
            out[-1] = Span(prev.start, s.end, prev.etype, max(prev.conf, s.conf), (prev.value + " " + s.value).strip(),
                           prev.role, dict(prev.meta))
        else:
            out.append(s)
    return out
