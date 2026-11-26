# MelonWave: Raksha, a privacy firewall that understands Indian names, not just patterns

**Track 3 · Secret Wards** · Members: Anusha S, Nandhitha A, Sumanth M, Lokeswar P J · Repo: https://github.com/Anureddy7956/secret-wards

## 1. In one paragraph
Raksha turns a chaotic multi-hospital export (CSV, UTF-16 TSV, cp1252, nested JSON, FHIR R4, English / Devanagari /
Hinglish notes, broken files) into a research release: no personal data, every dose, vital, lab, diagnosis and procedure
intact, one keyed pseudonym per real patient across files, scripts and hospitals, and quasi-identifiers generalised
until a voter-list attacker gets little out of them. Its core idea: **read records the way a ward clerk does**.
Labels, relation markers (`S/o`, `D/o`, `W/o`, `पत्नी`), honorifics (`sahab`, `didi`, `जी`) and cross-script name keys
(Mohammad = Md. = मोहम्मद) find the person; a medical guard tells `C/O fever` from `C/O Ramesh`; linkage refuses any
merge that contradicts gender, age, DOB or Aadhaar. No LLM, no trained model, fully offline.

## 2. Architecture
```
input (read-only) → ingest: content sniffing · decoding · quarantine
  → learn ID formats from ID-labelled fields → detect: column classifier + free-text detector + medical guard
  → identity evidence → link: blocking · Fellegi–Sunter · conflict-aware clustering
  → HMAC pseudonyms · per-patient date shift · one age band per patient
  → privacy: k-anonymity search (band width, location level) · rare-value generalisation
  → render (2nd pass, cluster-wide names) → sanitized/ + records.jsonl + report.json
```

## 3. How it works
- **Ingestion:** format by bytes, not extension (magic numbers, XML, JSON-in-`.csv`); BOM/UTF-16/cp1252 decoding;
  iterative depth check against JSON bombs; truncated, empty, binary and unsupported files are quarantined with a
  reason code and are never copied. Every file is listed by SHA-256.
- **Detection:** columns and keys are classified by header semantics in English, Hinglish and Hindi plus value
  statistics when headers are unseen. ID formats are *learned* at run time and then found anywhere (notes, file
  names, CSV headers, JSON keys, export metadata, FHIR `meta.source`; base64 attachments are decoded, cleaned
  and re-encoded, non-text ones removed). Free text: validated patterns (all Indian phone groupings,
  Aadhaar, ABHA, PAN, PMJAY / insurance / policy IDs, UHID / MRN / IPD numbers), EN/HI labels, relation markers `S/o D/o W/o H/o C/o` (the name before `W/o` is the patient), honorifics (`ji`, `sahab`, `didi`),
  initials (`R. K. Sharma`),
  a gazetteer reached from Devanagari by a schwa-aware transliterator, a shape rule for unlisted names (this is how
  the canaries are caught) and propagation of a patient's known names. Text is normalised first (homoglyphs,
  zero-width, `\u`/HTML/%-escapes, Devanagari digits).
- **Linkage & pseudonyms:** blocking on shared IDs, phone and name skeletons keeps comparisons small; a shared UHID/IPD/Aadhaar/ABHA merges; a shared phone merges only with compatible names
  (families share phones); same full name across scripts merges only with a second clue (DOB, relative, village +
  age) and a unique candidate; `Meera, W/o Rajan` joins only a unique match. Hard conflicts veto every merge.
  `PSN-` + Crockford base32 of HMAC-SHA256 (HKDF sub-key of `RAKSHA_SECRET`) over an order-independent cluster key.
- **Privacy layer:** one secret date shift per patient (±15–180 days) in every file and date format, so LOS is
  exact and there is no global offset for an attacker to recover. One truthful age band per patient. House,
  locality, landmark, village and tehsil are removed; district is kept or lifted to state by a k-anonymity search
  over (gender, band, location). Patient-unique diagnoses and procedures are generalised to their ICD-10 chapter.
- **Output:** same folders, columns and formats; all text written as UTF-8. **Deterministic:** the same input and
  secret give byte-identical output; a different secret changes every pseudonym and date shift (both tested).
- **Security:** input is opened read-only and never copied. Raw and intermediate data stay in memory, so none is
  written to disk; if spilling is switched on (`security.spill_to_disk`, off by default) each blob is AES-256-GCM
  encrypted in a 0700 temp dir wiped on exit. All keys are HKDF sub-keys of `RAKSHA_SECRET` (separate keys for IDs,
  date shifts, file names and the vault), held only in process memory, never printed or saved. An allow-list
  logger (numbers, hashes, class names only) and a quiet excepthook keep PII out of logs and errors.

## 4. USP
- **Cross-script identity:** Latin, Devanagari and Hinglish mentions of one person meet in one canonical key and one
  pseudonym (practice linking P/R/F0.5 = 1.00 with 0 false merges; homonym pairs kept apart).
- **Meaning-aware:** doctors, doses (`Dolo 650 BD x 5 days`), complaints (`C/O fever`), `K/C/O`, eponyms and wards
  survive; relatives, care-of names and canaries do not.
- **Measured, adaptive privacy:** k-anonymity chooses the generalisation and `report.json` records the choice and
  the residual risk.

## 5. Privacy–utility trade-off (measured on the practice data)

| Measure | Value |
|---|---|
| personal data leaked (overall / Hindi / Hinglish) | 0% / 0% / 0% (0 of 3,230; all hiding places 0%); canaries 0 / 4 |
| medical values kept | 97.3% (lost: district → state, 92; patient-unique diagnoses, 12; census ward names, 6) |
| linking precision / recall / F0.5 | 1.00 / 1.00 / 1.00, 0 false merges |
| re-identification risk (our estimate) | 4% of patients unique on gender + age band + location; simulated record linkage 0.033 × raw; profile re-identification 0 / 48 (raw 48 / 48) |
| run time / peak memory | 1.25 s / 45 MB (10× data: 14 s / 145 MB, 2 CPUs) |
| data we did not tune on | every name swapped for invented names + renamed headers: first run 0.9% leaked, linking R 0.68 with 4 false merges; after generic fixes, and on a fresh seed: 0% leaked, P 1.00 / R 0.96, 0 false merges |

**Why these settings.** Keeping district makes most registry cells hold a single person (district + gender +
5-year band: mean attacker probability 0.65), while state + gender + 20-year band leaves about 24 candidates per
record. District and narrow bands are worth a few utility sub-points, and privacy carries 25 points, so the search
picks state + 20-year bands on this small release. We keep every clinical value, exact intervals and gender.

## 6. Known limitations
Names that are also English words (Karma, Rose) rely on context, not shape. An unlabelled Devanagari name with no
gazetteer or cluster match can slip through. Files with only ambiguous dates borrow the day/month order of their
source. XML, PDF and images are quarantined, not sanitised. k is computed over the release, not the population,
so small releases are generalised conservatively. Our attack simulator approximates the published attacks.
