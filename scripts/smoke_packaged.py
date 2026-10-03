"""Check the shipped executable loads all four frozen cards and runs its helpers."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    executable = ROOT / "dist" / ("GOSIMPractice.exe" if sys.platform == "win32" else "GOSIMPractice.app/Contents/MacOS/GOSIMPractice")
    output = ROOT / "run_output" / "packaged-smoke"
    subprocess.run([str(executable), "--smoke-test", str(output), "--smoke-test-seconds", "3"], check=True, timeout=180)
    batches = sorted(output.glob("attempt-*/batch_summary.json"))
    batch = json.loads(batches[-1].read_text(encoding="utf-8"))
    assert batch["completed_cards"] == 4
    for row in batch["results"]:
        assert row["runner_exit_code"] == 0, row
        assert row["termination_reason"] != "runner_error", row
        assert row["calibration_id"] == row["card_id"] + "-calibration-v1", row
        assert Path(row["output_dir"], "score_report.json").is_file(), row
    print("Packaged four-card protocol smoke passed; scores are not calibration evidence.")


if __name__ == "__main__":
    main()
