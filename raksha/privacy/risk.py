"""k-anonymity search over (gender, age band, location) equivalence classes of patients (clusters).

For each candidate (age width, location level) in widening order, compute the share of patients whose
class has fewer than k members; choose the first setting whose violation share <= the allowed share.
Patients still below k afterwards get their rare quasi-identifier values suppressed (rare_values.py).
"""
from __future__ import annotations

from collections import Counter

from .age_band import band_for


def evaluate(patients: list[dict], width: int, level: str, top: int) -> tuple[float, int, Counter]:
    keys = []
    for p in patients:
        band = band_for(p["ages"], width, top) if p["ages"] else None
        loc = p.get("district") if level in ("district", "tehsil", "village") else p.get("state")
        keys.append((p.get("gender"), band, loc))
    c = Counter(keys)
    sizes = [c[k] for k in keys]
    if not sizes:
        return 0.0, 0, c
    viol = sum(1 for s in sizes if s < patients[0].get("k", 5)) / len(sizes)
    return viol, min(sizes), c


def choose(patients: list[dict], policy) -> dict:
    k = int(policy.get("k_anonymity.k_target", 5))
    allowed = float(policy.get("k_anonymity.max_violation_share", 0.1))
    widths = [int(w) for w in policy.get("k_anonymity.age_widths", [5, 10, 20])]
    floor = int(policy.get("age.band_width", 10))
    widths = [w for w in widths if w >= floor] or [floor]
    levels = list(policy.get("k_anonymity.levels", ["district", "state"]))
    top = int(policy.get("age.top_code", 80))
    for p in patients:
        p["k"] = k
    tried = []
    for level in levels:
        for w in widths:
            viol, kmin, _ = evaluate(patients, w, level, top)
            tried.append({"width": w, "level": level, "violation_share": round(viol, 4), "k_min": kmin})
            if viol <= allowed:
                return {"width": w, "level": level, "tried": tried, "k_min": kmin, "violation_share": viol}
    last = tried[-1] if tried else {"width": widths[-1], "level": levels[-1], "k_min": 0, "violation_share": 1.0}
    return {"width": last["width"], "level": last["level"], "tried": tried, "k_min": last["k_min"],
            "violation_share": last["violation_share"]}
