# Results

All numbers are measured on the kit's practice data (200 files, 48 patients, 4 hospitals)
with `RAKSHA_SECRET=practice` and the kit's `check_dev.py` and `validate_output.py`.

## Practice data

| Measure | Result |
|---|---|
| Personal data left in output (overall / Hindi / Hinglish) | 0 of 3,230 items (0% / 0% / 0%) |
| Planted "canary" names leaked | 0 of 4 |
| Medical values kept | 97.3% |
| Patient linking (precision / recall / F0.5) | 1.00 / 1.00 / 1.00, no wrong merges |
| Valid FHIR bundles | 19 of 19 |
| Run time / peak memory | 1.3 s / 45 MB (10× the data: 14 s / 145 MB on 2 CPUs) |

The missing 2.7% of medical values is deliberate: districts are generalised to state (92
values), diagnoses only one patient has are generalised (12), and census ward names (6).

## Data we did not tune on

Every name replaced with invented names and the column headers renamed
(`tools/perturb_dev.py`, `tools/make_synthetic.py`):

| Run | Leaked | Linking |
|---|---|---|
| first run | 0.9% | recall 0.68, 4 wrong merges |
| after general fixes, on a fresh seed | 0% | precision 1.00, recall 0.96, no wrong merges |

A harder generated set, `tools/make_tough.py` (46 files): unseen Hinglish headers, ragged CSV rows,
names that are English words, bracketed phones, IDs inside URLs and file names, base64
attachments, a two-patient FHIR Bundle, two different women with the same name, and broken
files. Scored with `tools/leak_scan.py`:

| Run | Leaked | Medical values kept | Linking |
|---|---|---|---|
| first run | 9 of 170 | 20 of 20 | 48 pairs found, 33 missed, 1 wrong merge |
| after fixes (seeds 3, 5, 11, 42) | 0 of 170 | 20 of 20 | 81 of 81 found, no wrong merges |

## Re-identification risk

* 4% of patients are unique on gender + age band + location.

| Attack (kit `docs/ATTACKS.md`) | Raw input | Our output |
|---|---:|---:|
| A1 direct exposure (patients) | 100% | 0% |
| A3 record linkage (probability on the true person) | 0.60 | 0.043 (0.07 × raw) |
| A4 profile re-identification (patients, confidence ≥ 0.5) | 48 of 48 | 4 of 48 |
| A5 targeted, known facts (14 targets, 4 decoys) | 1.00 | 0.55; 1 decoy wrongly claimed |
| A6 pseudonym inversion | – | 0% |
| A7 cross-release linking (second secret) | – | 0% same pseudonym, 0% same date |

Measured with `tools/attack_sim.py`, an approximation of the kit's published attacks, using
the registry's leaked-contacts columns and `known_facts.jsonl` with its decoys.

**Known weaknesses.** The four A4 hits come from shifted birth dates: a DOB moved by under
six months still gives the birth year, which is much narrower than the 20-year age band.
A5 comes from the diagnosis together with gender, age band and hospital, plus exact lengths
of stay. On 48 patients most of those combinations are unique. Generalising rare diagnoses
further (`rare_values.min_patients` 2 → 4) costs medical values (97.3% → 94.4% kept)
without lowering A5.

## Privacy vs. utility

Keeping the district makes most registry cells hold a single person (district + gender +
5-year band: mean attacker probability 0.65). State + gender + 20-year band leaves about 24
candidates per record. On a release this small the k-anonymity search therefore picks state
and 20-year bands. Every clinical value, exact interval and gender is kept. The choice is
recorded in the `privacy` block of `report.json`.

## Checks that pass

```text
pytest -q                              87 passed
validate_output.py                     CONTRACT OK
check_submission.py --repo . --run     READY TO SUBMIT
```
