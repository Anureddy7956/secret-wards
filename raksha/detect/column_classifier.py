"""Classify a CSV column / JSON key path by (a) header semantics in English, Hinglish and Hindi and
(b) statistics of its values. Value rules alone decide when the header is unseen or garbage."""
from __future__ import annotations

import re
import statistics

from ..translit.devanagari import has_devanagari, transliterate
from . import names as N
from .patterns import AADHAAR_RX, ABHA_RX, EMAIL_RX, MASKED_AADHAAR_RX, PAN_RX, PHONE_RX, digits, id_shape
from ..privacy.dates import find_dates

CLASSES = {
    "PATIENT_NAME", "NAME_PART", "RELATIVE_NAME", "OTHER_NAME", "RELATION", "DOCTOR", "PHONE", "EMAIL", "MRN",
    "AADHAAR", "ABHA_NUMBER", "ABHA_ADDRESS", "PAN", "INSURANCE_ID", "ADDRESS", "VILLAGE", "TEHSIL", "DISTRICT",
    "STATE", "PIN", "DOB", "AGE", "AGE_SEX", "GENDER", "DATE", "TEXT", "KEEP", "SOURCE_PATH", "BASE64",
}

KEEP_PARENTS = {"facility", "hospital", "lab", "laboratory", "organization", "organisation", "org", "panel", "panels",
                "test", "tests", "drug", "drugs", "rx", "medication", "medications", "medicine", "department", "ward",
                "wards", "practitioner", "doctor", "diagnosis", "diagnoses", "code", "coding", "results", "result",
                "item", "items", "product", "package", "insurer", "payer", "company", "clinic", "branch", "system",
                "serviceprovider", "author", "performer", "requester", "qualification", "location"}
OTHER_PERSON_PARENTS = {"raised", "visitors", "callers", "raised_by", "raisedby", "caller", "visitor", "witness", "staff", "user", "operator",
                        "reporter", "informant", "contact_person", "escort", "submitted_by", "created_by", "agent"}
RELATIVE_WORDS = {"guardian", "relative", "father", "mother", "husband", "spouse", "pita", "pati", "mata", "kin",
                  "attendant", "nok", "parent", "wife", "son", "daughter", "s_o", "d_o", "w_o", "c_o", "so", "wo",
                  "guarantor", "nominee", "mothers", "fathers", "abhibhavak", "sambandhi"}


HINDI_HEADER = {
    "मोबाइल": " mobile ", "फोन": " phone ", "फ़ोन": " phone ", "नाम": " name ", "पता": " address ", "ग्राम": " village ",
    "गांव": " village ", "गाँव": " village ", "तहसील": " tehsil ", "जिला": " district ", "ज़िला": " district ",
    "आयु": " age ", "उम्र": " age ", "लिंग": " gender ", "जन्म": " birth ", "तिथि": " date ", "तारीख": " date ",
    "दिनांक": " date ", "आधार": " aadhaar ", "पिता": " father ", "पति": " husband ", "माता": " mother ", "पिन": " pin ",
    "पंजीकरण": " reg ", "संख्या": " no ", "सं.": " no ", "नं.": " no ", "मरीज़": " patient ", "मरीज": " patient ",
    "रोगी": " patient ", "मोहल्ला": " mohalla ", "राज्य": " state ", "ईमेल": " email ", "पिनकोड": " pincode ",
}


def label_tokens(label: str) -> list[str]:
    s = label
    for hw, en in HINDI_HEADER.items():
        if hw in s:
            s = s.replace(hw, en)
    if has_devanagari(s):
        s = transliterate(s)
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = s.lower().replace("'s", "")
    return [t for t in re.split(r"[^a-z0-9]+", s) if t]


def _has(toks, words) -> bool:
    return any(t in words for t in toks)


