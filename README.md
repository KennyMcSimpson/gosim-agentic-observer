# GOSIM 巡天智能体 v4 本地评测台

这个仓库用于调试提交到平台的 Agent。默认入口是 `agent/baseline_agent.py`，本地评测使用官方 v4 runner，但测试环境分成两类：四张固定的 alpha–delta 校准卡，以及完全独立的 seed 额外测试。

## 两类本地卡

`alpha`、`beta`、`gamma`、`delta` 保留用户提供 ZIP 中的公开目标、脚印和夜间日历。平台没有公开天气真值、事件真值、观测请求和完整预报。本地分别拟合这些缺失环境，再把完整文件冻结在 `simulator/calibration-v1/`；应用逐文件校验 SHA256 后加载，不会重新抽样。它们是本地合成环境，不是恢复出的官方隐藏真值。

2026-10-04 用官方裸 Agent、900 秒预算完整重跑，均以 `survey_complete` 结束：α 3336.68（+92.85）、β 4586.39（+27.94）、γ 3817.94（−75.19）、δ 3036.41（+60.85）。四卡都在截图目标 ±100 内。应用启动时显示这份冻结裸 Agent 记录；开始评测后显示本次 Agent 成绩。完整哈希、分项和计数见 [验证记录](simulator/calibration-v1/validation_report.json) 和 [校准说明](CALIBRATION_RESULTS.md)。

Seed 模式使用 `alpha-like`、`beta-like`、`gamma-like`、`delta-like` 基础 profile，卡片 ID 形如 `synthetic-alpha-like-seed-42`。它保留对应公开目录和日历，生成独立天气、事件、设备状态及请求目标；不继承校准调参，不覆盖固定卡。该页隐藏截图参照，运行明细展示生成 ID 和环境摘要。

官方 examples 的 L1–L4、真值和 runner 回归材料已迁移到团队仓库 `gosim-2026-team/training/official-v4/`。主应用不再把 L1–L4 当作默认测试卡；需要验证官方 runner 时，在团队仓库执行回归说明中的命令。

## 本地运行

Windows 使用仓库解释器：

```powershell
.venv\Scripts\python.exe practice_gui.py
```

也可以直接运行一张固定校准卡：

```powershell
.venv\Scripts\python.exe -c "from pathlib import Path; from practice_backend import run_batch; run_batch(Path('agent/baseline_agent.py'), ['alpha'], 0, Path('run_output/alpha'), enforce_quota=False, wallclock_seconds=900, mode='alpha-calibration')"
```

GUI 支持每卡最长 900 秒、可选本地每日 5 批额度、运行目录和 AnyRouter/OpenAI 兼容接口。Key 由使用者在应用中填写，无需交给仓库维护者。应用不保存 Key；确定性模式隔离环境变量和 Agent `.env` 中的 API 配置。自定义 Agent 应自行遵守密钥日志约定。900 秒是运行预算，巡天提前完成即可结束；短 smoke 不用于证明分数达标。

`runner_worker.py` 只解决 Windows 匿名管道无法使用 `select()` 的进程边界问题；`vendor/gosim-official-v4/runner/` 中的官方评分文件不做修改。

## 结果解释

每张卡输出 `score_report.json` 和 `run_manifest.json`，批次输出 `batch_summary.json`。报告记录总分、目标观测数、必做目标缺失数、报告结算、均匀性惩罚、限时请求和动作/观测/决策数量。输入、Agent 和评分器版本均有哈希记录。`decisions`、`observe_actions` 与 `observations` 分别展示，不冒充未核准语义的“结果提交数”。固定卡记录截图目标、参考高分和差值；批次显示平均分。8000/7400 是参考高分，不用于缩放实际评分。

## 下载应用

[最新桌面版](https://github.com/KennyMcSimpson/gosim-agentic-observer/releases/latest) 提供 Windows EXE、Windows ZIP 和 macOS 双架构 ZIP。使用包含 `calibration-v1` 的 v0.4.0 或更新版本。

## 来源与许可

`vendor/public-input/alpha` 到 `delta` 是 2026-10-03 收到的公开 taskcard ZIP，仅保留公开输入。`vendor/gosim-official-v4` 是 GOSIM examples 包的本地开发副本，按上游 CC BY-NC 4.0 保留署名与许可。详见 [VENDOR_PROVENANCE.md](VENDOR_PROVENANCE.md)。

线上提交仍只需要 `observer.project.json` 指向的 JSONL Agent；本地 GUI、模拟器和 score report 不会被当作官方提交结果。
