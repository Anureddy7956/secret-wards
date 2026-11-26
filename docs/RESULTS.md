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

## Re-identification risk

* 4% of patients are unique on gender + age band + location.
* Simulated record-linkage attack: 0.033 × the success it has on raw data.
* Profile re-identification: 0 of 48 patients (48 of 48 on raw data).

Measured with `tools/attack_sim.py`, an approximation of the kit's published attacks.

## Privacy vs. utility

Keeping the district makes most registry cells hold a single person (district + gender +
5-year band: mean attacker probability 0.65). State + gender + 20-year band leaves about 24
candidates per record. On a release this small the k-anonymity search therefore picks state
and 20-year bands. Every clinical value, exact interval and gender is kept. The choice is
recorded in the `privacy` block of `report.json`.

## Checks that pass

```text
pytest -q                              70 passed
bash samples/check_samples.sh          11 passed, 0 failed
validate_output.py                     CONTRACT OK
check_submission.py --repo . --run     READY TO SUBMIT
```
