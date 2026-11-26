#!/usr/bin/env python3
"""Dev-only re-identification attack simulator (approximation of the kit's docs/ATTACKS.md).

Uses the practice attacker knowledge (dev/attacker/registry.csv with its leaked-contacts columns, and
dev/attacker/known_facts.jsonl with its decoys) plus the practice truth to score a release. Never
imported by the pipeline (the attacker files are not available on event day). Every attack is run on
the raw input too, and the ratio ours/raw is printed, as the kit normalises.

    A1  direct exposure        surviving direct identifiers / full names (content and file names)
    A3  record linkage         registry filtering: phone, email, Aadhaar last 4, masked phone, district,
                               gender, age, birth year, tehsil, village, PIN, PIN prefix; name/relative/house
                               weights
    A4  profile re-id          records pooled through shared pseudonyms, attacked again (share >= 0.5)
    A5  targeted (known facts) visit date / condition / length of stay / hospital, with global-shift recovery;
                               claims on decoys = membership-inference false positives
    A6  pseudonym inversion    pseudonym equals / prefixes a hash, base64, reversal... of the patient's IDs
    A7  cross-release linking  needs --output2 (a run with a different RAKSHA_SECRET)

    python tools/attack_sim.py --kit ../Secret-Wards-ToolKit --output out [--output2 out_other_secret] [-v]
"""
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

PSN = re.compile(r"PSN-[0-9A-Z]{6,}")


def norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


def load_registry(kit: Path):
    rows = list(csv.DictReader(open(kit / "dev/attacker/registry.csv", encoding="utf-8")))
    for r in rows:
        r["age"] = int(r["age"])
        parts = r["name"].lower().split()
        r["given"], r["sur"] = parts[0], parts[-1]
        r["email"] = r.get("email", "").strip().lower()
        r["aadhaar_last4"] = r.get("aadhaar_last4", "").strip()
        r["house_no"] = r.get("house_no", "").strip().lower()
    return rows


def load_facts(kit: Path):
    p = kit / "dev/attacker/known_facts.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def read_file(root: Path, rel: str, cache: dict) -> str:
    if rel not in cache:
        try:
            cache[rel] = (root / rel).read_bytes().decode("utf-8", errors="replace").lstrip("﻿")
        except OSError:
            cache[rel] = ""
    return cache[rel]


def record_text(root: Path, rel: str, loc: str, cache: dict) -> str:
    text = read_file(root, rel, cache)
    if loc == "doc" or not text:
        return text
    if loc.startswith("row:"):
        i = int(loc[4:])
        try:
            delim = "\t" if rel.endswith(".tsv") or "\t" in text.split("\n", 1)[0] else ","
            rows = list(csv.reader(io.StringIO(text), delimiter=delim))
            header, body = rows[0], rows[1:]
            row = body[i] if i < len(body) else []
            return " | ".join(f"{h}: {c}" for h, c in zip(header, row))
        except Exception:
            return ""
    if loc.startswith("/"):
        try:
            obj = json.loads(text)
            for part in loc.strip("/").split("/"):
                obj = obj[int(part)] if isinstance(obj, list) else obj[part.replace("~1", "/").replace("~0", "~")]
            return json.dumps(obj, ensure_ascii=False)
        except Exception:
            return text
    return text


# --------------------------------------------------------------------------- evidence extraction

AGE_RX = [re.compile(r"(?<![\d.\-])(\d{1,3})\s*-\s*(\d{1,3})\s*(?:yrs?|y|years?|वर्ष)?\s*(?:/|\s|\"|$|,)", re.I),
          re.compile(r"(?<![\d.\-])(\d{1,3})\+")]
