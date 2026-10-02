"""Exercise the exact complete-project entry declared by observer.project.json."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOTAL = 6512.721299


def read_manifest(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path} is not an object")
    return value


def validate_manifests() -> tuple[dict, dict]:
    root = read_manifest(ROOT / "observer.project.json")
    agent = read_manifest(ROOT / "agent" / "observer.project.json")
    for label, manifest in (("root", root), ("agent", agent)):
        if manifest.get("schema_version") != "observer-project-v1":
            raise AssertionError(f"{label} manifest has the wrong schema")
        if manifest.get("protocol") != "jsonl-v2":
            raise AssertionError(f"{label} manifest must declare jsonl-v2")
        if not isinstance(manifest.get("build"), list):
            raise AssertionError(f"{label} manifest build must be an array")
        if manifest.get("environment", {}).get("MODEL_PROVIDER") != "openai":
            raise AssertionError(f"{label} manifest must select the platform OpenAI-compatible proxy")
        if manifest.get("environment", {}).get("PYTHONPATH") != ".deps":
            raise AssertionError(f"{label} manifest must expose build dependencies from .deps")
        build = manifest.get("build")
        if len(build) != 1 or "--target" not in build[0] or ".deps" not in build[0]:
            raise AssertionError(f"{label} manifest must install agent dependencies into .deps")
    if root["run"] != ["python3", "-u", "agent/minimal_agent.py"]:
        raise AssertionError("root manifest run path changed")
    if agent["run"] != ["python3", "-u", "minimal_agent.py"]:
        raise AssertionError("agent manifest run path changed")
    return root, agent


def main() -> int:
    root, _agent = validate_manifests()
    # The two public practice scenarios currently use the legacy v1 wire
    # contract. Validate the v2 envelopes declared by the complete-project
    # manifest as a separate protocol check so the smoke output stays honest.
    sys.path.insert(0, str(ROOT / "agent"))
    from protocol import decision_response, parse_platform_message

    parse_platform_message({
        "protocol_version": "participant-agent-protocol-v2",
        "message_type": "initialize",
        "payload": {"schema_version": "initial-publication-v2"},
    })
    parse_platform_message({
        "protocol_version": "participant-agent-protocol-v2",
        "message_type": "finish",
        "payload": {"termination_reason": "survey_complete"},
    })
    response = decision_response(1, {"action": "wait"})
    if response["protocol_version"] != "participant-agent-protocol-v2":
        raise AssertionError("v2 response did not preserve the declared protocol")
    output = ROOT / "build" / "project-smoke"
    command = [
        sys.executable,
        str(ROOT / "local_runner.py"),
        "--scenario",
        str(ROOT / "scenarios" / "dev-fortnight"),
        "--agent",
        str(ROOT / root["run"][2]),
        "--wallclock",
        "18000",
        "--out",
        str(output),
    ]
    # The normal smoke mirrors the platform's scrubbed deterministic process.
    # CI can opt into the installed participant dependency path without making
    # local runs inherit a developer's environment or API credentials.
    if os.environ.get("SMOKE_INHERIT_ENV") == "1":
        command.append("--inherit-env")
    process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=300)
    if process.returncode:
        raise RuntimeError(f"complete-project entry exited {process.returncode}: {process.stderr[-2000:]}")
    result = json.loads((output / "workflow_result.json").read_text(encoding="utf-8"))
    if result.get("termination_reason") != "survey_complete":
        raise AssertionError(f"unexpected termination: {result.get('termination_reason')}")
    report = json.loads((output / "score_report.json").read_text(encoding="utf-8"))
    total = float(report["score"]["total"])
    if not math.isclose(total, EXPECTED_TOTAL, rel_tol=0, abs_tol=0.000001):
        raise AssertionError(f"expected {EXPECTED_TOTAL}, got {total}")
    print(f"complete-project entry: {total:.6f}; survey_complete; public-v1 path + v2 envelope")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
