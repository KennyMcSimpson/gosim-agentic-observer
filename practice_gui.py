"""Desktop launcher for the local GOSIM complete-project practice run.

The GUI deliberately stays local: it only calls ``practice_backend`` and
displays the files produced by that backend.  The same module also exposes a
small ``--smoke-test`` entry point for source and frozen-package checks.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any


KNOWN_SCENARIOS = ("dev-fortnight", "dev-reference")

try:
    from practice_backend import (
        available_scenarios,
        default_agent_path,
        default_output_root,
        run_practice,
    )
except Exception as exc:  # pragma: no cover - exercised by a missing bundle.
    _BACKEND_IMPORT_ERROR: Exception | None = exc
    available_scenarios = None  # type: ignore[assignment]
    default_agent_path = None  # type: ignore[assignment]
    default_output_root = None  # type: ignore[assignment]
    run_practice = None  # type: ignore[assignment]
else:
    _BACKEND_IMPORT_ERROR = None


def _format_value(value: Any) -> str:
    """Render event values without allowing an exception to break the GUI."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _first_value(mapping: Any, *keys: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _summary_score(summary: Any) -> Any:
    """Accept the backend's compact summary and future nested score objects."""
    value = _first_value(summary, "total", "total_score", "score")
    if isinstance(value, dict):
        value = _first_value(value, "total", "value")
    return value


def _termination_label(value: Any) -> str:
    labels = {
        "survey_complete": "已完成",
        "global_wallclock_expired": "达到运行时限",
        "agent_error": "代理错误",
        "agent_initialization_error": "代理初始化错误",
    }
    if value is None or value == "":
        return "—"
    text = str(value)
    return labels.get(text, text)


def _score_label(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value):,.6f}"
    except (TypeError, ValueError):
        return str(value)


def _open_path(path: Path) -> None:
    """Open a file or directory with the native file manager on each desktop."""
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    if sys.platform == "win32":
        os.startfile(str(resolved))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(resolved)])
    else:
        subprocess.Popen(["xdg-open", str(resolved)])


def _smoke_print(message: str) -> None:
    """Frozen ``--windowed`` builds may expose ``sys.stderr`` as ``None``."""
    stream = sys.stderr
    if stream is not None:
        print(message, file=stream)


def _smoke_test(output_root: Path) -> int:
    """Run both public practice scenarios without creating a Tk window."""
    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    smoke_path = output_root / "smoke_result.json"
    scenarios = list(KNOWN_SCENARIOS)
    payload: dict[str, Any] = {
        "smoke_test": True,
        "scenarios": scenarios,
        "output_root": str(output_root),
        "passed": False,
    }

    if _BACKEND_IMPORT_ERROR is not None:
        payload["error"] = f"backend import failed: {_BACKEND_IMPORT_ERROR}"
        smoke_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _smoke_print(payload["error"])
        return 2

    try:
        agent = Path(default_agent_path()).expanduser()

        def on_event(event: dict) -> None:
            kind = event.get("type", "event")
            scenario = event.get("scenario")
            suffix = f" [{scenario}]" if scenario else ""
            _smoke_print(f"{kind}{suffix}")

        result = run_practice(agent, scenarios, output_root, on_event, None)
        payload.update(result if isinstance(result, dict) else {"result": result})
        results = payload.get("results")
        payload["passed"] = (
            isinstance(results, list)
            and len(results) == len(scenarios)
            and all(isinstance(item, dict) and item.get("exit_code") == 0 for item in results)
        )
    except Exception as exc:
        payload["error"] = f"{type(exc).__name__}: {exc}"
        payload["traceback"] = traceback.format_exc()
        _smoke_print(payload["error"])

    smoke_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    _smoke_print(f"smoke result: {smoke_path}")
    return 0 if payload.get("passed") else 1


