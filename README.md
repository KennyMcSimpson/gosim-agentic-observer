# GOSIM 巡天智能体 v4 本地评测台

这个仓库现在只保留 v4 流程：官方 examples 的 Python anchor-search Agent、官方公开 L1–L4 本地卡、官方 v4 runner，以及一个可选的桌面评测界面。

## 先分清三种卡

`vendor/gosim-official-v4/local-cards/L1` 到 `L4` 是 examples 包附带的完整本地卡。它们包含 `config/`、公开输入和裁判 truth，可以离线调用官方 runner 评分。分数只用于本地调试，不能当作线上或隐藏卡成绩。

官网练习用的 alpha、beta、gamma、delta 是另一组云端卡。仓库不会把 L1–L4 冒充 alpha–delta。`vendor/public-input/alpha/` 到 `delta/` 保存四个 ZIP 的公开配置和目标目录；它们都没有 truth、天气、事件或 observation requests，因此不能凭它们复现官方分数。正式平台会在运行时逐步提供允许 Agent 看到的公告和预报，裁判真值仍在平台侧。

官方 examples 的裸 Agent 已放在 `agent/baseline_agent.py` 和 `agent/agent_core/`。本地没有 key 时，入口会把模型请求导向立即失败的本地地址，让官方 planner 使用自己的确定性回退；平台或 GUI 提供 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和 `OPENAI_MODEL` 时，才会启用 OpenAI 兼容模型调用。

## 运行 Agent

在 Windows 机器上使用仓库自带的解释器：

```powershell
.venv\Scripts\python.exe runner_worker.py --card L1 --agent ".venv\Scripts\python.exe -u agent\baseline_agent.py" --agent-cwd . --wallclock 30 --out run_output\cli-l1
```

运行四张卡：

```powershell
.venv\Scripts\python.exe -c "from pathlib import Path; from practice_backend import run_batch; run_batch(Path('agent/baseline_agent.py'), ['L1','L2','L3','L4'], 0, Path('run_output/batch'), enforce_quota=False, wallclock_seconds=900, mode='official-fixed')"
```

Windows 的 `select()` 不能轮询匿名管道，`runner_worker.py` 只在本地进程边界提供线程队列适配；`vendor/gosim-official-v4/runner/challenge/` 和评分文件保持官方 `ENGINE_MANIFEST.json` 的字节校验。

## 桌面界面

```powershell
.venv\Scripts\python.exe practice_gui.py
```

界面支持：选择 L1–L4、每卡 900 秒上限、可选本地五批额度、逐卡进度和分数、输出目录与回放目录、官方 anchor-search Agent，以及 OpenAI 兼容接口（包括 AnyRouter）。API key 只在当前运行进程的环境中使用，不写入仓库、设置文件或日志。

`官方固定卡` 模式读取卡片自带的固定天气和事件 truth。`Seed 压力测试` 模式复制官方卡，只扰动隐藏 weather truth 的数值，用来测试策略鲁棒性；它不是官方卡，也不等价于主办方重新生成的 alpha–delta。

## 提交入口

根目录 `observer.project.json` 已声明 `jsonl-v4`，平台入口是 `agent/baseline_agent.py`。GUI、runner 和本地卡不参与线上提交。若改用自己的 Agent，只要它从 stdin 读取 JSONL、向 stdout 输出 JSONL，并遵守 v4 协议即可。

## 来源与许可

`vendor/gosim-official-v4/` 来自 GOSIM 2026 Agentic Observer examples release，包含官方公开卡、runner、文档和 `LICENSE.md`。组织方材料按 CC BY-NC 4.0 使用，仓库保留署名和许可文件；参赛队自己写的 Agent 代码仍归参赛队所有。详见 [VENDOR_PROVENANCE.md](VENDOR_PROVENANCE.md)。

本地结果只用于调试，正式结果以平台为准。
