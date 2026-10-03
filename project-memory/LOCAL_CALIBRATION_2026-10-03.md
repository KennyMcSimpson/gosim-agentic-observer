# Alpha–delta simulator checkpoint (2026-10-03)

## Superseding checkpoint: 2026-10-04

The previous score table below is historical. Current frozen `calibration-v1` complete replays measured alpha 3336.681494 (+92.851494), beta 4586.385590 (+27.935590), gamma 3817.940628 (-75.189372), and delta 3036.405311 (+60.845311). Every card used a 900-second budget and ended with `survey_complete`. The official Python entrypoint (renamed only) and all agent_core modules were checked byte-for-byte against the supplied examples ZIP. All 16 official engine modules matched their manifest. Exact receipts are retained in `simulator/calibration-v1/validation_report.json`.

The old v15 generator regenerated different hidden files because its version string was included in the RNG seed. Historical fit scores were therefore not the current v15 score. The application now loads independent frozen truth overlays and checks every input hash; changing the generator or seed distributions cannot alter a fixed calibration card.

The GUI displays frozen bare-Agent scores, screenshot targets, differences and reference highs on startup. Custom runs replace these with their own scores. Seed uses separate Alpha-like through Delta-like names, hides screenshot columns, and shows a generated ID and local environment summary. Full score components and raw counts remain separate. Small-window and calibration/seed interaction probes passed. API configuration is entered at runtime; deterministic runs isolate inherited credentials and Agent .env files.

The Windows packaged smoke found a dynamic-import omission in the runner host. The build now explicitly analyzes run_local and collects challenge/project_platform modules. CI verifies the official engine, frozen inputs and the packaged executable. Binary release completion is recorded in the parent project checkpoint after actual checks.

Sources: supplied taskcard ZIPs and official examples ZIP; source replays under `run_output/exact-official-v1-{alpha,beta,gamma,delta}`; screenshots under `run_output/ui-verified`. This is fitted local simulation, not recovered official truth or a guarantee for other Agents' cloud scores. Team training remains at commit `70b0042`. Central project resolution returned PROJECT_UNRESOLVED; no central-memory synchronization is claimed.

## Verified

- The complete official L1–L4 training/regression bundle was copied to `KennyMcSimpson/gosim-2026-team/training/official-v4/` and pushed as commit `70b0042`. The application repository no longer tracks the L1–L4 local card directories.
- `simulator/cards.py` preserves alpha–delta public `targets.csv`, `footprint.csv`, and `v4_night_calendar.csv` byte-for-byte, then creates compatible local truth and bulletin products. Fixed cards and seed cards use separate namespaces and deterministic SHA-256-derived random streams.
- The Windows runner adapter and all 16 vendored engine hashes pass `verify_engine.py`. Four-card GUI smoke and seed smoke both returned runner exit code 0. Five unit tests pass.
- Full local runs were executed with the deterministic fallback Agent and a 900-second limit. The closest retained profiles measured alpha 1969.58 vs 3243.83, beta 5715.21 vs 4558.45, gamma 3493.84 vs 3893.13, and delta 3090.79 vs 2975.56. These are synthetic local measurements; the requested +/-100 fit was not reached for every card.

## Boundary

The screenshot numbers are calibration references supplied by Kenny. Alpha–delta truth is not published, so the local generator must not be described as recovering official hidden weather or as predicting cloud scores. Any future tuning should change only the synthetic profile parameters, rerun the complete cards, and update `CALIBRATION_RESULTS.md` with fresh score-report paths.
