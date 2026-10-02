"""Run the deterministic v4 demo card through the local v4 workflow."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from challenge.v4_workflow import run_v4


CARD_ROOT = ROOT / "scenarios" / "v4-demo"
AGENT_PATH = ROOT / "agent" / "v4_minimal_agent.py"


def main() -> int:
    if not CARD_ROOT.is_dir():
        print(f"v4 smoke card not found: {CARD_ROOT}", file=sys.stderr)
        return 1
    if not AGENT_PATH.is_file():
        print(f"v4 smoke agent not found: {AGENT_PATH}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="gosim-v4-smoke-") as temporary:
        output_root = Path(temporary) / "run"
        try:
            result = run_v4(
                CARD_ROOT,
                AGENT_PATH,
                output_root,
                wallclock_seconds=10,
            )
        except Exception as exc:
            print(f"v4 smoke crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

        workflow = result.get("workflow", {})
        termination_reason = workflow.get("termination_reason")
        if termination_reason == "agent_error":
            error_path = output_root / "runner_error.txt"
            detail = error_path.read_text(encoding="utf-8").strip() if error_path.is_file() else "unknown agent error"
            print(f"v4 smoke agent_error: {detail}", file=sys.stderr)
            return 2
        if termination_reason != "agent_finish":
            print(
                f"v4 smoke did not finish cleanly: {termination_reason!r}",
                file=sys.stderr,
            )
            return 1

        score = result.get("score", {})
        score_values = score.get("score", {})
        completion = score.get("completion", {})
        required_missing = completion.get("required_missing", [])
        requests = score.get("requests", [])
        if workflow.get("committed_action_count") != 5:
            print(
                "v4 smoke expected five committed actions: "
                f"{workflow.get('committed_action_count')}",
                file=sys.stderr,
            )
            return 1
        if completion.get("targets_observed") != 4:
            print(
                "v4 smoke expected four observed targets: "
                f"{completion.get('targets_observed')}",
                file=sys.stderr,
            )
            return 1
        if required_missing:
            print(f"v4 smoke missing required targets: {required_missing}", file=sys.stderr)
            return 1
        if not requests or not all(request.get("completed") for request in requests):
            print(f"v4 smoke request completion failed: {requests}", file=sys.stderr)
            return 1

        print(
            "v4 smoke passed: "
            f"actions={workflow['committed_action_count']} "
            f"targets={completion['targets_observed']} "
            f"score={score_values.get('total')} "
            f"termination={termination_reason}"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
