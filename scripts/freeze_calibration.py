"""Freeze one completed 900-second calibration candidate, including its evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(card: str, attempt: Path, profile: dict | None = None) -> Path:
    report = json.loads((attempt / card / "score_report.json").read_text(encoding="utf-8"))
    workflow = json.loads((attempt / card / "workflow_result.json").read_text(encoding="utf-8"))
    if workflow.get("global_wallclock_seconds") != 900 or report["termination"]["reason"] != "survey_complete":
        raise ValueError("only complete survey runs with a 900-second budget can be frozen")
    source = attempt / "generated-cards" / f"{card}-calibration"
    destination = ROOT / "simulator" / "calibration-v1" / card
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    hashes = {}
    for folder in ("config", "public", "truth"):
        for path in sorted((source / folder).rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(source).as_posix()
            hashes[relative] = sha256(path)
            if relative not in {"public/targets.csv", "public/footprint.csv", "public/v4_night_calendar.csv"}:
                output = destination / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, output)
    original = json.loads((source / "simulation_manifest.json").read_text(encoding="utf-8"))
    manifest = {
        **original,
        "schema_version": "synthetic-frozen-card-v1",
        "calibration_id": f"{card}-calibration-v1",
        "frozen_date": "2026-10-04",
        "source_attempt": attempt.relative_to(ROOT).as_posix(),
        "sha256": hashes,
        "profile": profile,
        "profile_provenance": "recorded candidate" if profile else "historical exact truth files; original parameter list unavailable",
        "validation": {
            "wallclock_budget_seconds": 900,
            "termination_reason": report["termination"]["reason"],
            "total": report["total"],
            "components": report["components"],
            "counts": report["counts"],
        },
    }
    (destination / "simulation_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (destination / "baseline_score_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{card}: {report['total']:.6f} -> {destination}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("card", choices=("alpha", "beta", "gamma", "delta"))
    parser.add_argument("attempt", type=Path)
    parser.add_argument("--profile", type=json.loads)
    args = parser.parse_args()
    freeze(args.card, args.attempt.resolve(), args.profile)


if __name__ == "__main__":
    main()
