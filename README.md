
<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/hero-dark.svg">
  <img alt="Raksha: input files → read → detect → link → protect → write → sanitized output" src="docs/assets/hero-light.svg" width="100%">
</picture>

# Raksha · Privacy Firewall

**Yugaantar DevForge · Track 3: Secret Wards · Team MelonWave**

*Remove the person. Keep the medicine.*

[**Quick start**](#quick-start) · [How it works](#how-it-works) · [Results](#results) · [Security](#security) · [**Project brief (PDF)**](docs/brief.pdf)

### 📄 [Read the 2-page Project Brief (PDF)](docs/brief.pdf)

</div>

---

## In one paragraph

Raksha cleans a folder of hospital records so it can be shared for research. It removes
personal data, keeps every medical value, and gives each patient one fake ID across all
files, in English, Hindi and Hinglish. It runs offline, on a normal CPU, with **no AI model**.

**Team MelonWave:** Anusha S · Nandhitha A · Sumanth M · Lokeswar P J

## What's in this repo

| | Path | What it is |
|---|---|---|
| 📄 | [`docs/brief.pdf`](docs/brief.pdf) | the 2-page Project Brief |
| ▶️ | [`main.py`](main.py) | the command-line entry point |
| 🧠 | [`raksha/`](raksha) | the program: `ingest/` (reading), `detect/`, `link/`, `privacy/`, `pseudo/`, `write/`, `security/`, `translit/`, `data/` (name and medical word lists) |
| ⚙️ | [`config/policy.yaml`](config/policy.yaml) | every privacy setting in one file: age bands, date shifts, k-anonymity target, linking thresholds |
| 🧾 | [`raksha.toml`](raksha.toml) | the submission file: team name, setup and run commands |
| 🧪 | [`tests/`](tests) | 87 automatic tests (`pytest -q`) |
| 🛠️ | [`tools/`](tools) | test helpers: hard and synthetic test data, leak scanner, attack simulator |

The organisers' practice data and checkers are in the
[Team Kit](https://github.com/Reinforce-SST/Secret-Wards-ToolKit).

## Quick start

```bash
pip install -r requirements.txt
RAKSHA_SECRET=any-secret python main.py --input <input folder> --output <output folder>
```

Check it with the kit's tools (kit cloned next to this repo as `../Secret-Wards-ToolKit`):

```bash
RAKSHA_SECRET=practice python main.py --input ../Secret-Wards-ToolKit/dev/input --output out/practice
python ../Secret-Wards-ToolKit/validate_output.py --input ../Secret-Wards-ToolKit/dev/input --output out/practice   # CONTRACT OK
python ../Secret-Wards-ToolKit/check_dev.py --output out/practice                                                    # leaks, medical values, linking
python ../Secret-Wards-ToolKit/check_submission.py --repo . --run                                                     # READY TO SUBMIT
```

Test it on data it was not tuned on, and run the tests:

```bash
pip install -r requirements-dev.txt
python tools/make_tough.py --out out/tough_data --seed 3                          # 46 hard files: every encoding, hiding place and trap
python tools/leak_scan.py --data out/tough_data --out out/tough                   # leaks, medical values kept, linking
python tools/attack_sim.py --kit ../Secret-Wards-ToolKit --output out/practice   # re-identification attacks A1-A7
pytest -q --cov=raksha --cov-report=term-missing
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

```
output/
├── sanitized/       ← cleaned copies of every file: same folders, columns and formats, UTF-8
├── report.json      ← every input file (by SHA-256), cleaned or set aside, and true totals
└── records.jsonl    ← which fake patient ID each record belongs to
```

## How it works

Two passes: pass 1 reads every file and builds patient identities (needed to link records
across files); pass 2 rewrites each file. Everything stays in memory.

| | Step | What happens |
|---|---|---|
| 1 | **Read** | format decided from the contents, not the extension; UTF-8, UTF-16, cp1252; broken, empty, binary and unsupported files quarantined with a reason, never copied |
| 2 | **Detect** | columns by header (`Patient Name`, `Umar`, `मोबाइल`) or, when unfamiliar, by their values; patterns for every Indian phone format, Aadhaar, ABHA, PAN, insurance and hospital IDs (ID formats learned at run time); context such as `Name:`, `नाम:`, `S/o`, `W/o`, `sahab`, `didi`; a medical guard keeps doctors, doses, vitals and diseases |
| 3 | **Link** | shared UHID / Aadhaar / ABHA links; a shared phone links only if the names fit; the same name needs a second clue and a unique candidate; merges that contradict gender, age, birth date or Aadhaar are refused; `मोहम्मद` = `Mohammad` = `Md.`; too little evidence gives `"patient": null` |
| 4 | **Protect** | `PSN-` + HMAC-SHA256 fake IDs keyed from the secret; one secret date shift per patient (±15–180 days, so stay lengths stay exact); age bands; house, locality and village removed; district kept or raised to state by a k-anonymity search; diagnoses only one patient has generalised to their ICD-10 chapter |
| 5 | **Write** | same folders, columns and formats; personal data replaced everywhere: values, file names, JSON keys, CSV headers, metadata, URLs and base64 attachments; CSV, JSON and FHIR R4 stay valid |

The same input and secret give byte-identical output; a different secret changes every fake
ID and date shift.

## What makes it different

* **Cross-script identity.** Latin, Devanagari and Hinglish mentions of one person
  (`Mohammad Arif`, `Md. Arif`, `मोहम्मद आरिफ`, `Arif sahab`) meet in one key and one fake ID,
  while two different people with the same name stay apart.
* **Reads meaning, not just patterns.** `C/O fever` is a complaint, `C/O Ramesh` is a person;
  `Dr. Ramesh` stays, `W/o Ramesh` goes; `Dolo 650 BD x 5 days`, `K/C/O Parkinson's` and lab
  values survive.
* **Measured privacy.** A k-anonymity search picks the generalisation, and every number in
  this README comes from the kit's checkers or our attack simulator.

## Results

**Practice data** (200 files, 48 patients, `check_dev.py`):

| | Measure | Result |
|---|---|---|
| 🛡️ | Personal data left in output (overall / Hindi / Hinglish) | **0 of 3,230** items (0% / 0% / 0%) |
| 🐤 | Planted "canary" names leaked | **0 of 4** |
| 💊 | Medical values kept | **97.3%** |
| 🔗 | Patient linking (precision / recall / F0.5) | **1.00 / 1.00 / 1.00**, no wrong merges |
| 📦 | Valid FHIR R4 bundles | **19 of 19** |
| ⚡ | Run time / memory | **1.2 s / 45 MB** |

**Data we did not tune on:**

| Test set | Leaked | Linking |
|---|---|---|
| practice data with every name invented and headers renamed (`tools/perturb_dev.py`) | 0% | precision 1.00, recall 0.96, no wrong merges |
| hard generated set, 4 seeds (`tools/make_tough.py`): unseen Hinglish headers, ragged rows, names that are English words, IDs in URLs and file names, a two-patient FHIR bundle | 0 of 170 | 81 of 81 record pairs, no wrong merges |

**Re-identification attacks** (`tools/attack_sim.py`, our approximation of the kit's attacks, raw input vs our output):

| Attack | Raw | Ours |
|---|---:|---:|
| A1 direct exposure (patients) | 100% | 0% |
| A3 record linkage against the voter list | 0.60 | 0.04 |
| A4 profile re-identification (patients) | 48 of 48 | 4 of 48 |
| A5 targeted attack with known facts | 1.00 | 0.55 |
| A6 fake ID reversed to a real ID | – | 0% |
| A7 two releases linked (different secrets) | – | 0% |

**The privacy–utility trade-off.** Keeping the district leaves most patients alone in their
(gender, age band, district) group. State plus 20-year bands leaves 10% unique, so on a release
this small the search picks state and 20-year bands. The 2.7% of medical values not kept are
this choice: districts raised to state (92 values), diagnoses only one patient has (12) and
census ward names (6). Every dose, vital, lab value, interval and gender is kept.

## Security

*Assume the server will be breached one day.*

* **Data at rest:** the input is opened read-only and never copied. Raw and intermediate
  data stay in memory. If spilling is switched on (`security.spill_to_disk`, off by default),
  each blob is AES-256-GCM encrypted in a private 0700 temp folder wiped at exit.
* **Keys:** the only secret is `RAKSHA_SECRET`; without it the program stops. Separate keys
  are derived from it with HKDF for fake IDs, date shifts, file names and encryption, held
  only in memory, never printed or saved. In production we would keep it in a key-management
  service, wrap the data keys with it (envelope encryption) and rotate it per release.
* **Logs and errors:** an allow-list logger prints only counts, file hashes, stage names and
  error class names; a quiet exception hook keeps names out of tracebacks.
* **Quarantine:** files that cannot be cleaned are listed in `report.json` by SHA-256 with a
  reason and never copied, so a half-cleaned file cannot leak.

Tests check that no personal data or secret reaches the output, the report or printed output,
and that a missing secret fails closed.

## Models used

**None.** No AI model of any kind. Detection uses rules and word lists; matching uses string
similarity (`rapidfuzz`).

## Known limitations

* Names that are also English words are caught by a nickname list or a following surname
  (Rose Ekka, Lovely Singh); on their own they rely on context.
* A Hindi name with no label or known spelling elsewhere can be missed.
* Shifted birth dates still give away the birth year, and in a small release a diagnosis plus
  gender, age band and hospital is often unique (targeted attack 0.55).
* XML, PDF and image files are set aside rather than cleaned.
* With few patients, privacy settings are cautious (20-year age bands, state instead of district).

---

<div align="center">

Team **MelonWave** · Anusha S · Nandhitha A · Sumanth M · Lokeswar P J<br>
Built for Yugaantar DevForge, Track 3. All data used is synthetic.

</div>
