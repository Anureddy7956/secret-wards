#!/usr/bin/env python3
"""Make a perturbed copy of the practice data for an honest generalisation test (kit advice:
"rename columns, swap in new names, change date formats, then run check_dev.py again").

* every Latin patient / relative name token is replaced by an invented name (in no gazetteer, not English)
* CSV headers and JSON keys are renamed to unseen synonyms
* the answer key is rewritten with the same substitutions, so check_dev.py can score the result

    python tools/perturb_dev.py --kit ../Secret-Wards-ToolKit --out /tmp/perturbed
    python ../Secret-Wards-ToolKit/check_dev.py --output <run output> --truth /tmp/perturbed/truth/truth.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from raksha.detect.lexicon import get_lexicon  # noqa: E402

HEADER_MAP = {"Patient Name": "Name of the Patient", "Mobile": "Contact No.", "UHID": "Hospital Reg ID",
              "Relative Name": "Guardian/Spouse", "Village/Mohalla": "Locality/Gram", "Address": "Residential Addr",
              "patient_name": "pt_full_name", "uhid": "hosp_mrn", "age_sex": "age/gender", "Naam": "Rogi ka Naam",
              "Mobile No": "Phone Number", "Gaon": "Gram", "PatientID": "MR Number", "Phone": "Cell",
              "FirstName": "Given Name", "LastName": "Family Name", "Guardian": "Next of Kin", "Zip": "Postal Code"}
KEY_MAP = {"patient_ref": "pt_id", "notes": "clinician_remarks", "mobile": "contact_number", "hospital_uhid": "reg_id"}

SYL1 = ["Vir", "Jas", "Ruk", "Tej", "Bal", "Sum", "Div", "Kan", "Nir", "Ujj", "Yash", "Lav", "Dhan", "Ish", "Om",
        "Pav", "Shub", "Trish", "Avan", "Chet", "Ekan", "Hima", "Kesh", "Miti", "Nav", "Rish", "Sav", "Tanv"]
SYL2 = ["endro", "ikaya", "meshu", "vatika", "preeto", "oshila", "anthi", "ilavi", "ushan", "irvan", "alok",
        "anshi", "oram", "ubhi", "eeshar", "ajit", "ovan", "inder", "akshi", "umith"]


def invent(r, used, lex):
    while True:
        w = r.choice(SYL1) + r.choice(SYL2)
        lw = w.lower()
        if lw not in used and not lex.is_name_gaz(w) and lw not in lex.english:
            used.add(lw)
            return w


def style(src: str, new: str) -> str:
    if src.isupper():
        return new.upper()
    if src.islower():
        return new.lower()
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit", default="../Secret-Wards-ToolKit")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    kit, out = Path(a.kit), Path(a.out)
    lex = get_lexicon()
    r = random.Random(a.seed)
    truth = json.loads((kit / "dev/truth/truth.json").read_text(encoding="utf-8"))
    tokens = set()
    for f in truth["files"].values():
        for u in f["units"].values():
            for e in u["entities"]:
                if e["type"] in ("PATIENT_NAME", "RELATIVE_NAME") and e["script"] != "deva":
                    for t in re.findall(r"[A-Za-z]{3,}", e["surface"]):
                        if t.lower() not in lex.generic and t.lower() not in ("sahab", "behenji", "didi", "amma",
                                                                               "bhai", "bhaiya", "chachu", "mama"):
                            tokens.add(t.lower())
    used = set()
    mapping = {t: invent(r, used, lex) for t in sorted(tokens)}
    rx = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted(map(re.escape, mapping), key=len, reverse=True)) + r")(?![A-Za-z])",
                    re.I)

    def sub(s: str) -> str:
        return rx.sub(lambda m: style(m.group(0), mapping[m.group(0).lower()]), s)

    if out.exists():
        shutil.rmtree(out)
    (out / "truth").mkdir(parents=True)
    src_root = kit / "dev/input"
    new_files = {}
    for rel, f in truth["files"].items():
        p = src_root / rel
        raw = p.read_bytes()
        enc = f.get("encoding") or "utf-8"
        new_rel = "/".join(sub(x) for x in rel.split("/"))
        try:
            text = raw.decode(enc if enc != "utf-16" else "utf-16")
            ok = f["format"] in ("csv", "tsv", "json", "fhir", "text") and f.get("expect") != "either"
        except UnicodeDecodeError:
            ok = False
        if ok:
            text = sub(text)
            if f["format"] in ("csv", "tsv"):
                lines = text.split("\n", 1)
                d = "\t" if f["format"] == "tsv" else ","
                hdr = [HEADER_MAP.get(h.strip("﻿"), h) for h in lines[0].rstrip("\r").split(d)]
                if lines[0].startswith("﻿"):
                    hdr[0] = "﻿" + hdr[0].lstrip("﻿")
                text = d.join(hdr) + ("\r" if lines[0].endswith("\r") else "") + "\n" + (lines[1] if len(lines) > 1 else "")
            if f["format"] == "json":
                for k, v in KEY_MAP.items():
                    text = text.replace(f'"{k}"', f'"{v}"')
            raw = text.encode(enc if enc not in ("utf-16",) else "utf-16")
        dest = out / "input" / new_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        nf = json.loads(json.dumps(f))
        nf["sha256"] = hashlib.sha256(raw).hexdigest()
        for u in nf["units"].values():
            for e in u["entities"]:
                e["surface"] = sub(e["surface"])
            for pv in u.get("preserve") or []:
                pv["text"] = sub(pv["text"])
        new_files[new_rel] = nf
    truth["files"] = new_files
    (out / "truth" / "truth.json").write_text(json.dumps(truth, ensure_ascii=False), encoding="utf-8")
    print(f"perturbed {len(new_files)} files, {len(mapping)} name tokens replaced")


if __name__ == "__main__":
    main()
