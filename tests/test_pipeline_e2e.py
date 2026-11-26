"""End-to-end tests on a small crafted dataset (new names, not from dev)."""
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

REG = (
    "UHID,Patient Name,Gender,Age,DOB,Relation,Relative Name,Address,Village/Mohalla,District,PIN,Mobile,Reg Date\n"
    "QHS/26/001001,Mohammad Arif,M,47,03/02/1979,S/o,Yusuf Khan,\"H.No. 12, near Masjid, Distt. Sitapur\","
    "Rampur Kalan,Sitapur,261001,+91 98390 11223,01/01/2026\n"
    "QHS/26/001002,Mohammad Arif,M,23,15/08/2002,S/o,Salim Ansari,\"House 9, Distt. Unnao\",Bhimpur,Unnao,209801,"
    "9123456780,02/01/2026\n"
    "QHS/26/001003,Kusum Lata,F,61,10/10/1964,W/o,Om Prakash,\"Makan No. 4, Distt. Unnao\",Navabganj,Unnao,209802,"
    "9988776655,03/01/2026\n"
)
RX_HI = "Qwerty Hospital - ओपीडी पर्चा\nनाम: मोहम्मद आरिफ   आयु: 47 वर्ष\nग्राम: रामपुर कलां\nतारीख: 05/03/2026\nमोबाइल: ९८३९०११२२३\nRx\n1. Tab Paracetamol 650 mg 1-0-1 x 5 days\n"
NOTE = ("NURSING NOTES - Ward 3 (Medicine), Bed 2 - QHS/26/001001\n\n"
        "01/03/2026 22:00 - Arif sahab ka BP 150/90, pulse 90. Md. Arif - K/C/O HTN.\n"
        "Admission: 01/03/2026  Discharge: 10/03/2026\n")
VISITS = {"_export_meta": {"hospital": "Qwerty Hospital", "source_path": "D:\\exports\\Mohammad_Arif_001001\\v.json"},
          "visits": [{"patient_ref": "QHS/26/001001", "visit_date": "04/03/2026", "notes": "Arif ka BP 140/90",
                      "doctor": "Dr. Kavita Rao", "Arif_visit": "follow-up"},
                     {"patient_ref": "QHS/26/001002", "visit_date": "05/03/2026", "notes": "Arif bhai stable",
                      "doctor": "Dr. Kavita Rao"}]}


def make_input(root: Path):
    (root / "reg").mkdir(parents=True)
    (root / "reg" / "patients.csv").write_text(REG, encoding="utf-8")
    (root / "rx").mkdir()
    (root / "rx" / "rx_001.txt").write_text(RX_HI, encoding="utf-8")
    (root / "notes").mkdir()
    (root / "notes" / "mohammad_arif.txt").write_text(NOTE, encoding="utf-8")
    (root / "opd").mkdir()
    (root / "opd" / "visits.json").write_text(json.dumps(VISITS, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "misc").mkdir()
    (root / "misc" / "truncated.json").write_text('{"visits": [{"patient": "Kusum Lata", "mobile": "99887', encoding="utf-8")
    (root / "misc" / "scan.jpg").write_bytes(b"\xff\xd8\xff\xe0" + os.urandom(64))
    (root / "misc" / "empty.csv").write_bytes(b"")


def run(inp: Path, out: Path, secret: str):
    env = dict(os.environ, RAKSHA_SECRET=secret)
    p = subprocess.run([sys.executable, str(ROOT / "main.py"), "--input", str(inp), "--output", str(out)],
                       env=env, capture_output=True, text=True, cwd=ROOT)
    return p


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    base = tmp_path_factory.mktemp("e2e")
    inp = base / "in"
    make_input(inp)
    before = {p: p.read_bytes() for p in inp.rglob("*") if p.is_file()}
    a = run(inp, base / "a", "secret-one")
    b = run(inp, base / "b", "secret-one")
    c = run(inp, base / "c", "secret-two")
    after = {p: p.read_bytes() for p in inp.rglob("*") if p.is_file()}
    return {"inp": inp, "a": base / "a", "b": base / "b", "c": base / "c", "proc": [a, b, c],
            "unchanged": before == after}


def records(out):
    return [json.loads(l) for l in (out / "records.jsonl").read_text().splitlines()]


def tree(out):
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*")
            if p.is_file() and p.name != "report.json"}


