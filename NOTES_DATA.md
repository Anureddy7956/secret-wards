# NOTES_DATA: what the practice kit contains

Kit: `Reinforce-SST/Secret-Wards-ToolKit` (cloned to `../Secret-Wards-ToolKit`). The answer key is
`dev/truth/truth.json`; the attacker's files are `dev/attacker/registry.csv` and
`dev/attacker/known_facts.jsonl`. Everything below was observed in `dev/`. None of the names or
file names are copied into the pipeline.

## 1. Inventory (200 files, 815 records, 48 patients, 4 hospitals)

| Folder | Files | Format / encoding | Shape |
|---|---|---|---|
| registration/ | 5 | CSV UTF-8-BOM (×2, byte-identical duplicate `… (1).csv`), TSV **UTF-16-LE** with CRLF, CSV **cp1252**, nested JSON | one row / one JSON object per patient |
| opd/ | 29 | JSON `{_export_meta, visits:[…]}` | record = `/visits/N`; some visits carry a nested `patient {name, age_sex, mobile}` |
| discharge/ | 25 | text: English template, Devanagari template, 2-line fragment notes | record = `doc` |
| notes/ | 11 | Hinglish nursing notes, a visitor log | `doc` |
| prescriptions/ | 46 | English and Devanagari OPD slips | `doc` |
| lab/ | 37 | 4 lab CSVs (one row per test), JSON reports (`patient{…}`, `panels[]`), a bulk export `{results:[…144]}`, WhatsApp forwards | rows / docs / `/results/N` |
| fhir/ | 19 | FHIR R4 document Bundles | `doc`; resources: Composition, Patient, Practitioner, Organization, Encounter, Condition, Observation (incl. BP panel with components), MedicationRequest, Procedure, DocumentReference |
| billing/ | 4 | CSV claims | rows |
| clean/ | 4 | protocol txt, formulary csv, lab-range csv, census json | **no PII**; every token must survive |
| misc/ | 14 | traps: PDF, JPEG, XML (HL7 CDA), empty CSV, invalid-UTF-8 text, truncated JSON, a 1,500-deep JSON, JSON behind a `.csv` extension, a base64 "scanned" form, helpdesk tickets, a patient index keyed by UHID/name, a vitals sheet whose **headers** are `UHID Firstname`, an ambulance log | `expect: either` (quarantine is fine) for 8 of them |

Date conventions: Sanjeevani and Jeevan Jyoti use day-first (`dd/mm/yyyy`, `dd-mm-yyyy`), Arogya uses
**month-first** (`mm/dd/yyyy`, also in its discharge summaries and nursing notes), Hardoi uses ISO and `dd.mm.yyyy`.
There are also ISO datetimes with time zones (FHIR, export metadata, lab JSON), `[dd/mm/yy, h:mm pm]`
(WhatsApp) and `5 September` with no year (fragment notes). Devanagari digits appear (`मोबाइल: ८५९९२५३५२५`).

## 2. What counts as PII (`truth.json` entity types, count in dev)

PATIENT_NAME 962, MRN 850 (UHIDs **and IPD / admission numbers**: the scorer matches their digit core), PHONE 308,
RELATIVE_NAME 232, VILLAGE 150, HOUSE 136, PIN 136, DOB 111, LOCALITY 103 (`Ward 20`, `Mohalla Raja Bazar`),
AADHAAR 71, LANDMARK 64 (`near Pani Tanki`), ABHA_NUMBER 46, PAN 22, INSURANCE_ID 22 (`PMJAY-UP-…`, `POL/…`),
AADHAAR_MASKED 16 (`XXXX XXXX 5866`), EMAIL 1, CANARY 4.

Hiding places (channels): content 3115, **filename 48**, **metadata 40** (`_export_meta.source_path`
`D:\HIS\exports\opd\Anita_Sharma_010565\…`, FHIR `meta.source`), **key 12** (JSON keys = UHIDs / names),
**base64 11** (FHIR DocumentReference attachments, a consent form), **header 8** (CSV header `JJH-0077112 Zainab`).

Scripts: latin 2980, deva 143, hinglish 111 (`Shahid sahab`, `Asha ji`, `Kamal Bhaiya`, `Reena behenji`).

**Not** PII: doctor names (`Dr. Ramesh Srivastava`, `ref_doctor`, FHIR Practitioner), hospital names, wards
(`Ward 4 (Medicine)`, `Ward 8 (Medicine), Bed 2`), districts (they are preserve-probes, but also quasi-identifiers),
visit/bill/sample IDs (`OPD/26/10/00181`, `BL/26/000235`, `S26000187`), ICD/LOINC codes.

Generic name parts do not count on their own: Devi, Kumar, Md., ji.

## 3. What must be preserved (preserve-probe kinds)

