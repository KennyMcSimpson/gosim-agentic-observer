"""Run fixed calibration and seed-generated local v4 environments."""
from __future__ import annotations

import json
import os
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
CALIBRATION_MODE = "alpha-calibration"
SEED_MODE = "synthetic-seed"
CALIBRATION_CARD_IDS = ("alpha", "beta", "gamma", "delta")
CALIBRATION_REFERENCES = {
    "alpha": {"frozen_baseline_score": 3243.83, "calibration_target_score": 3243.83, "high_score": 8000.0},
    "beta": {"frozen_baseline_score": 4558.45, "calibration_target_score": 4558.45, "high_score": 7400.0},
    "gamma": {"frozen_baseline_score": 3893.13, "calibration_target_score": 3893.13, "high_score": 7400.0},
    "delta": {"frozen_baseline_score": 2975.56, "calibration_target_score": 2975.56, "high_score": 7400.0},
}
CALIBRATION_REFERENCE_SOURCE = "用户提供的官网裸 Agent 结果截图；本地隐藏环境为合成估计"
DAILY_ATTEMPT_LIMIT = 5
VENDOR_RELATIVE = Path("vendor") / "gosim-official-v4"


def available_modes() -> List[dict]:
    return [
        {
            "mode": CALIBRATION_MODE,
            "label": "α–δ 固定校准",
            "description": "固定的本地合成隐藏环境；对照官网截图基线，不代表官方真值或官网成绩。",
        },
        {
            "mode": SEED_MODE,
            "label": "Seed 额外测试",
            "description": "按 α/β/γ/δ 风格生成独立的合成环境；不属于四张固定校准卡。",
        },
    ]


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def vendor_root() -> Path:
    return resource_root() / VENDOR_RELATIVE


def _simulator_cards_api():
    try:
        from simulator.cards import available_fixed_cards, list_base_profiles
    except ImportError as exc:
        raise RuntimeError("本地合成卡生成器 simulator.cards 未安装。") from exc
    return available_fixed_cards, list_base_profiles


def _card_key(card: object) -> str:
    if isinstance(card, dict):
        return str(card.get("card_id") or card.get("profile_id") or card.get("id") or "")
    return str(card)


def _profile_key(card: object) -> str:
    if isinstance(card, dict):
        return str(card.get("base_profile") or card.get("profile_id") or card.get("id") or card.get("card_id") or "")
    return str(card)


def _profile_label(card: object, profile_id: str) -> str:
    if isinstance(card, dict):
        return str(card.get("label") or card.get("title") or card.get("name") or (profile_id + " 风格"))
    return profile_id + " 风格"


def available_cards(mode: Optional[str] = None) -> List[dict]:
    """Return the card catalog for one mode; seeded profiles stay visibly distinct."""
    selected_mode = str(mode or CALIBRATION_MODE).strip().lower()
    available_fixed_cards, list_base_profiles = _simulator_cards_api()
    if selected_mode == CALIBRATION_MODE:
        cards = []
        for raw in available_fixed_cards():
            card = dict(raw) if isinstance(raw, dict) else {"card_id": str(raw)}
            card_id = _card_key(card)
            if card_id not in CALIBRATION_CARD_IDS:
                continue
            card["card_id"] = card_id
            card["source"] = "synthetic-fixed-calibration"
            card["reference_source"] = CALIBRATION_REFERENCE_SOURCE
            card.update(CALIBRATION_REFERENCES[card_id])
            cards.append(card)
        return cards
    if selected_mode == SEED_MODE:
        cards = []
        for raw in list_base_profiles():
            profile_id = _profile_key(raw)
            if profile_id.startswith("synthetic-"):
                profile_id = profile_id[len("synthetic-"):]
            if profile_id.endswith("-like"):
                profile_id = profile_id[:-5]
            cards.append({
                "card_id": "synthetic-" + profile_id + "-like",
                "base_profile": profile_id,
                "label": _profile_label(raw, profile_id),
                "source": "synthetic-seed-profile",
                **{key: raw[key] for key in ("symbol", "title", "target_count", "night_count") if isinstance(raw, dict) and key in raw},
            })
        return cards
    raise ValueError("环境模式必须是 alpha-calibration 或 synthetic-seed。")


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


def _prepared_card(value: object) -> tuple[Path, dict]:
    """Accept a scenario path and optional metadata from the simulator layer."""
    metadata: dict = {}
    raw_path = value
    if isinstance(value, dict):
        raw_path = value.get("path") or value.get("card_path") or value.get("scenario_path")
        candidate = value.get("metadata")
        if isinstance(candidate, dict):
            metadata = dict(candidate)
    elif isinstance(value, tuple) and value:
        raw_path = value[0]
        if len(value) > 1 and isinstance(value[1], dict):
            metadata = dict(value[1])
    if raw_path is None:
        raise ValueError("合成卡生成器没有返回场景目录。")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_dir() or not (path / "config" / "v4_scenario.json").is_file():
        raise FileNotFoundError("生成的 v4 场景目录不完整：%s" % path)
    return path, metadata


