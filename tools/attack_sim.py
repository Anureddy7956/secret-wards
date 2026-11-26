#!/usr/bin/env python3
"""Dev-only re-identification attack simulator (approximation of the kit's docs/ATTACKS.md).

Uses the practice attacker knowledge (dev/attacker/registry.csv, known_facts.jsonl) and the practice
truth to score a release. Never imported by the pipeline (the attacker files are not available on
event day). Prints A1-A5 style numbers for our output and for the raw input.

    python tools/attack_sim.py --kit ../Secret-Wards-ToolKit --output out
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
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
    return rows


def record_text(root: Path, rel: str, loc: str, cache: dict) -> str:
    p = root / rel
    if rel not in cache:
        try:
            cache[rel] = p.read_bytes().decode("utf-8", errors="replace").lstrip("﻿")
        except OSError:
            cache[rel] = ""
    text = cache[rel]
    if loc == "doc" or not text:
        return text
    if loc.startswith("row:"):
        i = int(loc[4:])
        try:
            rows = list(csv.reader(text.splitlines(), delimiter="\t" if rel.endswith(".tsv") else ","))
            header, body = rows[0], rows[1:]
            # multi-line cells: fall back to csv over the whole text
            body = list(csv.reader(__import__("io").StringIO(text), delimiter="\t" if "\t" in rows[0][0:1] or
                                   rel.endswith(".tsv") else ","))[1:]
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


AGE_RX = [re.compile(r"(?<![\d.\-])(\d{1,3})\s*-\s*(\d{1,3})\s*(?:yrs?|y|years?|वर्ष)?\s*(?:/|\s|\"|$|,)", re.I),
          re.compile(r"(?<![\d.\-])(\d{1,3})\+")]
AGE_EXACT = [re.compile(r"(?<![\d/.\-])(\d{1,3})\s*(?:Yrs?|Y|years?|वर्ष)?\s*/\s*[MF]\b"),
             re.compile(r"(?i)\bage\W{1,4}(\d{1,3})\b"), re.compile(r"(\d{1,3})\s*वर्ष"),
             re.compile(r"(?i)\"(?:age|umar)\"\s*:\s*(\d{1,3})\b"), re.compile(r"(?i)\bumar:\s*(\d{1,3})")]


def evidence(text: str, reg_index) -> dict:
    t = norm(text)
    ev = {"ages": [], "gender": None, "district": None, "tehsil": None, "village": None, "pin": None,
          "pin3": None, "names": set(), "phones": set(), "dates": set()}
    for rx in AGE_RX[:1]:
        for m in rx.finditer(text):
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
    for m in re.finditer(r"(?<!\d)([6-9]\d{9})(?!\d)", re.sub(r"[\s\-]", "", text)):
        ev["phones"].add(m.group(1))
    cleaned = re.sub(r"dr\.?\s+\w+(\s+\w+)?", " ", t)
    words = set(re.findall(r"[a-z]+", cleaned))
    ev["names"] = words & reg_index["name_tokens"]
    for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", text):
        ev["dates"].add(m.group(0))
    return ev


def attack(ev: dict, reg) -> dict:
    cands = reg
    def filt(pred):
        nonlocal cands
        nxt = [r for r in cands if pred(r)]
        if nxt:
            cands = nxt
    if ev["phones"]:
        filt(lambda r: r["phone"] in ev["phones"])
    if ev["district"]:
        filt(lambda r: r["district"].lower() == ev["district"])
    if ev["gender"]:
        filt(lambda r: r["gender"] == ev["gender"])
    for lo, hi in ev["ages"][:3]:
        filt(lambda r, lo=lo, hi=hi: lo - 1 <= r["age"] <= hi + 2)
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
        w[r["rid"]] = x
    tot = sum(w.values()) or 1.0
    return {rid: v / tot for rid, v in w.items()}


def merge(evs):
    out = {"ages": [], "gender": None, "district": None, "tehsil": None, "village": None, "pin": None, "pin3": None,
           "names": set(), "phones": set(), "dates": set()}
    for e in evs:
        out["ages"] += e["ages"]
        for k in ("gender", "district", "tehsil", "village", "pin", "pin3"):
            out[k] = out[k] or e[k]
        out["names"] |= e["names"]
        out["phones"] |= e["phones"]
        out["dates"] |= e["dates"]
    return out


def run(kit: Path, root: Path, records: list, truth: dict, reg):
    reg_index = {"district": {r["district"].lower() for r in reg}, "tehsil": {r["tehsil"].lower() for r in reg},
                 "village": {r["village"].lower() for r in reg},
                 "name_tokens": {t for r in reg for t in (r["given"], r["sur"])} | {
                     r["relative_name"].lower().split()[0] for r in reg if r["relative_name"]}}
    pat_rid = {p: v["rid"] for p, v in truth["patients"].items()}
    cache = {}
    rec_ev, rec_pat, rec_psn = [], [], []
    for (rel, loc, pat) in records:
        txt = record_text(root, rel, loc, cache)
        rec_ev.append(evidence(txt, reg_index))
        rec_pat.append(pat)
        m = PSN.search(txt)
        rec_psn.append(m.group(0) if m else None)
    # A2/A3
    probs = []
    for ev, pat in zip(rec_ev, rec_pat):
        probs.append(attack(ev, reg).get(pat_rid[pat], 0.0))
    a3 = sum(probs) / len(probs) if probs else 0
    # A4 profiles via pseudonyms
    prof = defaultdict(list)
    for i, psn in enumerate(rec_psn):
        if psn:
            prof[psn].append(i)
    best = defaultdict(float)
    for i, (p, pr) in enumerate(zip(rec_pat, probs)):
        best[p] = max(best[p], pr)
    for psn, idx in prof.items():
        ev = merge([rec_ev[i] for i in idx])
        res = attack(ev, reg)
        for i in idx:
            p = rec_pat[i]
            best[p] = max(best[p], res.get(pat_rid[p], 0.0))
    a4 = sum(1 for v in best.values() if v >= 0.5) / max(1, len(best))
    return a3, a4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", default="../Secret-Wards-ToolKit")
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    kit, out = Path(a.kit), Path(a.output)
    truth = json.loads((kit / "dev/truth/truth.json").read_text(encoding="utf-8"))
    reg = load_registry(kit)
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
    r3, r4 = run(kit, kit / "dev/input", raw, truth, reg)
    o3, o4 = run(kit, out / "sanitized", ours, truth, reg)
    print(f"A3 record linkage   raw {r3:.3f}  ours {o3:.3f}  ratio {o3 / r3 if r3 else 0:.3f}")
    print(f"A4 profile reid     raw {r4:.3f}  ours {o4:.3f}  ratio {o4 / r4 if r4 else 0:.3f}")


if __name__ == "__main__":
    main()
