# How Raksha works

```
input files ─► 1 Read ─► 2 Detect ─► 3 Link ─► 4 Protect ─► 5 Write ─► sanitized/, report.json, records.jsonl
                 │
                 └─► broken or unsupported files are set aside (quarantined), never copied
```

The pipeline makes two passes. Pass 1 reads every file and builds patient identities, which
is needed to link records across files. Pass 2 rewrites each file. Everything stays in memory.

## 1. Read

* Each file's format is decided from its **contents**, not its extension (magic numbers,
  XML, JSON saved as `.csv`).
* UTF-8, UTF-8 with BOM, UTF-16 and old Windows encodings (cp1252) are decoded.
* Broken files (cut-off JSON, empty files, images, PDFs, XML) are quarantined with a reason
  code. They are listed in `report.json` by SHA-256 and never copied to the output.
* The input folder is only read, never changed.

## 2. Detect

Personal data is found in three ways:

* **Columns and keys**, by their header (`Patient Name`, `Naam`, `मोबाइल`, `Contact#`) or,
  when the header is unfamiliar, by what the values look like.
* **Patterns** for phones in every Indian format, Aadhaar, ABHA numbers and addresses, PAN,
  emails, insurance and policy IDs (PMJAY), and UHID / MRN / IPD numbers. Hospital ID
  formats are learned from ID-labelled fields at run time, then found anywhere.
* **Context** in free text: labels (`Name:`, `नाम:`), relation markers (`S/o`, `D/o`, `W/o`,
  `H/o`, `C/o`, `पत्नी`), honorifics (`ji`, `sahab`, `didi`, `जी`), initials
  (`R. K. Sharma`), and name lists in English and Hindi reached through a transliterator.

Text is normalised first: look-alike characters, zero-width characters, escapes and
Devanagari digits.

A **medical guard** protects doctor names, doses, vitals, complaints (`C/O fever` is a
complaint, `C/O Ramesh` is a person), procedures and disease names such as Parkinson's.

## 3. Link

* **Blocking** on shared IDs, phone numbers and name keys keeps the number of comparisons small.
* A shared UHID, IPD number, Aadhaar or ABHA links two records.
* A shared phone links only when the names also fit, because families share phones.
* The same name links only with a second clue (birth date, relative, or village plus age)
  and only when there is exactly one candidate.
* A merge is refused if gender, age, birth date or Aadhaar disagree, so two different
  people with the same name stay separate.
* Hindi and English spellings meet in one key (`मोहम्मद` = `Mohammad` = `Md.`).
* When the evidence is too weak, the record gets `"patient": null` instead of a guess.

## 4. Protect

* **Fake IDs:** `PSN-` plus an HMAC-SHA256 of the patient's identity, keyed from
  `RAKSHA_SECRET`. It cannot be reversed without the secret.
* **Dates:** every date of one patient moves by the same secret number of days (±15–180),
  so lengths of stay stay exact.
* **Ages** become bands. **Addresses** (house, locality, landmark, village) are removed.
* **Districts** are kept or raised to state, chosen by a k-anonymity search over gender,
  age band and location.
* **Rare values:** a diagnosis or procedure that only one patient has is generalised to its
  ICD-10 chapter.

## 5. Write

* Same folders, file names, columns and formats as the input. All text is written as UTF-8.
* Personal data is replaced everywhere: values, file names, JSON keys, CSV headers, export
  metadata, FHIR `meta.source` and base64 attachments (decoded, cleaned and re-encoded;
  non-text attachments are removed).
* CSV keeps the same columns in the same order. JSON stays valid JSON. FHIR stays a valid R4
  Bundle whose references resolve.
* The patient's fake ID is written inside the cleaned record, and `records.jsonl` lists it.

## Determinism

The same input and the same secret give byte-identical output (only `timing` and
`resources` in `report.json` change). A different secret changes every fake ID and date
shift. Both are covered by tests in `tests/test_pipeline_e2e.py`.
