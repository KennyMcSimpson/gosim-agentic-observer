# Alpha–delta simulator checkpoint (2026-10-03)

## Verified

- The complete official L1–L4 training/regression bundle was copied to `KennyMcSimpson/gosim-2026-team/training/official-v4/` and pushed as commit `70b0042`. The application repository no longer tracks the L1–L4 local card directories.
- `simulator/cards.py` preserves alpha–delta public `targets.csv`, `footprint.csv`, and `v4_night_calendar.csv` byte-for-byte, then creates compatible local truth and bulletin products. Fixed cards and seed cards use separate namespaces and deterministic SHA-256-derived random streams.
- The Windows runner adapter and all 16 vendored engine hashes pass `verify_engine.py`. Four-card GUI smoke and seed smoke both returned runner exit code 0. Five unit tests pass.
- Full local runs were executed with the deterministic fallback Agent and a 900-second limit. The closest retained profiles measured alpha 1969.58 vs 3243.83, beta 5715.21 vs 4558.45, gamma 3493.84 vs 3893.13, and delta 3090.79 vs 2975.56. These are synthetic local measurements; the requested +/-100 fit was not reached for every card.

## Boundary

The screenshot numbers are calibration references supplied by Kenny. Alpha–delta truth is not published, so the local generator must not be described as recovering official hidden weather or as predicting cloud scores. Any future tuning should change only the synthetic profile parameters, rerun the complete cards, and update `CALIBRATION_RESULTS.md` with fresh score-report paths.
