# AgentForge AI P0 架构基线

2026 年 10 月 14 日，Asia/Shanghai。项目根目录：`D:\AIProjects\AgentForge-AI`。

本次最新需求作为正式 P0 基线。旧方案来自 ChatGPT 对话，没有可核实的规划文件和实现清单；不认定已有可运行项目。本轮仅完成规划文档，P1 必须获得用户明确确认后开始。

## 文档入口

- [架构设计与技术选型](docs/P0_ARCHITECTURE.md)
- [原方案与新基线差异](docs/P0_CHANGES.md)
- [目录规划与实施路线图](docs/P0_IMPLEMENTATION_PLAN.md)
- [自动化验收标准](docs/P0_ACCEPTANCE.md)
- [P0 完成报告](docs/P0_REPORT.md)

## 核心决策

采用 FastAPI、LangGraph、LangChain、React、PostgreSQL、Redis 和 SSE。四个独立模型槽位分别服务 Planner、Coder、Researcher、Reviewer。所有工具调用经过服务端 Tool Gateway；人工审批不能替代权限校验。

不可信代码只在符合安全策略的 Docker Linux 容器内执行。Docker 不可用或关键隔离机制无法验证时 Fail Closed，禁止宿主机执行回退。预热容器单次租赁使用，执行后销毁，不复用执行过不可信代码的容器。

Docker 共享内核，存在逃逸及宿主机风险，不能视为绝对安全。文档中的限制参数是拟实施的初始值，尚未运行或验证。

## 当前状态

P0 文档已完成，等待确认。没有生成应用代码、Dockerfile、Compose、迁移脚本、依赖锁文件或可执行测试，没有部署或启动服务。后续自动化测试的设计不代表测试已通过。
