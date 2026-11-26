"""Conflict-aware agglomerative linkage.

Order of evidence (strongest first), never naive transitive closure:
 1. shared strong identifier (UHID/IPD/Aadhaar/ABHA/PAN/insurance/email), then phone;
 2. same full name (cross-script, spelling-tolerant) + a corroborating clue (DOB, relative, village + age),
    scored Fellegi-Sunter style and accepted only when the candidate is unique;
 3. fragment mentions (first name + relative, e.g. 'Meera, W/o Rajan') linked only to a unique match.
Every merge is vetoed by hard conflicts between the two clusters: gender, birth year, DOB,
different Aadhaar / ABHA numbers, or incompatible names.
"""
from __future__ import annotations

from collections import defaultdict

from ..translit.canonical import skeleton, token_match
from . import compare as C
from .extract_identity import Identity

ID_ORDER = {"MRN": 0, "AADHAAR": 1, "ABHA_NUMBER": 2, "ABHA_ADDRESS": 3, "EMAIL": 4, "INSURANCE_ID": 5, "PAN": 6,
            "PHONE": 7}
EXCLUSIVE = ("AADHAAR", "ABHA_NUMBER")


class Cluster:
    __slots__ = ("members", "names", "weak", "ids", "rel", "genders", "years", "dobs", "villages", "hospitals")

    def __init__(self, idx: int, ident: Identity):
        self.members = [idx]
        self.names = list(ident.names)
        self.weak = list(ident.weak_names)
        self.ids = set(ident.ids)
        self.rel = list(ident.relatives)
        self.genders = set(ident.genders)
        self.years = list(ident.birth_years())
        self.dobs = set(ident.dobs)
        self.villages = set(ident.villages)
        self.hospitals = {ident.hospital} if ident.hospital else set()

    def absorb(self, o: "Cluster"):
        self.members += o.members
        self.names += o.names
        self.weak += o.weak
        self.ids |= o.ids
        self.rel += o.rel
        self.genders |= o.genders
        self.years += o.years
        self.dobs |= o.dobs
        self.villages |= o.villages
        self.hospitals |= o.hospitals


def conflict(a: Cluster, b: Cluster, gap: int, jw: float) -> bool:
    if a.genders and b.genders and not (a.genders & b.genders):
        return True
    if len(a.genders) > 1 or len(b.genders) > 1:
        pass
    yc = C.years_compatible(a.years, b.years, gap)
    if yc is False:
        return True
    if C.dob_compatible(a.dobs, b.dobs) is False:
        return True
    for t in EXCLUSIVE:
        va = {v for k, v in a.ids if k == t}
        vb = {v for k, v in b.ids if k == t}
        if va and vb and not (va & vb):
            return True
    if not C.names_compatible(a.names, b.names, jw):
        return True
    # a fragment's first name must agree with the other side's names
    if a.weak and b.names and not C.names_compatible([w for w in a.weak], b.names, jw):
        return True
    if b.weak and a.names and not C.names_compatible([w for w in b.weak], a.names, jw):
        return True
    return False


def name_score(a: Cluster, b: Cluster, w: dict, jw: float) -> float:
    s = 0.0
    if C.any_name_pair(a.names, b.names, C.full_name_agree, jw):
        s += w.get("full_name_agree", 6)
    else:
        if C.any_name_pair(a.names, b.names, C.first_agree, jw):
            s += w.get("first_name_agree", 3)
        if C.any_name_pair(a.names, b.names, C.surname_agree, jw):
            s += w.get("surname_agree", 2)
    dc = C.dob_compatible(a.dobs, b.dobs)
    if dc:
        s += w.get("dob_agree", 7)
    if C.relative_agree(a.rel, b.rel, jw):
        s += w.get("relative_agree", 5)
    village = bool(a.villages & b.villages)
    yc = C.years_compatible(a.years, b.years, 1)
    if village and yc:
        s += w.get("village_agree", 3) + w.get("age_agree", 2)
    return s


