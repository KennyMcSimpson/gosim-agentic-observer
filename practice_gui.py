"""Polished local GUI for the GOSIM v4 practice runner."""
from __future__ import annotations

import argparse
import inspect
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

try:
    from practice_backend import available_cards, default_agent_path, default_output_root, quota_status, run_batch
    _BACKEND_PARAMS = set(inspect.signature(run_batch).parameters)
    _BACKEND_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - absent bundle
    available_cards = default_agent_path = default_output_root = quota_status = run_batch = None  # type: ignore[assignment]
    _BACKEND_PARAMS = set()
    _BACKEND_IMPORT_ERROR = exc

BG, PANEL, NAVY = "#f3f6fb", "#ffffff", "#14233d"
INK, MUTED, BLUE, GREEN, RED = "#172033", "#68758a", "#2864dc", "#16845b", "#b33b42"
BORDER = "#dce3ed"


def _card_id(card: Any) -> str:
    if isinstance(card, dict):
        return str(card.get("card_id") or card.get("id") or card.get("name") or "")
    return str(card)


def _card_title(card: Any) -> str:
    if not isinstance(card, dict):
        return str(card)
    symbol = str(card.get("symbol") or "")
    title = str(card.get("title") or card.get("label") or card.get("name") or _card_id(card))
    detail = []
    for key, label in (("target_count", "目标"), ("nights", "夜晚"), ("required_count", "必做")):
        if card.get(key) is not None:
            try:
                detail.append(f"{label} {int(card[key]):,}")
            except (TypeError, ValueError):
                pass
    return (f"{symbol}  " if symbol else "") + title + ("   ·   " + "   ·   ".join(detail) if detail else "")