def _seed_card_id(profile_id: str, seed: int) -> str:
    slug = str(profile_id).strip().lower().replace("_", "-").replace(" ", "-")
    if slug.startswith("synthetic-"):
        slug = slug[len("synthetic-"):]
    if slug.endswith("-like"):
        slug = slug[:-5]
    return "synthetic-%s-like-seed-%s" % (slug, seed)


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
    mode: str = CALIBRATION_MODE,
) -> dict:
    mode = str(mode or CALIBRATION_MODE).strip().lower()
    if mode not in {CALIBRATION_MODE, SEED_MODE}:
        raise ValueError("环境模式必须是 alpha-calibration 或 synthetic-seed。")
    try:
        seed_value = int(seed)
    except (TypeError, ValueError) as exc:
        raise ValueError("Seed 必须是整数。") from exc
    requested = list(dict.fromkeys(str(x) for x in card_ids))
    catalog = available_cards(mode)
    cards_by_id = {str(card["card_id"]): card for card in catalog}
    if not requested:
        raise ValueError("至少选择一张卡。")
    unknown = [card_id for card_id in requested if card_id not in cards_by_id]
    if unknown:
        expected = "α–δ 固定校准卡" if mode == CALIBRATION_MODE else "synthetic-*-like 种子基础型"
        raise ValueError("所选卡与当前模式不匹配；请选择当前模式的%s。未知项：%s" % (expected, ", ".join(unknown)))
    if wallclock_seconds <= 0 or wallclock_seconds > 900:
        raise ValueError("每卡运行时限必须大于 0 且不超过 900 秒。")
    agent_command, agent_cwd = _resolve_agent(agent, python_executable)
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    quota = _consume_quota(root) if enforce_quota else quota_status(root)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    session = root / ("attempt-%s-%s" % (stamp, uuid.uuid4().hex[:8]))
    session.mkdir(parents=True, exist_ok=False)
    used_seed = seed_value if mode == SEED_MODE else None
    if on_event:
        on_event({"type": "batch_start", "output_dir": str(session), "cards": requested, "mode": mode, "seed": used_seed, "quota": quota})

    try:
        from simulator.cards import prepare_fixed_card, prepare_seed_card
    except ImportError as exc:
        raise RuntimeError("本地合成卡生成器 simulator.cards 未安装。") from exc

    model_env = _model_env(model_mode, base_url, model, api_key)
    runner_env = _minimal_runner_environment(model_env)
    results: List[dict] = []
    for requested_id in requested:
        if stop_event is not None and stop_event.is_set():
            break
        card_meta = dict(cards_by_id[requested_id])
        profile_id = str(card_meta.get("base_profile") or "")
        run_card_id = requested_id if mode == CALIBRATION_MODE else _seed_card_id(profile_id, seed_value)
        symbol = str(card_meta.get("symbol") or "")
        title = str(card_meta.get("title") or card_meta.get("label") or requested_id)
        label = (symbol + " · " if symbol else "") + title
        if mode == SEED_MODE:
            label = "%s · seed %s" % (label, seed_value)
        output_dir = session / run_card_id
        output_dir.mkdir(parents=True, exist_ok=True)
        if on_event:
            on_event({"type": "batch_card_start", "card_id": run_card_id, "requested_card_id": requested_id, "label": label, "output_dir": str(output_dir)})
        try:
            raw_card = (
                prepare_fixed_card(requested_id, session)
                if mode == CALIBRATION_MODE
                else prepare_seed_card(profile_id, seed_value, session)
            )
            card_path, generated_meta = _prepared_card(raw_card)
            item = _run_official_card(
                run_card_id,
                card_path,
                agent_command,
                agent_cwd,
                output_dir,
                wallclock_seconds,
                runner_env,
                stop_event,
                on_event,
            )
            item.update(generated_meta)
            item.update({
                "card_id": run_card_id,
                "requested_card_id": requested_id,
                "label": label,
                "mode": mode,
                "simulation_source": "synthetic-fixed-calibration" if mode == CALIBRATION_MODE else "synthetic-seed",
                "output_dir": str(output_dir),
            })
            if mode == CALIBRATION_MODE:
                item.update({key: card_meta[key] for key in (
                    "frozen_baseline_score", "calibration_target_score", "high_score", "reference_source"
                ) if key in card_meta})
                score = item.get("total")
                target = card_meta.get("calibration_target_score")
                if score is not None and target is not None:
                    item["calibration_residual"] = round(float(score) - float(target), 2)
            else:
                item.update({"base_profile": profile_id, "seed": seed_value})
        except Exception as exc:
            item = {
                "card_id": run_card_id,
                "requested_card_id": requested_id,
                "label": label,
                "mode": mode,
                "simulation_source": "synthetic-fixed-calibration" if mode == CALIBRATION_MODE else "synthetic-seed",
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
    note = (
        "α–δ 使用按公开输入构造并冻结的本地合成隐藏环境；截图分数仅是校准参照，不代表恢复了官方隐藏真值。"
        if mode == CALIBRATION_MODE
        else "Seed 模式按风格基础型生成独立合成环境；结果用于额外稳健性测试，不属于 α–δ 固定校准卡或官方成绩。"
    )
    record = {
        "schema_version": "observer-practice-batch-v2",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "cards": [item.get("card_id", requested_id) for requested_id, item in zip(requested, results)],
        "requested_cards": requested,
        "mode": mode,
        "seed": used_seed,
        "wallclock_seconds_per_card": float(wallclock_seconds),
        "model_mode": "anyrouter" if model_env.get("USE_LLM") == "1" else "deterministic",
        "model": model if model_env.get("USE_LLM") == "1" else "",
        "quota": quota,
        "total": round(total, 8),
        "completed_cards": len(results),
        "results": results,
        "note": note,
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
