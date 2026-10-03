"""Verify full replay receipts against the frozen four-card inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"alpha": 3243.83, "beta": 4558.45, "gamma": 3893.13, "delta": 2975.56}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_roots", nargs=4, type=Path)
    args = parser.parse_args()
    rows = {}
    for card, run_root in zip(TARGETS, args.run_roots):
        reports = list(run_root.glob(f"attempt-*/{card}/score_report.json"))
        if len(reports) != 1:
            raise ValueError(f"expected one {card} full replay, got {len(reports)}")
        output = reports[0].parent
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        receipt = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
        frozen = json.loads((ROOT / "simulator/calibration-v1" / card / "simulation_manifest.json").read_text(encoding="utf-8"))
        assert report["termination"]["reason"] == "survey_complete", card
        assert receipt["wallclock_budget_seconds"] == 900, card
        assert receipt["model_mode"] == "deterministic", card
        assert receipt["card_sha256"] == frozen["sha256"], card
        current_agent = {name: hashlib.sha256((ROOT / "agent" / name).read_bytes()).hexdigest() for name in receipt["agent_sha256"]}
        assert receipt["agent_sha256"] == current_agent, card
        assert report["total"] == frozen["validation"]["total"], card
        assert report["counts"] == frozen["validation"]["counts"], card
        assert abs(report["total"] - TARGETS[card]) < 100, card
        rows[card] = {"calibration_id": frozen["calibration_id"], "target": TARGETS[card], "total": report["total"],
                      "residual": round(report["total"] - TARGETS[card], 6), "budget_seconds": 900,
                      "termination": "survey_complete", "card_input_sha256": hashlib.sha256(json.dumps(receipt["card_sha256"], sort_keys=True).encode()).hexdigest(),
                      "agent_sha256": receipt["agent_sha256"], "engine_manifest_sha256": receipt["engine_manifest_sha256"],
                      "counts": report["counts"], "components": report["components"]}
    assert len({json.dumps(row["agent_sha256"], sort_keys=True) for row in rows.values()}) == 1
    result = {"schema_version": "frozen-calibration-verification-v1", "verified_date": "2026-10-04",
              "model_mode": "deterministic", "official_truth": False, "cards": rows,
              "mean_local_score": sum(row["total"] for row in rows.values()) / 4}
    output = ROOT / "simulator/calibration-v1/validation_report.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({card: {key: row[key] for key in ("total", "residual")} for card, row in rows.items()}, indent=2))


if __name__ == "__main__":
    main()
