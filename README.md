# GOSIM 本地完整项目练习器

一个只在本机运行的桌面练习应用。它让你选择自己的 Python Agent，按官方公开的完整项目练习流程，在 dev-fortnight 和 dev-reference 场景上逐轮运行，每场景上限 18000 秒，并用随入门包提供的评分器计算结果。每次运行都会另存完整轨迹、评分报告、Agent 日志和回放页面；可以反复运行。

这里仅实现公开场景的本地练习。应用不连接赛事账号、不上传作品，也不模拟隐藏场景或云端容器。练习赛每日 5 次是官网的云端提交额度，本地运行没有这个额度。

## 使用

1. Windows：直接下载 [GOSIMPractice.exe](https://github.com/KennyMcSimpson/gosim-agentic-observer/releases/download/v0.1.0/GOSIMPractice.exe)，保存后双击运行。macOS：从 [v0.1.0 Release](https://github.com/KennyMcSimpson/gosim-agentic-observer/releases/tag/v0.1.0) 下载与你的处理器对应的 ZIP，解压后打开 GOSIMPractice.app。
2. 默认使用随应用附带的官方最简确定性 Agent。也可以选择你自己的 agent.py、minimal_agent.py、main.py 或其所在文件夹。
3. 勾选一个或两个公开场景，选输出目录，点击“开始本地练习”。界面展示各场景分数和状态；“打开结果”可查看 score_report.json、decisions.csv、agent.log 和 decision_replay.html。
4. 再次点击运行会建立新的结果目录，不覆盖上一次。

内置 Agent Host 运行标准库 Python Agent。若自己的 Agent 依赖额外 Python 包，在界面选择安装了这些依赖的 Python 3.9+ 解释器；此时它替代内置 Agent Host，仅用于运行所选 Agent。Agent 文件夹的 .env 如存在，仍由本地 runner 读取；不要把密钥放入本仓库。

## 从源码运行与构建

需要 Python 3.12（含 Tkinter）。

    python practice_gui.py
    python -m pip install 'pyinstaller>=6,<7'
    python scripts/build.py

打包脚本在当前操作系统上生成对应应用；Windows 与 macOS 需要分别在各自系统构建。仓库的 GitHub Actions 工作流构建并用内置 Agent 实跑两个场景，然后将系统包附到版本 Release。CI 的无界面实跑验证 JSONL 协议、逐轮仿真和评分；macOS 图形界面仍需在真实 Mac 上打开检查。当前包没有代码签名或公证，系统可能显示首次打开警告。

## 范围与来源

- 本应用调用入门包中的 local_runner.py、challenge/ 评分与仿真模块、最简 Agent，并附公开场景数据；未引入本地 local-lab/、H0/H1 研究工具或参赛提交逻辑。
- dev-fortnight 从官网公开场景接口获取；dev-reference 随入门包提供。场景文件依公开 manifest 校验。上游资料与本地改动见 [VENDOR_PROVENANCE.md](VENDOR_PROVENANCE.md)。
- 本地分数只说明当前打包的公开数据和评分器输出，不能代表正式赛的隐藏场景成绩。以[赛事当前规则](https://create.gosim.org/survey26/platform/rules)与主办方公告为准。