class PracticeApp(tk.Tk):
    """Small, thread-safe Tkinter front end for ``practice_backend``."""

    def __init__(self) -> None:
        super().__init__()
        self.title("GOSIM 巡天智能体 · 本地完整项目练习")
        self.minsize(980, 700)
        self.geometry("1180x820")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._closing = False
        self._run_active = False
        self._run_had_error = False
        self._run_got_done = False
        self._current_output_dir: Path | None = None
        self._scenario_rows: dict[str, str] = {}
        self._scenario_vars: dict[str, tk.BooleanVar] = {}

        self.agent_var = tk.StringVar()
        self.interpreter_var = tk.StringVar()
        self.output_root_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪")
        self.backend_var = tk.StringVar(value="")

        self._build_widgets()
        self._load_defaults()
        self.after(80, self._drain_events)

    def _build_widgets(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(3, weight=1)

        outer = ttk.Frame(self, padding=(16, 14, 16, 14))
        outer.grid(row=0, column=0, rowspan=4, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)
        outer.rowconfigure(3, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="本地完整项目练习", font=("TkDefaultFont", 18, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="按公开练习场景在本机运行代理，每次运行都会保存到新的输出目录。",
            foreground="#555555",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(header, textvariable=self.status_var).grid(row=0, column=1, rowspan=2, sticky="e")

        controls = ttk.LabelFrame(outer, text="运行设置", padding=10)
        controls.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="代理入口").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(controls, textvariable=self.agent_var).grid(row=0, column=1, sticky="ew", pady=4)
        self.agent_file_button = ttk.Button(controls, text="选择 agent.py", command=self._choose_agent_file)
        self.agent_file_button.grid(row=0, column=2, padx=(8, 0), pady=4)
        self.agent_dir_button = ttk.Button(controls, text="选择代理文件夹", command=self._choose_agent_dir)
        self.agent_dir_button.grid(row=0, column=3, padx=(8, 0), pady=4)

        ttk.Label(controls, text="Python 解释器（可选）").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=4
        )
        ttk.Entry(controls, textvariable=self.interpreter_var).grid(row=1, column=1, sticky="ew", pady=4)
        self.interpreter_button = ttk.Button(controls, text="选择解释器", command=self._choose_interpreter)
        self.interpreter_button.grid(row=1, column=2, columnspan=2, sticky="e", padx=(8, 0), pady=4)

        ttk.Label(controls, text="输出根目录").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(controls, textvariable=self.output_root_var).grid(row=2, column=1, sticky="ew", pady=4)
        self.output_button = ttk.Button(controls, text="选择目录", command=self._choose_output_root)
        self.output_button.grid(row=2, column=2, columnspan=2, sticky="e", padx=(8, 0), pady=4)

        scenarios = ttk.LabelFrame(outer, text="练习场景", padding=10)
        scenarios.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        scenarios.columnconfigure(0, weight=1)
        scenarios.rowconfigure(1, weight=1)
        scenario_top = ttk.Frame(scenarios)
        scenario_top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        scenario_top.columnconfigure(0, weight=1)
        ttk.Label(scenario_top, textvariable=self.backend_var, foreground="#666666").grid(
            row=0, column=0, sticky="w"
        )
        self.run_button = ttk.Button(scenario_top, text="运行所选场景", command=self._start_run)
        self.run_button.grid(row=0, column=1, sticky="e")

        self.scenario_checks = ttk.Frame(scenarios)
        self.scenario_checks.grid(row=1, column=0, sticky="nw")
        self._populate_scenarios()

        results = ttk.LabelFrame(outer, text="场景结果", padding=8)
        results.grid(row=3, column=0, sticky="nsew", pady=(0, 10))
        results.columnconfigure(0, weight=1)
        results.rowconfigure(0, weight=1)
        self.results_tree = ttk.Treeview(
            results,
            columns=("scenario", "score", "termination", "output"),
            show="headings",
            selectmode="browse",
        )
        headings = {
            "scenario": ("场景", 180),
            "score": ("分数", 150),
            "termination": ("终止状态", 180),
            "output": ("运行目录", 570),
        }
        for column, (label, width) in headings.items():
            self.results_tree.heading(column, text=label)
            self.results_tree.column(column, width=width, minwidth=100, anchor="w")
        self.results_tree.grid(row=0, column=0, sticky="nsew")
        results_scroll = ttk.Scrollbar(results, orient="vertical", command=self.results_tree.yview)
        results_scroll.grid(row=0, column=1, sticky="ns")
        self.results_tree.configure(yscrollcommand=results_scroll.set)
        self.results_tree.bind("<Double-1>", lambda _event: self._open_selected_output())
        result_buttons = ttk.Frame(results)
        result_buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(result_buttons, text="打开选中输出", command=self._open_selected_output).pack(side="left")
        ttk.Button(result_buttons, text="打开本次输出", command=self._open_current_output).pack(side="left", padx=(8, 0))

        logs = ttk.LabelFrame(outer, text="运行日志", padding=8)
        logs.grid(row=4, column=0, sticky="nsew")
        outer.rowconfigure(4, weight=1)
        logs.columnconfigure(0, weight=1)
        logs.rowconfigure(0, weight=1)
        self.log_text = ScrolledText(logs, height=8, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.tag_configure("error", foreground="#a32626")

    def _populate_scenarios(self) -> None:
        for child in self.scenario_checks.winfo_children():
            child.destroy()
        self._scenario_vars.clear()
        names: list[str] = []
        if _BACKEND_IMPORT_ERROR is None:
            try:
                available = list(available_scenarios())
                names = [name for name in KNOWN_SCENARIOS if name in available]
                if not names:
                    names = list(KNOWN_SCENARIOS)
                    self._append_log("后端暂未报告可用场景；仍显示两个公开练习选项，运行时会给出具体错误。")
            except Exception as exc:
                names = list(KNOWN_SCENARIOS)
                self._append_log(f"读取场景列表失败：{exc}", error=True)
        else:
            names = list(KNOWN_SCENARIOS)
        for index, name in enumerate(names):
            variable = tk.BooleanVar(value=True)
            self._scenario_vars[name] = variable
            ttk.Checkbutton(self.scenario_checks, text=name, variable=variable).grid(
                row=0, column=index, sticky="w", padx=(0, 20)
            )
        if names:
            self.backend_var.set("默认已选择两个公开场景，可按需单独运行。")
        else:
            self.backend_var.set("当前没有可用场景。")

    def _load_defaults(self) -> None:
        if _BACKEND_IMPORT_ERROR is not None:
            self._append_log(f"无法加载练习后端：{_BACKEND_IMPORT_ERROR}", error=True)
            self.status_var.set("后端不可用")
            self.run_button.configure(state="disabled")
            return
        try:
            self.agent_var.set(str(Path(default_agent_path()).expanduser()))
        except Exception as exc:
            self._append_log(f"读取默认代理入口失败：{exc}", error=True)
        try:
            self.output_root_var.set(str(Path(default_output_root()).expanduser()))
        except Exception as exc:
            fallback = Path.home() / "Documents" / "GOSIM Practice Runs"
            self.output_root_var.set(str(fallback))
            self._append_log(f"读取默认输出目录失败，使用 {fallback}：{exc}", error=True)
        self._append_log("就绪：选择代理入口和场景后即可开始本地运行。")

    def _append_log(self, message: str, *, error: bool = False) -> None:
        if not hasattr(self, "log_text"):
            return
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n", "error" if error else "")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _choose_agent_file(self) -> None:
        current = Path(self.agent_var.get()).expanduser()
        path = filedialog.askopenfilename(
            title="选择 agent.py",
            initialdir=str(current.parent if current.parent.exists() else Path.cwd()),
            filetypes=(("Python 文件", "*.py"), ("所有文件", "*.*")),
        )
        if path:
            self.agent_var.set(path)

    def _choose_agent_dir(self) -> None:
        current = Path(self.agent_var.get()).expanduser()
        path = filedialog.askdirectory(
            title="选择代理文件夹",
            initialdir=str(current if current.is_dir() else current.parent if current.parent.exists() else Path.cwd()),
            mustexist=True,
        )
        if path:
            self.agent_var.set(path)

    def _choose_interpreter(self) -> None:
        current = Path(self.interpreter_var.get()).expanduser()
        path = filedialog.askopenfilename(
            title="选择 Python 解释器",
            initialdir=str(current.parent if current.parent.exists() else Path.cwd()),
            filetypes=(("可执行文件", "*.exe"), ("所有文件", "*.*")),
        )
        if path:
            self.interpreter_var.set(path)

    def _choose_output_root(self) -> None:
        current = Path(self.output_root_var.get()).expanduser()
        path = filedialog.askdirectory(
            title="选择输出根目录",
            initialdir=str(current if current.is_dir() else current.parent if current.parent.exists() else Path.cwd()),
            mustexist=False,
        )
        if path:
            self.output_root_var.set(path)

    def _selected_scenarios(self) -> list[str]:
        selected = []
        for name in KNOWN_SCENARIOS:
            variable = self._scenario_vars.get(name)
            if variable is not None and variable.get():
                selected.append(name)
        return selected

    def _start_run(self) -> None:
        if self._run_active:
            return
        if _BACKEND_IMPORT_ERROR is not None or run_practice is None:
            messagebox.showerror("后端不可用", str(_BACKEND_IMPORT_ERROR or "练习后端未加载。"))
            return

        agent_text = self.agent_var.get().strip()
        output_text = self.output_root_var.get().strip()
        interpreter_text = self.interpreter_var.get().strip()
        scenarios = self._selected_scenarios()
        if not agent_text:
            messagebox.showwarning("缺少代理入口", "请选择 agent.py 或代理文件夹。")
            return
        if not output_text:
            messagebox.showwarning("缺少输出目录", "请选择输出根目录。")
            return
        if not scenarios:
            messagebox.showwarning("缺少场景", "至少选择一个练习场景。")
            return
        agent = Path(agent_text).expanduser()
        if not agent.is_file() and not agent.is_dir():
            messagebox.showerror("代理入口不存在", str(agent))
            return
        interpreter: str | None = interpreter_text or None
        if interpreter is not None and not Path(interpreter).expanduser().is_file():
            messagebox.showerror("解释器不存在", interpreter)
            return
        output_root = Path(output_text).expanduser()

        self._run_active = True
        self._run_had_error = False
        self._run_got_done = False
        self._current_output_dir = None
        self._scenario_rows.clear()
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        self.status_var.set("运行中…")
        self._set_controls_enabled(False)
        self._append_log(f"开始运行：{', '.join(scenarios)}")

        self._worker = threading.Thread(
            target=self._run_worker,
            args=(agent, scenarios, output_root, interpreter),
            name="gosim-practice",
            daemon=True,
        )
        self._worker.start()

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (
            self.agent_file_button,
            self.agent_dir_button,
            self.interpreter_button,
            self.output_button,
            self.run_button,
        ):
            widget.configure(state=state)

    def _run_worker(
        self,
        agent: Path,
        scenarios: list[str],
        output_root: Path,
        interpreter: str | None,
    ) -> None:
        try:
            run_practice(agent, scenarios, output_root, self._event_queue.put, interpreter)
        except BaseException as exc:
            self._event_queue.put(
                {
                    "type": "error",
                    "message": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            )
        finally:
            self._event_queue.put({"type": "_thread_finished"})

    def _drain_events(self) -> None:
        if self._closing:
            return
        try:
            while True:
                self._handle_event(self._event_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(80, self._drain_events)

    def _handle_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "start":
            value = event.get("output_dir")
            if value:
                self._current_output_dir = Path(str(value))
            self._append_log(f"本次输出目录：{value or '—'}")
            return
        if kind == "scenario_start":
            scenario = str(event.get("scenario", ""))
            output_dir = str(event.get("output_dir", ""))
            self._set_result_row(scenario, "—", "运行中", output_dir)
            self._append_log(f"开始场景：{scenario}")
            return
        if kind == "scenario_done":
            scenario = str(event.get("scenario", ""))
            summary = event.get("summary")
            error = event.get("error")
            score = _score_label(_summary_score(summary))
            raw_termination = _first_value(summary, "termination_reason", "termination", "status")
            termination = _termination_label(raw_termination)
            exit_code = event.get("exit_code")
            try:
                failed_exit = exit_code is not None and int(exit_code) != 0
            except (TypeError, ValueError):
                failed_exit = bool(exit_code)
            failed_status = raw_termination in {"agent_error", "agent_initialization_error", "error", "failed"}
            if error or failed_exit or failed_status:
                if termination == "—":
                    termination = "错误"
                self._run_had_error = True
                detail = error or f"返回码 {exit_code}"
                self._append_log(f"场景 {scenario} 失败：{detail}", error=True)
            else:
                self._append_log(f"场景 {scenario} 完成：分数 {score}，终止状态 {_format_value(termination)}")
            self._set_result_row(scenario, score, termination, str(event.get("output_dir", "")))
            return
        if kind == "done":
            self._run_got_done = True
            value = event.get("output_dir")
            if value:
                self._current_output_dir = Path(str(value))
            self._append_log(f"本次练习完成：{value or '—'}")
            return
        if kind == "error":
            self._run_had_error = True
            message = str(event.get("message") or event.get("error") or "未知错误")
            self._append_log(message, error=True)
            details = event.get("traceback")
            if details:
                self._append_log(str(details), error=True)
            self.status_var.set("运行失败")
            return
        if kind == "_thread_finished":
            self._run_active = False
            self._worker = None
            if self._run_had_error:
                self.status_var.set("完成（含错误）" if self._run_got_done else "运行失败")
            else:
                self.status_var.set("已完成")
            self._set_controls_enabled(True)

    def _set_result_row(self, scenario: str, score: str, termination: str, output: str) -> None:
        if scenario in self._scenario_rows:
            self.results_tree.item(self._scenario_rows[scenario], values=(scenario, score, termination, output))
            return
        row = self.results_tree.insert("", "end", values=(scenario, score, termination, output))
        self._scenario_rows[scenario] = row

    def _open_selected_output(self) -> None:
        selection = self.results_tree.selection()
        if not selection:
            messagebox.showinfo("没有选中结果", "请先选择一个场景结果。")
            return
        output = self.results_tree.item(selection[0], "values")[3]
        self._open_output_value(output)

    def _open_current_output(self) -> None:
        if self._current_output_dir is None:
            messagebox.showinfo("没有运行输出", "完成一次运行后，这里会打开本次输出目录。")
            return
        self._open_output_value(str(self._current_output_dir))

    def _open_output_value(self, value: str) -> None:
        if not value:
            messagebox.showinfo("没有输出路径", "该结果还没有输出目录。")
            return
        try:
            _open_path(Path(value))
        except Exception as exc:
            messagebox.showerror("无法打开输出路径", f"{value}\n\n{exc}")

    def _on_close(self) -> None:
        if self._run_active:
            should_close = messagebox.askyesno(
                "运行仍在继续",
                "后台练习尚未结束。关闭窗口后本次本地进程仍可能继续运行，确定退出吗？",
            )
            if not should_close:
                return
        self._closing = True
        self.destroy()


def _launch_gui() -> int:
    app = PracticeApp()
    app.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GOSIM 本地完整项目练习 GUI")
    parser.add_argument(
        "--smoke-test",
        metavar="OUTPUT_ROOT",
        help="无界面运行 dev-fortnight 和 dev-reference，并在 OUTPUT_ROOT 写入 smoke_result.json",
    )
    args = parser.parse_args(argv)
    if args.smoke_test:
        return _smoke_test(Path(args.smoke_test))
    return _launch_gui()


if __name__ == "__main__":
    raise SystemExit(main())