def classify_header(path: list[str]) -> tuple[str | None, str | None]:
    """Return (class, date_order_hint) from the key path (last element is the field label)."""
    if not path:
        return None, None
    label = path[-1]
    toks = label_tokens(label)
    joined = " ".join(toks)
    parents = [t for p in path[:-1] for t in label_tokens(p)]
    parents += [re.sub(r"[^a-z0-9]+", "_", p.lower()).strip("_") for p in path[:-1]]
    parents = set(parents)
    order = "mdy" if re.search(r"mm\W*dd\W*yy", label, re.I) else ("dmy" if re.search(r"dd\W*mm\W*yy", label, re.I)
                                                                     else None)
    if not toks:
        return None, order
    last = toks[-1]
    is_name_key = _has(toks, {"name", "naam", "nam", "fullname", "patientname", "ptname", "pname"}) or joined in (
        "nama",)
    # --- organisational / clinical parents: their 'name' is not a person
    if is_name_key and _has(parents, KEEP_PARENTS) and not _has(parents | set(toks), {"patient", "pt", "guardian", "contact", "patients"}) \
            and not _has(toks, {"patientname", "ptname", "pname"}):
        return "KEEP", order
    if _has(toks, {"doctor", "consultant", "physician", "dr", "practitioner", "surgeon"}) or joined in (
            "referred by", "ref by", "referredby", "ref doctor", "treating"):
        return "DOCTOR", order
    if joined in ("relation", "rel", "relationship", "rishta", "sambandh") or last in ("relation", "relationship"):
        return "RELATION", order
    if _has(parents, OTHER_PERSON_PARENTS) and (is_name_key or len(toks) == 1 and toks[0] in ("by",)):
        return "OTHER_NAME", order
    if _has(toks, RELATIVE_WORDS) or (is_name_key and _has(parents, RELATIVE_WORDS | {"contact"})):
        if not _has(toks, {"mobile", "phone", "mob", "relation", "relationship", "date"}):
            return "RELATIVE_NAME", order
    if _has(toks, {"birth", "dob", "janm", "birthdate", "janam"}) or joined == "d o b":
        return "DOB", order
    if _has(toks, {"email", "mail", "e"}) and _has(toks, {"email", "mail"}):
        return "EMAIL", order
    if "abha" in toks and _has(toks, {"address", "addr"}):
        return "ABHA_ADDRESS", order
    if _has(toks, {"abha", "healthid"}) or joined in ("health id",):
        return "ABHA_NUMBER", order
    if _has(toks, {"aadhaar", "aadhar", "adhar", "aadha", "uid", "aadhaarno"}):
        return "AADHAAR", order
    if _has(toks, {"pan"}) or joined in ("payer pan", "pan no"):
        return "PAN", order
    if _has(toks, {"pmjay", "policy", "insurance", "ayushman", "member", "polno", "insurer_id"}):
        return "INSURANCE_ID", order
    if _has(toks, {"date", "dt", "tithi", "timestamp", "datetime", "time", "on", "at", "registered", "lastupdated",
                   "dated", "tarikh"}) and not _has(toks, {"no", "number", "id"}):
        return "DATE", order
    if _has(toks, {"mobile", "mob", "phone", "tel", "telephone", "cell", "callback", "whatsapp", "contactno",
                   "mobileno", "ph", "phno", "landline"}) or joined in ("contact", "contact no", "contact number"):
        return "PHONE", order
    if _has(toks, {"uhid", "mrn", "uid", "crno", "patientid", "pid", "regno", "ipd", "ipno", "admno",
                   "hospno", "patientref"}) or joined in (
            "patient id", "patient ref", "reg no", "reg number", "registration no", "registration number", "mr no",
            "cr no", "hospital uhid", "hospital no", "admission no", "ipd no", "card no", "patient no", "regn no",
            "patient_ref", "hospital id", "mr number", "file no"):
        return "MRN", order
    if _has(toks, {"pin", "pincode", "zip", "zipcode", "postal", "postalcode", "postcode"}):
        return "PIN", order
    if _has(toks, {"tehsil", "taluk", "taluka", "tahsil", "block", "mandal"}):
        return "TEHSIL", order
    if _has(toks, {"district", "distt", "dist", "jila", "zila", "zilla", "janpad"}):
        return "DISTRICT", order
    if _has(toks, {"state", "rajya", "pradesh"}):
        return "STATE", order
    if _has(toks, {"village", "gaon", "gram", "city", "town", "mohalla", "locality", "basti", "ward_no", "gali",
                   "colony", "area"}):
        return "VILLAGE", order
    if _has(toks, {"address", "addr", "street", "pata", "house", "residence", "line", "makan", "landmark", "line1",
                   "line2", "nivas"}):
        return "ADDRESS", order
    if joined in ("age sex", "agesex", "age gender", "age_sex") or ("age" in toks and _has(toks, {"sex", "gender"})):
        return "AGE_SEX", order
    if _has(toks, {"age", "umar", "umr", "aayu", "ayu", "umra"}):
        return "AGE", order
    if _has(toks, {"gender", "sex", "ling"}):
        return "GENDER", order
    if _has(toks, {"first", "firstname", "given", "fname", "last", "lastname", "surname", "family", "lname",
                   "middle", "middlename"}):
        return "NAME_PART", order
    if is_name_key or joined in ("patient", "pt", "mareez", "rogi", "name local", "local"):
        if joined == "local" and not _has(parents, {"name"}):
            return None, order
        return "PATIENT_NAME", order
    if _has(toks, {"path", "filename", "file", "source", "sourcepath", "url", "uri"}) and not _has(toks, {"system"}):
        return "SOURCE_PATH", order
    if joined in ("data",):
        return "BASE64", order
    return None, order


