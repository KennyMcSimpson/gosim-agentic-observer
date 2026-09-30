# 上游来源与本地修改

- 检查日期：2026-09-30（北京时间）。
- 官方入门包：2026-09-30 从官网 Resources 页当前下载地址获取的 agent-observer-starter-kit.zip，SHA-256 为 31D8FBA44BFBE0DB14FA15203421BA62572A967DD623EE0A0EF4B8622BDCAD3F。此前用户提供的 2026-09-26 ZIP 哈希为 825EF59E7D110E5FB6A2FEA44805A31DC932565719DB6BE88FB9578E88BC4A52；当前包已经变更，本应用的运行器与 Agent 以当前包为准。
- 从当前包复制 local_runner.py、运行所需的 challenge/*.py、回放模板、官方最简 Agent 及 dev-reference 公开场景。当前运行器包含末尾 finish 消息和 30 秒收尾宽限。
- dev-fortnight 用入门包 fetch_scenario.py 于 2026-09-30 从官网公开场景接口下载；脚本报告 22 个文件的 manifest SHA-256 校验通过。
- 唯一上游运行器改动：local_runner.py 的 build_agent_env 在 Windows 上把 TEMP、TMP 指向运行目录的 scratch，并传递 SYSTEMROOT，以允许 PyInstaller 内置 Agent Host 解包。应用调用时把官网完整项目练习的场景上限显式设为 18000 秒；公开场景文件自带的默认值较短。仿真与评分公式未修改。
- 原包没有找到明确的 LICENSE/COPYING 文件；上游代码与数据不在此声明为我们的原创，也不以本仓库为它们授予新许可证。当前 GitHub 仓库按 private 处理，仅供用户自己的本地练习；公开 Release 前需要取得上游再分发许可，或改成首次运行时下载并校验公开资源。
