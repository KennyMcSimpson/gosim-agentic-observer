"""Exercise the participant JSONL v2 process contract without network access."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_SOURCE = ROOT / "agent"
RUNTIME_FILES = (
    "minimal_agent.py",
    "decision_graph.py",
    "model_factory.py",
    "protocol.py",
    "scoring_preview.py",
    "anomaly_detection.py",
    "state.py",
)


def public_messages() -> tuple[dict, dict, list[dict]]:
    """Build v2 envelopes around public data from the repository's scenario API.

    The checked-in practice scenarios still use the legacy snapshot schema. The
    fixture keeps their actual public catalogs and first snapshot, normalizes
    the public v3 weather view, and wraps it in the v2 participant contract.
    """
    sys.path.insert(0, str(ROOT))
    from challenge.challenge_workflow import ChallengeWorkflow

    workflow = ChallengeWorkflow(root=ROOT / "scenarios" / "dev-reference")
    initialize = {
        "protocol_version": "participant-agent-protocol-v2",
        "message_type": "initialize",
        "payload": workflow.initial_publication(),
    }
    snapshot = workflow.decision_snapshot(1)
    snapshot = copy.deepcopy(snapshot)
    # The legacy public fixture includes the simulator's efficiency column for
    # its old v2 contract. A v3 participant must see the efficiency-free view;
    # keep all other values sourced from the repository's public API.
    snapshot.get("current_site_weather", {}).pop("instrument_efficiency", None)
    for candidate in snapshot.get("candidate_tiles", []):
        candidate.get("effective_weather", {}).pop("instrument_efficiency", None)
    if any(
        "instrument_efficiency" in candidate.get("effective_weather", {})
        for candidate in snapshot.get("candidate_tiles", [])
    ) or "instrument_efficiency" in snapshot.get("current_site_weather", {}):
        raise AssertionError("v2 smoke fixture leaked instrument_efficiency")
    snapshot["schema_version"] = "decision-snapshot-v3"
    snapshot.setdefault("tile_last_finished", None)
    request = {
        "protocol_version": "participant-agent-protocol-v2",
        "message_type": "decision_request",
        "decision_sequence": 1,
        "payload": snapshot,
    }
    finish = {
        "protocol_version": "participant-agent-protocol-v2",
        "message_type": "finish",
        "payload": {
            "termination_reason": "survey_complete",
            "last_decision_sequence": 1,
            "grace_seconds": 30,
        },
    }
    return initialize, request, [initialize, request, finish]


def make_agent_copy(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for filename in RUNTIME_FILES:
        shutil.copy2(AGENT_SOURCE / filename, destination / filename)
    (destination / "my_strategy.py").write_text(
        """def choose_action(candidates, snapshot, memory):
    if len(candidates) > 1:
        return {**candidates[1], "reason": "smoke selected second legal candidate"}
    return candidates[0] if candidates else None
