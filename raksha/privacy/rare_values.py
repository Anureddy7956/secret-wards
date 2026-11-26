"""Rare-value suppression for the re-identification trap.

A diagnosis (ICD-10 code + its display text) or a procedure held by fewer than
`rare_values.min_patients` distinct patients in the release is a near-unique quasi-identifier
(attack A5 weights such a condition x8). Those values are generalised for the affected records only:
ICD code -> its ICD-10 chapter range, display text -> chapter title, procedure -> '[RARE PROCEDURE]'.
Lengths of stay, vitals, labs and doses are never touched.
"""
from __future__ import annotations

import re
from collections import defaultdict

CHAPTERS = [
    ("A00", "B99", "Certain infectious and parasitic diseases"), ("C00", "D49", "Neoplasms"),
    ("D50", "D89", "Diseases of the blood and immune mechanism"), ("E00", "E89", "Endocrine, nutritional and metabolic diseases"),
    ("F01", "F99", "Mental and behavioural disorders"), ("G00", "G99", "Diseases of the nervous system"),
    ("H00", "H59", "Diseases of the eye and adnexa"), ("H60", "H95", "Diseases of the ear and mastoid process"),
    ("I00", "I99", "Diseases of the circulatory system"), ("J00", "J99", "Diseases of the respiratory system"),
    ("K00", "K95", "Diseases of the digestive system"), ("L00", "L99", "Diseases of the skin and subcutaneous tissue"),
    ("M00", "M99", "Diseases of the musculoskeletal system"), ("N00", "N99", "Diseases of the genitourinary system"),
    ("O00", "O9A", "Pregnancy, childbirth and the puerperium"), ("P00", "P96", "Perinatal conditions"),
    ("Q00", "Q99", "Congenital malformations"), ("R00", "R99", "Symptoms and abnormal findings"),
    ("S00", "T88", "Injury and poisoning"), ("V00", "Y99", "External causes"), ("Z00", "Z99", "Factors influencing health status"),
]
ICD_RX = re.compile(r"(?<![A-Za-z0-9.])([A-TV-Z]\d{2}(?:\.\d{1,2})?)(?![A-Za-z0-9])")
DISPLAY_CODE_RX = re.compile(r"([A-Za-z][A-Za-z ,'’()\-]{3,80}?)\s*\(\s*([A-TV-Z]\d{2}(?:\.\d{1,2})?)\s*\)")
PROC_TEXT_RX = re.compile(r"(?i)\bProcedure\s*:\s*([^\n.;]{3,80}?)\s+(?:done|performed|on\b)")


def chapter(code: str):
    c3 = code[:3].upper()
    for lo, hi, name in CHAPTERS:
        if lo <= c3 <= hi:
            return f"{lo}-{hi}", name
    return "R00-R99", "Symptoms and abnormal findings"


def _record_strings(pipe, d, rec):
    from ..pipeline import data_get
    out = []
    if d.fmt == "text":
        out.append(d.text)
    elif d.fmt == "csv":
        idx = d.records.index(rec)
        row = d.rows[idx + 1]
        header = d.rows[0]
        for i, c in enumerate(row):
            h = header[i].lower() if i < len(header) else ""
            out.append(("PROC::" + c) if "procedure" in h and c.strip() else c)
    else:
        for path, cls, _ in rec.fields:
            v = data_get(d.parsed, path)
            if isinstance(v, str):
                keys = [k for k in path if isinstance(k, str)]
                if d.fmt == "fhir" and len(path) > 2:
                    res = data_get(d.parsed, path[:3]) or {}
                    if isinstance(res, dict) and res.get("resourceType") == "Procedure" and keys[-1:] in (["display"], ["text"]):
                        out.append("PROC::" + v)
                        continue
                if keys and keys[-1].lower() in ("procedure", "procedures"):
                    out.append("PROC::" + v)
                    continue
                out.append(v)
    return out


def plan(pipe, policy) -> dict:
    if not policy.get("rare_values.enabled", True):
        return {"codes": {}, "displays": {}, "procs": set()}
    minp = int(policy.get("rare_values.min_patients", 2))
    code_pat = defaultdict(set)
    proc_pat = defaultdict(set)
    displays = defaultdict(set)
    for d in pipe.docs:
        if d.status != "sanitized":
            continue
        for rec in d.records:
            who = ("c", rec.cid) if rec.cid is not None else ("r", d.rel, rec.loc)
            strings = _record_strings(pipe, d, rec)
            for s in strings:
                if s.startswith("PROC::"):
                    p = s[6:].strip()
                    if p:
                        proc_pat[p.lower()].add(who)
                    continue
                for m in ICD_RX.finditer(s):
                    code_pat[m.group(1).upper()].add(who)
                for m in DISPLAY_CODE_RX.finditer(s):
                    displays[m.group(2).upper()].add(m.group(1).strip(" ,;:").strip())
                for m in PROC_TEXT_RX.finditer(s):
                    proc_pat[m.group(1).strip().lower()].add(who)
            # structured code/display siblings (OPD JSON, FHIR coding)
            if d.fmt in ("json", "fhir"):
                for path, cls, _ in rec.fields:
                    if path and path[-1] == "code":
                        from ..pipeline import data_get
                        parent = data_get(d.parsed, path[:-1])
                        if isinstance(parent, dict) and isinstance(parent.get("display"), str):
                            code = str(parent.get("code", "")).upper()
                            if ICD_RX.fullmatch(code):
                                displays[code].add(parent["display"])
    rare_codes = {c: chapter(c) for c, who in code_pat.items() if len(who) < minp}
    disp = {}
    for c in rare_codes:
        for t in displays.get(c, ()):
            if len(t) >= 4:
                disp[t.lower()] = rare_codes[c][1]
    procs = {p for p, who in proc_pat.items() if len(who) < minp and len(p) >= 4}
    return {"codes": rare_codes, "displays": disp, "procs": procs}


def apply(pipe, rec, text: str) -> str:
    r = getattr(pipe, "rare", None)
    if not r or not text or not (r["codes"] or r["procs"]):
        return text
    orig = text
    for disp, chap in sorted(r["displays"].items(), key=lambda kv: -len(kv[0])):
        if disp in text.lower():
            text = re.sub(re.escape(disp), chap, text, flags=re.I)
    if r["codes"]:
        text = ICD_RX.sub(lambda m: r["codes"][m.group(1).upper()][0] if m.group(1).upper() in r["codes"]
                          else m.group(1), text)
    for p in sorted(r["procs"], key=len, reverse=True):
        if p in text.lower():
            text = re.sub(re.escape(p), "[RARE PROCEDURE]", text, flags=re.I)
    if text != orig and rec is not None:
        rec.suppressed = True
    return text
