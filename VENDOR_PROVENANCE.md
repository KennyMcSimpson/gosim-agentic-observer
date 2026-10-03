# Vendor provenance

## Official v4 examples

`vendor/gosim-official-v4/` is copied from `gosim-observer-examples.zip` supplied by the GOSIM 2026 Agentic Observer challenge on 2026-10-03. The copied `local-cards/L1`–`L4` are complete public local practice cards. The copied `runner/challenge/` and `runner/project_platform/` files are the organizer-provided v4 scoring engine; `runner/ENGINE_MANIFEST.json` and `runner/verify_engine.py` are retained.

The vendor bundle is licensed by the organizers under CC BY-NC 4.0. `LICENSE.md` is kept beside the bundle. The local `runner_worker.py` is a platform adapter for Windows anonymous pipes; it does not alter the vendored engine modules.

The upstream Python example Agent is copied into `agent/agent_core/` with its `agent.py` entry adapted as `agent/baseline_agent.py`. The only local change is the no-key fail-fast endpoint described in the README, so a local run follows the upstream deterministic fallback instead of contacting a default remote service.

## Alpha-delta public input

`vendor/public-input/alpha/` through `delta/` are the public-only `taskcard-*.zip` files received on 2026-10-03. Each contains only its `config/` and `public/` files; none has a `truth/` directory, weather truth, event truth, or observation-request truth. They are retained for schema inspection and agent development only and are not locally scoreable cards.

## Local additions

The local no-key fallback is a small runtime adaptation around the upstream Agent. The upstream planner reads only the v4 initialize payload, current decision snapshots, public bulletins/forecasts, and its own observation feedback. Any OpenAI-compatible model call is optional and uses environment values supplied at runtime.

`practice_backend.py` runs the vendored official engine in a separate process. `official-fixed` uses the copied L1–L4 directories unchanged. `stress-seed` clones one official card and perturbs only numeric hidden weather truth with a reproducible seed; it is a local robustness test and is never presented as official parity.