""",
        encoding="utf-8",
    )


def run_agent(agent_dir: Path, messages: list[dict]) -> subprocess.CompletedProcess[str]:
    # Keep host credentials and unrelated process settings out of the smoke.
    # The participant runner only needs a small deterministic environment.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        # The manifest targets the platform proxy. Without a key this still
        # exercises the deterministic configuration fallback.
        "MODEL_PROVIDER": "openai",
    }
    if os.name == "nt" and os.environ.get("SYSTEMROOT"):
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    input_text = "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in messages)
    return subprocess.run(
        [sys.executable, "-B", str(agent_dir / "minimal_agent.py")],
        cwd=agent_dir,
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=30,
    )


def assert_rejected(agent_dir: Path, name: str, messages: list[dict]) -> None:
    result = run_agent(agent_dir, messages)
    if result.returncode == 0:
        raise AssertionError(f"{name}: invalid protocol stream was accepted")
    if result.stdout.strip():
        raise AssertionError(f"{name}: rejected stream wrote a response to stdout")
    print(f"rejected {name}: exit={result.returncode}")


def check_model_fallback(initialize: dict, snapshot: dict) -> None:
    sys.path.insert(0, str(AGENT_SOURCE))
    from decision_graph import MinimalDecisionAgent
    import decision_graph

    class InvalidModel:
        def invoke(self, _messages):
            return type(
                "Response",
                (),
                {"content": '{"action":"observe","tile_id":"NOT-A-CANDIDATE","program":"DARK","request_id":""}'},
            )()

    original_strategy = decision_graph.my_strategy
    decision_graph.my_strategy = None
    try:
        agent = MinimalDecisionAgent(initialize["payload"], model=InvalidModel(), top_k=12)
        decision = agent.decide(copy.deepcopy(snapshot))
    finally:
        decision_graph.my_strategy = original_strategy
    if decision.get("decision_source") != "deterministic":
        raise AssertionError(f"invalid model candidate did not use deterministic fallback: {decision}")
    if decision.get("tile_id") == "NOT-A-CANDIDATE":
        raise AssertionError("invalid model candidate escaped validation")
    print(f"invalid model candidate fallback: {decision['action']} {decision.get('tile_id', '')}; source=deterministic")


def check_two_stage_model_budget(initialize: dict, snapshot: dict) -> None:
    """Verify planner+selector run only at the bounded night refresh trigger."""
    sys.path.insert(0, str(AGENT_SOURCE))
    from decision_graph import MinimalDecisionAgent
    from scoring_preview import preview_actions

    candidates = preview_actions(snapshot, initialize["payload"]["scoring_contract"])
    if len(candidates) < 2:
        raise AssertionError("two-stage smoke needs two legal candidates")
    selected = candidates[1]

    class TwoStageModel:
        def __init__(self):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            if self.calls % 2 == 1:
                return type("Response", (), {"content": '{"preferred_region_ids":[],"priority_request_ids":[],"reason":"smoke plan"}'})()
            return type(
                "Response",
                (),
                {"content": json.dumps({
                    "action": "observe",
                    "tile_id": selected.tile_id,
                    "program": selected.program,
                    "request_id": selected.request_id,
                    "reason": "smoke selector",
                })},
            )()

    model = TwoStageModel()
    agent = MinimalDecisionAgent(initialize["payload"], model=model, top_k=12, model_refresh_nights=7)
    first = agent.decide(copy.deepcopy(snapshot))
    if model.calls != 2 or first.get("decision_source") != "model":
        raise AssertionError(f"planner/selector did not run once: calls={model.calls}, decision={first}")
    agent.decide(copy.deepcopy(snapshot))
    if model.calls != 2:
        raise AssertionError(f"same-night model refresh exceeded budget: calls={model.calls}")
    later = copy.deepcopy(snapshot)
    later["cursor"] = {**later["cursor"], "night_id": "N20261012"}
    agent.decide(later)
    if model.calls != 4:
        raise AssertionError(f"seven-night model refresh was not re-armed: calls={model.calls}")
    print("two-stage model smoke: planner+selector=2 calls per refresh; same-night repeat=0; refresh=2")


def main() -> int:
    manifest = json.loads((ROOT / "observer.project.json").read_text(encoding="utf-8"))
    if manifest.get("protocol") != "jsonl-v2":
        raise AssertionError("root project manifest must declare jsonl-v2")

    initialize, request, messages = public_messages()
    snapshot = request["payload"]
    sys.path.insert(0, str(AGENT_SOURCE))
    from scoring_preview import preview_actions

    previews = preview_actions(snapshot, initialize["payload"]["scoring_contract"])
    if len(previews) < 2:
        raise AssertionError("public dev-reference fixture must expose at least two legal candidates")
    expected_choice = previews[1]

    with tempfile.TemporaryDirectory(prefix="gosim-protocol-smoke-") as temporary:
        agent_dir = Path(temporary) / "agent"
        make_agent_copy(agent_dir)
        valid = run_agent(agent_dir, messages)
        if valid.returncode != 0:
            raise RuntimeError(f"valid v2 stream exited {valid.returncode}: {valid.stderr[-2000:]}")
        responses = [json.loads(line) for line in valid.stdout.splitlines() if line.strip()]
        if len(responses) != 1:
            raise AssertionError(f"expected one response before finish, got {len(responses)}")
        response = responses[0]
        expected_tuple = (expected_choice.tile_id, expected_choice.program, expected_choice.request_id)
        actual_tuple = (response.get("tile_id"), response.get("program"), response.get("request_id"))
        if response.get("protocol_version") != "participant-agent-protocol-v2":
            raise AssertionError(f"wrong response protocol: {response}")
        if response.get("message_type") != "decision_response" or response.get("decision_sequence") != 1:
            raise AssertionError(f"wrong response envelope: {response}")
        if response.get("action") != "observe" or actual_tuple != expected_tuple:
            raise AssertionError(
                f"custom strategy candidate did not take effect: {response}; expected={expected_tuple}"
            )
        if response.get("decision_source") != "strategy":
            raise AssertionError(f"custom strategy source was not preserved: {response}")
        if "finished: termination_reason=survey_complete decisions=1 last_decision_sequence=1" not in valid.stderr:
            raise AssertionError(f"finish message was not consumed cleanly: {valid.stderr}")
        print(f"v2 initialize/decision/finish: exit=0; selected second legal candidate {actual_tuple}")
        print("finish emitted no response; one decision was counted")

        assert_rejected(
            agent_dir,
            "unsupported protocol envelope",
            [{**initialize, "protocol_version": "participant-agent-protocol-v99"}],
        )
        assert_rejected(
            agent_dir,
            "non-object envelope payload",
            [{**initialize, "payload": []}],
        )
        assert_rejected(
            agent_dir,
            "unsupported message type",
            [{**initialize, "message_type": "unknown"}],
        )
        assert_rejected(
            agent_dir,
            "initialize schema",
            [{**initialize, "payload": {**initialize["payload"], "schema_version": "initial-publication-v99"}}],
        )
        assert_rejected(agent_dir, "decision before initialize", [request])
        assert_rejected(
            agent_dir,
            "decision snapshot schema",
            [initialize, {**request, "payload": {**snapshot, "schema_version": "decision-snapshot-v99"}}],
        )
        assert_rejected(
            agent_dir,
            "decision sequence mismatch",
            [initialize, {**request, "decision_sequence": 2}],
        )

    check_model_fallback(initialize, snapshot)
    check_two_stage_model_budget(initialize, snapshot)
    print("protocol smoke passed; fixture source=scenarios/dev-reference via ChallengeWorkflow public API")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
