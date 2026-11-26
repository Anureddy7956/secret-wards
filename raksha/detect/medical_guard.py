"""Protected (never-redact) spans: the meaning traps.

* clinicians: 'Dr. Ramesh Srivastava', 'डॉ. …', 'Doctor X'
* complaint / history markers: 'C/O fever x 3 days', 'K/C/O addison's disease', 'H/O TB'
* doses, frequencies, durations: 'Dolo 650', 'Ramipril 5 mg', '1-0-1', 'BD x 5 days'
* vitals and labs with units: 'BP 150/90', 'SpO2 96%', 'Hb 9.8 g/dL'
* eponyms: "Parkinson's disease", 'Down syndrome', 'Hodgkin lymphoma'
* hospital wards / beds: 'Ward 4 (Medicine)', 'Ward/Bed: …', 'Bed 24'
* organisation names: '… Hospital', '… Pathology', 'ASHA worker'
Each guard is (start, end, kind).
"""
from __future__ import annotations

import re

from .lexicon import get_lexicon

UNITS = (r"(?:mg/dl|mg/dL|g/dl|g/dL|mmol/l|mmol/L|meq/l|mEq/L|iu/l|IU/L|u/l|U/L|mIU/L|miu/l|µIU/mL|uIU/mL|ng/ml|ng/mL|"
         r"pg/ml|pg/mL|/cumm|/cu\.?mm|/ul|/uL|/µL|/mm3|cells/cumm|lakh/cumm|mmHg|mm\s?Hg|/min|bpm|breaths/min|kg|kgs|"
         r"cm|mcg|µg|mg|gm|g|ml|mL|l|L|iu|IU|units?|%|°F|°C|F|C|puffs?|drops?|tabs?|caps?|sachets?|mm|fl|pg|sec|s)")

DOCTOR_RX = re.compile(
    r"(?:\b(?:Dr|DR|dr|Doctor|DOCTOR|Prof|Consultant\s+Dr)\b\.?[ \t]*|डॉ\.?[ \t]*|डा\.[ \t]*|डॉक्टर[ \t]+)"
    r"((?:[A-Z]\.[ ]?){0,3}[A-Z][A-Za-z'’]+(?:[ ][A-Z][A-Za-z'’]+){0,2}|(?:[A-Z]\.[ ]?){1,3}"
    r"|[\u0900-\u097F]+(?:[ ][\u0900-\u097F]+){0,2})"
)
COMPLAINT_RX = re.compile(r"\b(?:K/C/O|k/c/o|C/O|c/o|H/O|h/o|C/o|H/o|K/c/o)\b\s*:?\s*")
FREQ_RX = re.compile(r"(?<![\d\-])[0-4](?:[\-–][0-4½]){2,3}(?![\d\-])")
FREQ_WORD_RX = re.compile(r"\b(?:OD|BD|BID|TDS|TID|QID|QDS|HS|SOS|STAT|PRN|AC|PC|QHS|OW|BBF)\b")
DURATION_RX = re.compile(r"\b[xX×]\s*\d+\s*(?:days?|d|wks?|weeks?|months?|mths?|yrs?|years?|hrs?|hours?|doses?)\b")
DOSE_RX = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?:\s*\+\s*\d+(?:\.\d+)?)?\s*" + UNITS + r"(?![A-Za-z])")
BP_RX = re.compile(r"\b(?:BP|B\.P\.?|bp)\s*[:\-]?\s*\d{2,3}\s*/\s*\d{2,3}(?:\s*mm\s?Hg)?")
VITAL_RX = re.compile(
    r"\b(?:SpO2|SPO2|spo2|PR|HR|RR|Pulse|pulse|Temp|temp|Wt|Weight|Ht|Height|GRBS|RBS|FBS|PPBS|Hb|HbA1c|TLC|Plt)"
    r"\s*[:\-]?\s*\d+(?:\.\d+)?\s*(?:" + UNITS + r")?")
EPONYM_RX = re.compile(
    r"\b[A-Z][a-z]+(?:['’]s)?(?:[\s\-][A-Z][a-z]+(?:['’]s)?)?\s+(?:disease|syndrome|palsy|sarcoma|lymphoma|tumou?r|"
    r"anomaly|phenomenon|sign|ulcer|fracture|anaemia|anemia|encephalopathy|disorder)\b", re.I)
EPONYM_POSS_RX = re.compile(r"\b[A-Za-z][a-z]+['’]s\b")
WARD_RX = re.compile(r"\b(?:Ward|WARD)\s*(?:No\.?)?\s*:?\s*\d+\s*\([A-Za-z &]+\)|\bWard\s*/\s*Bed\s*:[^\n]*|"
                     r"\b(?:Bed|BED)\s*(?:No\.?)?\s*:?\s*\d+\b|\bWard\s*:\s*\d+\s*\([A-Za-z ]+\)")