# ---------------------------------------------------------------------------------------- values
GENDER_VALUES = {"m", "f", "male", "female", "o", "other", "t", "पुरुष", "महिला", "स्त्री", "unknown", "u", "mard",
                 "aurat", "man", "woman", "boy", "girl"}
AGE_SEX_RX = re.compile(r"^\s*\d{1,3}\s*(?:y|yrs?|years?)?\s*/\s*[MFmf]\w*\s*$")


def _frac(values, pred) -> float:
    vals = [v for v in values if v.strip()]
    if not vals:
        return 0.0
    return sum(1 for v in vals if pred(v)) / len(vals)


def _is_phone(v: str) -> bool:
    m = PHONE_RX.search(v)
    return bool(m) and len(digits(v)) <= 13 and m.end() - m.start() >= len(v.strip()) - 3


def _name_value(v: str) -> bool:
    v = v.strip()
    if not v or any(c.isdigit() for c in v) or len(v) > 60:
        return False
    toks = N.tokens(v)
    if not 1 <= len(toks) <= 4:
        return False
    return all(N.name_like(t[2], strict=False) or N.is_gaz(t[2]) for t in toks)


def classify_values(values: list[str], learned_shapes: set | None = None, ref_year: int = 2026) -> str | None:
    vals = [str(v) for v in values if v is not None and str(v).strip()]
    if len(vals) == 0:
        return None
    sample = vals[:400]
    if _frac(sample, lambda v: bool(EMAIL_RX.fullmatch(v.strip()))) > 0.6:
        return "EMAIL"
    if _frac(sample, lambda v: bool(ABHA_RX.fullmatch(v.strip()))) > 0.6:
        return "ABHA_NUMBER"
    if _frac(sample, lambda v: bool(AADHAAR_RX.fullmatch(v.strip()) or MASKED_AADHAAR_RX.fullmatch(v.strip()))) > 0.6:
        return "AADHAAR"
    if _frac(sample, lambda v: bool(PAN_RX.fullmatch(v.strip()))) > 0.6:
        return "PAN"
    if _frac(sample, _is_phone) > 0.6:
        return "PHONE"
    if learned_shapes and _frac(sample, lambda v: id_shape(v.strip()) in learned_shapes) > 0.6:
        return "MRN"
    if _frac(sample, lambda v: bool(AGE_SEX_RX.match(v))) > 0.6:
        return "AGE_SEX"
    if _frac(sample, lambda v: v.strip().lower() in GENDER_VALUES) > 0.8:
        return "GENDER"
    date_frac = _frac(sample, lambda v: len(find_dates(v)) == 1 and len(v.strip()) <= 32)
    if date_frac > 0.6:
        years = []
        for v in sample:
            for h in find_dates(v):
                d = h.parse("dmy", ref_year) or h.parse("mdy", ref_year)
                if d:
                    years.append(d.year)
        if len(years) >= 3 and max(years) - min(years) >= 15 and statistics.median(years) < ref_year - 5:
            return "DOB"
        return "DATE"
    if _frac(sample, lambda v: bool(re.search(r"(?i)\b(?:h\.?\s?no|house|makan|mohalla|near|tehsil|distt|"
                                              r"village|vill\.|gram)\b|मकान|मोहल्ला|तहसील|जिला", v))) > 0.5:
        return "ADDRESS"
    if _frac(sample, lambda v: bool(re.fullmatch(r"[1-9]\d{5}", v.strip()))) > 0.9:
        return "PIN_CANDIDATE"
    if _frac(sample, lambda v: bool(re.match(r"(?i)^\s*(?:s|d|w)\s*/\s*o\b", v))) > 0.6:
        return "RELATIVE_NAME"
    if _frac(sample, _name_value) > 0.7:
        gaz = _frac(sample, lambda v: any(N.is_gaz(t[2]) for t in N.tokens(v)))
        if gaz > 0.5:
            return "PATIENT_NAME"
    return None


def classify(path: list[str], values: list[str], learned_shapes: set | None = None) -> tuple[str, str | None]:
    cls, order = classify_header(path)
    if cls is None or cls in ("SOURCE_PATH",):
        vcls = classify_values(values, learned_shapes)
        if vcls == "PIN_CANDIDATE":
            vcls = None
        if vcls is not None and cls is None:
            return vcls, order
    return (cls or "TEXT"), order
