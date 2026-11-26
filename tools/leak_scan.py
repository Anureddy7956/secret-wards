#!/usr/bin/env python3
"""Leak scan: run the pipeline on a dataset with a manifest of PII strings and canaries, then grep the output
tree, output file names, stdout/stderr and a private TMPDIR for every PII string (normalised, digits matched
across separators). Also reports linking and clinical values on the synthetic manifest.

    python tools/leak_scan.py --data /tmp/synth [--secret x]
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--secret", default="leak-scan-secret")
    ap.add_argument("--out", help="keep the pipeline output here (default: a throwaway temp folder)")
    a = ap.parse_args()
    data = Path(a.data)
    man = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp(prefix="leakscan-"))
    out = Path(a.out) if a.out else tmp / "out"
    if out.exists() and any(out.iterdir()):
        sys.exit(f"--out {out} is not empty; remove it first")
    run_tmp = tmp / "tmpdir"
    run_tmp.mkdir()
    env = dict(os.environ, RAKSHA_SECRET=a.secret, TMPDIR=str(run_tmp), HOME=str(run_tmp))
    p = subprocess.run([sys.executable, str(ROOT / "main.py"), "--input", str(data / "input"), "--output", str(out)],
                       env=env, capture_output=True, text=True)
    blobs = {"stdout/stderr": p.stdout + p.stderr}
    names = []
    for f in sorted(out.rglob("*")):
        names.append(f.relative_to(out).as_posix())
        if f.is_file():
            blobs[f.relative_to(out).as_posix()] = f.read_bytes().decode("utf-8", "replace")
    for f in sorted(run_tmp.rglob("*")):
        blobs["TMPDIR/" + f.name] = f.read_bytes().decode("utf-8", "replace") if f.is_file() else ""
    blobs["filenames"] = "\n".join(names)
    all_text = norm("\n".join(blobs.values()))
    # Devanagari / other Unicode digits count as digits: '९८७६...' is the same phone as '9876...'
    digits_only = "".join(str(unicodedata.digit(c)) for c in "\n".join(blobs.values()) if c.isdigit())
    leaks = []
    for s in man["pii"] + man["canaries"]:
        d = re.sub(r"\D", "", s)
        hit = norm(s) in all_text or (len(d) >= 8 and d in digits_only)
        if hit:
            where = [k for k, v in blobs.items() if norm(s) in norm(v)]
            leaks.append((s if s not in man["canaries"] else "CANARY", where[:3]))
    recs = {}
    if (out / "records.jsonl").exists():
        rep = json.loads((out / "report.json").read_text())
        ren = {}
        for l in (out / "records.jsonl").read_text().splitlines():
            r = json.loads(l)
            recs[(r["file"], r["loc"])] = r["patient"]
        # map input rel -> output path via sha
        import hashlib
        sha_out = {e["input_sha256"]: e["output"] for e in rep["files"]}
        for f in (data / "input").rglob("*"):
            if f.is_file():
                ren[f.relative_to(data / "input").as_posix()] = sha_out.get(hashlib.sha256(f.read_bytes()).hexdigest())
    tp = fp = fn = 0
    by_pid = {}
    for mrn, members in man["groups"].items():
        pids = [recs.get((ren.get(rel), loc)) for rel, loc in members]
        for x, y in itertools.combinations(pids, 2):
            if x and x == y:
                tp += 1
            else:
                fn += 1
        for x in pids:
            if x:
                by_pid.setdefault(x, set()).add(mrn)
    fp = sum(len(v) - 1 for v in by_pid.values())
    missing = [c for c in man["clinical"] if norm(c) not in all_text]
    kept = len(man["clinical"]) - len(missing)
    wrong = [pair for pair in man.get("must_not_merge", [])
             if any(pair[0] in v and pair[1] in v for v in by_pid.values())]
    print(f"exit code {p.returncode}")
    print(f"PII strings leaked: {len(leaks)} of {len(man['pii']) + len(man['canaries'])}")
    for l in leaks[:30]:
        print("   ", l)
    print(f"clinical values kept: {kept}/{len(man['clinical'])}")
    for c in missing:
        print("    missing:", c)
    print(f"linking: true pairs found {tp}, missed {fn}, pseudonyms merging different people {fp}")
    if "must_not_merge" in man:
        print(f"same-name different people wrongly merged: {len(wrong)} of {len(man['must_not_merge'])}")
    print(f"TMPDIR leftovers: {len(list(run_tmp.rglob('*')))}")
    print(f"output folder: {out}")


if __name__ == "__main__":
    main()
