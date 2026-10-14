# AgentForge AI P3 Docker Sandbox

2026 年 10 月 15 日，Asia/Shanghai。项目根目录：`D:\AIProjects\AgentForge-AI`。

本项目按已确认的 P0 基线完成 P1–P3。现有骨架包括 FastAPI/React、四模型配置、真实 PostgreSQL/Redis、LangGraph 异步协作、审批、取消、预算预留和 SSE。P3 已实现并实际验收独立可信 Runner、受限 Docker Python 执行和真实 Sandbox Center。模型回答与模型费用仍为明确 Mock，未接通真实模型、MCP 或 Skills。

## 文档入口

- [本地启动指南](docs/GETTING_STARTED.md)
- [源码学习路径](docs/LEARNING_PATH.md)
- [P1 完成报告](docs/P1_REPORT.md)
- [项目状态](docs/PROJECT_STATUS.md)
- [P2 工作流契约](docs/P2_CONTRACT.md)
- [P2 完成报告](docs/P2_REPORT.md)
- [P3 实施与验收报告](docs/P3_REPORT.md)
- [沙箱安全边界](docs/SANDBOX_SECURITY.md)
- [沙箱执行协议](docs/SANDBOX_EXECUTION_PROTOCOL.md)
- [P1 执行范围](docs/P1_SCOPE.md)
- [架构设计与技术选型](docs/P0_ARCHITECTURE.md)
- [原方案与新基线差异](docs/P0_CHANGES.md)
- [目录规划与实施路线图](docs/P0_IMPLEMENTATION_PLAN.md)
- [自动化验收标准](docs/P0_ACCEPTANCE.md)
- [P0 完成报告](docs/P0_REPORT.md)

## 核心决策

采用 FastAPI、LangGraph、LangChain、React、PostgreSQL、Redis 和 SSE。四个独立模型槽位分别服务 Planner、Coder、Researcher、Reviewer。P2 Mock 工作流保持不变；P3 代码执行经过受限服务端 Runner，独立审批不能替代权限检查。MCP Tool Gateway 与 Skills 的真实执行仍待后续授权。

不可信代码只在符合安全策略的 Docker Linux 容器内执行。Docker 不可用或关键隔离机制无法验证时 Fail Closed，禁止宿主机执行回退。预热默认关闭；未来预热只能单次租赁使用，执行后销毁，不复用执行过不可信代码的容器。

Docker 共享内核，存在逃逸及宿主机风险，不能视为绝对安全。Compose 中 PostgreSQL/Redis 是持久化开发服务；独立 `runner` 是可信控制面，具有 Docker daemon Socket 权限。实际执行容器是固定非 root、无网络、只读根、资源受限的一次性容器，不挂载 Socket 或宿主机目录。P3 默认禁止预热复用。

本地访问前端 `http://127.0.0.1:15173/sandbox`、后端文档 `http://127.0.0.1:18100/docs`。Runner 默认 `127.0.0.1:18120`，仅可信 Worker 用独立服务端 Token 调用，不是公共 API。启动、镜像登记、独立审批与测试命令见 GETTING_STARTED。

## 当前状态

P3 已完成验收并暂停，等待 P4 单独授权。最终 Python 测试 153/153 通过（117 单元/HTTP、36 真实集成，其中沙箱 16 项），浏览器 8/8 通过，无失败或跳过。类型检查、前端构建、迁移、pip check 和实际 OS Worker 重启验证通过；阶段结束无任何策略版本的遗留执行容器。

真实 PostgreSQL/Redis 健康，当前可信 Runner 可用。测试不能证明内核/VM 无逃逸，也未专门强杀 Runner OS 进程以覆盖全部崩溃窗口。完整证据、修复过程、残余风险和提交见 P3_REPORT 与 PROJECT_STATUS。P0/P1/P2 历史报告保留，不自动进入 P4。
