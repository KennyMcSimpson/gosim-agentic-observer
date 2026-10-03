# Frozen Local Calibration v1

Verified on 2026-10-04 with the unmodified official Python baseline and vendored v4 scorer. Each replay used a 900-second budget, no effective model API, and ended with `survey_complete`.

| Card | Screenshot reference | Local score | Residual |
| --- | ---: | ---: | ---: |
| alpha | 3243.83 | 3336.68 | +92.85 |
| beta | 4558.45 | 4586.39 | +27.94 |
| gamma | 3893.13 | 3817.94 | -75.19 |
| delta | 2975.56 | 3036.41 | +60.85 |

All four absolute differences are below 100. Local mean: 3694.35; screenshot mean: 3667.74. These are fitted synthetic measurements, not organizer truth or official cloud scores. Matching one baseline does not guarantee that another Agent's official and local scores will match.

## Exact Frozen Inputs

The application loads `simulator/calibration-v1/{alpha,beta,gamma,delta}` and overlays the unchanged public catalogues and calendars. Every config, public and truth file is checked against its manifest SHA256. Runtime generator changes cannot replace the frozen calibration environment. Seed generation uses separate distributions and IDs.

Each card retains its own independent environment. Alpha comes from `tune-alpha-f`, gamma from `tune-gamma-q`, beta from the historical complete `fit9-900`, and delta from `fit15-900`. Alpha and gamma parameter lists are recorded. The original beta/delta parameter lists were not retained; their exact frozen truth files, rather than a guessed parameter list, are authoritative.

`validation_report.json` records the repeated complete scores, input fingerprints, identical Agent hashes, scorer manifest hash, score components and counts. Per-card `baseline_score_report.json` retains the scorer output. Verification compared the entire input hash map and counts, not just the scenario JSON or rounded total. All 16 official engine modules matched `ENGINE_MANIFEST.json`.

## Corrected Historical Claim

The older table alpha 3435.68 / beta 4586.39 / gamma 3665.01 / delta 3036.41 referred to retained historical artifacts. It did not describe the environment regenerated under the v15 generator. Direct v15 reruns measured alpha 1522.98 and gamma 4178.42. The generator version was part of its RNG key, so changing that version changed the hidden files. The new frozen file loader and complete replay verification resolve this discrepancy; the older table must not be used as the current result.

The scorer and baseline strategy were not changed to fit the screenshot values. Reference highs of 8000/7400 are display-only and never scale or cap local scores. Short build smokes verify packaging and protocol only.