def _score(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "—" if value is None else str(value)


def _status(value: Any) -> str:
    return {
        "survey_complete": "巡天完成", "wallclock_timeout": "达到时限",
        "global_wallclock_expired": "达到时限", "agent_finish": "Agent 主动结束",
        "agent_error": "Agent 错误", "agent_initialization_error": "初始化错误",
        "cancelled": "已停止", "runner_error": "运行器错误",
    }.get(str(value or ""), str(value or "—"))


def _open_path(value: str | Path) -> None:
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class PracticeApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("GOSIM · 巡天智能体本地评测")
        self.geometry("1280x880")
        self.minsize(1080, 740)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.active = False
        self.closing = False
        self.had_error = False
        self.output_dir: Path | None = None
        self.cards = self._load_cards()
        self.modes = self._load_modes()
        self.card_vars: dict[str, tk.BooleanVar] = {}
        self.card_rows: dict[str, str] = {}
        self.current_card = ""
        self.completed = 0
        self.requested = 0

        self.agent_var = tk.StringVar()
        self.interpreter_var = tk.StringVar()
        self.output_root_var = tk.StringVar()
        default_mode = "official-fixed" if "official-fixed" in self.modes else self.modes[0] if self.modes else "stress-seed"
        self.mode_var = tk.StringVar(value=default_mode)
        self.seed_var = tk.StringVar(value="20261003")
        self.seconds_var = tk.StringVar(value="900")
        self.quota_var = tk.BooleanVar(value=True)
        self.model_mode_var = tk.StringVar(value="deterministic")
        self.base_url_var = tk.StringVar(value=os.environ.get("OPENAI_BASE_URL", ""))
        self.model_var = tk.StringVar(value=os.environ.get("OPENAI_MODEL", ""))
        self.api_key_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="就绪")
        self.mode_note_var = tk.StringVar()
        self.quota_note_var = tk.StringVar()
        self.progress_note_var = tk.StringVar(value="等待开始")
        self.batch_score_var = tk.StringVar(value="—")
        self._styles()
        self._layout()
        self._load_defaults()
        self._update_mode()
        self._update_model()
        self._refresh_quota()
        self.after(100, self._drain_events)

    def _load_cards(self) -> list[Any]:
        if available_cards is None:
            return []
        try:
            return list(available_cards())
        except Exception:
            return []

    def _load_modes(self) -> list[str]:
        if _BACKEND_IMPORT_ERROR is not None:
            return []
        try:
            from practice_backend import available_modes  # type: ignore
            return [str(x.get("mode") if isinstance(x, dict) else x) for x in available_modes()]
        except Exception:
            pass
        if "environment_mode" in _BACKEND_PARAMS or "mode" in _BACKEND_PARAMS:
            return ["official-fixed", "stress-seed"]
        if any(isinstance(c, dict) and c.get("source") == "official" for c in self.cards):
            return ["official-fixed"]
        return ["stress-seed"]

    def _styles(self) -> None:
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure("TFrame", background=BG)
        s.configure("Panel.TFrame", background=PANEL)
        s.configure("TLabel", background=PANEL, foreground=INK, font=("Segoe UI", 9))
        s.configure("Muted.TLabel", foreground=MUTED, font=("Segoe UI", 8))
        s.configure("Title.TLabel", background=NAVY, foreground="white", font=("Segoe UI", 20, "bold"))
        s.configure("Subtitle.TLabel", background=NAVY, foreground="#c6d2e4", font=("Segoe UI", 9))
        s.configure("PanelTitle.TLabel", font=("Segoe UI", 11, "bold"))
        s.configure("TLabelframe", background=PANEL, bordercolor=BORDER)
        s.configure("TLabelframe.Label", background=PANEL, foreground=INK, font=("Segoe UI", 9, "bold"))
        s.configure("TEntry", padding=(7, 5), fieldbackground="#fbfcfe")
        s.configure("TCheckbutton", background=PANEL, foreground=INK, font=("Segoe UI", 9))
        s.configure("TRadiobutton", background=PANEL, foreground=INK, font=("Segoe UI", 9))
        s.configure("TButton", padding=(8, 6), font=("Segoe UI", 9))
        s.configure("Primary.TButton", background=BLUE, foreground="white", padding=(12, 9), font=("Segoe UI", 10, "bold"))
        s.map("Primary.TButton", background=[("disabled", "#aab8d0"), ("active", "#1f53bd")])
        s.configure("Danger.TButton", background="#fff1f1", foreground=RED, padding=(12, 9), font=("Segoe UI", 9, "bold"))
        s.configure("Treeview", rowheight=28, background="white", fieldbackground="white", foreground=INK, font=("Segoe UI", 9))
        s.configure("Treeview.Heading", background="#edf1f7", foreground="#4b5870", font=("Segoe UI", 9, "bold"), padding=6)
        s.map("Treeview", background=[("selected", "#dce8ff")], foreground=[("selected", INK)])
        s.configure("Horizontal.TProgressbar", troughcolor="#e5ebf3", background=BLUE, thickness=9)

    def _layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        header = tk.Frame(self, bg=NAVY, height=84)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="GOSIM  ·  巡天智能体", style="Title.TLabel").grid(row=0, column=0, sticky="sw", padx=21, pady=(11, 0))
        ttk.Label(header, text="v4 本地评测台   ·   固定练习卡、环境压力测试与运行回放", style="Subtitle.TLabel").grid(row=1, column=0, sticky="nw", padx=22, pady=(0, 11))
        self.status_badge = tk.Label(header, textvariable=self.status_var, bg="#233757", fg="#e7eef9", font=("Segoe UI", 9, "bold"), padx=14, pady=8)
        self.status_badge.grid(row=0, column=1, rowspan=2, padx=20, sticky="e")

        body = ttk.Frame(self, padding=13)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, minsize=400, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self.left_panel = ttk.Frame(body, style="Panel.TFrame", padding=11)
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.left_panel.columnconfigure(0, weight=1)
        self._agent_panel(self.left_panel, 0)
        self._cards_panel(self.left_panel, 1)
        self._environment_panel(self.left_panel, 2)
        self._model_panel(self.left_panel, 3)
        self._output_panel(self.left_panel, 4)
        self.run_button = ttk.Button(self.left_panel, text="▶   开始本地评测", style="Primary.TButton", command=self._start_or_stop)
        self.run_button.grid(row=5, column=0, sticky="ew", pady=(9, 0))

        right = ttk.Frame(body, style="Panel.TFrame", padding=13)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=3)
        right.rowconfigure(5, weight=2)
        top = ttk.Frame(right, style="Panel.TFrame")
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        ttk.Label(top, text="评测结果", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        box = tk.Frame(top, bg="#eef4ff", padx=11, pady=5)
        box.grid(row=0, column=1, sticky="e")
        tk.Label(box, text="本地累计分数", bg="#eef4ff", fg=MUTED, font=("Segoe UI", 8)).pack(side="left", padx=(0, 7))
        tk.Label(box, textvariable=self.batch_score_var, bg="#eef4ff", fg=BLUE, font=("Segoe UI", 12, "bold")).pack(side="left")
        prog = ttk.Frame(right, style="Panel.TFrame")
        prog.grid(row=1, column=0, sticky="ew", pady=(9, 7))
        prog.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(prog, mode="determinate", maximum=1, value=0)
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 9))
        ttk.Label(prog, textvariable=self.progress_note_var, style="Muted.TLabel", width=22).grid(row=0, column=1, sticky="e")
        table = ttk.Frame(right, style="Panel.TFrame")
        table.grid(row=2, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        cols = ("card", "status", "score", "observed", "missing", "output")
        self.results = ttk.Treeview(table, columns=cols, show="headings", selectmode="browse")
        for col, title, width, anchor in (
            ("card", "练习卡", 92, "w"), ("status", "状态", 115, "w"),
            ("score", "分数", 90, "e"), ("observed", "已观测", 75, "e"),
            ("missing", "必做未完成", 95, "e"), ("output", "运行目录", 250, "w"),
        ):
            self.results.heading(col, text=title)
            self.results.column(col, width=width, minwidth=55, anchor=anchor, stretch=col == "output")
        self.results.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.results.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.results.configure(yscrollcommand=scroll.set)
        self.results.bind("<Double-1>", lambda _e: self._open_selected())
        self.results.tag_configure("running", foreground=BLUE)
        self.results.tag_configure("error", foreground=RED)
        self.results.tag_configure("done", foreground=GREEN)
        buttons = ttk.Frame(right, style="Panel.TFrame")
        buttons.grid(row=3, column=0, sticky="ew", pady=(8, 12))
        ttk.Button(buttons, text="打开选中卡片输出", command=self._open_selected).pack(side="left")
        ttk.Button(buttons, text="打开本批目录", command=lambda: self._open(self.output_dir)).pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="打开输出根目录", command=lambda: self._open(self.output_root_var.get())).pack(side="left", padx=(6, 0))
        ttk.Label(right, text="运行日志", style="PanelTitle.TLabel").grid(row=4, column=0, sticky="w", pady=(0, 5))
        self.log = ScrolledText(right, height=13, wrap="word", state="disabled", bg="#101a2a", fg="#d8e3f2", insertbackground="white", relief="flat", padx=10, pady=8, font=("Cascadia Mono", 9))
        self.log.grid(row=5, column=0, sticky="nsew")
        self.log.tag_configure("error", foreground="#ff9292")
        self.log.tag_configure("good", foreground="#8fe0b5")

    def _agent_panel(self, parent: ttk.Frame, row: int) -> None:
        p = ttk.LabelFrame(parent, text="1  ·  Agent 入口", padding=(9, 7))
        p.grid(row=row, column=0, sticky="ew", pady=(0, 7))
        p.columnconfigure(0, weight=1)
        line = ttk.Frame(p, style="Panel.TFrame")
        line.grid(row=0, column=0, sticky="ew")
        line.columnconfigure(0, weight=1)
        ttk.Entry(line, textvariable=self.agent_var).grid(row=0, column=0, sticky="ew")
        self.agent_file_button = ttk.Button(line, text="文件", width=6, command=self._choose_agent_file)
        self.agent_file_button.grid(row=0, column=1, padx=(4, 0))
        self.agent_dir_button = ttk.Button(line, text="项目", width=6, command=self._choose_agent_dir)
        self.agent_dir_button.grid(row=0, column=2, padx=(4, 0))
        ttk.Label(p, text="支持 .py 入口或 Agent 项目目录。", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _cards_panel(self, parent: ttk.Frame, row: int) -> None:
        p = ttk.LabelFrame(parent, text="2  ·  练习卡", padding=(9, 7))
        p.grid(row=row, column=0, sticky="ew", pady=(0, 7))
        p.columnconfigure(0, weight=1)
        tools = ttk.Frame(p, style="Panel.TFrame")
        tools.grid(row=0, column=0, sticky="ew")
        tools.columnconfigure(0, weight=1)
        ttk.Label(tools, text="勾选要跑的卡；默认全选。", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(tools, text="全选", width=6, command=lambda: self._select_cards(True)).grid(row=0, column=1, padx=(3, 0))
        ttk.Button(tools, text="清空", width=6, command=lambda: self._select_cards(False)).grid(row=0, column=2, padx=(3, 0))
        self.cards_frame = ttk.Frame(p, style="Panel.TFrame")
        self.cards_frame.grid(row=1, column=0, sticky="ew", pady=(3, 0))
        self.cards_frame.columnconfigure(0, weight=1)
        self.card_source_note = ttk.Label(p, text="", style="Muted.TLabel", wraplength=360, justify="left")
        self.card_source_note.grid(row=2, column=0, sticky="w", pady=(4, 0))
        self._populate_cards()

    def _populate_cards(self) -> None:
        for child in self.cards_frame.winfo_children():
            child.destroy()
        self.card_vars.clear()
        if not self.cards:
            ttk.Label(self.cards_frame, text="未能读取练习卡列表。", foreground=RED).grid(row=0, column=0, sticky="w")
            self.card_source_note.configure(text="请检查 v4 后端是否安装完整。")
            return
        for i, card in enumerate(self.cards):
            card_id = _card_id(card)
            self.card_vars[card_id] = tk.BooleanVar(value=True)
            ttk.Checkbutton(self.cards_frame, text=_card_title(card), variable=self.card_vars[card_id]).grid(row=i, column=0, sticky="w", pady=1)
        if any(isinstance(c, dict) and c.get("source") == "official" for c in self.cards):
            self.card_source_note.configure(text="已加载官方公开本地练习卡；固定卡模式保留卡片与公开数据。")
        else:
            self.card_source_note.configure(text="卡片来源由后端决定；运行前请核对下方环境模式。")

    def _environment_panel(self, parent: ttk.Frame, row: int) -> None:
        p = ttk.LabelFrame(parent, text="3  ·  环境与运行时限", padding=(9, 7))
        p.grid(row=row, column=0, sticky="ew", pady=(0, 7))
        p.columnconfigure(0, weight=1)
        radios = ttk.Frame(p, style="Panel.TFrame")
        radios.grid(row=0, column=0, sticky="w")
        labels = {"official-fixed": "官方固定卡", "stress-seed": "Seed 压力测试"}
        modes = self.modes or ["stress-seed"]
        for i, mode in enumerate(modes):
            ttk.Radiobutton(radios, text=labels.get(mode, mode), variable=self.mode_var, value=mode, command=self._update_mode).grid(row=0, column=i, sticky="w", padx=(0, 9))
        line = ttk.Frame(p, style="Panel.TFrame")
        line.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        ttk.Label(line, text="Seed").pack(side="left")
        self.seed_entry = ttk.Entry(line, textvariable=self.seed_var, width=11)
        self.seed_entry.pack(side="left", padx=(5, 12))
        ttk.Label(line, text="每卡秒数").pack(side="left")
        ttk.Entry(line, textvariable=self.seconds_var, width=7).pack(side="left", padx=(5, 4))
        ttk.Label(line, text="最多 900", style="Muted.TLabel").pack(side="left")
        ttk.Checkbutton(p, text="模拟每天最多 5 批（UTC 日期重置）", variable=self.quota_var, command=self._refresh_quota).grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Label(p, textvariable=self.quota_note_var, style="Muted.TLabel").grid(row=3, column=0, sticky="w")
        ttk.Label(p, textvariable=self.mode_note_var, style="Muted.TLabel", wraplength=360, justify="left").grid(row=4, column=0, sticky="w", pady=(3, 0))

    def _model_panel(self, parent: ttk.Frame, row: int) -> None:
        p = ttk.LabelFrame(parent, text="4  ·  决策模型", padding=(9, 7))
        p.grid(row=row, column=0, sticky="ew", pady=(0, 7))
        p.columnconfigure(0, weight=1)
        radios = ttk.Frame(p, style="Panel.TFrame")
        radios.grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(radios, text="确定性", variable=self.model_mode_var, value="deterministic", command=self._update_model).pack(side="left")
        ttk.Radiobutton(radios, text="AnyRouter / OpenAI 兼容", variable=self.model_mode_var, value="anyrouter", command=self._update_model).pack(side="left", padx=(10, 0))
        fields = ttk.Frame(p, style="Panel.TFrame")
        fields.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        fields.columnconfigure(1, weight=1)
        self.model_widgets: list[ttk.Widget] = []
        for row, label, variable, secret in (
            (0, "接口地址", self.base_url_var, False), (1, "模型名", self.model_var, False), (2, "API Key", self.api_key_var, True),
        ):
            ttk.Label(fields, text=label).grid(row=row, column=0, sticky="w", padx=(0, 6), pady=2)
            entry = ttk.Entry(fields, textvariable=variable, show="•" if secret else "")
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            self.model_widgets.append(entry)
        ttk.Label(p, text="Key 仅在本次运行内存中使用，不写入设置或日志。", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(3, 0))

    def _output_panel(self, parent: ttk.Frame, row: int) -> None:
        p = ttk.LabelFrame(parent, text="5  ·  输出目录", padding=(9, 7))
        p.grid(row=row, column=0, sticky="ew")
        p.columnconfigure(0, weight=1)
        line = ttk.Frame(p, style="Panel.TFrame")
        line.grid(row=0, column=0, sticky="ew")
        line.columnconfigure(0, weight=1)
        ttk.Entry(line, textvariable=self.output_root_var).grid(row=0, column=0, sticky="ew")
        self.output_button = ttk.Button(line, text="浏览", width=7, command=self._choose_output_root)
        self.output_button.grid(row=0, column=1, padx=(4, 0))
        ttk.Label(p, text="按批保存评分、日志和 replay 文件。", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 0))

    def _load_defaults(self) -> None:
        if _BACKEND_IMPORT_ERROR is not None:
            self._append_log(f"后端未加载：{_BACKEND_IMPORT_ERROR}", error=True)
            self.status_var.set("后端不可用")
            self.run_button.configure(state="disabled")
            return
        try:
            self.agent_var.set(str(Path(default_agent_path()).expanduser()))
            self.output_root_var.set(str(Path(default_output_root()).expanduser()))
        except Exception as exc:
            self._append_log(f"默认路径读取失败：{exc}", error=True)
        if not self.cards:
            self._append_log("后端未返回练习卡。", error=True)
        self._append_log("就绪：选择卡片、环境模式与 Agent 后开始。")

    def _append_log(self, message: str, *, error: bool = False, good: bool = False) -> None:
        if not hasattr(self, "log"):
            return
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n", "error" if error else "good" if good else "")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _update_mode(self) -> None:
        if self.mode_var.get() == "official-fixed":
            self.mode_note_var.set("固定官方练习卡和公开数据；卡片本身不重新抽样。")
            self.seed_entry.configure(state="disabled")
        else:
            official_cards = any(isinstance(c, dict) and c.get("source") == "official" for c in self.cards)
            if official_cards:
                note = "固定官方卡；Seed 只用于后端明确支持的天气、故障等隐藏状态压力测试。"
            else:
                note = "当前后端提供种子化本地生成卡，用于压力测试；其分数不等同于官方固定练习卡成绩。"
            self.mode_note_var.set(note)
            self.seed_entry.configure(state="normal")

    def _update_model(self) -> None:
        state = "normal" if self.model_mode_var.get() == "anyrouter" else "disabled"
        for widget in self.model_widgets:
            widget.configure(state=state)

    def _selected_cards(self) -> list[str]:
        return [card_id for card_id, var in self.card_vars.items() if var.get()]

    def _select_cards(self, value: bool) -> None:
        for var in self.card_vars.values():
            var.set(value)

    def _refresh_quota(self) -> None:
        if not self.output_root_var.get().strip() or quota_status is None:
            self.quota_note_var.set("额度状态暂不可用。")
            return
        try:
            q = quota_status(Path(self.output_root_var.get().strip()).expanduser())
            suffix = "（启用）" if self.quota_var.get() else "（关闭）"
            self.quota_note_var.set(f"UTC {q.get('utc_date', '')}：已用 {q.get('attempts', 0)}/{q.get('limit', 5)} 批  {suffix}")
        except Exception as exc:
            self.quota_note_var.set(f"额度状态读取失败：{exc}")

    def _choose_agent_file(self) -> None:
        current = Path(self.agent_var.get()).expanduser()
        path = filedialog.askopenfilename(title="选择 Agent Python 入口", initialdir=str(current.parent if current.parent.exists() else Path.cwd()), filetypes=(("Python 文件", "*.py"), ("所有文件", "*.*")))
        if path:
            self.agent_var.set(path)

    def _choose_agent_dir(self) -> None:
        current = Path(self.agent_var.get()).expanduser()
        initial = current if current.is_dir() else current.parent if current.parent.exists() else Path.cwd()
        path = filedialog.askdirectory(title="选择 Agent 项目目录", initialdir=str(initial), mustexist=True)
        if path:
            self.agent_var.set(path)

    def _choose_output_root(self) -> None:
        current = Path(self.output_root_var.get()).expanduser()
        initial = current if current.is_dir() else current.parent if current.parent.exists() else Path.cwd()
        path = filedialog.askdirectory(title="选择输出目录", initialdir=str(initial), mustexist=False)
        if path:
            self.output_root_var.set(path)
            self._refresh_quota()

    def _start_or_stop(self) -> None:
        if self.active:
            self.stop_event.set()
            self.run_button.configure(text="正在停止…", state="disabled")
            self.status_var.set("正在停止")
            self._append_log("收到停止请求；当前决策结束后将停止。")
            return
        if _BACKEND_IMPORT_ERROR is not None or run_batch is None:
            messagebox.showerror("后端不可用", str(_BACKEND_IMPORT_ERROR or "v4 后端未加载。"))
            return
        agent = Path(self.agent_var.get().strip()).expanduser()
        output_text = self.output_root_var.get().strip()
        output = Path(output_text).expanduser()
        interpreter_text = self.interpreter_var.get().strip()
        cards = self._selected_cards()
        try:
            seed, seconds = int(self.seed_var.get().strip()), float(self.seconds_var.get().strip())
        except ValueError:
            messagebox.showwarning("参数格式错误", "Seed 必须是整数，每卡秒数必须是数字。")
            return
        if not agent.exists():
            messagebox.showerror("Agent 入口无效", "选择现存的 .py 文件或项目目录。")
            return
        if not output_text or not cards:
            messagebox.showwarning("设置未完成", "请选择输出目录并至少勾选一张卡。")
            return
        if seconds <= 0 or seconds > 900:
            messagebox.showwarning("运行时限无效", "每卡时限需大于 0 且不超过 900 秒。")
            return
        if interpreter_text and not Path(interpreter_text).expanduser().is_file():
            messagebox.showerror("Python 解释器不存在", interpreter_text)
            return
        if self.mode_var.get() not in self.modes:
            messagebox.showerror("环境模式不可用", "当前后端未提供此模式；请先更新后端，避免误把模拟环境当成官方卡。")
            return
        if self.model_mode_var.get() == "anyrouter":
            if not self.base_url_var.get().strip() or not self.model_var.get().strip():
                messagebox.showwarning("AnyRouter 配置未完成", "填写 OpenAI 兼容接口地址和模型名。")
                return
            if not self.api_key_var.get().strip() and not os.environ.get("OPENAI_API_KEY"):
                messagebox.showwarning("缺少 API Key", "填写 Key，或在启动前设置 OPENAI_API_KEY 环境变量。")
                return

        self.active, self.completed, self.requested = True, 0, len(cards)
        self.had_error = False
        self.stop_event.clear()
        self.output_dir = None
        self.current_card = ""
        self.card_rows.clear()
        self.batch_score_var.set("—")
        self.progress.configure(maximum=len(cards), value=0)
        self.progress_note_var.set(f"准备运行 {len(cards)} 张卡")
        for item in self.results.get_children():
            self.results.delete(item)
        for card in cards:
            self.card_rows[card] = self.results.insert("", "end", values=(card, "排队中", "—", "—", "—", ""))
        self.status_var.set("运行中")
        self.status_badge.configure(bg="#1f684f")
        self.run_button.configure(text="■   停止运行", style="Danger.TButton", state="normal")
        self._set_controls_enabled(False)
        self._append_log(f"开始运行 {len(cards)} 张卡：{', '.join(cards)}")
        self._refresh_quota()
        args = (
            agent, cards, seed, output, interpreter_text or None,
            seconds, self.quota_var.get(), self.mode_var.get(), self.model_mode_var.get(),
            self.base_url_var.get().strip(), self.model_var.get().strip(), self.api_key_var.get(),
        )
        self.worker = threading.Thread(target=self._run_worker, args=args, name="gosim-v4-practice", daemon=True)
        self.worker.start()

    def _set_controls_enabled(self, enabled: bool) -> None:
        controllable = (ttk.Button, ttk.Entry, ttk.Checkbutton, ttk.Radiobutton)
        def walk(widget: tk.Misc) -> None:
            for child in widget.winfo_children():
                if child is not self.run_button and isinstance(child, controllable):
                    child.configure(state="normal" if enabled else "disabled")
                walk(child)
        walk(self.left_panel)
        self.run_button.configure(state="normal")

    def _run_worker(self, agent: Path, cards: list[str], seed: int, output: Path,
                    interpreter: str | None, seconds: float, enforce_quota: bool,
                    mode: str, model_mode: str, base_url: str, model: str, api_key: str) -> None:
        old_key, had_key = os.environ.get("OPENAI_API_KEY"), "OPENAI_API_KEY" in os.environ
        secret_to_redact = api_key.strip() or old_key or ""
        if api_key.strip():
            os.environ["OPENAI_API_KEY"] = api_key.strip()
        try:
            kwargs: dict[str, Any] = {
                "agent": agent, "card_ids": cards, "seed": seed, "output_root": output,
                "on_event": self.events.put, "python_executable": interpreter,
                "wallclock_seconds": seconds, "enforce_quota": enforce_quota,
                "model_mode": model_mode, "base_url": base_url, "model": model,
                "stop_event": self.stop_event,
            }
            if "environment_mode" in _BACKEND_PARAMS:
                kwargs["environment_mode"] = mode
            elif "mode" in _BACKEND_PARAMS:
                kwargs["mode"] = mode
            if "api_key" in _BACKEND_PARAMS:
                kwargs["api_key"] = api_key.strip()
            run_batch(**kwargs)
        except BaseException as exc:
            error = str(exc).replace(secret_to_redact, "[REDACTED]") if secret_to_redact else str(exc)
            trace = traceback.format_exc().replace(secret_to_redact, "[REDACTED]") if secret_to_redact else traceback.format_exc()
            self.events.put({"type": "error", "message": f"{type(exc).__name__}: {error}", "traceback": trace})
        finally:
            if had_key:
                os.environ["OPENAI_API_KEY"] = old_key or ""
            else:
                os.environ.pop("OPENAI_API_KEY", None)
            self.events.put({"type": "_thread_finished"})

    def _set_row(self, card: str, **changes: Any) -> None:
        item = self.card_rows.get(card)
        if item is None:
            return
        values = list(self.results.item(item, "values"))
        indexes = {"status": 1, "score": 2, "observed": 3, "missing": 4, "output": 5}
        for key, value in changes.items():
            if key in indexes and value is not None:
                values[indexes[key]] = value
        tag = changes.get("tag")
        self.results.item(item, values=values, tags=(tag,) if tag else ())

    def _handle(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind in {"batch_start", "start"}:
            value = event.get("output_dir")
            if value:
                self.output_dir = Path(str(value))
            self._append_log(f"本批输出：{value or '—'}")
            if isinstance(event.get("quota"), dict):
                q = event["quota"]
                self.quota_note_var.set(f"UTC {q.get('utc_date', '')}：已用 {q.get('attempts', 0)}/{q.get('limit', 5)} 批")
            return
        if kind in {"card_start", "batch_card_start"}:
            self.current_card = str(event.get("card_id") or event.get("card") or "")
            self._set_row(self.current_card, status="运行中", output=str(event.get("output_dir", "")), tag="running")
            self.progress_note_var.set(f"正在运行 {self.current_card}  ({self.completed + 1}/{self.requested})")
            self._append_log(f"开始练习卡 {self.current_card}")
            return
        if kind == "card_done":
            card = str(event.get("card_id") or self.current_card)
            if event.get("termination_reason") in {"runner_error", "agent_error", "agent_initialization_error"}:
                self.had_error = True
            self._set_row(card, status=_status(event.get("termination_reason")), score=_score(event.get("score")), output=str(event.get("output_dir", "")), tag="done")
            self._append_log(f"练习卡 {card} 结束：{_status(event.get('termination_reason'))}，分数 {_score(event.get('score'))}", good=True)
            return
        if kind == "batch_card_done":
            card = str(event.get("card_id") or "")
            if event.get("termination_reason") in {"runner_error", "agent_error", "agent_initialization_error"}:
                self.had_error = True
            self._set_row(card, status=_status(event.get("termination_reason")), score=_score(event.get("total")), observed=event.get("targets_observed", "—"), missing=event.get("required_missing", "—"), output=str(event.get("output_dir", "")), tag="done")
            self.completed += 1
            self.progress.configure(value=self.completed)
            self.progress_note_var.set(f"已完成 {self.completed}/{self.requested} 张卡")
            return
        if kind == "batch_done":
            value = event.get("output_dir")
            if value:
                self.output_dir = Path(str(value))
            scores = []
            for result in event.get("results", []):
                try:
                    scores.append(float(result.get("total")))
                except (TypeError, ValueError, AttributeError):
                    pass
            if scores:
                self.batch_score_var.set(_score(sum(scores)))
            self.progress_note_var.set(f"批次完成：{len(event.get('results', []))} 张卡")
            self._append_log(f"本批完成：{value or '—'}", good=True)
            self._refresh_quota()
            return
        if kind in {"error", "runner_error"}:
            self.had_error = True
            self.status_var.set("运行失败")
            self.status_badge.configure(bg="#8d343a")
            self._append_log(str(event.get("message") or event.get("error") or "未知错误"), error=True)
            if event.get("traceback"):
                self._append_log(str(event["traceback"]), error=True)
            self._set_row(str(event.get("card_id") or self.current_card), status="运行错误", tag="error")
            return
        if kind in {"decision", "progress", "step"}:
            self.progress_note_var.set(f"{self.current_card} · 决策 {event.get('decision_sequence', event.get('step', ''))}")
            return
        if kind == "_thread_finished":
            self.active, self.worker = False, None
            stopped = self.stop_event.is_set()
            self.status_var.set("已停止" if stopped else "完成（含错误）" if self.had_error else "已完成")
            self.status_badge.configure(bg="#6b7380" if stopped else "#8d343a" if self.had_error else "#1f684f")
            self.run_button.configure(text="▶   开始本地评测", style="Primary.TButton", state="normal")
            self._set_controls_enabled(True)
            self._refresh_quota()

    def _drain_events(self) -> None:
        if self.closing:
            return
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _append_event_error(self, message: str) -> None:
        self._append_log(message, error=True)

    def _open_selected(self) -> None:
        selected = self.results.selection()
        if not selected:
            messagebox.showinfo("没有选中卡片", "请先选择结果表中的练习卡。")
            return
        self._open(self.results.item(selected[0], "values")[5])

    def _open(self, value: Any) -> None:
        if not value:
            messagebox.showinfo("没有输出路径", "运行启动后会生成对应输出目录。")
            return
        try:
            _open_path(value)
        except Exception as exc:
            messagebox.showerror("无法打开路径", f"{value}\n\n{exc}")

    def _on_close(self) -> None:
        if self.active:
            if not messagebox.askyesno("运行仍在继续", "本地练习还在运行。发送停止请求并关闭窗口吗？"):
                return
            self.stop_event.set()
        self.closing = True
        self.destroy()


def _smoke_test(output_root: Path, seconds: float) -> int:
    if _BACKEND_IMPORT_ERROR is not None or run_batch is None:
        print(f"backend import failed: {_BACKEND_IMPORT_ERROR}", file=sys.stderr)
        return 2
    try:
        ids = [_card_id(card) for card in available_cards()]
        result = run_batch(Path(default_agent_path()), ids, 0, output_root,
                           wallclock_seconds=seconds, enforce_quota=False, mode="official-fixed")
        errors = [x for x in result.get("results", []) if x.get("termination_reason") == "runner_error"]
        print(f"cards={len(result.get('results', []))} runner_errors={len(errors)}", file=sys.stderr)
        return int(bool(errors))
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GOSIM v4 本地评测 GUI")
    parser.add_argument("--smoke-test", metavar="OUTPUT_ROOT", help="无界面运行后端卡片，用于构建检查")
    parser.add_argument("--smoke-test-seconds", type=float, default=2.0, help="每卡运行秒数，默认 2")
    args = parser.parse_args(argv)
    if args.smoke_test:
        return _smoke_test(Path(args.smoke_test), args.smoke_test_seconds)
    app = PracticeApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
