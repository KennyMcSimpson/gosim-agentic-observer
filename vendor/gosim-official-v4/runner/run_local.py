#!/usr/bin/env python3
"""Run your agent against a public local practice card using the platform's own v4 engine
and print the score breakdown.

    python3 run_local.py --card L1 --agent "python3 agent.py"
    python3 run_local.py --card L2 --agent "node dist/index.js" --agent-cwd ../ts-agent
    python3 run_local.py --card L3 --agent "./target/release/rust-agent" --agent-cwd ../rust-agent/target/release

This file is the ONLY new code in runner/. Everything under runner/challenge/ and
runner/project_platform/ is an unmodified, byte-identical copy of the files the cloud
platform actually runs for a v4 project submission (see ENGINE_MANIFEST.json / verify_engine.py);
this script calls them the same way project_platform.trusted_engine.run_v4_session does:
  challenge.v4_workflow.V4Workflow(card_dir).run(decide, output_dir, wallclock_seconds=..., initialize=...)
over a project_platform.transport.JsonlTransport talking to your agent subprocess, with the
same message flow, the same wall-clock enforcement and the same scoring call. The only things
intentionally not reproduced are the parts that only make sense with a remote session server
(model-proxy quotas, a second externally-imposed deadline) -- there is no server in a local run.

What happens (same engine the platform uses):
  * your agent starts as its own process, speaking participant-agent-protocol-v4 (one JSON
    object per line on stdin/stdout; stderr goes to <out>/agent.log);
  * it gets one `initialize`, then `decision_request` after `decision_request`, and answers each one;
  * one global wall clock (default: the card's own limit, capped at 900s) starts at the first request;
  * at the end it gets one `finish` message, stdin is closed, and it has 30 grace seconds to exit.

--agent takes a full shell command (quoted), not just a Python script, so any language works:
python, node, a compiled binary, a wrapper shell script, etc. It is split with shlex and run directly
(no shell), with --agent-cwd (default: current directory) as its working directory.

Environment: the agent gets a clean environment (PATH, HOME/TMPDIR in <out>/scratch) plus
SAC_SCENARIO/SAC_WALLCLOCK_SECONDS/PARTICIPANT_PROTOCOL, then KEY=VALUE lines from <agent-cwd>/.env
(put OPENAI_BASE_URL / OPENAI_API_KEY there to try an LLM-backed agent locally; the real platform
injects those for you).

本地分数用来调试，正式成绩以平台为准。
Local scores are for debugging; official results come from the platform.

Outputs in --out: decisions.csv, observations.csv, messages.jsonl, score_report.json, workflow_result.json,
actions.jsonl, agent.log. The last stdout line is a JSON summary. Exit code 0 = the run ended normally, 2 = agent error.
Standard library only (Python 3.9+).
"""
from __future__ import annotations

import sys

if sys.version_info < (3, 9):
    sys.stderr.write("run_local: Python 3.9 or newer is required\n")
    sys.exit(3)

import argparse
import json
import os
import re
import shlex
import time
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent
CARDS_ROOT = KIT_ROOT.parent / "local-cards"
if str(KIT_ROOT) not in sys.path:
    sys.path.insert(0, str(KIT_ROOT))

from challenge.v4_workflow import PROTOCOL_VERSION, V4Workflow, V4_SCENARIO_PATH  # noqa: E402
from project_platform.transport import JsonlTransport, ExecutionError, GlobalDeadlineExpired  # noqa: E402,F401

SAFE_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
PROTECTED_KEYS = {"PATH", "HOME", "TMPDIR", "LD_PRELOAD", "PYTHONPATH", "PYTHONSTARTUP"}
DEFAULT_WALLCLOCK = 900.0


def scenario_path(card_dir: Path) -> Path:
    return Path(card_dir) / V4_SCENARIO_PATH


def load_card(card_dir: Path) -> dict:
    """Public card metadata (task_card) from config/v4_scenario.json -- same shape the
    platform's ColocatedProvider publishes as part of `initialize`."""
    config = json.loads(scenario_path(card_dir).read_text(encoding="utf-8"))
    card = dict(config.get("task_card") or {"card_id": str(config["name"])})
    card.setdefault("scenario_slug", str(config["name"]))
    return card


def resolve_card(card_arg: str) -> Path:
    direct = Path(card_arg)
    if scenario_path(direct).is_file():
        return direct.resolve()
    by_name = CARDS_ROOT / card_arg
    if scenario_path(by_name).is_file():
        return by_name.resolve()
    raise SystemExit(f"card not found: {card_arg!r} (tried {direct} and {by_name})")


def load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if SAFE_ENV_KEY.match(key):
            env[key] = value
    return env


