"""Search independent synthetic profiles against the supplied screenshot references."""
from __future__ import annotations

import itertools
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from practice_backend import run_batch
from simulator import cards

TARGETS = {"alpha": 3243.83, "beta": 4558.45, "gamma": 3893.13, "delta": 2975.56}


def main() -> int:
    card = sys.argv[1] if len(sys.argv) > 1 else "alpha"
    if card not in TARGETS:
        raise SystemExit("card must be alpha, beta, gamma, or delta")
    base = dict(cards._FIXED_PROFILES[card])
    keys = ["candidate-%s-%03d" % (card, i) for i in range(12)]
    candidates = []
    for i, key in enumerate(keys):
        profile = dict(base)
        profile["rng_key"] = key
        profile["closed_slot_extra"] = max(0.0, min(0.12, base["closed_slot_extra"] + (i - 5) * 0.01))
        profile["seeing_shift"] = base["seeing_shift"] + (i - 5) * 0.025
        profile["transparency_shift"] = base["transparency_shift"] - (i - 5) * 0.012
        profile["sky_shift"] = base["sky_shift"] - (i - 5) * 0.012
        cards._FIXED_PROFILES[card] = profile
        out = ROOT / "run_output" / "search" / card / str(i)
        shutil.rmtree(out, ignore_errors=True)
        result = run_batch(ROOT / "agent" / "baseline_agent.py", [card], 0, out, enforce_quota=False, wallclock_seconds=20, mode="alpha-calibration")
        row = result["results"][0]
        score = float(row.get("total") or -1e9)
        candidates.append({"card": card, "index": i, "score": score, "residual": score - TARGETS[card], "profile": profile})
        print(json.dumps(candidates[-1], ensure_ascii=False), flush=True)
    best = min(candidates, key=lambda row: abs(row["residual"]))
    print("BEST " + json.dumps(best, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
