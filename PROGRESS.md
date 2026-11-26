# Progress (measured with the kit's tools after each milestone)

All runs: `RAKSHA_SECRET=practice`, practice data, `check_dev.py` and `validate_output.py` from the kit.
k-min / share below k from `report.json`; A3/A4 from `tools/attack_sim.py` (approximation, ratio to raw).

| Milestone | PII visible | Medical kept | Linking P / R / F0.5 | k-min (share < 5) | A3 / A4 vs raw | Runtime | Peak RSS |
|---|---|---|---|---|---|---|---|
| M0 starter (CONTRACT OK) | 2718 / 3230 (84.1%) | 100.0% | 0 / 0 / 0 | n/a | n/a | not measured | not measured |
| M1–M4 detection + linkage | 0 / 3230 | 98.1% | 1.00 / 1.00 / 1.00 | n/a (5-year bands, district) | n/a | 3.0 s | 44 MB |
| M5 privacy layer | 0 / 3230 | 97.3% | 1.00 / 1.00 / 1.00 | 1 (37.5%), 20-year bands, state | 0.033 / 0.000 | 3.2 s | 44 MB |
| M6 hidden places + FHIR (19/19 valid) | 0 / 3230 | 97.3% | 1.00 / 1.00 / 1.00 | 1 (37.5%) | 0.033 / 0.000 | 3.2 s | 44 MB |
| M7 generalisation + caching | 0 / 3230 | 97.3% | 1.00 / 1.00 / 1.00 | 1 (37.5%) | 0.033 / 0.000 | 1.25 s | 45 MB |

Generalisation (M7):

| Dataset | PII visible | Linking | Notes |
|---|---|---|---|
| perturbed practice data, first run before fixes | 28 / 3230 (0.9%) | P 0.98 / R 0.68, 4 false merges | unseen first names before Hinglish particles, name keys, renamed ID headers |
| perturbed practice data after generic fixes (seed 11) | 0 / 3230 | P 1.00 / R 0.96, 0 false merges | |
| fresh perturbation seed 23 (not inspected before measuring) | 0 / 3230 | P 1.00 / R 0.96, 0 false merges | |
| synthetic unseen-format set, first run | 4 / 112 strings | 46 / 48 pairs | `R/o`, `Husband/Father:`, colon-less `Pt.` |
| synthetic, after fixes (seed 7) / fresh seed 99 | 0 / 112 · 0 / 112 | 48 / 48 · 48 / 48, 0 false merges | canaries 0 / 3 |
| 10× practice data (2,000 files) | n/a | n/a | 14 s, 145 MB on 2 CPUs |
