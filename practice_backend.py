"""Run the organizer's fixed public v4 practice cards in the local app."""
from __future__ import annotations

import json
import os
import csv
import random
import shlex
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Callable, Dict, List, Optional

EventHandler = Callable[[dict], None]
ALL_CARDS = ("L1", "L2", "L3", "L4")
CARD_LABELS = {
    "L1": "L1 · 简单",
    "L2": "L2 · 中等",
    "L3": "L3 · 中等偏难",
    "L4": "L4 · 困难",
}
DAILY_ATTEMPT_LIMIT = 5
VENDOR_RELATIVE = Path("vendor") / "gosim-official-v4"


def available_modes() -> List[dict]:
    return [
        {"mode": "official-fixed", "label": "官方固定卡", "description": "官方公开 L1-L4 与固定 truth"},
        {"mode": "stress-seed", "label": "Seed 压力测试", "description": "基于官方卡的本地天气 truth 扰动，不代表官方成绩"},
    ]


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def vendor_root() -> Path:
    return resource_root() / VENDOR_RELATIVE


def available_cards() -> List[dict]:
    return [
        {"card_id": card_id, "label": CARD_LABELS[card_id], "source": "official"}
        for card_id in ALL_CARDS
    ]


def default_agent_path() -> Path:
    return resource_root() / "agent" / "baseline_agent.py"


def default_output_root() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    return base / "GOSIM v4 Practice" / "runs"


def _agent_python() -> str:
    if not getattr(sys, "frozen", False):
        return sys.executable
    helper = resource_root() / ("PracticeAgentHost.exe" if sys.platform == "win32" else "PracticeAgentHost")
    if not helper.is_file():
        raise FileNotFoundError("bundled v4 agent host is missing: %s" % helper)
    return str(helper)


def _runner_prefix() -> List[str]:
    if getattr(sys, "frozen", False):
        helper = resource_root() / ("PracticeRunnerHost.exe" if sys.platform == "win32" else "PracticeRunnerHost")
        if not helper.is_file():
            raise FileNotFoundError("bundled official v4 runner is missing: %s" % helper)
        return [str(helper)]
    # Route development runs through the same Windows pipe adapter used by the
    # frozen runner helper. The official runner's select() transport cannot
    # poll anonymous subprocess pipes on Windows.
    script = resource_root() / "runner_worker.py"
    if not script.is_file():
        raise FileNotFoundError("official v4 runner adapter is missing: %s" % script)
    return [sys.executable, str(script)]


def _read_quota(path: Path) -> dict:
    if not path.is_file():
        return {"utc_date": "", "attempts": 0}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    except (OSError, ValueError):
        pass
    return {"utc_date": "", "attempts": 0}


def quota_status(output_root: Path) -> dict:
    path = Path(output_root).expanduser().resolve() / ".quota.json"
    today = datetime.now(timezone.utc).date().isoformat()
    value = _read_quota(path)
    if value.get("utc_date") != today:
        return {"utc_date": today, "attempts": 0, "limit": DAILY_ATTEMPT_LIMIT, "path": str(path)}
    return {
        "utc_date": today,
        "attempts": int(value.get("attempts", 0)),
        "limit": DAILY_ATTEMPT_LIMIT,
        "path": str(path),
    }


