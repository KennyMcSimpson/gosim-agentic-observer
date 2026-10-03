# GOSIM Agentic Observer 示例项目 / Example projects

- `python/` `typescript/` `rust/`：三个完整的示例智能体项目，各自的 README 和 AGENTS.md 说明如何配置与打包上传。
- `docs/`：参赛文档（中文 / English）。
- `local-cards/L1`–`L4`：四张完全公开的本地练习卡。
- `runner/`：本地裁判程序，与平台使用同一份评测代码（`python3 runner/verify_engine.py` 可核对）。只需要 Python 3，无需安装任何库。

## 本地跑分 / Local scoring

```
python3 runner/run_local.py --inherit-env --card local-cards/L1 --agent "python3 python/agent.py"
python3 runner/run_local.py --inherit-env --card local-cards/L1 --agent "node typescript/dist/index.js"   # 先 cd typescript && npm ci && npm run build
python3 runner/run_local.py --inherit-env --card local-cards/L1 --agent "./rust/target/release/rust-agent" # 先 cd rust && cargo build --release
```

运行前设置大模型密钥：`export OPENAI_API_KEY=...`（默认 Kimi Coding Plan，见各项目 README）。

本地分数用来调试，正式成绩以平台为准。
Local scores are for debugging; official results come from the platform.