# exact ages only: never the ends of a band ("Age: 60-79", "60-79 वर्ष", "80+"), which would wrongly exclude
# the true person and overstate privacy (the kit's attacker self-check)
_NOBAND = r"(?![\d+]|\s*[-–]\s*\d)"
AGE_EXACT = [re.compile(r"(?<![\d/.\-–])(\d{1,3})\s*(?:Yrs?|Y|years?|वर्ष)?\s*/\s*[MF]\b"),
             re.compile(r"(?i)\bage\W{1,4}(\d{1,3})" + _NOBAND),
             re.compile(r"(?<![\d\-–])(\d{1,3})\s*वर्ष"),
             re.compile(r"(?i)\"(?:age|umar)\"\s*:\s*(\d{1,3})\b"),
             re.compile(r"(?i)\bumar:\s*(\d{1,3})" + _NOBAND)]
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
LAST4 = re.compile(r"(?i)(?:x{4}|\*{4})[\s-]?(?:x{4}|\*{4})[\s-]?(\d{4})(?!\d)")
MASKED_PHONE = re.compile(r"(?<![\dA-Za-z])([6-9]\d)[xX*]{6}(\d{2})(?!\d)")
HOUSE = re.compile(r"(?i)\b(?:h\.?\s*no\.?|house\s*no\.?|मकान\s*नं\.?)\s*[:\-]?\s*(\d{1,4}[a-z]?)\b")
DOB = re.compile(r"(?i)(?:dob|d\.o\.b\.?|date of birth|birth_?date|जन्म\s*तिथि)\W{0,6}"
                 r"(?:\d{1,2}[/.\-]\d{1,2}[/.\-](\d{4})|(\d{4})-\d{2}-\d{2})")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                       "nov", "dec"], 1)}
D_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
D_NUM = re.compile(r"(?<![\d.])(\d{1,2})([/.\-])(\d{1,2})\2(\d{4}|\d{2})(?![\d])")
D_TXT = re.compile(r"(?i)(?<!\d)(\d{1,2})[\s\-]([a-z]{3})[a-z]*[\s\-,]+(\d{4})")

HOSPITALS = {"sanjeevani": "sanjeevani multispeciality hospital", "arogya": "arogya seva sadan",
             "jeevan jyoti": "jeevan jyoti charitable hospital", "jeevanjyoti": "jeevan jyoti charitable hospital",
             "hardoi": "district hospital hardoi", "dhhardoi": "district hospital hardoi"}
# Public ICD-10 codes for the condition vocabulary (the attacker's "rare-disease vocabulary").
ICD = {"type 2 diabetes mellitus": ["E11"], "rabies": ["A82"], "tuberculosis of lung": ["A15.0", "A15"],
       "visceral leishmaniasis": ["B55.0"], "kala-azar": ["B55.0"], "essential (primary) hypertension": ["I10"],
       "typhoid fever": ["A01.0"], "infectious gastroenteritis": ["A09"], "dengue": ["A90", "A91"],
       "malaria": ["B50", "B51", "B54"], "cholera": ["A00"], "leprosy": ["A30"], "addison": ["E27.1"]}


