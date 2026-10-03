"""Short offline smoke for the official L1-L4 v4 runner."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from practice_backend import run_batch


def main() -> int:
    result = run_batch(
        ROOT / "agent" / "baseline_agent.py",
        ["L1", "L2", "L3", "L4"],
        0,
        ROOT / "run_output" / "ci-smoke",
        enforce_quota=False,
        wallclock_seconds=3,
        mode="official-fixed",
    )
    if result.get("completed_cards") != 4:
        raise SystemExit("official v4 smoke did not complete all four cards")
    for row in result["results"]:
        if row.get("runner_exit_code") not in (0, None):
            raise SystemExit(f"official v4 runner failed for {row.get('card')}: {row}")
        if not Path(row["output_dir"], "score_report.json").is_file():
            raise SystemExit(f"missing score report for {row.get('card')}")
    print(json.dumps({"cards": result["cards"], "total": result["total"], "mode": result["mode"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
