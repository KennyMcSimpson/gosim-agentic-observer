# 上游来源与本地修改

- 检查日期：2026-10-01（北京时间）。
- 官方入门包：2026-09-30 从官网 Resources 页当前下载地址获取的 agent-observer-starter-kit.zip，SHA-256 为 31D8FBA44BFBE0DB14FA15203421BA62572A967DD623EE0A0EF4B8622BDCAD3F。此前用户提供的 2026-09-26 ZIP 哈希为 825EF59E7D110E5FB6A2FEA44805A31DC932565719DB6BE88FB9578E88BC4A52；当前包已经变更，本应用的运行器与 Agent 以当前包为准。
- 从当前包复制 local_runner.py、运行所需的 challenge/*.py、回放模板、官方最简 Agent 及 dev-reference 公开场景。当前运行器包含末尾 finish 消息和 30 秒收尾宽限。
- dev-fortnight 用入门包 fetch_scenario.py 于 2026-09-30 从官网公开场景接口下载；脚本报告 22 个文件的 manifest SHA-256 校验通过。
- 唯一上游运行器改动：local_runner.py 的 build_agent_env 在 Windows 上把 TEMP、TMP 指向运行目录的 scratch，并传递 SYSTEMROOT，以允许 PyInstaller 内置 Agent Host 解包。应用调用时把官网完整项目练习的场景上限显式设为 18000 秒；公开场景文件自带的默认值较短。仿真与评分公式未修改。
- 本地构建会先把 agent/ 复制到忽略 `.env`、常见 `secret`/`credential`/`password`/`api_key`/`access_token` 文件、证书密钥和 Python 缓存的暂存目录，再交给 PyInstaller，避免个人本地模型配置进入桌面包；CI smoke 会校验根/agent manifest、声明的完整项目入口、JSONL v2 envelope 和无环境文件输入。
- GitHub Actions 的 tag 发布会从同一批通过 smoke 的 ZIP/EXE 生成 `SHA256SUMS.txt`；README 使用 latest Release 链接，避免旧版本桌面包与当前源码脱节。
- 根完整项目 manifest 使用平台要求的 `MODEL_PROVIDER=openai`、`.deps` build 和 `PYTHONPATH=.deps`；六个直接依赖已固定到 2026-10-01 现场解析成功的版本，没有 key 的本地 smoke 会明确回退到确定性路径。模型阶段现在是夜初 planner 加合法候选 selector 两个有界环节，默认每 7 个新夜晚最多各调用一次，默认单次超时 4 秒、无重试；仍没有带真实 key 的云端模型 smoke 证据，不能把正式评奖准备宣称为已完成。
- 原包没有找到明确的 LICENSE/COPYING 文件；上游代码与数据不在此声明为我们的原创，也不以本仓库为它们授予新许可证。用户明确要求队友可直接访问，因此仓库现为 public；公开使用前应保留上游来源说明，并注意上游未提供明确再分发许可。

## v4 harness provenance

- 核查日期：2026-10-02（北京时间）。官方 v4 资料来源为 [Rules](https://create.gosim.org/survey26/platform/rules)、[Resources](https://create.gosim.org/survey26/platform/resources) 和 [官方 `skill-v4.md`](https://create.gosim.org/survey26/platform/skill-v4.md)。这些页面用于核对 `participant-agent-protocol-v4`、动作集合、曝光范围、墙钟时间、评分字段和错误语义；它们不是本地 fixture 的成绩来源。
- 本地 v4 harness 位于 `challenge/v4_protocol.py`、`challenge/v4_geometry.py`、`challenge/v4_scorer.py` 和 `challenge/v4_workflow.py`，确定性 smoke Agent 位于 `agent/v4_minimal_agent.py`。这些文件组成独立的本地契约回归入口；根目录 `observer.project.json` 仍为 `observer-project-v1` / `jsonl-v2` 的 v3 练习入口，没有切换正式提交协议。
- `scenarios/v4-demo/` 是本仓库本地构造的契约 fixture：`config/` 描述 v4 场景、光纤和评分边界，`public/` 与 `truth/` 提供可重复的本地输入。其 `task_card.card_id` 为 `demo`、站点为虚拟 Paranal、光纤数为 16、最低高度角为 30 度、曝光范围为 60--3600 秒；它不是 Resources 页下载的官方 α--δ、A--D 或 E--H 任务卡，也不代表任何正式成绩。
- fixture provenance：fixture 的目录结构和字段形状按公开 v4 契约组织，具体目标、天气、事件、请求、日历和评分参数是为本地协议/评分回归准备的仓库内输入；没有把云端私有卡、登录态数据或隐藏赛数据复制进来。由此产生的 `score_report.json` 只能说明本地 fixture 和本地 scorer 的行为。
- 本次 v4 harness、fixture 和文档范围不包含密码、模型 API key、访问令牌、其他凭据、讲座视频或私人数据。不要把本地 Agent 的 `.env`、密钥或私人实验文件放入仓库、ZIP 或发布包。