def test_exit_ok_and_input_untouched(runs):
    assert all(p.returncode == 0 for p in runs["proc"])
    assert runs["unchanged"]


def test_deterministic_same_secret(runs):
    assert tree(runs["a"]) == tree(runs["b"])


def test_different_secret_changes_pseudonyms(runs):
    pa = {r["patient"] for r in records(runs["a"]) if r["patient"]}
    pc = {r["patient"] for r in records(runs["c"]) if r["patient"]}
    assert pa and not (pa & pc)


def test_language_trap_same_pseudonym_homonym_separated(runs):
    recs = {(r["file"].split("/")[-2] + "/" + r["loc"]): r["patient"] for r in records(runs["a"])}
    arif1 = recs["reg/row:0"]
    arif2 = recs["reg/row:1"]
    assert arif1 and arif2 and arif1 != arif2            # two Mohammad Arifs, different age/phone
    rx = [r for r in records(runs["a"]) if "/rx/" in r["file"]][0]["patient"]
    note = [r for r in records(runs["a"]) if "/notes/" in r["file"]][0]["patient"]
    visit0 = recs["opd/" + "/visits/0"] if "opd//visits/0" in recs else [r for r in records(runs["a"]) if r["loc"] == "/visits/0"][0]["patient"]
    assert rx == arif1 and note == arif1 and visit0 == arif1


def test_pseudonym_inside_record(runs):
    for r in records(runs["a"]):
        if r["patient"]:
            assert r["patient"] in (runs["a"] / r["file"]).read_text(encoding="utf-8")


def test_quarantine_and_report(runs):
    rep = json.loads((runs["a"] / "report.json").read_text())
    shas = {hashlib.sha256(p.read_bytes()).hexdigest() for p in runs["inp"].rglob("*") if p.is_file()}
    assert {f["input_sha256"] for f in rep["files"]} == shas
    q = [f for f in rep["files"] if f["status"] == "quarantined"]
    assert len(q) == 3 and all(f["output"] is None and f["reason"] for f in q)
    names = {p.name for p in (runs["a"] / "sanitized").rglob("*")}
    assert "truncated.json" not in names and "scan.jpg" not in names
    c = rep["counts"]
    assert c["files_total"] == c["files_sanitized"] + c["files_quarantined"] == len(shas)
    assert c["records_processed"] == len(records(runs["a"]))


def test_filename_and_key_cleaned(runs):
    files = [p.name for p in (runs["a"] / "sanitized").rglob("*")]
    assert "mohammad_arif.txt" not in files
    visits = json.loads((runs["a"] / "sanitized/opd/visits.json").read_text())
    assert not any("Arif" in k for k in visits["visits"][0])
    assert "Arif" not in visits["_export_meta"]["source_path"]


def test_length_of_stay_preserved(runs):
    note = [r for r in records(runs["a"]) if "/notes/" in r["file"]][0]
    text = (runs["a"] / note["file"]).read_text()
    m = re.search(r"Admission: (\d\d)/(\d\d)/(\d{4})  Discharge: (\d\d)/(\d\d)/(\d{4})", text)
    a = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    b = dt.date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
    assert (b - a).days == 9 and a != dt.date(2026, 3, 1)


def test_no_pii_or_secret_in_side_channels(runs):
    pii = ["Arif", "Yusuf", "Kusum", "98390", "9123456780", "001001", "आरिफ", "Rampur"]
    for p in runs["proc"]:
        logs = p.stdout + p.stderr
        assert not any(x in logs for x in pii)
        assert "secret-one" not in logs and "secret-two" not in logs
    for out in (runs["a"], runs["c"]):
        blob = b"".join(f.read_bytes() for f in out.rglob("*") if f.is_file()).decode("utf-8", "replace")
        assert "secret-one" not in blob and "secret-two" not in blob
        for x in pii:
            assert x not in blob, x


