"""Run public complete-project practice scenarios entirely on this computer."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import local_runner

SCENARIOS = ("dev-fortnight", "dev-reference")
PRACTICE_WALLCLOCK_SECONDS = 18000
EventHandler = Callable[[dict], None]


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def available_scenarios() -> list[str]:
    root = resource_root() / "scenarios"
    return [name for name in SCENARIOS if (root / name / "config" / "workflow_config.json").is_file()]


def default_agent_path() -> Path:
    return resource_root() / "agent" / "minimal_agent.py"


def default_output_root() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    return base / "GOSIM Local Practice" / "runs"


def _agent_python() -> str:
    if not getattr(sys, "frozen", False):
        return sys.executable
    worker = resource_root() / ("PracticeAgentHost.exe" if sys.platform == "win32" else "PracticeAgentHost")
    if not worker.is_file():
        raise FileNotFoundError(f"Bundled agent host is missing: {worker}")
    return str(worker)


def run_practice(
    agent: Path,
    scenarios: list[str],
    output_root: Path,
    on_event: EventHandler,
    python_executable: str | None = None,
) -> dict:
    """Run each selected public scenario once and report progress to the GUI."""
    requested = list(dict.fromkeys(scenarios))
    if not requested or any(name not in SCENARIOS for name in requested):
        raise ValueError("Select dev-fortnight and/or dev-reference")
    missing = [name for name in requested if name not in available_scenarios()]
    if missing:
        raise FileNotFoundError(f"Bundled scenario missing: {', '.join(missing)}")
    entry = local_runner.find_entry(Path(agent).expanduser())
    interpreter = python_executable or _agent_python()
    if not Path(interpreter).is_file():
        raise FileNotFoundError(f"Python / agent host not found: {interpreter}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    session = Path(output_root).expanduser().resolve() / f"practice-{stamp}-{uuid.uuid4().hex[:8]}"
    session.mkdir(parents=True, exist_ok=False)
    on_event({"type": "start", "output_dir": str(session), "scenarios": requested})
    results = []
    for name in requested:
        output_dir = session / name
        on_event({"type": "scenario_start", "scenario": name, "output_dir": str(output_dir)})
        stdout, stderr = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = local_runner.main([
                    "--scenario", str(resource_root() / "scenarios" / name),
                    "--agent", str(entry),
                    "--wallclock", str(PRACTICE_WALLCLOCK_SECONDS),
                    "--python", str(interpreter),
                    "--out", str(output_dir),
                ])
            summary = json.loads(stdout.getvalue())
            result = {"scenario": name, "exit_code": exit_code, "summary": summary, "output_dir": str(output_dir)}
        except Exception as exc:
            result = {"scenario": name, "exit_code": 1, "error": f"{type(exc).__name__}: {exc}", "output_dir": str(output_dir)}
            stderr.write(traceback.format_exc())
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "runner.log").write_text(stderr.getvalue(), encoding="utf-8")
        results.append(result)
        on_event({"type": "scenario_done", **result})
    record = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "agent": str(entry),
        "scenarios": requested,
        "results": results,
        "note": "Local public-scenario rehearsal; not an official cloud submission or hidden-scenario score.",
    }
    (session / "practice_result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    on_event({"type": "done", "output_dir": str(session), "results": results})
    return record
