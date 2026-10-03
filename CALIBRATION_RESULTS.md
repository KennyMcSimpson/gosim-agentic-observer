# Local Calibration Record

The fixed cards use deterministic, independently calibrated per-card profiles. The reference values are the user's bare-Agent screenshot values, not organizer truth. Scores below are local runs with the vendored scorer and no effective model API.

| Card | Screenshot reference | Local score | Residual |
| --- | ---: | ---: | ---: |
| alpha | 3243.83 | 3435.68 | +191.85 |
| beta | 4558.45 | 4586.39 | +27.94 |
| gamma | 3893.13 | 3665.01 | -228.12 |
| delta | 2975.56 | 3036.41 | +60.85 |

The table is the retained screenshot-fit candidate record: α/δ came from `run_output/fit15-900/`, while β/γ came from `run_output/fit9-900/`. Each card uses its own RNG key and hidden synthetic profile; the four environments are intentionally not identical. A fresh direct v15 rerun on 2026-10-04 measured α 1522.98 (residual -1720.85) and γ 4178.42 (residual +285.29), so the candidate table is not a current ±100 validation. The discrepancy is retained as evidence that historical generated-card artifacts must be frozen by full truth-file hashes before further fitting. These are local synthetic measurements against the screenshot references, not recovered organizer truth or official cloud scores.
