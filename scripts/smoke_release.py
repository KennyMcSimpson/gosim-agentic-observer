"""Run bundled baseline against both public scenarios in the packaged app."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {"dev-fortnight": 6512.721299, "dev-reference": 12287.478365}


def main() -> int:
    if sys.platform == "win32":
        app = ROOT / "dist" / "GOSIMPractice.exe"
    elif sys.platform == "darwin":
        app = ROOT / "dist" / "GOSIMPractice.app" / "Contents" / "MacOS" / "GOSIMPractice"
    else:
        raise RuntimeError("This release workflow builds Windows and macOS only")
    output_root = ROOT / "build" / "smoke"
    output_root.mkdir(parents=True, exist_ok=True)
    process = subprocess.run([str(app), "--smoke-test", str(output_root)], timeout=300, capture_output=True, text=True)
    if process.returncode:
        raise RuntimeError(f"Packaged app exited {process.returncode}: {process.stderr[-2000:]}")
    result_path = output_root / "smoke_result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    actual = {item["scenario"]: item for item in result["results"]}
    if set(actual) != set(EXPECTED):
        raise AssertionError(f"Wrong scenarios: {sorted(actual)}")
    for name, expected in EXPECTED.items():
        item = actual[name]
        if item["exit_code"] != 0 or item["summary"]["termination_reason"] != "survey_complete":
            raise AssertionError(f"{name}: incomplete: {item}")
        total = float(item["summary"]["total"])
        if not math.isclose(total, expected, rel_tol=0, abs_tol=0.000001):
            raise AssertionError(f"{name}: expected {expected}, got {total}")
        report = json.loads((Path(item["output_dir"]) / "score_report.json").read_text(encoding="utf-8"))
        if not math.isclose(total, float(report["score"]["total"]), rel_tol=0, abs_tol=0.000001):
            raise AssertionError(f"{name}: summary and score report differ")
        print(f"{name}: {total:.6f}; {item['summary']['termination_reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
