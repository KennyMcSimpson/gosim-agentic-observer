"""Local JSONL runner for the isolated Agent Observer v4 harness."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Mapping

from .v4_protocol import (
    PROTOCOL_VERSION,
    V4ProtocolError,
    decision_response,
    parse_platform_message,
    validate_decision_response,
)
from .v4_scorer import V4Card, V4Scorer


class V4AgentProcess:
    def __init__(self, command: list[str], *, cwd: Path, env: Mapping[str, str], log_path: Path):
        self.process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=dict(env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log_path.open("w", encoding="utf-8"),
            text=True,
            bufsize=1,
        )
        self.lines: queue.Queue[str | BaseException | None] = queue.Queue()
        assert self.process.stdout is not None
        self.reader = threading.Thread(target=self._read_stdout, daemon=True)
        self.reader.start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                self.lines.put(line)
        except BaseException as exc:
            self.lines.put(exc)
        finally:
            self.lines.put(None)

    def send(self, message: Mapping[str, object]) -> None:
        if self.process.stdin is None or self.process.poll() is not None:
            raise RuntimeError("v4 agent is not running")
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def receive(self, timeout: float) -> dict:
        try:
            item = self.lines.get(timeout=max(0.01, timeout))
        except queue.Empty as exc:
            raise TimeoutError("v4 agent did not answer before the local wall-clock deadline") from exc
        if item is None:
            raise RuntimeError(f"v4 agent exited with code {self.process.poll()}")
        if isinstance(item, BaseException):
            raise RuntimeError("v4 stdout reader failed") from item
        try:
            value = json.loads(item)
        except json.JSONDecodeError as exc:
            raise V4ProtocolError("v4 agent wrote non-JSON stdout") from exc
        if not isinstance(value, dict):
            raise V4ProtocolError("v4 agent response must be a JSON object")
        return value

    def finish(self, termination_reason: str, sequence: int) -> None:
        if self.process.poll() is not None:
            return
        if self.process.stdin is not None:
            try:
                self.send({
                    "protocol_version": PROTOCOL_VERSION,
                    "message_type": "finish",
                    "payload": {
                        "termination_reason": termination_reason,
                        "last_decision_sequence": sequence,
                        "grace_seconds": 30,
                    },
                })
                self.process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        try:
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)


def _entry(agent: Path) -> tuple[Path, Path]:
    agent = agent.resolve()
    if agent.is_file():
        return agent, agent.parent
    for name in ("baseline_agent.py", "agent.py", "main.py", "v4_minimal_agent.py"):
        candidate = agent / name
        if candidate.is_file():
            return candidate, agent
    raise SystemExit(f"no v4 agent entry in {agent}")


def _envelope(message_type: str, payload: Mapping[str, object], sequence: int | None = None) -> dict[str, object]:
    result: dict[str, object] = {"protocol_version": PROTOCOL_VERSION, "message_type": message_type}
    if sequence is not None:
        result["decision_sequence"] = sequence
    result["payload"] = dict(payload)
    return result


def run_v4(card_path: Path, agent: Path, out_dir: Path, wallclock_seconds: float = 900.0) -> dict[str, object]:
    card = V4Card(card_path)
    scorer = V4Scorer(card)
    entry, agent_dir = _entry(agent)
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    initial_path = out_dir / "initial_publication.json"
    decisions_path = out_dir / "decisions.jsonl"
    result_path = out_dir / "workflow_result.json"
    score_path = out_dir / "score_report.json"
    initial_path.write_text(json.dumps(card.initial_publication(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    decisions_path.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "PYTHONUNBUFFERED": "1",
        "PARTICIPANT_PROTOCOL": PROTOCOL_VERSION,
        "SAC_SCENARIO": str(card_path.resolve()),
        "SAC_WALLCLOCK_SECONDS": str(int(wallclock_seconds)),
    })
    kit_root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = kit_root + os.pathsep + env.get("PYTHONPATH", "")
    process = V4AgentProcess([sys.executable, "-u", str(entry)], cwd=agent_dir, env=env, log_path=out_dir / "agent.log")
    started = time.monotonic()
    sequence = 0
    termination_reason = "agent_error"
    committed = []
    try:
        process.send(_envelope("initialize", card.initial_publication()))
        while True:
            remaining = wallclock_seconds - (time.monotonic() - started)
            if remaining <= 0:
                termination_reason = "wallclock_timeout"
                break
            snapshot = scorer.snapshot(sequence, remaining)
            process.send(_envelope("decision_request", snapshot, sequence))
            raw = process.receive(remaining)
            decision = validate_decision_response(sequence, raw)
            committed.append({"decision_sequence": sequence, "decision": decision})
            with decisions_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(decision_response(sequence, decision), sort_keys=True) + "\n")
            if decision["action"] == "finish":
                scorer.apply(decision)
                termination_reason = "agent_finish"
                break
            scorer.apply(decision)
            if scorer.now_utc >= card.last_utc:
                termination_reason = "survey_complete"
                break
            sequence += 1
    except (V4ProtocolError, TimeoutError, RuntimeError, OSError) as exc:
        termination_reason = "agent_error"
        (out_dir / "runner_error.txt").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
    finally:
        if termination_reason != "wallclock_timeout":
            process.finish(termination_reason, sequence)
        else:
            process.stop()
    score = scorer.finalize(termination_reason)
    workflow = {
        "schema_version": "workflow-result-v4",
        "termination_reason": termination_reason,
        "committed_action_count": len(committed),
        "accounted_wallclock_seconds": round(time.monotonic() - started, 6),
        "global_wallclock_seconds": wallclock_seconds,
        "initial_publication": str(initial_path),
        "score_report": str(score_path),
    }
    result_path.write_text(json.dumps(workflow, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    score_path.write_text(json.dumps(score, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"workflow": workflow, "score": score, "paths": {"score_report": str(score_path), "agent_log": str(out_dir / "agent.log")}}