def link(identities: list[Identity], policy) -> list[int | None]:
    gap = int(policy.get("linkage.max_age_gap_years", 2))
    jw = float(policy.get("linkage.name_jw_threshold", 0.9))
    thr = float(policy.get("linkage.link_threshold", 10.0))
    weights = policy.get("linkage.weights", {}) or {}

    clusters: dict[int, Cluster] = {}
    parent: dict[int, int] = {}
    for i, ident in enumerate(identities):
        if ident.has_patient_evidence() or ident.weak_names:
            clusters[i] = Cluster(i, ident)
            parent[i] = i

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y) -> bool:
        rx, ry = find(x), find(y)
        if rx == ry:
            return True
        a, b = clusters[rx], clusters[ry]
        if conflict(a, b, gap, jw):
            return False
        keep, drop = (rx, ry) if rx < ry else (ry, rx)
        clusters[keep].absorb(clusters[drop])
        del clusters[drop]
        parent[drop] = keep
        return True

    # 1. strong identifiers
    index = defaultdict(list)
    for i in sorted(clusters):
        for t, v in sorted(identities[i].ids):
            index[(ID_ORDER.get(t, 9), t, v)].append(i)
    for key in sorted(index):
        members = index[key]
        for j in members[1:]:
            union(members[0], j)

    # 2. full-name + corroboration (blocking on name skeletons)
    for _round in range(2):
        blocks = defaultdict(set)
        for r, c in clusters.items():
            for n in c.names:
                core = C._core(n)
                if len(core) < 2:
                    core = n
                if len(core) >= 2:
                    blocks[(skeleton(core[0]), skeleton(core[-1]))].add(r)
                    blocks[(skeleton(core[-1]), skeleton(core[0]))].add(r)
        cands = {}
        for key in sorted(blocks):
            members = sorted(blocks[key])
            for x in range(len(members)):
                for y in range(x + 1, len(members)):
                    a, b = members[x], members[y]
                    if (a, b) in cands:
                        continue
                    ca, cb = clusters[a], clusters[b]
                    if conflict(ca, cb, gap, jw):
                        continue
                    sc = name_score(ca, cb, weights, jw)
                    if sc >= thr:
                        cands[(a, b)] = sc
        # uniqueness: each cluster may take only its single best partner
        best = defaultdict(list)
        for (a, b), sc in cands.items():
            best[a].append((sc, b))
            best[b].append((sc, a))
        merged = False
        def anchored(x):
            return [o for _, o in best[x] if o in clusters and clusters[o].ids]

        for (a, b), sc in sorted(cands.items(), key=lambda kv: (-kv[1], kv[0])):
            if a not in clusters or b not in clusters:
                continue
            ok = len(best[a]) == 1 and len(best[b]) == 1
            # an identifier-less cluster may join its single identifier-anchored candidate
            if not ok and not clusters[a].ids and clusters[b].ids and anchored(a) == [b]:
                ok = True
            if not ok and not clusters[b].ids and clusters[a].ids and anchored(b) == [a]:
                ok = True
            if not ok:
                continue
            if a in clusters and b in clusters and find(a) != find(b):
                merged |= union(a, b)
        if not merged:
            break

    # 3. fragments: weak first-name evidence + relative / village+age, unique candidate only
    for r in sorted(list(clusters)):
        if r not in clusters:
            continue
        c = clusters[r]
        if c.names or c.ids or not c.weak:
            continue
        matches = []
        for o, oc in clusters.items():
            if o == r or not oc.names:
                continue
            if not any(C.first_agree(w, n, jw) for w in c.weak for n in oc.names):
                continue
            support = C.relative_agree(c.rel, oc.rel, jw) or (bool(c.villages & oc.villages)
                                                            and bool(C.years_compatible(c.years, oc.years, 1)))
            if support and not conflict(c, oc, gap, jw):
                matches.append(o)
        if len(matches) == 1:
            union(r, matches[0])

    out: list[int | None] = []
    for i in range(len(identities)):
        out.append(find(i) if i in parent else None)
    return out
