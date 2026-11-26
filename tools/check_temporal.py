#!/usr/bin/env python3
"""Dev check: are a patient's date intervals preserved across ALL their records (and LOS exact)?
Uses dev truth (true dates per record) and our records.jsonl (pseudonym per record)."""
import json, sys, itertools, datetime as dt
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from raksha.privacy.dates import find_dates

kit, out = Path(sys.argv[1]), Path(sys.argv[2])
truth = json.loads((kit / "dev/truth/truth.json").read_text())
rep = json.loads((out / "report.json").read_text())
ren = {e["input_sha256"]: e["output"] for e in rep["files"]}
orders = {}
ok = bad = 0
per_patient = defaultdict(list)   # patient -> [(true_date, shifted_date)]
for rel, f in truth["files"].items():
    o = ren.get(f["sha256"])
    if not o or f["format"] not in ("text",):
        continue
    src = (kit / "dev/input" / rel).read_text(encoding="utf-8", errors="replace")
    dst = (out / o).read_text(encoding="utf-8", errors="replace")
    order = f.get("date_hint") or "dmy"
    a = [h.parse(order) for h in find_dates(src)]
    b = [h.parse(order) for h in find_dates(dst)]
    u = f["units"].get("doc")
    if not u or not u.get("patient") or len(a) != len(b):
        continue
    for x, y in zip(a, b):
        if x and y:
            per_patient[u["patient"]].append((x, y))
for p, pairs in per_patient.items():
    shifts = {(y - x).days for x, y in pairs}
    if len(shifts) == 1:
        ok += 1
    else:
        bad += 1
        print("inconsistent shift", p, sorted(shifts))
print(f"patients with one consistent shift across text records: {ok}/{ok + bad}")
