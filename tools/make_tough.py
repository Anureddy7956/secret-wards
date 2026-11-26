#!/usr/bin/env python3
"""Generate a deliberately HARD dataset that exercises every part of raksha/ (not tuned on).

What it throws at each module:
  ingest/    UTF-16 TSV, cp1252 CSV, UTF-8 BOM, JSON saved as .txt, CSV with no extension, quoted multi-line
             cells, ragged rows, CR-only line endings, XML / PDF / DOCX / PNG bytes, a truncated JSON, an empty file,
             a 2,000-level-deep JSON, a ~1.5 MB single-line note
  detect/    names that are English words (Rose, Happy, Golden, Pinky), a patient surnamed Graves next to
             "Graves disease", Devanagari names, Devanagari digits in a phone, Hinglish honorifics, every phone
             style, Aadhaar plain / hyphenated / masked, ABHA number and ABHA address, PAN, email, insurance IDs,
             MRN styles; doses, vitals and labs that look like IDs or dates
  hidden     PII in file names, a folder name, CSV headers, JSON keys, source_path metadata, base64 attachments
  link/      one man written as Mohammad / Mohd. / Md / मोहम्मद across files, linked only by phone or Aadhaar;
             two different women both called "Sunita Devi" (must NOT merge)
  privacy/   ten date formats with exact lengths of stay, many age forms, a 97-year-old with a rare disease
  write/     filename sanitising, structure-preserving CSV/JSON/FHIR output
  security/  canaries inside a truncated file, a JSON key and a base64 blob (must not reach logs or temp files)

Writes <out>/input/... and <out>/manifest.json in the format tools/leak_scan.py reads.

    python tools/make_tough.py --out /tmp/tough --seed 3
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import shutil
from pathlib import Path

DEVA_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DOCTOR = "Dr. Meenakshi Sundaram"
CANARIES = ["Zorawar Phukan", "Ilakkiya Nambiar", "Dechen Wangmo", "Bhrigu Lahiri"]


def phone(r):
    return str(r.choice([6, 7, 8, 9])) + "".join(str(r.randint(0, 9)) for _ in range(9))


def styles(p):
    """Every common way an Indian mobile is written."""
    return [f"+91 {p[:5]} {p[5:]}", f"0{p[:5]}-{p[5:]}", f"+91-{p}", p, f"{p[:3]} {p[3:6]} {p[6:]}",
            f"0091{p}", f"({p[:3]}) {p[3:]}"]


def aadhaar(r):
    return "".join(str(r.randint(0, 9)) for _ in range(12))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=3)
    a = ap.parse_args()
    r = random.Random(a.seed)
    root = Path(a.out)
    inp = root / "input"
    if root.exists() and any(root.iterdir()):
        # re-running: replace an earlier generated dataset, but never wipe a folder this script did not make
        if not (root / "manifest.json").exists():
            raise SystemExit(f"{root} is not empty and was not made by this script; choose another --out")
        shutil.rmtree(inp, ignore_errors=True)
        (root / "manifest.json").unlink()
    for sub in ("registration", "opd", "ipd", "notes", "lab", "fhir", "billing", "misc", "clean"):
        (inp / sub).mkdir(parents=True, exist_ok=True)

    P = []  # people

    def person(name, g, age, village, district, deva=None, variants=None, rare=None):
        p = {"name": name, "g": g, "age": age, "village": village, "district": district, "deva": deva,
             "variants": variants or [], "phone": phone(r), "aadhaar": aadhaar(r), "rare": rare,
             "mrn": f"UHID/2026/{r.randint(10000, 99999)}", "ipd": f"IPD-26-{r.randint(1000, 9999)}",
             "pan": "".join(r.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5)) + str(r.randint(1000, 9999)) + "P",
             "rel": r.choice(["Bhupender Rawat", "Lakhan Kushwaha", "Shamsher Ali", "Tarachand Bairwa",
                              "Joginder Malik", "Hemant Lodhi", "Nizamuddin Ansari"]),
             "pin": str(r.choice([226, 229, 241, 209, 261])) + str(r.randint(100, 999))}
        P.append(p)
        return p

    irfan = person("Mohammad Irfan Qureshi", "M", 52, "Bhitauli Kalan", "Barabanki", "मोहम्मद इरफ़ान कुरैशी",
                   ["Mohd. Irfan", "Md Irfan Qureshi", "Irfan bhai"])
    sun1 = person("Sunita Devi", "F", 34, "Malihabad", "Lucknow", "सुनीता देवी")
    sun2 = person("Sunita Devi", "F", 67, "Sandila", "Hardoi", "सुनीता देवी")
    rose = person("Rose Ekka", "F", 29, "Gosainganj", "Lucknow")
    happy = person("Happy Singh", "M", 41, "Bachhrawan", "Rae Bareli")
    golden = person("Golden Kaur", "F", 58, "Nawabganj", "Unnao")
    pinky = person("Pinky Rani", "F", 23, "Maharajganj", "Rae Bareli", "पिंकी रानी")
    graves = person("Mary Graves", "F", 45, "Kakori", "Lucknow")
    elder = person("Ramadhar Pasi", "M", 97, "Atrauli", "Hardoi", "रामाधार पासी", rare=("E75.21", "Fabry disease"))
    sundar = person("Sundar Lal Prajapati", "M", 61, "Bighapur", "Unnao", "सुंदर लाल प्रजापति", ["Sundar ji"])
    shabnam = person("Shabnam Bano", "F", 38, "Rudauli", "Ayodhya", "शबनम बानो", ["Shabnam didi"])
    for n, g in [("Tsering Angmo", "F"), ("Lalchhanhima Pachuau", "M"), ("Kavya Ramaswamy", "F"),
                 ("Baljinder Dhillon", "M"), ("Anjali Toppo", "F"), ("Prosenjit Barman", "M"),
                 ("Nirmala Oraon", "F"), ("Vikrant Bisht", "M"), ("Hasina Khatoon", "F"), ("Om Prakash", "M")]:
        person(n, g, r.randint(19, 85), r.choice(["Itaunja", "Haidergarh", "Purwa", "Tiloi"]),
               r.choice(["Lucknow", "Barabanki", "Unnao", "Hardoi"]))

    pii, groups = [], {}

    def grp(p, rel, loc):
        groups.setdefault(p["aadhaar"], []).append((rel, loc))

    for p in P:
        pii += [p["name"], p["rel"], p["phone"], p["aadhaar"], p["mrn"], p["ipd"], p["pan"]]
        if p["deva"]:
            pii.append(p["deva"])
    pii += [irfan["variants"][1]]

    # ---------------------------------------------------------------- registration
    # (a) UTF-8 BOM CSV, unseen headers, quoted multi-line address, ragged trailing column, header carrying a name
    hdr = ["Reg#", "Name of the Patient", "Gndr", "Umar", "Janam Tithi", "Guardian (S/o-W/o)", "Full Address",
           "Gram/Mohalla", "Zila", "Pin Code", "Contact#", "Aadhaar Card No.", "PAN No", "e-mail",
           f"Remarks (entered by {rose['name']})"]
    rows = [",".join(hdr)]
    for i, p in enumerate(P):
        dob = f"{r.randint(1, 28):02d}/{r.randint(1, 12):02d}/{2026 - p['age']}"
        ad = p["aadhaar"]
        ad_fmt = [f"{ad[:4]} {ad[4:8]} {ad[8:]}", f"{ad[:4]}-{ad[4:8]}-{ad[8:]}", ad][i % 3]
        addr = f"\"H.No. {r.randint(1, 400)}, near Shiv Mandir,\nVill. {p['village']}, Distt. {p['district']}\""
        email = f"{p['name'].split()[0].lower()}.{r.randint(10, 99)}@gmail.com"
        pii.append(email)
        rel = ("S/o " if p["g"] == "M" else "W/o ") + p["rel"]
        rows.append(",".join([p["mrn"], p["name"], p["g"], str(p["age"]), dob, rel, addr, p["village"],
                              p["district"], p["pin"], styles(p["phone"])[i % 7], ad_fmt, p["pan"], email]
                             + (["ok"] if i % 2 else [])))
        grp(p, "registration/reg_main.csv", f"row:{i}")
    (inp / "registration" / "reg_main.csv").write_bytes(("\ufeff" + "\r\n".join(rows) + "\r\n").encode("utf-8"))
    # (b) UTF-16 TSV with Devanagari headers
    t = ["क्रमांक\tमरीज़ का नाम\tआयु\tलिंग\tमोबाइल\tपता"]
    for p in [x for x in P if x["deva"]]:
        t.append(f"{p['mrn']}\t{p['deva']}\t{p['age']} वर्ष\t{'पुरुष' if p['g'] == 'M' else 'महिला'}\t{p['phone']}\t"
                 f"ग्राम {p['village']}, जिला {p['district']}")
    (inp / "registration" / "hindi_reg.tsv").write_bytes("\r\n".join(t).encode("utf-16"))
    # (c) legacy cp1252 CSV with smart quotes, CR-only line endings, no file extension
    leg = "id,patient,phone,comment\r"
    leg += f"1,{happy['name']},{happy['phone']},“VIP” – call before 10am\r2,{golden['name']},{golden['phone']},“Diabetic”\r"
    (inp / "registration" / "legacy_export").write_bytes(leg.encode("cp1252"))

    # ---------------------------------------------------------------- OPD JSON (keys and metadata hide PII)
    visits = []
    for i, p in enumerate(P[:12]):
        drug = r.choice([("Metformin", "500 mg", "1-0-1"), ("Amlodipine", "5 mg", "0-0-1"),
                         ("Paracetamol", "650 mg", "1-1-1")])
        dx = ("E05.0", "Graves disease") if p in (graves, golden, rose) else ("I10", "Essential (primary) hypertension")
        visits.append({"visit_id": f"OPD/{2026}/{r.randint(10000, 99999)}",
                       "patient": {"nm": p["name"], "mob": styles(p["phone"])[(i + 3) % 7], "uhid": p["mrn"]},
                       "vitals": {"bp": "146/92", "pulse": 88, "spo2": 97, "hba1c": "8.2 %"},
                       "diagnosis": [{"code": dx[0], "display": dx[1]}],
                       "rx": [{"drug": drug[0], "dose": drug[1], "freq": drug[2], "days": 30}],
                       "meta": {"source_path": f"C:\\HIS\\exports\\{p['name'].replace(' ', '_')}_{p['phone']}\\opd.json",
                                "entered_by": DOCTOR}})
        grp(p, "opd/opd_visits.json", f"/visits/{i}")
    opd = {"hospital": "Shanti Seva Hospital", "visits": visits,
           "followups": {golden["name"]: {"due": "2026-04-11"}, CANARIES[0]: {"due": "2026-05-02"}}}
    (inp / "opd" / "opd_visits.json").write_text(json.dumps(opd, ensure_ascii=False, indent=2), encoding="utf-8")
    # JSON saved with a .txt extension
    (inp / "opd" / "export_note.txt").write_text(json.dumps(
        {"patient_name": sundar["name"], "phone": sundar["phone"], "complaint": "C/O chest pain x 2 days",
         "ecg": "ST depression V4-V6"}, ensure_ascii=False), encoding="utf-8")
    grp(sundar, "opd/export_note.txt", "doc")

    # ---------------------------------------------------------------- IPD discharge notes: dates, LOS, names in scripts
    date_fmts = [lambda d: d.strftime("%d/%m/%Y"), lambda d: d.strftime("%Y-%m-%d"), lambda d: d.strftime("%d-%b-%Y"),
                 lambda d: d.strftime("%d.%m.%y"), lambda d: f"{d.day}th {d.strftime('%B %Y')}",
                 lambda d: d.strftime("%b %d, %Y"), lambda d: d.strftime("%d %b %Y")]
    import datetime as dt
    for i, p in enumerate(P[:14]):
        a0 = dt.date(2026, r.randint(1, 10), r.randint(1, 20))
        los = r.randint(2, 11)
        f = date_fmts[i % len(date_fmts)]
        dx = p["rare"] or ("A90", "Dengue fever")
        age = [f"{p['age']} Yrs/{p['g']}", f"{p['age']}Y {p['g']}", f"Age-{p['age']}", f"{p['age']} वर्ष",
               f"aged {p['age']}"][i % 5]
        nm = p["name"] if i % 3 else (p["deva"] or p["name"])
        body = (f"DISCHARGE SUMMARY\nPatient: {nm}   {age}\nIPD No: {p['ipd']}   UHID: {p['mrn']}\n"
                f"{'S/o' if p['g'] == 'M' else 'W/o'} {p['rel']}, R/o Vill. {p['village']}, PIN {p['pin']}\n"
                f"Admitted: {f(a0)}   Discharged: {f(a0 + dt.timedelta(days=los))}\n"
                f"Diagnosis: {dx[1]} ({dx[0]})\nK/C/O Parkinson's disease, Bell's palsy (2019)\n"
                f"Platelets 45,000 /cumm on admission, 1,62,000 at discharge. Hb 9.8 g/dL.\n"
                f"Inj Ceftriaxone 1 g IV BD x 5 days. Tab Pantoprazole 40 mg 1-0-0 BBF.\n"
                f"{p['name'].split()[0]} {'ji' if p['g'] == 'M' else 'didi'} ko aaram hai, BP 128/84.\n"
                f"Attendant mob {styles(p['phone'])[i % 7]}. Seen by {DOCTOR}.\n")
        fn = f"DS_{p['name'].replace(' ', '_')}_{p['ipd']}.txt" if i % 2 else f"ds_{i:03d}.txt"
        (inp / "ipd" / fn).write_text(body, encoding="utf-8")
        grp(p, f"ipd/{fn}", "doc")

    # ---------------------------------------------------------------- notes: Hinglish, variants, Devanagari digits
    notes = {
        "n_irfan_1.txt": f"Mohd. Irfan (52/M) aaye the, ph {irfan['phone']}. Sugar 245 mg/dL fasting. "
                         f"Tab Glimepiride 2 mg 1-0-0 shuru kiya.\n",
        "n_irfan_2.txt": f"नाम: {irfan['deva']}\nफोन: {irfan['phone'].translate(DEVA_DIGITS)}\nआधार: {irfan['aadhaar']}\n"
                         f"शुगर 245 mg/dL, Tab Glimepiride 2 mg 1-0-0\n",
        "n_irfan_3.txt": f"Md Irfan Qureshi follow-up. Aadhaar XXXX XXXX {irfan['aadhaar'][-4:]}. "
                         f"Real Aadhaar {irfan['aadhaar'][:4]} {irfan['aadhaar'][4:8]} {irfan['aadhaar'][8:]}. "
                         f"ABHA 91-{r.randint(1000, 9999)}-{r.randint(1000, 9999)}-{r.randint(1000, 9999)}, "
                         f"ABHA address irfan.q52@abdm. HbA1c 9.1 %.\n",
        "n_sunita_a.txt": f"Sunita Devi (34/F) W/o {sun1['rel']}, Malihabad, mob {sun1['phone']}. ANC visit, "
                          f"Hb 10.2 g/dL, Tab Iron Folic Acid 1-0-0.\n",
        "n_sunita_b.txt": f"Sunita Devi (67/F) W/o {sun2['rel']}, Sandila, mob {sun2['phone']}. "
                          f"K/C/O COPD, Inhaler Tiotropium 18 mcg 0-0-1.\n",
        "n_graves.txt": f"Pt. Mary Graves, 45/F. K/C/O Graves disease. Tab Carbimazole 10 mg 1-0-1. TSH 0.01 mIU/L.\n",
        "n_words.txt": f"Rose Ekka aur Happy Singh dono ka BP 130/80 tha. Golden Kaur ko Insulin 10 units SC HS. "
                       f"Pinky Rani 23/F, sickle cell trait. Rose water gargles advised; patient is happy.\n",
        "n_shabnam.txt": f"Shabnam didi ka sugar control me hai. शबनम बानो, मो. {shabnam['phone']}, "
                         f"Tab Metformin 500 mg 1-0-1.\n",
        "n_sundar.txt": f"Sundar ji (61 Y/M) ka ECG: ST depression V4-V6. Inj Enoxaparin 60 mg SC BD. "
                        f"Son Hemant called on {sundar['phone'][:5]}-{sundar['phone'][5:]}.\n",
        "n_elder.txt": f"{elder['name']}, 97 Yrs/M, Atrauli. Diagnosed {elder['rare'][1]} ({elder['rare'][0]}). "
                       f"Enzyme replacement started. eGFR 38 mL/min.\n",
    }
    for fn, body in notes.items():
        (inp / "notes" / fn).write_text(body, encoding="utf-8")
    for fn, p in [("n_irfan_1.txt", irfan), ("n_irfan_2.txt", irfan), ("n_irfan_3.txt", irfan),
                  ("n_sunita_a.txt", sun1), ("n_sunita_b.txt", sun2), ("n_graves.txt", graves),
                  ("n_shabnam.txt", shabnam), ("n_sundar.txt", sundar), ("n_elder.txt", elder)]:
        grp(p, f"notes/{fn}", "doc")
    # a folder whose NAME is personal data
    d = inp / "notes" / f"{pinky['name'].replace(' ', '_')}_{pinky['phone']}"
    d.mkdir()
    (d / "visit.txt").write_text(f"Pinky Rani 23/F, sickle cell trait, Hb 8.9 g/dL. Tab Folic Acid 5 mg 1-0-0.\n",
                                 encoding="utf-8")
    # one huge single-line note (stress: speed and memory)
    filler = "Vitals stable, BP 120/80, pulse 78, afebrile. " * 30000
    (inp / "notes" / "long_line.txt").write_text(f"Pt {happy['name']} mob {happy['phone']}. " + filler +
                                                 f" Contact {happy['name']} on {happy['phone']}.", encoding="utf-8")

    # ---------------------------------------------------------------- lab: phone in filename, base64 attachment
    for p in (irfan, rose):
        fn = f"{p['phone']}_report_{r.randint(1000, 9999)}.json"
        att = base64.b64encode(f"Name: {p['name']}\nMobile: {p['phone']}\nHb 11.4 g/dL\n".encode()).decode()
        (inp / "lab" / fn).write_text(json.dumps({"patient": p["name"], "tests": [{"name": "Haemoglobin",
                                      "value": 11.4, "unit": "g/dL"}], "scan_b64": att}), encoding="utf-8")
        grp(p, f"lab/{fn}", "doc")
    can64 = base64.b64encode(f"Visitor pass: {CANARIES[1]}".encode()).decode()
    (inp / "lab" / "forward.txt").write_text(f"Fwd: report of {golden['name']} 58 Y / F, Hb 12.1 g/dL\n"
                                             f"attachment: {can64}\n", encoding="utf-8")

    # ---------------------------------------------------------------- FHIR bundle
    ents = []
    for i, p in enumerate([irfan, shabnam]):
        ents.append({"fullUrl": f"urn:uuid:pat-{i}", "resource": {
            "resourceType": "Patient", "id": f"pat-{i}",
            "meta": {"source": f"http://his.local/{p['mrn']}"},
            "identifier": [{"system": "https://healthid.ndhm.gov.in", "value": p["aadhaar"]},
                           {"system": "http://hospital.local/uhid", "value": p["mrn"]}],
            "name": [{"text": p["name"]}], "telecom": [{"system": "phone", "value": p["phone"]}],
            "gender": "male" if p["g"] == "M" else "female", "birthDate": f"{2026 - p['age']}-03-14",
            "address": [{"text": f"Vill. {p['village']}", "district": p["district"], "postalCode": p["pin"]}]}})
        ents.append({"fullUrl": f"urn:uuid:obs-{i}", "resource": {
            "resourceType": "Observation", "id": f"obs-{i}", "status": "final",
            "code": {"text": "HbA1c"}, "subject": {"reference": f"urn:uuid:pat-{i}"},
            "effectiveDateTime": "2026-03-02", "valueQuantity": {"value": 8.2, "unit": "%"}}})
    (inp / "fhir" / "bundle_01.json").write_text(json.dumps({"resourceType": "Bundle", "type": "collection",
                                                             "entry": ents}, indent=1), encoding="utf-8")

    # ---------------------------------------------------------------- billing: insurance and PAN
    b = ["Claim No|Beneficiary|PMJAY ID|PAN|Amount|Package"]
    for p in P[:6]:
        pm = f"PMJAY-UP-{r.randint(10000000, 99999999)}"
        pii.append(pm)
        b.append(f"CLM{r.randint(100000, 999999)}|{p['name']}|{pm}|{p['pan']}|{r.randint(5, 90) * 1000}|"
                 f"Dengue management")
    (inp / "billing" / "claims.psv").write_text("\n".join(b) + "\n", encoding="utf-8")

    # ---------------------------------------------------------------- clean reference data (must survive untouched)
    (inp / "clean" / "formulary.csv").write_text(
        "Drug,Strength,Frequency,Notes\nMetformin,500 mg,1-0-1,with food\nCarbimazole,10 mg,1-0-1,monitor TSH\n"
        "Ceftriaxone,1 g,BD,IV\n", encoding="utf-8")
    (inp / "clean" / "dengue_protocol.txt").write_text(
        "Dengue: platelets below 20,000 /cumm need transfusion review. Paracetamol 650 mg 1-1-1. Avoid NSAIDs.\n",
        encoding="utf-8")

    # ---------------------------------------------------------------- misc: broken / unsupported / hostile
    (inp / "misc" / "cut.json").write_text('{"patient": {"name": "' + CANARIES[2] + '", "phone": "98', encoding="utf-8")
    (inp / "misc" / "empty.csv").write_bytes(b"")
    (inp / "misc" / "scan.pdf").write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\n" + f"({rose['name']})".encode() + b"\n%%EOF")
    (inp / "misc" / "form.docx").write_bytes(b"PK\x03\x04" + bytes(range(200)))
    (inp / "misc" / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4)
    (inp / "misc" / "hl7.xml").write_text(f"<msg><pid><name>{happy['name']}</name><ph>{happy['phone']}</ph></pid></msg>",
                                          encoding="utf-8")
    deep = {"name": CANARIES[3]}
    for _ in range(2000):
        deep = {"n": deep}
    (inp / "misc" / "deep.json").write_text(json.dumps(deep), encoding="utf-8")
    (inp / "misc" / "binary.csv").write_bytes(bytes(r.randint(0, 255) for _ in range(3000)))

    manifest = {"pii": sorted(set(pii)), "canaries": CANARIES, "groups": groups,
                "clinical": ["146/92", "8.2 %", "Graves disease", "Parkinson's disease", "Bell's palsy",
                             "Platelets 45,000 /cumm", "Hb 9.8 g/dL", "Inj Ceftriaxone 1 g IV BD x 5 days",
                             "Tab Pantoprazole 40 mg 1-0-0", "Sugar 245 mg/dL", "ST depression V4-V6",
                             "Tab Carbimazole 10 mg 1-0-1", "TSH 0.01 mIU/L", "Insulin 10 units SC HS",
                             "Inj Enoxaparin 60 mg SC BD", "eGFR 38 mL/min", DOCTOR, "Rose water gargles",
                             "Inhaler Tiotropium 18 mcg 0-0-1", "platelets below 20,000 /cumm need transfusion"],
                "must_not_merge": [[sun1["aadhaar"], sun2["aadhaar"]]]}
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {sum(1 for x in inp.rglob('*') if x.is_file())} files to {inp}")


if __name__ == "__main__":
    main()
