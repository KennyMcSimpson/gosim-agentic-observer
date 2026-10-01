# 上游来源与本地修改

- 检查日期：2026-10-01（北京时间）。
- 官方入门包：2026-09-30 从官网 Resources 页当前下载地址获取的 agent-observer-starter-kit.zip，SHA-256 为 31D8FBA44BFBE0DB14FA15203421BA62572A967DD623EE0A0EF4B8622BDCAD3F。此前用户提供的 2026-09-26 ZIP 哈希为 825EF59E7D110E5FB6A2FEA44805A31DC932565719DB6BE88FB9578E88BC4A52；当前包已经变更，本应用的运行器与 Agent 以当前包为准。
- 从当前包复制 local_runner.py、运行所需的 challenge/*.py、回放模板、官方最简 Agent 及 dev-reference 公开场景。当前运行器包含末尾 finish 消息和 30 秒收尾宽限。
- dev-fortnight 用入门包 fetch_scenario.py 于 2026-09-30 从官网公开场景接口下载；脚本报告 22 个文件的 manifest SHA-256 校验通过。
- 唯一上游运行器改动：local_runner.py 的 build_agent_env 在 Windows 上把 TEMP、TMP 指向运行目录的 scratch，并传递 SYSTEMROOT，以允许 PyInstaller 内置 Agent Host 解包。应用调用时把官网完整项目练习的场景上限显式设为 18000 秒；公开场景文件自带的默认值较短。仿真与评分公式未修改。
- 本地构建会先把 agent/ 复制到忽略 `.env`、常见 `secret`/`credential`/`password`/`api_key`/`access_token` 文件、证书密钥和 Python 缓存的暂存目录，再交给 PyInstaller，避免个人本地模型配置进入桌面包；CI smoke 会校验根/agent manifest、声明的完整项目入口、JSONL v2 envelope 和无环境文件输入。
- GitHub Actions 的 tag 发布会从同一批通过 smoke 的 ZIP/EXE 生成 `SHA256SUMS.txt`；README 使用 latest Release 链接，避免旧版本桌面包与当前源码脱节。
- 根完整项目 manifest 当前回到官方示例的 `MODEL_PROVIDER=deterministic`，用于无密钥的公开场景云端 smoke；模型依赖文件和平台 `OPENAI_BASE_URL`/`OPENAI_API_KEY` 适配仍保留，但没有带 key 的模型云端 smoke 证据。当前仍只有一个已实现的模型决策环节，未声称满足正式奖项的两阶段要求。
- 原包没有找到明确的 LICENSE/COPYING 文件；上游代码与数据不在此声明为我们的原创，也不以本仓库为它们授予新许可证。用户明确要求队友可直接访问，因此仓库现为 public；公开使用前应保留上游来源说明，并注意上游未提供明确再分发许可。
