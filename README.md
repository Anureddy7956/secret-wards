# Raksha — privacy firewall for hospital records

Raksha cleans a folder of hospital records so it can be shared for research.
It removes personal data, keeps every medical value, and gives each patient one
fake ID across all files. It runs offline, on a normal CPU, with no AI model.

Built for **Track 3: Secret Wards** (Yugaantar DevForge).

## Quick start

```bash
pip install -r requirements.txt
RAKSHA_SECRET=any-secret python main.py --input <input folder> --output <output folder>
```

Try it on the included demo (7 small files, 11 automatic checks):

```bash
bash samples/check_samples.sh
```

## What it does

| Input | Output |
|---|---|
| `Patient Name: Mohammad Arif   Age/Sex: 47 Yrs/M` | `Patient Name: PSN-WR6SWW   Age/Sex: 40-59 Yrs/M` |
| `नाम: मोहम्मद आरिफ` (Hindi) | `नाम: PSN-WR6SWW` (same patient, same ID) |
| `S/o Yusuf Khan`, `Mobile: +91 98390 11223` | `S/o [RELATIVE]`, `Mobile: [PHONE]` |
| `Date of Admission: 01/03/2026` → `Discharge: 10/03/2026` | `04/04/2026` → `13/04/2026` (shifted, still 9 days) |
| `Dr. Ramesh Srivastava`, `C/O fever x 3 days`, `Ramipril 5 mg 1-0-1` | unchanged |

The output folder contains:

- `sanitized/` — cleaned copies of every file, same folders, columns and formats
- `report.json` — every input file (by SHA-256), whether it was cleaned or set aside, and totals
- `records.jsonl` — which fake patient ID each record belongs to

## Results on the practice data

| Measure | Result |
|---|---|
| Personal data left in output | 0 of 3,230 items |
| Planted "canary" names leaked | 0 of 4 |
| Medical values kept | 97.3% |
| Patient linking (precision / recall) | 1.00 / 1.00, no wrong merges |
| Valid FHIR bundles | 19 of 19 |
| Run time / memory | 1.3 s / 45 MB |

On data we did not tune on (every name replaced with invented names, column
headers renamed), it still leaked nothing and linked with precision 1.00 and
recall 0.96. The missing 2.7% of medical values is deliberate: districts are
generalised to state, and diagnoses only one patient has are generalised.

## How it works

```
input files ─► 1 Read ─► 2 Detect ─► 3 Link ─► 4 Protect ─► 5 Write ─► sanitized/, report.json, records.jsonl
                 │
                 └─► broken or unsupported files are set aside, never copied
```

1. **Read.** Each file's format is decided from its contents, not its extension.
   UTF-8, UTF-16 and old Windows encodings are handled. Broken files (cut-off
   JSON, images, PDFs) are set aside with a reason.
2. **Detect.** Personal data is found in three ways:
   - *Columns and keys* by their header (`Patient Name`, `Naam`, `मोबाइल`, `Contact#`)
     or, if the header is unfamiliar, by what the values look like.
   - *Patterns* for phones, Aadhaar, ABHA, PAN, emails and hospital IDs.
   - *Context* in free text: labels (`Name:`, `नाम:`), relations (`S/o`, `W/o`),
     honorifics (`sahab`, `didi`, `जी`), and name lists in English and Hindi.

   A medical guard protects doctor names, doses, vitals, complaints
   (`C/O fever` is a complaint, `C/O Ramesh` is a person) and disease names
   like Parkinson's.
3. **Link.** Records of the same person are grouped using hospital IDs, Aadhaar,
   phone, or the same name plus a second clue (birth date, relative, village and age).
   A merge is refused if gender, age or Aadhaar disagree, so two people with the
   same name stay separate. Hindi and English spellings match
   (`मोहम्मद` = `Mohammad` = `Md.`).
4. **Protect.** Each patient gets a fake ID made from the secret key (HMAC), so it
   cannot be reversed. All of a patient's dates move by the same secret number of
   days. Ages become bands, addresses are removed, and districts become states when
   needed to stop someone being singled out (k-anonymity).
5. **Write.** Personal data is replaced in every value, including file names, JSON keys,
   CSV headers, export metadata and attachments.

## Security

- Nothing personal is written to disk except the cleaned output.
- The secret key is never printed or saved. Separate keys are derived from it for
  IDs, date shifts and file names.
- Logs show only counts and file hashes, never content. Errors show only the error type.
- Files that cannot be cleaned are listed in the report but never copied.

## Project layout

| Path | Purpose |
|---|---|
| `main.py` | Command-line entry point |
| `raksha/` | The program: `ingest/` (reading), `detect/`, `link/`, `privacy/`, `write/`, `security/`, `data/` (name and medical word lists) |
| `config/policy.yaml` | All privacy settings in one file |
| `tests/` | 70 automatic tests (`pytest -q`) |
| `samples/` | Demo input, its output, and a check script |
| `tools/` | Development helpers: synthetic data, leak scanner, attack simulator |
| `docs/brief.pdf` | 2-page project brief |

## Models used

None. No AI model of any kind. Detection uses rules and word lists; matching
uses string similarity (`rapidfuzz`).

## Known limitations

- Names that are also English words (Rose, Karma) are only caught when the context gives them away.
- A Hindi name with no label or known spelling elsewhere can be missed.
- XML, PDF and image files are set aside rather than cleaned.
- With few patients, privacy settings are cautious (20-year age bands, state instead of district).