def agent_environment(agent_cwd: Path, scratch: Path, card: dict, wallclock: float, inherit: bool) -> tuple[dict, list[str]]:
    base = dict(os.environ) if inherit else {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}
    if sys.platform == "win32" and not inherit:
        base["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "C:\\Windows")
    env = {**base, "HOME": str(scratch), "TMPDIR": str(scratch), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
           "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
           "PARTICIPANT_PROTOCOL": PROTOCOL_VERSION, "SAC_SCENARIO": card["scenario_slug"],
           "SAC_WALLCLOCK_SECONDS": str(int(wallclock)), "SAC_LOCAL_RUNNER": "1"}
    dotenv = load_dotenv(agent_cwd / ".env")
    for key, value in dotenv.items():
        if key not in PROTECTED_KEYS:
            env[key] = value
    return env, sorted(dotenv)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--card", required=True, help="card name under local-cards/ (e.g. L1) or a path to a card folder")
    parser.add_argument("--agent", required=True, help='full command to launch your agent, e.g. "python3 agent.py" or '
                                                        '"node dist/index.js" or "./target/release/rust-agent-v4"')
    parser.add_argument("--agent-cwd", type=Path, default=Path.cwd(), help="working directory for the agent command "
                                                                           "(default: current directory); .env is read from here")
    parser.add_argument("--wallclock", type=float, default=DEFAULT_WALLCLOCK,
                        help=f"global wall clock in seconds (default {DEFAULT_WALLCLOCK:g}); as on the platform the "
                             "effective budget is min(this, the card's limit, 900)")
    parser.add_argument("--out", type=Path, default=KIT_ROOT / "run_output", help="output folder (default: run_output)")
    parser.add_argument("--init-timeout", type=float, default=30.0, help="seconds for the agent to read `initialize`")
    parser.add_argument("--grace", type=float, default=30.0, help="seconds the agent may take to exit after `finish`")
    parser.add_argument("--inherit-env", action="store_true", help="pass your whole shell environment to the agent")
    parser.add_argument("--show-agent-stderr", action="store_true", help="print the agent's stderr here instead of agent.log")
    parser.add_argument("--quiet", action="store_true", help="print only the final JSON summary")
    args = parser.parse_args(argv)

    card_dir = resolve_card(args.card)
    if args.wallclock <= 0:
        raise SystemExit("--wallclock must be positive")
    card = load_card(card_dir)
    workflow = V4Workflow(card_dir)
    budget = workflow.wallclock_budget(args.wallclock)  # min(this, card limit, 900) -- same call the platform makes
    command = shlex.split(args.agent)
    if not command:
        raise SystemExit("--agent must not be empty")
    agent_cwd = args.agent_cwd.resolve()
    if not agent_cwd.is_dir():
        raise SystemExit(f"--agent-cwd is not a directory: {agent_cwd}")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    scratch = out / "scratch"
    scratch.mkdir(exist_ok=True)
    env, dotenv_keys = agent_environment(agent_cwd, scratch, card, budget, args.inherit_env)
    say = (lambda text: None) if args.quiet else (lambda text: print(text, file=sys.stderr, flush=True))
    say(f"[run_local] card={card['card_id']} agent={args.agent!r} cwd={agent_cwd} wallclock={budget:g}s dotenv_keys={dotenv_keys}")

    transport = JsonlTransport(command, cwd=agent_cwd, environment=env, initialization_seconds=args.init_timeout)
    transport.protocol_version = PROTOCOL_VERSION  # same line project_platform.trusted_engine.run_v4_session runs

    def decide(message, deadline):
        transport.send(message, deadline)
        return transport.receive(deadline)

    initialization_error = [None]

    def initialize(payload):
        try:
            transport.publish_initial(payload)
        except Exception as error:
            initialization_error[0] = error
            raise

    started = time.monotonic()
    startup_error = None
    result = None
    try:
        result = workflow.run(decide, out, wallclock_seconds=budget, initialize=initialize)
        result.pop("initialization_error", None)
        if initialization_error[0] is not None:
            # Same as the platform: a failed startup fails the run rather than publishing a score.
            startup_error = initialization_error[0]
        else:
            # The score is already final and on disk; this is a best-effort courtesy message only.
            try:
                transport.finish(result["termination_reason"], result["last_decision_sequence"], grace_seconds=args.grace,
                                 extra=V4Workflow.finish_payload(result))
            except Exception:
                pass
    finally:
        transport.close(force=True)
        try:
            (out / "agent.log").write_text(transport.log, encoding="utf-8")
        except OSError:
            pass
        if args.show_agent_stderr:
            sys.stderr.write(transport.log)

    if startup_error is not None:
        say(f"[run_local] agent failed to initialize: {type(startup_error).__name__}: {startup_error}")
        print(json.dumps({"card": card["card_id"], "termination_reason": "agent_error",
                          "error": f"initialize: {type(startup_error).__name__}: {startup_error}"},
                         indent=2, sort_keys=True))
        return 2

    report = result["score_report"]
    summary = {
        "card": card["card_id"],
        "termination_reason": result["termination_reason"],
        "total": report["total"],
        "sum_best_scores": report["components"]["sum_best_scores"],
        "required_penalty": report["components"]["required_penalty"],
        "uniformity_penalty": report["components"]["uniformity_penalty"],
        "report_settlement": report["components"]["report_settlement"],
        "observation_request_reward": report["components"]["observation_request_reward"],
        "targets_observed": report["counts"]["targets_observed"],
        "required_missing": report["counts"]["required_missing"],
        "observe_actions": report["counts"]["observe_actions"],
        "observation_requests_issued": report["counts"]["observation_requests_issued"],
        "observation_requests_completed": report["counts"]["observation_requests_completed"],
        "decision_requests": result["decision_requests"],
        "termination_detail": result["termination_detail"],
        "wall_seconds": result["accounted_wallclock_seconds"],
        "runner_seconds": round(time.monotonic() - started, 3),
        "note": "Local scores are for debugging; official results come from the platform. "
                "本地分数用来调试，正式成绩以平台为准。",
        "outputs": {name: str(out / name) for name in
                    ("decisions.csv", "observations.csv", "score_report.json", "workflow_result.json", "agent.log")},
    }
    if result["termination_reason"] == "agent_error" and not args.quiet:
        say(f"[run_local] agent error: {result['termination_detail']}")
        for line in (out / "agent.log").read_text(encoding="utf-8", errors="replace").splitlines()[-15:]:
            say("    " + line)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 2 if result["termination_reason"] == "agent_error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
