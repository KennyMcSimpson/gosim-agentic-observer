# Vendor provenance

## Public alpha–delta inputs

`vendor/public-input/alpha` through `delta` are the public-only `taskcard-*.zip` files received on 2026-10-03. Each contains its `config/` and `public/` files only. They do not include weather truth, event truth, observation-request truth, or the organizer's complete forecast history.

## Synthetic simulator

`simulator/cards.py` preserves the public target catalogue, footprint, and night calendar byte-for-byte. Fixed cards load independently fitted, hash-verified files from `simulator/calibration-v1/`; they are never regenerated at runtime. Seed cards generate local slots, weather, events, earthquake effects, bulletins, forecasts and requests under a separate `synthetic-<profile>-like-seed-<n>` namespace. Every manifest marks `official_truth: false`.

The frozen baseline values and high-score values in `practice_backend.py` are the four values supplied by the user from the official bare-Agent screenshots. They are calibration references only. A local residual measures the difference between the locally generated score and that reference; it cannot establish official hidden-card parity.

## Official examples and training material

The complete organizer examples package, including L1–L4 truth and the official runner, is stored in the team repository `KennyMcSimpson/gosim-2026-team` under `training/official-v4/`. The application repository intentionally keeps alpha–delta as its main test surface so official regression material does not get confused with the cloud practice cards.

The upstream examples package is licensed CC BY-NC 4.0. The team bundle retains the upstream license, attribution, engine manifest, and hashes. The local `runner_worker.py` is only a Windows anonymous-pipe adapter and does not modify vendored scoring modules.

## Agent and model configuration

The Python example Agent is copied byte-for-byte into `agent/agent_core/`; its official `agent.py` is renamed `agent/baseline_agent.py` without source changes. Any OpenAI-compatible provider, including AnyRouter, is optional and supplied explicitly at runtime through the GUI. The app isolates inherited keys and Agent `.env` files. Keys are not stored in this repository.