lab 745, medication 595, vital 555, doctor 511, frequency 490, lab_test 404, dose 298, diagnosis_code 268,
diagnosis 237, complaint 176, history 119, context 110 (Hinglish clinical phrases), department 102, district 93,
ward 33, procedure 32, package 22, amount 22, hospital 19, eponym 16, range 8.

Meaning traps found: `C/O fever for 3 days` and `C/O: fever x 7 days` (complaint) vs `C/O Ramesh Patel, Ward 1` (care-of);
`K/C/O addison's disease`, `H/O TB 8 yrs back`; `Dr. Ramesh Srivastava reviewed the patient.` next to a relative
`Ramesh Patel`; `Dolo 650 BD x 5 days`, `Ramipril 5 mg`, `1-0-1`, `650mg 1-1-1 x 5 days`; `Addison's disease`,
`Crohn's disease`, `Bell's palsy`; `Referred by ASHA worker of the village` (ASHA ≠ the name Asha).

## 4. Linking ground truth

771 records must be linked, 2 are ambiguous, 110 have no patient. Within dev, **no strong identifier
(UHID, IPD no., phone, Aadhaar, ABHA, PAN, policy no.) is shared by two patients**. Name collisions are real:
two `Brijesh Yadav` and two `Harish Pandey` (the homonym traps: same name, different age, village and relative),
plus shared first names (Fatima, Zainab, Sunita, Sunil, Sukhwinder).
Traps: language (`Mohammad Shahid` / `Mohd. Shahid` / `Shahid sahab` / `मोहम्मद शाहिद`, with two Arogya UHIDs for the same man),
fragmented (`Asha, W/o Kamal` + a date, no ID), re-identification (a 97-year-old with kala-azar; a rabies case).
Files cross-reference through IPD numbers (nursing note `IP/26/00134` ↔ discharge summary with the UHID),
UHIDs in lab CSVs and billing, and phones in WhatsApp forwards.
Spelling variants of the same person: Rina/Reena, Fatma/Fatima, Brijesh/Brajesh, Harish/Hareesh, Irfan/Irfaan, upper-case rows.

## 5. The attacker (`dev/attacker/`, docs/ATTACKS.md)

`registry.csv`: 240 people (5× the patients). Columns: name, relation, relative, gender, age, house_no, mohalla,
village, tehsil, district, PIN; 62% also carry phone / email / last-4 Aadhaar. There are 8 districts, 22 tehsils and 65 villages.
`known_facts.jsonl`: 17 targets with a true visit date and hospital, sometimes a condition (always the rare one for trap patients), plus decoys.

Measured on the registry (mean probability the attacker puts on the true person, if only these QIs survive):

| QIs left in the release | mean 1/k | unique people |
|---|---:|---:|
| district + gender + 5-year band | 0.650 | 101 / 240 |
| district + gender + 10-year band | 0.479 | 50 |
| gender + 5-year band | 0.154 | 2 |
| gender + 10-year band | 0.083 | 1 |
| gender + 20-year band | 0.042 | 0 |

So district is the quasi-identifier that matters most. The raw input scores 0.92 linkage risk and 98% of patients re-identified
(`dev/truth/raw_attack.json`). The utility side values district at only 0.7 of a generalisation sub-score (2% of the total), so
the privacy layer should be allowed to generalise location to state level when k demands it.

## 6. Kit vs build prompt: where they differ (kit wins)

1. The kit was not at `../Secret-Wards-ToolKit`; I cloned the official repo there.
2. Paths: truth is `dev/truth/truth.json` (not `dev/truth.json`); attacker knowledge is `dev/attacker/{registry.csv,known_facts.jsonl}`.
3. **Brief format:** the kit requires a **2-page PDF** (`check_submission.py` warns without one), not only a Markdown draft.
4. **No new columns:** the prompt allows inserting a `patient_pseudonym` column. The kit scores "same columns, same header", so the
   pseudonym replaces an existing identifier or name field (`patient_ref`, `UHID`, `Patient Name`, a `Name:` line).
5. **Speed targets are stricter:** full speed and memory points need < 60 s and < 512 MB peak RSS (standard profile), not < 5 min / < 1 GB.
6. Status values: `sanitized | quarantined | suppressed`; `records.jsonl` may carry `out` and `status`.
7. `report.files` must not contain file names, only SHA-256 + output path. Renamed outputs are declared through `output`.
8. Age bands: the kit credits any truthful band (5 years 0.9, 10 years 0.8, 20 years 0.6), so band width is a policy choice driven by k, not fixed at 5.
9. A single global date shift is explicitly broken by attack A5, so non-patient dates (export timestamps) carry no patient signal and are left as they are.
   Every patient-linked date gets a per-patient shift; unlinked records get a per-record shift.
