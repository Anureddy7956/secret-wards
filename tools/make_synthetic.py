#!/usr/bin/env python3
"""Generate an UNSEEN-FORMAT synthetic dataset to test generalisation (not tuned on).

New names (many outside our gazetteer: North-East, South, Himalayan, Punjabi), renamed column labels,
a semicolon CSV, a different JSON shape, new note templates and date formats, broken files and canaries.
Writes <out>/input/... and <out>/manifest.json (PII strings, canaries, expected same-patient groups).

    python tools/make_synthetic.py --out /tmp/synth --seed 7
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

GIVEN_F = ["Tenzin Dolma", "Lalrinmawii Hmar", "Oinam Bembem", "Mrinalini Gogoi", "Jayashree Kalita",
           "Anbu Selvi", "Gurleen Sandhu", "Nazneen Parveen", "Rituparna Dey", "Swapna Mahato", "Heisnam Sanatombi",
           "Priyanka Solanki", "Lalita Baghel"]
GIVEN_M = ["Bikash Tamang", "Thangjam Ibomcha", "Anbu Selvan", "Karma Bhutia", "Ravindra Deshmukh", "Faizal Kutty",
           "Harjot Grewal", "Debashish Pal", "Rongmei Kamei", "Sanjib Hazarika", "Govind Maurya"]
DEVA = {"Priyanka Solanki": "प्रियंका सोलंकी", "Lalita Baghel": "ललिता बघेल", "Govind Maurya": "गोविंद मौर्य"}
RELATIVES = ["Pemba Sherpa", "Lalthanzuala Ralte", "Ningthoujam Tomba", "Arulmozhi Varman", "Kuldip Bains",
             "Ratul Bora", "Shibu Murmu", "Ashfaq Pathan"]
CANARIES = ["Wanbok Lyngdoh", "Chellammal Iyer", "Yangchen Lhamo"]
VILLAGES = ["Kharsang", "Majuli Gaon", "Phek Khullen", "Tirupattur Pudur", "Bhatinda Kalan"]
DISTRICTS = ["Sitapur", "Barabanki", "Hardoi", "Unnao"]
DRUGS = [("Amlodipine", "5 mg", "0-0-1"), ("Metformin", "500 mg", "1-0-1"), ("Azithromycin", "500 mg", "1-0-0"),
         ("Paracetamol", "650 mg", "1-1-1"), ("Levothyroxine", "50 mcg", "1-0-0")]
DIAG = [("I10", "Essential (primary) hypertension"), ("E11.9", "Type 2 diabetes mellitus without complications"),
        ("A01.0", "Typhoid fever"), ("J18.9", "Pneumonia, unspecified organism"), ("A90", "Dengue fever")]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def phone(r):
    return str(r.choice([6, 7, 8, 9])) + "".join(str(r.randint(0, 9)) for _ in range(9))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    r = random.Random(a.seed)
    root = Path(a.out)
    inp = root / "input"
    for sub in ("reg", "ipd", "notes", "lab", "junk"):
        (inp / sub).mkdir(parents=True, exist_ok=True)
    people = []
    names = [(n, "F") for n in GIVEN_F] + [(n, "M") for n in GIVEN_M]
    for i, (n, g) in enumerate(names):
        people.append({"name": n, "gender": g, "age": r.randint(18, 88), "phone": phone(r),
                       "mrn": f"KHC-{2026}-{10000 + i * 7}", "aadhaar": " ".join(str(r.randint(1000, 9999)) for _ in range(3)),
                       "relative": r.choice(RELATIVES), "village": r.choice(VILLAGES), "district": r.choice(DISTRICTS),
                       "pin": str(r.choice([261, 225, 241, 209])) + str(r.randint(100, 999))})
    pii, groups = [], {}
    # 1. registration: semicolon CSV, unseen labels
    lines = ["Hosp. Reg. No.;Patient's Name;Sex (M/F);Pt. Age;Father/Husband;Gram/Mohalla;Zila;Pincode;Contact#;Aadhar Card;D.O.B."]
    for p in people:
        dob = f"{r.randint(1, 28):02d}-{MONTHS[r.randint(0, 11)]}-{2026 - p['age']}"
        lines.append(";".join([p["mrn"], p["name"], p["gender"], str(p["age"]), "S/o " + p["relative"] if p["gender"] == "M"
                               else "W/o " + p["relative"], p["village"], p["district"], p["pin"],
                               "+91-" + p["phone"][:5] + "-" + p["phone"][5:], p["aadhaar"], dob]))
        pii += [p["name"], p["relative"], p["phone"], p["aadhaar"].replace(" ", ""), p["mrn"], p["village"]]
        groups.setdefault(p["mrn"], []).append(("reg/kh_registration.csv", f"row:{len(lines) - 2}"))
    (inp / "reg" / "kh_registration.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # 2. IPD JSON with a different shape
    recs = []
    for p in people[::2]:
        d0 = r.randint(1, 18)
        dx = r.choice(DIAG)
        recs.append({"pt": {"full_name": p["name"].upper(), "mob_no": p["phone"], "hosp_id": p["mrn"]},
                     "admit": f"2026/03/{d0:02d}", "discharge": f"2026/03/{d0 + 6:02d}",
                     "dx": f"{dx[1]} ({dx[0]})", "summary": f"{p['name'].split()[0]} ji was stable on discharge. "
                                                           f"BP 132/84. Tab {DRUGS[0][0]} {DRUGS[0][1]} {DRUGS[0][2]}."})
        groups.setdefault(p["mrn"], []).append(("ipd/khc_ipd.json", f"/records/{len(recs) - 1}"))
    (inp / "ipd" / "khc_ipd.json").write_text(json.dumps({"source": "KHC HIS", "records": recs}, indent=2),
                                             encoding="utf-8")
    # 3. notes: new templates, new date formats, Hinglish + Devanagari
    for i, p in enumerate(people):
        drug = r.choice(DRUGS)
        dx = r.choice(DIAG)
        if p["name"] in DEVA:
            body = (f"मरीज़ का नाम: {DEVA[p['name']]}   उम्र: {p['age']} साल\nफोन: {p['phone']}\n"
                    f"{DEVA[p['name']]} को 5 दिन से बुखार है।\nTab {drug[0]} {drug[1]} {drug[2]} x 5 days\n")
        else:
            body = (f"Pt. {p['name']} ({p['age']}/{p['gender']}), R/o {p['village']}, ph {p['phone']}\n"
                    f"Admitted on {r.randint(1, 20)}th March 2026 with C/O fever and cough x 4 days.\n"
                    f"Husband/Father: {p['relative']}. Seen by Dr. Meenakshi Sundaram.\n"
                    f"Dx: {dx[1]} ({dx[0]}). Tab {drug[0]} {drug[1]} {drug[2]} x 7 days. SpO2 95%.\n"
                    f"{p['name'].split()[0]} didi ko aaram hai.\n")
        fname = f"case_{i:03d}.txt" if i % 4 else f"{p['name'].replace(' ', '_')}_{p['mrn']}.txt"
        (inp / "notes" / fname).write_text(body, encoding="utf-8")
        groups.setdefault(p["mrn"], []).append(("notes/" + fname, "doc"))
    # 4. lab TSV in UTF-16 with renamed columns
    rows = ["Lab No\tName of Patient\tAge/Gender\tPatient ID\tInvestigation\tValue\tUnits\tReferred By"]
    for p in people[1::3]:
        rows.append(f"L{r.randint(10000, 99999)}\t{p['name']}\t{p['age']}/{p['gender']}\t{p['mrn']}\tHaemoglobin\t"
                    f"{r.randint(80, 150) / 10}\tg/dL\tDr. Meenakshi Sundaram")
    (inp / "lab" / "results.tsv").write_bytes("\r\n".join(rows).encode("utf-16"))
    # 5. canaries in hidden places
    (inp / "junk" / "callers.json").write_text(json.dumps({"log": [{"note": f"call received from {CANARIES[0]} "
                                                                             f"regarding bill"}],
                                                           CANARIES[1]: {"visits": 2}}), encoding="utf-8")
    (inp / "junk" / "desk.txt").write_text(f"Visitor: {CANARIES[2]}, mob {phone(r)}\nDr. Meenakshi Sundaram on duty.\n",
                                           encoding="utf-8")
    # 6. broken / unsupported
    (inp / "junk" / "cut.json").write_text('{"records": [{"pt": {"full_name": "' + people[0]["name"], encoding="utf-8")
    (inp / "junk" / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
    (inp / "junk" / "blank.txt").write_bytes(b"")
    (inp / "junk" / "legacy.csv").write_bytes(("id,name,city\n1," + people[2]["name"] + ",Kharsang\n").encode("cp1252"))
    manifest = {"pii": sorted(set(pii)), "canaries": CANARIES, "groups": groups,
                "clinical": ["C/O fever and cough x 4 days", "BP 132/84", "SpO2 95%", "Dr. Meenakshi Sundaram",
                             "Haemoglobin"]}
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