def _mkdate(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def parse_dates(text: str) -> dict:
    """{'D': [dates read day-first], 'M': [dates read month-first]}. ISO and textual dates go in both."""
    out = {"D": [], "M": []}
    for m in D_ISO.finditer(text):
        d = _mkdate(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d:
            out["D"].append(d)
            out["M"].append(d)
    for m in D_NUM.finditer(text):
        a, b, y = int(m.group(1)), int(m.group(3)), int(m.group(4))
        if y < 100:
            y += 2000
        if not 1900 <= y <= 2100:
            continue
        d1, d2 = _mkdate(y, b, a), _mkdate(y, a, b)
        if d1:
            out["D"].append(d1)
        if d2:
            out["M"].append(d2)
    for m in D_TXT.finditer(text):
        mo = MONTHS.get(m.group(2).lower())
        d = mo and _mkdate(int(m.group(3)), mo, int(m.group(1)))
        if d:
            out["D"].append(d)
            out["M"].append(d)
    return out


def evidence(text: str, reg_index, rel: str = "") -> dict:
    t = norm(text)
    ev = {"ages": [], "gender": None, "district": None, "tehsil": None, "village": None, "pin": None,
          "pin3": None, "names": set(), "phones": set(), "emails": set(), "last4": set(), "mphones": set(),
          "houses": set(), "byears": set(), "dates": set(), "intervals": set(), "hospitals": set()}
    for m in AGE_RX[0].finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        if 0 <= a < b <= 120 and b - a <= 25:
            ev["ages"].append((a, b))
    for m in AGE_RX[1].finditer(text):
        a = int(m.group(1))
        if 50 <= a <= 110:
            ev["ages"].append((a, 120))
    for rx in AGE_EXACT:
        for m in rx.finditer(text):
            a = int(m.group(1))
            if a <= 120:
                ev["ages"].append((a, a))
    if re.search(r"/\s*F\b|female|महिला|\bW/o\b|\bD/o\b|behenji|didi|\"F\"|,F,|\bF\t", text):
        ev["gender"] = "F"
    elif re.search(r"/\s*M\b|\bmale\b|पुरुष|\bS/o\b|sahab|\"M\"|,M,|\bM\t", text):
        ev["gender"] = "M"
    for d in reg_index["district"]:
        if d in t:
            ev["district"] = d
    for d in reg_index["tehsil"]:
        if re.search(r"\b" + re.escape(d) + r"\b", t):
            ev["tehsil"] = d
    for d in reg_index["village"]:
        if re.search(r"\b" + re.escape(d) + r"\b", t):
            ev["village"] = d
    m = re.search(r"(?<!\d)([1-9]\d{5})(?!\d)", text)
    if m:
        ev["pin"] = m.group(1)
    m = re.search(r"(?<!\d)([1-9]\d{2})(?:\*{3}|XXX)", text)
    if m:
        ev["pin3"] = m.group(1)
    for m in re.finditer(r"(?<!\d)([6-9]\d{9})(?!\d)", re.sub(r"(?<=\d)[\s\-]+(?=\d)", "", text)):
        ev["phones"].add(m.group(1))
    ev["emails"] = {e.lower() for e in EMAIL.findall(text)}
    ev["last4"] = set(LAST4.findall(text))
    ev["mphones"] = set(MASKED_PHONE.findall(text))
    ev["houses"] = {h.lower() for h in HOUSE.findall(text)}
    ev["byears"] = {int(a or b) for a, b in DOB.findall(text)}
    cleaned = re.sub(r"dr\.?\s+\w+(\s+\w+)?", " ", t)
    words = set(re.findall(r"[a-z]+", cleaned))
    ev["names"] = words & reg_index["name_tokens"]
    ds = parse_dates(text)
    ev["dates"] = set(ds["D"]) | set(ds["M"])
    for key in ("D", "M"):  # length of stay: every interval between dates inside one record
        xs = sorted(set(ds[key]))
        for i in range(len(xs)):
            for j in range(i + 1, len(xs)):
                gap = (xs[j] - xs[i]).days
                if 0 < gap <= 120:
                    ev["intervals"].add(gap)
    hay = t + " " + rel.lower()
    ev["hospitals"] = {v for k, v in HOSPITALS.items() if k in hay}
    ev["text"] = t
    return ev


# --------------------------------------------------------------------------- A3 record linkage

def attack(ev: dict, reg, ref_year: int = 2026) -> dict:
    cands = reg

    def filt(pred):
        nonlocal cands
        nxt = [r for r in cands if pred(r)]
        if nxt:  # a filter that would empty the set is skipped
            cands = nxt

    if ev["phones"]:
        filt(lambda r: r["phone"] in ev["phones"])
    if ev["emails"]:
        filt(lambda r: r["email"] in ev["emails"])
    if ev["last4"]:
        filt(lambda r: r["aadhaar_last4"] in ev["last4"])
    for a, b in list(ev["mphones"])[:2]:
        filt(lambda r, a=a, b=b: r["phone"].startswith(a) and r["phone"].endswith(b))
    if ev["district"]:
        filt(lambda r: r["district"].lower() == ev["district"])
    if ev["gender"]:
        filt(lambda r: r["gender"] == ev["gender"])
    for lo, hi in ev["ages"][:3]:
        filt(lambda r, lo=lo, hi=hi: lo - 1 <= r["age"] <= hi + 2)
    for by in list(ev["byears"])[:2]:
        filt(lambda r, by=by: abs((ref_year - by) - r["age"]) <= 1)
    if ev["tehsil"]:
        filt(lambda r: r["tehsil"].lower() == ev["tehsil"])
    if ev["village"]:
        filt(lambda r: r["village"].lower() == ev["village"])
    if ev["pin"]:
        filt(lambda r: r["pin"] == ev["pin"])
    if ev["pin3"]:
        filt(lambda r: r["pin"].startswith(ev["pin3"]))
    w = {}
    for r in cands:
        x = 1.0
        if r["given"] in ev["names"] and r["sur"] in ev["names"]:
            x *= 60
        elif r["given"] in ev["names"]:
            x *= 8
        elif r["sur"] in ev["names"]:
            x *= 3
        rel = r["relative_name"].lower().split()
        if rel and rel[0] in ev["names"]:
            x *= 8
        if r["house_no"] and r["house_no"] in ev["houses"]:
            x *= 2
        w[r["rid"]] = x
    tot = sum(w.values()) or 1.0
    return {rid: v / tot for rid, v in w.items()}


def merge(evs):
    out = {"ages": [], "gender": None, "district": None, "tehsil": None, "village": None, "pin": None, "pin3": None,
           "text": ""}
    sets = ("names", "phones", "emails", "last4", "mphones", "houses", "byears", "dates", "intervals", "hospitals")
    for k in sets:
        out[k] = set()
    for e in evs:
        out["ages"] += e["ages"]
        for k in ("gender", "district", "tehsil", "village", "pin", "pin3"):
            out[k] = out[k] or e[k]
        for k in sets:
            out[k] |= e[k]
        out["text"] += " \n " + e["text"]
    return out


# --------------------------------------------------------------------------- A5 targeted attack

def cond_terms(hint: str) -> list:
    h = norm(hint)
    terms = [h, re.sub(r"\s*,?\s*unspecified$", "", h), re.sub(r"\s*\(.*?\)", "", h).strip()]
    for k, codes in ICD.items():
        if k in h:
            terms += [c.lower() for c in codes]
    return [x for x in dict.fromkeys(terms) if len(x) >= 3]


def cond_match(terms: list, text: str) -> bool:
    for x in terms:
        if re.fullmatch(r"[a-z]\d{2}(\.\d)?", x):
            if re.search(r"(?<![a-z0-9])" + re.escape(x) + r"(?![0-9])", text):
                return True
        elif x in text:
            return True
    return False


def a5(profiles: dict, prof_true: dict, facts, rid_to_pat: dict, reg, ref_year: int, verbose=False):
    """profiles: pid -> merged evidence; prof_true: pid -> true patient. Returns (success, fp_rate, info)."""
    # 1) global shift recovery from confidently re-identified profiles
    facts_by_rid = {f["rid"]: f for f in facts}
    reid = {}
    for pid, ev in profiles.items():
        res = attack(ev, reg, ref_year)
        top = max(res.items(), key=lambda kv: kv[1]) if res else (None, 0)
        if top[1] >= 0.9:
            reid[pid] = top[0]
    support = defaultdict(set)
    for pid, rid in reid.items():
        f = facts_by_rid.get(rid)
        if not f:
            continue
        for kd in f.get("visit_dates", []):
            k = dt.date.fromisoformat(kd)
            for d in profiles[pid]["dates"]:
                off = (d - k).days
                if abs(off) <= 400:
                    support[off].add(rid)
    shift = 0
    if support:
        off, who = max(support.items(), key=lambda kv: (len(kv[1]), -abs(kv[0])))
        if len(who) >= 2:
            shift = off
    # 2) per-fact matching
    cond_count = Counter()
    fact_terms = {i: cond_terms(f["condition_hint"]) for i, f in enumerate(facts) if f.get("condition_hint")}
    for i, terms in fact_terms.items():
        cond_count[i] = sum(1 for ev in profiles.values() if cond_match(terms, ev["text"]))
    succ, n_real, fp, n_decoy, rows = 0.0, 0, 0, 0, []
    for i, f in enumerate(facts):
        known = {dt.date.fromisoformat(d) for d in f.get("visit_dates", [])}
        weights = {}
        for pid, ev in profiles.items():
            dates = {d - dt.timedelta(days=shift) for d in ev["dates"]}
            s = 0.0
            if known & dates:
                s += 1
            if i in fact_terms and cond_match(fact_terms[i], ev["text"]):
                s += 8 if cond_count[i] <= 3 else 1
            if f.get("stay_days") and f["stay_days"] in ev["intervals"]:
                s += 1
            if s <= 0:
                continue
            if f.get("hospital") and norm(f["hospital"]) in ev["hospitals"]:
                s *= 2
            res = attack(ev, reg, ref_year)  # the profile must be consistent with this person
            if f["rid"] not in res:
                continue
            weights[pid] = s
        tot = sum(weights.values())
        pat = rid_to_pat.get(f["rid"])
        top = max(weights.items(), key=lambda kv: kv[1]) if weights else (None, 0)
        conf = top[1] / tot if tot else 0.0
        if pat is None:  # decoy: never visited
            n_decoy += 1
            if conf >= 0.5:
                fp += 1
            rows.append((f["rid"], "decoy", conf, "CLAIMED (false positive)" if conf >= 0.5 else "no claim"))
            continue
        n_real += 1
        p_true = sum(w for pid, w in weights.items() if prof_true.get(pid) == pat) / tot if tot else 0.0
        succ += p_true
        rows.append((f["rid"], pat, p_true, f"{len(weights)} candidate profiles"))
    if verbose:
        print(f"    A5 recovered global shift: {shift} days (from {len(reid)} confident re-ids)")
        for r in rows:
            print(f"      {r[0]:<12} {r[1]:<8} p={r[2]:.2f}  {r[3]}")
    return succ / max(1, n_real), fp / max(1, n_decoy), {"shift": shift, "real": n_real, "decoys": n_decoy, "fp": fp}


# --------------------------------------------------------------------------- A1 / A6 / A7

DIRECT = {"PATIENT_NAME", "PHONE", "AADHAAR", "ABHA_NUMBER", "MRN", "PAN", "EMAIL", "INSURANCE_ID"}


def tree_text(root: Path) -> tuple[str, str]:
    parts = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            parts.append(str(p.relative_to(root)))
            try:
                parts.append(p.read_bytes().decode("utf-8", errors="replace"))
            except OSError:
                pass
    blob = "\n".join(parts)
    digits = re.sub(r"(?<=\d)[\s\-/.]+(?=\d)", "", blob)
    return norm(blob), digits


def a1(root: Path, truth: dict) -> float:
    blob, digits = tree_text(root)
    surfaces = defaultdict(set)
    for f in truth["files"].values():
        for u in f["units"].values():
            pat = u.get("patient")
            for e in u.get("entities", []):
                if e["type"] in DIRECT and e.get("role") == "patient" and pat:
                    if e["type"] == "PATIENT_NAME" and not e.get("full"):
                        continue
                    surfaces[pat].add((e["type"], e["surface"]))
    exposed = 0
    for pat, ss in surfaces.items():
        for typ, s in ss:
            d = re.sub(r"\D", "", s)
            if typ in ("PHONE", "AADHAAR", "ABHA_NUMBER") and len(d) >= 10:
                hit = d[-10:] in digits
            else:
                hit = norm(s) in blob
            if hit:
                exposed += 1
                break
    return exposed / max(1, len(surfaces))


def transforms(x: str) -> set:
    base = {x, x.lower(), x.upper(), re.sub(r"\D", "", x), x[::-1]}
    out = set(base)
    for b in base:
        if not b:
            continue
        bb = b.encode()
        for h in (hashlib.md5, hashlib.sha1, hashlib.sha256, hashlib.sha512):
            out.add(h(bb).hexdigest())
        out.add(base64.b64encode(bb).decode().rstrip("="))
    return {o.lower() for o in out if o}


def a6(root: Path, truth: dict, records: list) -> float:
    """records: (rel, loc, true patient). Inverted if a patient's pseudonym equals/prefixes a transform of their
    own original IDs, or embeds the UHID digit core or the phone."""
    origs = defaultdict(set)
    for pat, v in truth["patients"].items():
        for ids in v.get("uhids", {}).values():
            origs[pat] |= set(ids)
    for f in truth["files"].values():
        for u in f["units"].values():
            for e in u.get("entities", []):
                if not (u.get("patient") and e.get("role") == "patient"):
                    continue
                if e["type"] in ("PHONE", "AADHAAR", "ABHA_NUMBER", "MRN") or (
                        e["type"] == "PATIENT_NAME" and e.get("full") and e.get("script") == "latin"):
                    origs[u["patient"]].add(e["surface"])
    cache, psns = {}, defaultdict(set)
    for rel, loc, pat in records:
        for p in PSN.findall(record_text(root, rel, loc, cache)):
            psns[pat].add(p)
    inverted = 0
    for pat, ps in psns.items():
        tf = set().union(*(transforms(o) for o in origs[pat])) if origs[pat] else set()
        cores = {re.sub(r"\D", "", o) for o in origs[pat]}
        hit = False
        for p in ps:
            for cand in (p.lower(), p.lower().split("-", 1)[-1]):
                if cand in tf or (len(cand) >= 8 and any(t.startswith(cand) for t in tf)) or \
                        any(len(c) >= 6 and c in cand for c in cores):
                    hit = True
        inverted += hit
    return inverted / max(1, len(psns))


def a7(out1: Path, out2: Path, truth: dict) -> tuple[float, float]:
    def load(out):
        rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
        ren = {e["input_sha256"]: e["output"] for e in rep["files"]}
        psn = {}
        for line in (out / "records.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                psn[(r["file"], r["loc"])] = r.get("patient")
        return ren, psn
    (ren1, psn1), (ren2, psn2) = load(out1), load(out2)
    same_pat, pats, same_d, n_d = set(), set(), 0, 0
    c1, c2 = {}, {}
    for rel, f in truth["files"].items():
        o1, o2 = ren1.get(f["sha256"]), ren2.get(f["sha256"])
        if not (o1 and o2):
            continue
        for loc, u in f["units"].items():
            pat = u.get("patient")
            if not pat or loc.startswith("@"):
                continue
            pats.add(pat)
            p1, p2 = psn1.get((o1, loc)), psn2.get((o2, loc))
            if p1 and p1 == p2:
                same_pat.add(pat)
            t1 = parse_dates(record_text(out1, o1, loc, c1))["D"]
            t2 = parse_dates(record_text(out2, o2, loc, c2))["D"]
            for a, b in zip(t1, t2):
                n_d += 1
                same_d += a == b
    return len(same_pat) / max(1, len(pats)), same_d / max(1, n_d)


# --------------------------------------------------------------------------- driver

def run(root: Path, records: list, truth: dict, reg, facts, group_by_truth: bool, verbose=False, label=""):
    ref_year = int(truth.get("ref_date", "2026")[:4])
    reg_index = {"district": {r["district"].lower() for r in reg}, "tehsil": {r["tehsil"].lower() for r in reg},
                 "village": {r["village"].lower() for r in reg},
                 "name_tokens": {t for r in reg for t in (r["given"], r["sur"])} | {
                     r["relative_name"].lower().split()[0] for r in reg if r["relative_name"]}}
    pat_rid = {p: v["rid"] for p, v in truth["patients"].items()}
    rid_to_pat = {v: k for k, v in pat_rid.items()}
    cache = {}
    rec_ev, rec_pat, rec_psn = [], [], []
    for (rel, loc, pat) in records:
        txt = record_text(root, rel, loc, cache)
        rec_ev.append(evidence(txt, reg_index, rel))
        rec_pat.append(pat)
        m = PSN.search(txt)
        rec_psn.append(m.group(0) if m else None)
    # A3
    probs = [attack(ev, reg, ref_year).get(pat_rid[pat], 0.0) for ev, pat in zip(rec_ev, rec_pat)]
    a3 = sum(probs) / len(probs) if probs else 0
    # profiles: shared pseudonyms in the release; the raw input is joined through its shared names/IDs,
    # approximated by the true patient
    prof = defaultdict(list)
    for i, (psn, pat) in enumerate(zip(rec_psn, rec_pat)):
        key = ("T", pat) if group_by_truth else (("P", psn) if psn else ("R", i))
        prof[key].append(i)
    best = defaultdict(float)
    for p, pr in zip(rec_pat, probs):
        best[p] = max(best[p], pr)
    profiles, prof_true = {}, {}
    for key, idx in prof.items():
        ev = merge([rec_ev[i] for i in idx])
        profiles[key] = ev
        prof_true[key] = Counter(rec_pat[i] for i in idx).most_common(1)[0][0]
        res = attack(ev, reg, ref_year)
        for i in idx:
            p = rec_pat[i]
            best[p] = max(best[p], res.get(pat_rid[p], 0.0))
    a4 = sum(1 for v in best.values() if v >= 0.5) / max(1, len(best))
    if verbose:
        print(f"  [{label}] {len(records)} records, {len(profiles)} profiles")
    s5, fp5, info = a5(profiles, prof_true, facts, rid_to_pat, reg, ref_year, verbose)
    return {"A3": a3, "A4": a4, "A5": s5, "A5_fp": fp5, "A5_info": info}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", default="../Secret-Wards-ToolKit")
    ap.add_argument("--output", required=True)
    ap.add_argument("--output2", help="a second run with a different RAKSHA_SECRET, for A7")
    ap.add_argument("--truth", help="answer key (default: <kit>/dev/truth/truth.json)")
    ap.add_argument("--input", help="raw input (default: <kit>/dev/input)")
    ap.add_argument("-v", "--verbose", action="store_true", help="per-fact A5 detail")
    a = ap.parse_args()
    kit, out = Path(a.kit), Path(a.output)
    truth = json.loads(Path(a.truth or kit / "dev/truth/truth.json").read_text(encoding="utf-8"))
    raw_root = Path(a.input or kit / "dev/input")
    reg, facts = load_registry(kit), load_facts(kit)
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    ren = {e["input_sha256"]: e["output"] for e in rep["files"]}
    ours, raw = [], []
    for rel, f in truth["files"].items():
        o = ren.get(f["sha256"])
        for loc, u in f["units"].items():
            if u.get("patient") and loc not in ("@file", "@header", "@filename"):
                raw.append((rel, loc, u["patient"]))
                if o:
                    ours.append((o.replace("sanitized/", "", 1), loc, u["patient"]))
    R = run(raw_root, raw, truth, reg, facts, True, a.verbose, "raw")
    O = run(out / "sanitized", ours, truth, reg, facts, False, a.verbose, "ours")
    R["A1"], O["A1"] = a1(raw_root, truth), a1(out / "sanitized", truth)
    R["A6"], O["A6"] = 0.0, a6(out / "sanitized", truth, ours)

    def line(name, k, lower="lower is better"):
        r, o = R[k], O[k]
        ratio = f"{o / r:.3f}" if r else "  -  "
        print(f"{name:<28} raw {r:6.3f}   ours {o:6.3f}   ratio {ratio}   ({lower})")

    print("Re-identification attacks (share of patients / probability on the true person)")
    line("A1 direct exposure", "A1")
    line("A3 record linkage", "A3")
    line("A4 profile re-id (>=0.5)", "A4")
    line("A5 targeted, known facts", "A5")
    i = O["A5_info"]
    print(f"   A5 detail: {i['real']} real targets, {i['decoys']} decoys; decoys wrongly claimed: "
          f"raw {R['A5_info']['fp']}, ours {i['fp']}; global shift recovered: raw {R['A5_info']['shift']}, "
          f"ours {i['shift']} days")
    print(f"{'A6 pseudonym inversion':<28} ours {O['A6']:.3f}   (share of patients whose fake ID is invertible)")
    if a.output2:
        p, d = a7(out, Path(a.output2), truth)
        print(f"{'A7 cross-release linking':<28} same pseudonym {p:.3f}   same shifted date {d:.3f}   "
              f"risk {max(p, d):.3f}")
    else:
        print("A7 cross-release linking     skipped (pass --output2 <run with another RAKSHA_SECRET>)")


if __name__ == "__main__":
    main()