def _consume_quota(output_root: Path) -> dict:
    status = quota_status(output_root)
    if status["attempts"] >= DAILY_ATTEMPT_LIMIT:
        raise RuntimeError("今日本地模拟额度已用完（5 次）；可关闭额度模拟或等待 UTC 日期重置。")
    path = Path(status["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    updated = {"utc_date": status["utc_date"], "attempts": status["attempts"] + 1}
    path.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    return {**status, "attempts": updated["attempts"]}


def _model_env(model_mode: str, base_url: str = "", model: str = "", api_key: str = "") -> Dict[str, str]:
    mode = (model_mode or "deterministic").strip().lower()
    if mode in {"anyrouter", "openai", "llm"}:
        values = {"MODEL_PROVIDER": "openai", "USE_LLM": "1"}
        if base_url.strip():
            values["OPENAI_BASE_URL"] = base_url.strip()
        if model.strip():
            values["OPENAI_MODEL"] = model.strip()
        if api_key:
            values["OPENAI_API_KEY"] = api_key
        return values
    return {"MODEL_PROVIDER": "deterministic", "USE_LLM": "0"}


def _minimal_runner_environment(overrides: Dict[str, str]) -> dict:
    """Give the official launcher only process basics and explicitly entered model settings."""
    env = {"PATH": os.environ.get("PATH", "")}
    for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    env.update(overrides)
    return env


def _resolve_agent(agent: Path, python_executable: Optional[str]) -> tuple[List[str], Path]:
    agent = Path(agent).expanduser().resolve()
    if agent.is_dir():
        entry = next(
            (agent / name for name in ("baseline_agent.py", "agent.py", "main.py") if (agent / name).is_file()),
            None,
        )
        if entry is None:
            raise FileNotFoundError("代理文件夹中没有找到 baseline_agent.py、agent.py 或 main.py：%s" % agent)
    elif agent.is_file():
        entry = agent
    else:
        raise FileNotFoundError("Agent 入口不存在：%s" % agent)

    if entry.suffix.lower() == ".py":
        interpreter = python_executable or _agent_python()
        if not getattr(sys, "frozen", False) or python_executable:
            command = [interpreter, "-u", str(entry)]
        else:
            command = [interpreter, "-B", str(entry)]
    else:
        command = [str(entry)]
    return command, entry.parent


def _prepare_stress_card(card_id: str, seed: int, root: Path) -> Path:
    """Clone an official card and perturb hidden weather values only.

    This is deliberately a separate local robustness mode. Public targets,
    calendar, bulletins and forecasts remain official; the altered numeric
    weather truth is not an organizer card and must never be called official.
    """
    import shutil

    source = vendor_root() / "local-cards" / card_id
    destination = root / "stress-cards" / (f"{card_id}-seed-{int(seed)}")
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    weather_path = destination / "truth" / "v4_weather_truth.csv"
    rng = random.Random(f"{int(seed)}:{card_id}")
    rows = []
    with weather_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            for field, low, high in (
                ("seeing_arcsec", 0.75, 1.35),
                ("transparency", 0.78, 1.18),
                ("sky_quality", 0.78, 1.18),
                ("instrument_efficiency", 0.82, 1.12),
            ):
                if field not in row:
                    continue
                try:
                    value = float(row[field])
                except (TypeError, ValueError):
                    continue
                multiplier = rng.uniform(low, high)
                row[field] = f"{max(0.01, value * multiplier):.6f}"
            rows.append(row)
    with weather_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    config_path = destination / "config" / "v4_scenario.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.setdefault("task_card", {})["local_mode"] = "stress-seed"
    config["task_card"]["seed"] = int(seed)
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return destination


def _stop_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            process.kill()
    else:
        try:
            os.killpg(process.pid, 15)
        except OSError:
            process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _run_official_card(
    card_id: str,
    card_path: Optional[Path],
    agent_command: List[str],
    agent_cwd: Path,
    output_dir: Path,
    wallclock_seconds: float,
    runner_env: dict,
    stop_event: Optional[Event],
    on_event: Optional[EventHandler],
) -> dict:
    args = [
        *_runner_prefix(),
        "--card", str(card_path) if card_path is not None else card_id,
        "--agent", shlex.join(agent_command),
        "--agent-cwd", str(agent_cwd),
        "--wallclock", str(float(wallclock_seconds)),
        "--out", str(output_dir),
        "--inherit-env",
        "--quiet",
    ]
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        args,
        cwd=str(resource_root()),
        env=runner_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        start_new_session=(os.name != "nt"),
    )
    started = time.monotonic()
    next_progress = started + 5.0
    cancelled = False
    while process.poll() is None:
        if stop_event is not None and stop_event.is_set():
            cancelled = True
            _stop_process_tree(process)
            break
        now = time.monotonic()
        if on_event and now >= next_progress:
            on_event({"type": "batch_card_progress", "card_id": card_id, "elapsed_seconds": round(now - started, 1)})
            next_progress = now + 5.0
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            pass
    stdout, stderr = process.communicate()
    summary = None
    if stdout.strip():
        try:
            summary = json.loads(stdout)
        except ValueError:
            summary = None
    if cancelled:
        return {
            "card_id": card_id,
            "termination_reason": "cancelled",
            "exit_code": process.returncode,
            "output_dir": str(output_dir),
        }
    if not isinstance(summary, dict):
        return {
            "card_id": card_id,
            "termination_reason": "runner_error",
            "exit_code": process.returncode,
            "error": "Official runner did not return a JSON score summary.",
            "stderr_tail": stderr[-4000:],
            "output_dir": str(output_dir),
        }
    summary["runner_exit_code"] = process.returncode
    summary["runner_stderr_tail"] = stderr[-2000:] if stderr.strip() else ""
    summary["output_dir"] = str(output_dir)
    return summary


def run_batch(
    agent: Path,
    card_ids: List[str],
    seed: int,
    output_root: Path,
    on_event: Optional[EventHandler] = None,
    python_executable: Optional[str] = None,
    wallclock_seconds: float = 900.0,
    enforce_quota: bool = True,
    model_mode: str = "deterministic",
    base_url: str = "",
    model: str = "",
    stop_event: Optional[Event] = None,
    api_key: str = "",
    mode: str = "official-fixed",
) -> dict:
    requested = list(dict.fromkeys(card_ids))
    if not requested or any(card_id not in ALL_CARDS for card_id in requested):
        raise ValueError("请选择官方公开本地练习卡 L1–L4。")
    mode = str(mode or "official-fixed").strip().lower()
    if mode not in {"official-fixed", "stress-seed"}:
        raise ValueError("环境模式必须是 official-fixed 或 stress-seed。")
    if mode == "stress-seed" and int(seed) == 0:
        raise ValueError("stress-seed 模式需要非零整数 seed。")
    if wallclock_seconds <= 0:
        raise ValueError("每卡运行时限必须大于 0 秒。")
    agent_command, agent_cwd = _resolve_agent(agent, python_executable)
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    quota = _consume_quota(root) if enforce_quota else quota_status(root)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    session = root / ("attempt-%s-%s" % (stamp, uuid.uuid4().hex[:8]))
    session.mkdir(parents=True, exist_ok=False)
    if on_event:
        on_event({"type": "batch_start", "output_dir": str(session), "cards": requested, "mode": mode, "seed": int(seed), "quota": quota})

    model_env = _model_env(model_mode, base_url, model, api_key)
    runner_env = _minimal_runner_environment(model_env)
    results: List[dict] = []
    for card_id in requested:
        if stop_event is not None and stop_event.is_set():
            break
        output_dir = session / card_id
        output_dir.mkdir(parents=True, exist_ok=True)
        card_path = _prepare_stress_card(card_id, int(seed), session) if mode == "stress-seed" else None
        if on_event:
            on_event({"type": "batch_card_start", "card_id": card_id, "label": CARD_LABELS[card_id], "output_dir": str(output_dir)})
        try:
            item = _run_official_card(
                card_id,
                card_path,
                agent_command,
                agent_cwd,
                output_dir,
                wallclock_seconds,
                runner_env,
                stop_event,
                on_event,
            )
            item.setdefault("label", CARD_LABELS[card_id])
        except Exception as exc:
            item = {
                "card_id": card_id,
                "label": CARD_LABELS[card_id],
                "termination_reason": "runner_error",
                "error": "%s: %s" % (type(exc).__name__, exc),
                "traceback": traceback.format_exc(),
                "output_dir": str(output_dir),
            }
        results.append(item)
        if on_event:
            on_event({"type": "batch_card_done", **item})
        if item.get("termination_reason") == "cancelled":
            break

    total = sum(float(item.get("total", 0.0) or 0.0) for item in results)
    record = {
        "schema_version": "official-v4-local-batch-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "cards": requested,
        "mode": mode,
        "seed": int(seed),
        "wallclock_seconds_per_card": float(wallclock_seconds),
        "model_mode": "anyrouter" if model_env.get("USE_LLM") == "1" else "deterministic",
        "model": model if model_env.get("USE_LLM") == "1" else "",
        "quota": quota,
        "total": round(total, 8),
        "completed_cards": len(results),
        "results": results,
        "note": "Official-fixed uses the organizer's public L1-L4 cards. Stress-seed perturbs only hidden weather truth locally; neither mode is a cloud or hidden-card result.",
    }
    (session / "batch_summary.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if on_event:
        on_event({"type": "batch_done", "output_dir": str(session), "total": record["total"], "results": results, "quota": quota})
    return record


def run_practice(agent: Path, card_ids: List[str], output_root: Path, on_event=None, python_executable=None) -> dict:
    """Compatibility bridge for the former GUI call signature."""
    return run_batch(
        agent=agent,
        card_ids=card_ids,
        seed=0,
        output_root=output_root,
        on_event=on_event,
        python_executable=python_executable,
        wallclock_seconds=900,
        enforce_quota=False,
    )
