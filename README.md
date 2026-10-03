# GOSIM 巡天智能体 v4 本地评测台

这个仓库用于调试提交到平台的 Agent。默认入口是 `agent/baseline_agent.py`，本地评测使用官方 v4 runner，但测试环境分成两类：四张固定的 alpha–delta 校准卡，以及完全独立的 seed 额外测试。

## 两类本地卡

`alpha`、`beta`、`gamma`、`delta` 保留用户提供 ZIP 中的公开目标、脚印和夜间日历。平台没有公开天气真值、事件真值、观测请求和完整预报，因此 `simulator/cards.py` 按固定版本生成这些缺失文件。生成结果是可重复的本地合成环境，不是官方隐藏真值；界面中的冻结基线和官网高分只是来自用户截图的校准参照。

Seed 模式使用 `alpha-like`、`beta-like`、`gamma-like`、`delta-like` 基础 profile，卡片 ID 形如 `synthetic-alpha-like-seed-42`。它为额外稳健性测试生成独立环境，永远不会覆盖固定校准卡，也不会与 alpha–delta 的校准分数混在一起。

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

GUI 支持每卡最长 900 秒、可选本地每日 5 批额度、运行目录和 AnyRouter/OpenAI 兼容接口。API key 只在当前进程使用，不写入设置、日志或仓库。没有 key 时 Agent 使用确定性回退，适合先调试协议和策略。

`runner_worker.py` 只解决 Windows 匿名管道无法使用 `select()` 的进程边界问题；`vendor/gosim-official-v4/runner/` 中的官方评分文件不做修改。

## 结果解释

每张卡输出 `score_report.json` 和 `batch_summary.json`。报告会记录总分、目标观测数、必做目标缺失数、报告结算、均匀性惩罚、限时观测请求和动作/观测/决策数量。固定卡还记录截图基线、校准目标、参考高分以及 `calibration_residual`，便于调 Agent；这些字段不代表平台的隐藏成绩。

## 来源与许可

`vendor/public-input/alpha` 到 `delta` 是 2026-10-03 收到的公开 taskcard ZIP，仅保留公开输入。`vendor/gosim-official-v4` 是 GOSIM examples 包的本地开发副本，按上游 CC BY-NC 4.0 保留署名与许可。详见 [VENDOR_PROVENANCE.md](VENDOR_PROVENANCE.md)。

线上提交仍只需要 `observer.project.json` 指向的 JSONL Agent；本地 GUI、模拟器和 score report 不会被当作官方提交结果。