ASHA_RX = re.compile(r"\bASHA\b(?=\s+(?:worker|workers|karyakarta|karyakarti|sahyogini|facilitator|didi|bahu))|"
                     r"\bASHA\s+(?:worker|workers)\b", re.I)
ICD_PAREN_RX = re.compile(r"\(\s*[A-TV-Z]\d{2}(?:\.\d{1,2})?\s*\)")


def find_guards(text: str) -> list[tuple[int, int, str]]:
    lex = get_lexicon()
    g: list[tuple[int, int, str]] = []
    for m in DOCTOR_RX.finditer(text):
        g.append((m.start(), m.end(), "doctor"))
    # Complaint / history: marker followed by a clinical word, not a person
    for m in COMPLAINT_RX.finditer(text):
        marker = m.group(0).strip().rstrip(":").strip().upper()
        has_colon = ":" in m.group(0)
        rest = text[m.end(): m.end() + 60]
        if marker == "K/C/O" or has_colon or is_clinical_word(rest):
            end = text.find("\n", m.end())
            end = len(text) if end < 0 else end
            stop = re.search(r"[;|]|\.\s|\.$|\(S/o|\(W/o|\(D/o", text[m.end():end])
            if stop:
                end = m.end() + stop.start()
            g.append((m.start(), end, "complaint"))
    for rx, kind in ((FREQ_RX, "freq"), (FREQ_WORD_RX, "freq"), (DURATION_RX, "freq"), (DOSE_RX, "dose"),
                     (BP_RX, "vital"), (VITAL_RX, "vital"), (WARD_RX, "ward"), (ASHA_RX, "org"),
                     (ICD_PAREN_RX, "icd")):
        for m in rx.finditer(text):
            g.append((m.start(), m.end(), kind))
    for m in EPONYM_RX.finditer(text):
        g.append((m.start(), m.end(), "eponym"))
    for m in EPONYM_POSS_RX.finditer(text):
        nxt = text[m.end(): m.end() + 20].lower()
        if re.match(r"\s*(?:disease|syndrome|palsy|sarcoma|lymphoma|tumou?r|sign|ulcer|disorder|anaemia)", nxt):
            g.append((m.start(), m.end(), "eponym"))
    # drug name + strength: 'Dolo 650', 'Crocin 500'
    for m in re.finditer(r"\b([A-Za-z][A-Za-z\-]{2,})\s+(\d{2,4})(?:\s*(?:mg|mcg))?\b", text):
        if m.group(1).lower() in lex.drugs:
            g.append((m.start(), m.end(), "dose"))
    # organisation names: Titlecase run ending with an org word
    for m in re.finditer(r"(?:[A-Z][A-Za-z\-]*\s+){0,4}(?:" + "|".join(sorted(
            (re.escape(w.capitalize()) for w in lex.org_words if len(w) > 2), key=len, reverse=True)) + r")\b", text):
        g.append((m.start(), m.end(), "org"))
    for m in re.finditer(r"(?:[A-Z][A-Z\-]*\s+){0,4}(?:HOSPITAL|SADAN|CLINIC|LABS?|PATHOLOGY|DIAGNOSTICS|CENTRE|CENTER|"
                         r"NURSING HOME|INSTITUTE|TRUST)\b", text):
        g.append((m.start(), m.end(), "org"))
    return g


def is_clinical_word(rest: str) -> bool:
    """Is the text after C/O, H/O a complaint/history (True) or a person's name (False)?"""
    from ..translit.canonical import canon_token
    from ..translit.devanagari import transliterate
    lex = get_lexicon()
    first = re.match(r"\s*([^\s,;:()/]+)", rest)
    if not first:
        return True
    w = first.group(1)
    wl = w.lower().strip(".'’")
    if re.match(r"[\u0900-\u097F]", w):
        return canon_token(transliterate(w)) not in (lex.first | lex.sur)
    if any(ch.isdigit() for ch in w) or w[:1].islower():
        return True
    if re.match(r"[A-Za-z]+['’]s$", w):
        return True  # eponym: Addison's
    base = wl[:-1] if wl.endswith("s") else wl
    if wl in lex.medical or base in lex.medical:
        return True
    if lex.is_name_gaz(w):
        return False
    if w.isupper() and len(w) <= 5:
        return True  # TB, DM, HTN, COPD
    return lex.is_vocab(w)


def inside(guards, s: int, e: int, kinds=None) -> bool:
    for a, b, k in guards:
        if a <= s and e <= b and (kinds is None or k in kinds):
            return True
    return False


def overlaps(guards, s: int, e: int, kinds=None) -> bool:
    for a, b, k in guards:
        if s < b and a < e and (kinds is None or k in kinds):
            return True
    return False
