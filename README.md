# AgentForge AI P1 项目基础

2026 年 10 月 14 日，Asia/Shanghai。项目根目录：`D:\AIProjects\AgentForge-AI`。

本项目按已确认的 P0 基线及本次 P1 范围构建。现有能力为 FastAPI/React 项目骨架、真实健康联调、四模型配置校验与 PostgreSQL 持久化；模型调用、Agent、沙箱、MCP、Skills 和审批执行尚未实现。

## 文档入口

- [本地启动指南](docs/GETTING_STARTED.md)
- [源码学习路径](docs/LEARNING_PATH.md)
- [P1 完成报告](docs/P1_REPORT.md)
- [项目状态](docs/PROJECT_STATUS.md)
- [P1 执行范围](docs/P1_SCOPE.md)
- [架构设计与技术选型](docs/P0_ARCHITECTURE.md)
- [原方案与新基线差异](docs/P0_CHANGES.md)
- [目录规划与实施路线图](docs/P0_IMPLEMENTATION_PLAN.md)
- [自动化验收标准](docs/P0_ACCEPTANCE.md)
- [P0 完成报告](docs/P0_REPORT.md)

## 核心决策

采用 FastAPI、LangGraph、LangChain、React、PostgreSQL、Redis 和 SSE。四个独立模型槽位分别服务 Planner、Coder、Researcher、Reviewer。所有工具调用经过服务端 Tool Gateway；人工审批不能替代权限校验。

不可信代码只在符合安全策略的 Docker Linux 容器内执行。Docker 不可用或关键隔离机制无法验证时 Fail Closed，禁止宿主机执行回退。预热容器单次租赁使用，执行后销毁，不复用执行过不可信代码的容器。

Docker 共享内核，存在逃逸及宿主机风险，不能视为绝对安全。当前 Compose 是基础服务开发环境，不是代码执行沙箱。

## 当前状态

P1 基础实现已完成，验证结果见 P1_REPORT。P0 文档作为历史架构基线保留。P2 未开始，必须获得用户另行确认。
