"""Search independent synthetic profiles against the supplied screenshot references."""
from __future__ import annotations

import argparse
import json
import sys
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from practice_backend import run_batch
from simulator import cards

TARGETS = {"alpha": 3243.83, "beta": 4558.45, "gamma": 3893.13, "delta": 2975.56}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("card", choices=tuple(TARGETS))
    parser.add_argument("--candidates", type=int, default=12)
    args = parser.parse_args()
    card = args.card
    manifest = json.loads((ROOT / "simulator/calibration-v1" / card / "simulation_manifest.json").read_text(encoding="utf-8"))
    base = dict(manifest.get("profile") or cards._FIXED_PROFILES[card])
    keys = ["candidate-%s-%03d" % (card, i) for i in range(args.candidates)]
    candidates = []
    for i, key in enumerate(keys):
        profile = dict(base)
        profile["rng_key"] = key
        profile["closed_slot_extra"] = max(0.0, min(0.12, base["closed_slot_extra"] + (i - 5) * 0.01))
        profile["seeing_shift"] = base["seeing_shift"] + (i - 5) * 0.025
        profile["transparency_shift"] = base["transparency_shift"] - (i - 5) * 0.012
        profile["sky_shift"] = base["sky_shift"] - (i - 5) * 0.012
        out = ROOT / "run_output" / "search" / card / str(i)

        def prepare_candidate(card_id, workspace):
            return cards._prepare_card(card_id + "-calibration", card_id, profile["rng_key"], workspace,
                                       public_root=None, environment_type="fixed-synthetic-calibration", seed=None,
                                       candidate_profile=profile)

        with patch.object(cards, "prepare_fixed_card", prepare_candidate):
            result = run_batch(ROOT / "agent" / "baseline_agent.py", [card], 0, out, enforce_quota=False, wallclock_seconds=900, mode="alpha-calibration")
        row = result["results"][0]
        score = float(row.get("total") or -1e9)
        candidates.append({"card": card, "index": i, "score": score, "residual": score - TARGETS[card], "profile": profile,
                           "complete": row.get("termination_reason") == "survey_complete", "output_dir": row["output_dir"]})
        (Path(row["output_dir"]) / "candidate_profile.json").write_text(json.dumps(candidates[-1], indent=2) + "\n", encoding="utf-8")
        print(json.dumps(candidates[-1], ensure_ascii=False), flush=True)
    completed = [row for row in candidates if row["complete"]]
    if not completed:
        raise SystemExit("no full survey candidate completed")
    best = min(completed, key=lambda row: abs(row["residual"]))
    print("BEST " + json.dumps(best, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
