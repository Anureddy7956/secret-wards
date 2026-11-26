#!/usr/bin/env python3
"""Dev check: schema preservation between input and sanitized output (CSV shape/header, JSON key paths
and value types, text line counts), mirroring the kit's integrity scoring."""
import csv, io, json, sys, hashlib
from pathlib import Path

inp, out = Path(sys.argv[1]), Path(sys.argv[2])
rep = json.loads((out / "report.json").read_text())
m = {e["input_sha256"]: e["output"] for e in rep["files"] if e["output"]}
issues = 0


def paths(o, p=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from paths(v, p + (k,))
    elif isinstance(o, list):
        for v in o:
            yield from paths(v, p + ("[]",))
    else:
        yield p, type(o).__name__


for f in sorted(inp.rglob("*")):
    if not f.is_file():
        continue
    o = m.get(hashlib.sha256(f.read_bytes()).hexdigest())
    if not o:
        continue
    raw = f.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            src = raw.decode(enc); break
        except UnicodeDecodeError:
            continue
    dst = (out / o).read_text(encoding="utf-8-sig")
    rel = f.relative_to(inp).as_posix()
    if f.suffix in (".csv", ".tsv") and not src.lstrip().startswith("{"):
        d = "\t" if f.suffix == ".tsv" else ","
        a = list(csv.reader(io.StringIO(src), delimiter=d)); b = list(csv.reader(io.StringIO(dst), delimiter=d))
        if len(a) != len(b) or [len(r) for r in a] != [len(r) for r in b]:
            issues += 1; print("CSV shape", rel, len(a), len(b))
        changed = [x for x, y in zip(a[0], b[0]) if x.strip("﻿") != y]
        if changed:
            print("header renamed", rel, len(changed), "cells")
    elif src.lstrip()[:1] in "{[":
        try:
            ja, jb = json.loads(src), json.loads(dst)
        except Exception as e:
            issues += 1; print("JSON parse", rel, type(e).__name__); continue
        pa, pb = dict(paths(ja)), dict(paths(jb))
        jac = len(set(pa) & set(pb)) / max(1, len(set(pa) | set(pb)))
        types = [p for p in pa if p in pb and pa[p] != pb[p]]
        if jac < 1 or types:
            print(f"JSON {rel}: key-path jaccard {jac:.2f}, type changes {sorted(set(types))[:4]}")
    else:
        la, lb = src.count("\n"), dst.count("\n")
        if la != lb:
            print("text lines", rel, la, lb)
print("structural issues:", issues)