def test_missing_secret_fails_closed(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "RAKSHA_SECRET"}
    p = subprocess.run([sys.executable, str(ROOT / "main.py"), "--input", str(tmp_path), "--output",
                        str(tmp_path / "o")], env=env, capture_output=True, text=True, cwd=ROOT)
    assert p.returncode != 0


# --- found by tools/make_tough.py -----------------------------------------------------------------

def _records(out: Path):
    return {(r["file"], r["loc"]): r["patient"] for r in map(json.loads, (out / "records.jsonl").read_text().splitlines())}


@pytest.fixture(scope="module")
def tough(tmp_path_factory):
    base = tmp_path_factory.mktemp("tough")
    inp = base / "in"
    (inp / "reg").mkdir(parents=True)
    # ragged rows (optional last column left out) and unseen Hinglish headers
    (inp / "reg" / "reg.csv").write_text(
        "Reg#,Name of the Patient,Gndr,Umar,Janam Tithi,Gram/Mohalla,Pin Code,Contact#,Aadhaar Card No.,Remarks\n"
        "UHID/2026/71001,Tarini Mahato,F,52,03/02/1974,Kharsawan,833216,+91 98390 11224,4821 7754 9032\n"
        "UHID/2026/71002,Bhola Rajak,M,38,15/08/1988,Chandil,832401,9123456781,5512 6634 7781,ok\n", encoding="utf-8")
    (inp / "notes").mkdir()
    (inp / "notes" / "n1.txt").write_text("Tarini Mahato (52/F) aayi thi, ph 9839011224. Hb 9.8 g/dL.\n", encoding="utf-8")
    (inp / "notes" / "n2.txt").write_text("Bhola Rajak follow-up. Aadhaar 5512 6634 7781. BP 130/80.\n", encoding="utf-8")
    (inp / "lab").mkdir()
    (inp / "lab" / "9123456781_report.json").write_text(json.dumps({"patient": "Bhola Rajak", "hb": "13.1 g/dL"}),
                                                         encoding="utf-8")
    (inp / "fhir").mkdir()
    bundle = {"resourceType": "Bundle", "type": "collection", "entry": [
        {"resource": {"resourceType": "Patient", "id": "a", "gender": "female", "name": [{"text": "Tarini Mahato"}],
                      "identifier": [{"system": "https://healthid.ndhm.gov.in", "value": "482177549032"}]}},
        {"resource": {"resourceType": "Patient", "id": "b", "gender": "male", "name": [{"text": "Bhola Rajak"}],
                      "identifier": [{"system": "https://healthid.ndhm.gov.in", "value": "551266347781"}]}}]}
    (inp / "fhir" / "two_patients.json").write_text(json.dumps(bundle), encoding="utf-8")
    out = base / "out"
    assert run(inp, out, "tough-secret").returncode == 0
    return out


def test_ragged_rows_keep_column_meaning(tough):
    import csv
    rows = list(csv.reader((tough / "sanitized" / "reg" / "reg.csv").read_text(encoding="utf-8").splitlines()))
    for row in rows[1:]:
        assert row[3] in ("50-54", "45-54", "40-59", "50-59", "35-39", "30-39", "20-39", "35-44", "30-49") or "-" in row[3]
        assert "Kharsawan" not in row and "Chandil" not in row and "833216" not in row and "832401" not in row


def test_name_with_age_sex_and_aadhaar_notes_link(tough):
    rec = _records(tough)
    tarini = rec[("sanitized/reg/reg.csv", "row:0")]
    bhola = rec[("sanitized/reg/reg.csv", "row:1")]
    assert tarini and bhola and tarini != bhola
    notes = {k[0]: v for k, v in rec.items() if k[0].startswith("sanitized/notes/")}
    assert sorted(notes.values()) == sorted([tarini, bhola])
    lab = [v for k, v in rec.items() if k[0].startswith("sanitized/lab/")]
    assert lab == [bhola]                       # phone only in the file name


def test_two_patient_bundle_does_not_merge_people(tough):
    rec = _records(tough)
    assert rec[("sanitized/reg/reg.csv", "row:0")] != rec[("sanitized/reg/reg.csv", "row:1")]
    fhir = [v for k, v in rec.items() if k[0].startswith("sanitized/fhir/")]
    assert fhir == [None]
