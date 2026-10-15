# AgentForge AI P5 模型集成与有界协作

2026 年 10 月 15 日，Asia/Shanghai。项目根目录：`D:\AIProjects\AgentForge-AI`。

本项目保留 P0–P4 基线，并按单独授权实现 P5。现有骨架包括 FastAPI/React、四模型配置、真实 PostgreSQL/Redis、LangGraph 异步协作、审批、取消、预算预留和 SSE。P3 已实现并实际验收独立可信 Runner、受限 Docker Python 执行和真实 Sandbox Center。P4 增加真实受控 MCP stdio Client/Server、服务端 Tool Gateway 和声明式 Skills Registry。P5 增加四模型适配、真实调用路径、服务端预算、有界协作和 Chat；当前未配置真实 Key/测试额度，外部 API 验收 BLOCKED，默认使用明确 Mock。

## 文档入口

- [本地启动指南](docs/GETTING_STARTED.md)
- [源码学习路径](docs/LEARNING_PATH.md)
- [P1 完成报告](docs/P1_REPORT.md)
- [项目状态](docs/PROJECT_STATUS.md)
- [P2 工作流契约](docs/P2_CONTRACT.md)
- [P2 完成报告](docs/P2_REPORT.md)
- [P3 实施与验收报告](docs/P3_REPORT.md)
- [P4 契约与安全边界](docs/P4_CONTRACT.md)
- [P4 实施与验收报告](docs/P4_REPORT.md)
- [P5 开发与验收报告](docs/P5_REPORT.md)
- [模型集成与预算边界](docs/MODEL_INTEGRATION.md)
- [Multi-Agent 流程](docs/MULTI_AGENT.md)
- [沙箱安全边界](docs/SANDBOX_SECURITY.md)
- [沙箱执行协议](docs/SANDBOX_EXECUTION_PROTOCOL.md)
- [P1 执行范围](docs/P1_SCOPE.md)
- [架构设计与技术选型](docs/P0_ARCHITECTURE.md)
- [原方案与新基线差异](docs/P0_CHANGES.md)
- [目录规划与实施路线图](docs/P0_IMPLEMENTATION_PLAN.md)
- [自动化验收标准](docs/P0_ACCEPTANCE.md)
- [P0 完成报告](docs/P0_REPORT.md)

## 核心决策

采用 FastAPI、LangGraph、LangChain、React、PostgreSQL、Redis 和 SSE。四个独立模型槽位分别服务 Planner、Coder、Researcher、Reviewer。P2 Mock 工作流保持不变；P3 代码执行经过受限服务端 Runner，独立审批不能替代权限检查。P4 已获单独授权：固定目录笔记工具经过资源授权、严格 Schema、额度、幂等账本与独立审批；Skill 的安装和启用分别审批，停用、依赖变化或撤权阻止新调用。候选不自动下载或执行。

不可信代码只在符合安全策略的 Docker Linux 容器内执行。Docker 不可用或关键隔离机制无法验证时 Fail Closed，禁止宿主机执行回退。预热默认关闭；未来预热只能单次租赁使用，执行后销毁，不复用执行过不可信代码的容器。

Docker 共享内核，存在逃逸及宿主机风险，不能视为绝对安全。Compose 中 PostgreSQL/Redis 是持久化开发服务；独立 `runner` 是可信控制面，具有 Docker daemon Socket 权限。实际执行容器是固定非 root、无网络、只读根、资源受限的一次性容器，不挂载 Socket 或宿主机目录。P3 默认禁止预热复用。

本地访问前端 `http://127.0.0.1:15173/sandbox`、后端文档 `http://127.0.0.1:18100/docs`。Runner 默认 `127.0.0.1:18120`，仅可信 Worker 用独立服务端 Token 调用，不是公共 API。启动、镜像登记、独立审批与测试命令见 GETTING_STARTED。

## 当前状态

P5 实现与本地验收见 [P5_REPORT](docs/P5_REPORT.md)，真实外部 API 验收保持 **BLOCKED**（缺少真实模型 Key 与获准收费测试额度，实际请求 0 次）。自动化中的 Provider Stub 不算真实供应商验收。

本地页面：Model Center `/models`、Agent Tasks `/tasks`、AI Chat `/chat`、MCP Tools `/mcp`、Sandbox Center `/sandbox`、Skills Center `/skills`；前端默认 `http://127.0.0.1:15173`。数据库版本 `0006_real_models`。

真实调用需服务端开启、受保护凭据引用、端点受众绑定、经复核价格和预算。未配置时明确 Mock；真实故障不返回假结果。Key 只在本机环境配置，不发到聊天或前端。P3/P4 审批和沙箱策略继续强制执行。

本轮交付后暂停，不进入 P6。生产 IAM、加密/保留治理、真实供应商与计费验收仍需完成，详见报告。
