"""Regex detectors for direct identifiers. Each returns (start, end, type, normalized_value, confidence).

Digits are matched across separators (space, dash, dot); Devanagari digits are converted to ASCII
before detection (see normalize.py), so ९८७६५४३२१० is found like 9876543210.
"""
from __future__ import annotations

import re

SEP = r"[ \-.]"

PHONE_RX = re.compile(
    r"(?<![\w/+])"
    r"(?:(?:\+|00)\s?91[ \-.]?\(?0?\)?[ \-.]?|91[ \-]|\(?0\)?[ \-]?)?"
    r"([6-9]\d(?:[ \-.]?\d){8})"
    r"(?![\d/])(?!\.\d)"
)
LANDLINE_RX = re.compile(r"(?<![\w/])\(?0\d{2,4}\)?[ \-]\d{6,8}(?![\d/])")
AADHAAR_RX = re.compile(r"(?<![\w\-/.])(\d{4})([ \-]?)(\d{4})\2(\d{4})(?![\w\-/]|\.\d)")
ABHA_RX = re.compile(r"(?<![\w\-/.])\d{2}([ \-]?)\d{4}\1\d{4}\1\d{4}(?![\w\-/]|\.\d)")
ABHA_ADDR_RX = re.compile(r"\b[A-Za-z0-9._\-]{2,}@(?:abdm|sbx|ndhm|abha)\b", re.I)
EMAIL_RX = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}\b")
PAN_RX = re.compile(r"(?<![A-Za-z0-9])[A-Z]{5}\d{4}[A-Z](?![A-Za-z0-9])")
MASKED_AADHAAR_RX = re.compile(r"(?<![\w])[Xx*]{4}[ \-]?[Xx*]{4}[ \-]?\d{4}(?!\d)")
MASKED_PHONE_RX = re.compile(r"(?<![\w])(?:\+91[ \-]?)?[6-9]\d[Xx*]{5,6}\d{2,3}(?!\d)")
INSURANCE_RX = re.compile(
    r"(?<![A-Za-z0-9])(?:PMJAY|AB[\-\s]?PMJAY|ABPMJAY|CGHS|ESIC?|ECHS|RSBY)[ \-/]?(?:[A-Z]{2}[ \-/]?)?\d{6,14}(?!\d)"
    r"|(?<![A-Za-z0-9])POL(?:ICY)?[ \-/]?\d{2,4}[ \-/]\d{4,12}(?!\d)",
    re.I,
)
# Candidate alphanumeric identifiers: a letter-led token with >= 4 digits, internal / or - allowed.
ID_CANDIDATE_RX = re.compile(
    r"(?<![A-Za-z0-9/\-])([A-Za-z][A-Za-z0-9]*(?:[/\-][A-Za-z0-9]+)+|[A-Za-z]{1,6}\d{4,})(?![A-Za-z0-9/]|-[A-Za-z0-9])"
)
DIGIT_RUN_RX = re.compile(r"(?<![\d])\d{5,}(?![\d])")
ICD_RX = re.compile(r"\b[A-TV-Z]\d{2}(?:\.\d{1,2})?\b")


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def norm_id(s: str) -> str:
    """Normalised identifier key: uppercase alphanumerics only (SNJ/26/064127 == SNJ-26-064127)."""
    return re.sub(r"[^A-Za-z0-9]", "", s).upper()


def id_shape(s: str) -> str:
    """Shape of an identifier: letters kept (upper), digit runs -> '9' * len, separators unified."""
    s = s.upper()
    s = re.sub(r"[/\-]", "-", s)
    return re.sub(r"\d", "9", s)


def digit_core(s: str) -> str:
    d = digits(s)
    return d


def find_phones(text: str):
    out = []
    for m in PHONE_RX.finditer(text):
        core = digits(m.group(1))
        if len(core) != 10:
            continue
        out.append((m.start(), m.end(), "PHONE", core, 0.9))
    for m in LANDLINE_RX.finditer(text):
        d = digits(m.group(0))
        if 10 <= len(d) <= 12:
            out.append((m.start(), m.end(), "PHONE", d[-10:], 0.7))
    for m in MASKED_PHONE_RX.finditer(text):
        out.append((m.start(), m.end(), "PHONE", m.group(0), 0.8))
    return out


def find_direct_ids(text: str):
    """All pattern-based direct identifiers except names/addresses."""
    spans = []
    for m in EMAIL_RX.finditer(text):
        typ = "ABHA_ADDRESS" if ABHA_ADDR_RX.fullmatch(m.group(0)) else "EMAIL"
        spans.append((m.start(), m.end(), typ, m.group(0).lower(), 0.95))
    for m in ABHA_ADDR_RX.finditer(text):
        spans.append((m.start(), m.end(), "ABHA_ADDRESS", m.group(0).lower(), 0.95))
    for m in ABHA_RX.finditer(text):
        spans.append((m.start(), m.end(), "ABHA_NUMBER", digits(m.group(0)), 0.85))
    for m in AADHAAR_RX.finditer(text):
        spans.append((m.start(), m.end(), "AADHAAR", digits(m.group(0)), 0.85))
    for m in MASKED_AADHAAR_RX.finditer(text):
        spans.append((m.start(), m.end(), "AADHAAR_MASKED", digits(m.group(0)), 0.9))
    for m in PAN_RX.finditer(text):
        spans.append((m.start(), m.end(), "PAN", m.group(0), 0.9))
    for m in INSURANCE_RX.finditer(text):
        spans.append((m.start(), m.end(), "INSURANCE_ID", norm_id(m.group(0)), 0.9))
    spans.extend(find_phones(text))
    return spans


def find_id_candidates(text: str):
    """(start, end, raw) for alphanumeric ID-like tokens with >= 4 digits."""
    out = []
    for m in ID_CANDIDATE_RX.finditer(text):
        raw = m.group(1)
        if sum(c.isdigit() for c in raw) >= 4:
            out.append((m.start(1), m.end(1), raw))
    return out
