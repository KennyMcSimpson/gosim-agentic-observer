# Local runner

Run any agent against the public local practice cards (`L1`-`L4` in this folder's parent)
and get the same score breakdown the platform computes -- completely offline, no submission,
no API key beyond what your own agent needs for its LLM calls.

本地分数用来调试，正式成绩以平台为准。
Local scores are for debugging; official results come from the platform.

## Why you can trust this score

`run_local.py` is the only new code in this folder. Everything under `challenge/` and
`project_platform/` is an unmodified, byte-identical copy of the files the cloud platform
itself runs to score a project submission (traced from `project_platform/trusted_engine.py`'s
`run_v4_session`, which calls `challenge.v4_workflow.V4Workflow.run(...)` the same way
`run_local.py` does here). `ENGINE_MANIFEST.json` records the sha256 of every copied file and
the source commit; run `python3 verify_engine.py` any time to confirm nothing has drifted.

The whole engine/scoring chain is pure Python standard library -- see `requirements.txt`.
Nothing to install.

## Usage

```bash
python3 verify_engine.py   # optional: confirm the engine files are untouched

python3 run_local.py --card L1 --agent "python3 agent.py" --agent-cwd /path/to/your/agent
python3 run_local.py --card L2 --agent "node dist/index.js" --agent-cwd /path/to/ts-agent
python3 run_local.py --card L3 --agent "./rust-agent" --agent-cwd /path/to/rust-agent/target/release
```

`--card` takes a card name (`L1`..`L4`, resolved under this folder's parent) or any path to
a card folder. `--agent` takes a full command, split with `shlex` and run directly (no shell) --
any language works, as long as your agent speaks `participant-agent-protocol-v4` (one JSON
object per line on stdin/stdout). Put `OPENAI_BASE_URL` / `OPENAI_API_KEY` in a `.env` file in
`--agent-cwd` to try an LLM-backed agent locally.

Run `python3 run_local.py --help` for every option (wall clock, output folder, timeouts, etc.).

Outputs land in `--out` (default `run_output/`): `decisions.csv`, `observations.csv`,
`messages.jsonl`, `score_report.json`, `workflow_result.json`, `actions.jsonl`, `agent.log`.
The last line printed to stdout is a JSON score summary.

---

# 本地评分工具

对本目录上级的公开练习卡（`L1`-`L4`）运行你的 agent，拿到和平台一致的完整分数细项 --
完全离线，不需要提交，除了你的 agent 自己调用 LLM 需要的 key 之外不需要别的密钥。

本地分数用来调试，正式成绩以平台为准。
Local scores are for debugging; official results come from the platform.

## 为什么这个分数可信

本目录下唯一的新代码是 `run_local.py`。`challenge/` 和 `project_platform/` 下的所有文件都是
云端平台给项目提交计分时实际运行的文件的**未经修改、逐字节一致**的拷贝（从
`project_platform/trusted_engine.py` 的 `run_v4_session` 一路追溯而来，它调用
`challenge.v4_workflow.V4Workflow.run(...)` 的方式和这里的 `run_local.py` 完全一样）。
`ENGINE_MANIFEST.json` 记录了每个拷贝文件的 sha256 和来源 commit；随时运行
`python3 verify_engine.py` 即可确认文件没有被改动过。

整条引擎/打分链路全部是 Python 标准库，见 `requirements.txt`，不需要安装任何东西。

## 用法

```bash
python3 verify_engine.py   # 可选：确认引擎文件未被改动

python3 run_local.py --card L1 --agent "python3 agent.py" --agent-cwd /path/to/your/agent
python3 run_local.py --card L2 --agent "node dist/index.js" --agent-cwd /path/to/ts-agent
python3 run_local.py --card L3 --agent "./rust-agent" --agent-cwd /path/to/rust-agent/target/release
```

`--card`接受卡片名（`L1`..`L4`，相对本目录上级解析）或任意卡片目录路径。`--agent`
接受一整条命令，用 `shlex` 拆分后直接运行（不经过 shell）-- 只要你的 agent 用
`participant-agent-protocol-v4`（stdin/stdout 上每行一个 JSON 对象）说话，任何语言都可以。
想在本地试跑接 LLM 的 agent，把 `OPENAI_BASE_URL` / `OPENAI_API_KEY` 写进
`--agent-cwd` 目录下的 `.env` 文件即可。

运行 `python3 run_local.py --help` 查看全部选项（时间墙、输出目录、超时等）。

输出落在 `--out`（默认 `run_output/`）：`decisions.csv`、`observations.csv`、
`messages.jsonl`、`score_report.json`、`workflow_result.json`、`actions.jsonl`、`agent.log`。
标准输出的最后一行是 JSON 格式的分数摘要。
