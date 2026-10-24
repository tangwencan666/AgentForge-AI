# AgentForge AI

源码交付说明更新于 2026 年 10 月 24 日（Asia/Shanghai）。原项目目录：`D:\AIProjects\AgentForge-AI`。

AgentForge AI 是基于 FastAPI、React、PostgreSQL、Redis 和 LangGraph 的多 Agent 项目。源码已实现四模型槽位、异步协作、审批、取消、预算预留、SSE、Sandbox Center、受控 MCP stdio Client/Server、服务端 Tool Gateway、声明式 Skills Registry，以及 P5 模型适配和 Chat。目录还包含单次执行 Permit、Windows 生命周期保护、沙箱归属及维护冻结相关代码与迁移。

**当前交付状态：源码归档；运行验收仍为 `RUNTIME_BLOCKED`，实际部署仍为 `DEPLOYMENT_BLOCKED`。** 已实现不等于已通过当前环境验收。历史 P3/P4、离线与隔离环境测试记录保留在文档中，后续生命周期和 Runner 隔离阻塞仍未关闭。**VMware Mock 演示尚未通过验收，继续标为未验证。**

## 文档入口

- [核心 GitHub Actions CI 范围](docs/CORE_CI.md)
- [隔离 Mock 工作流 CI](docs/MOCK_WORKFLOW_CI.md)
- [自动浏览器 Mock 工作流 CI](docs/BROWSER_MOCK_CI.md)
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

最新已归档的验收限制见 [PROJECT_STATUS](docs/PROJECT_STATUS.md)。历史生命周期场景 `fake_coder_protected_start` 失败，错误为 `CONTROL_CHANNEL_UNVERIFIED`，后续场景未完成；后来的 Mock 专项通过不能证明原故障已修复。真实 Sandbox 集成与浏览器验收仍 **BLOCKED、未执行**，旧 Runner 的隔离、清理和交接风险尚未关闭。

真实外部模型与计费验收仍 **BLOCKED / 未完成**。Provider Stub、MockTransport 和 Mock 回答只作为相应测试证据。当前运行时的凭据、开关、预算、主服务与数据库状态，本次上传未核验；文档中的历史观察不能作为当前状态证明。

本地页面：Model Center `/models`、Agent Tasks `/tasks`、AI Chat `/chat`、MCP Tools `/mcp`、Sandbox Center `/sandbox`、Skills Center `/skills`；前端默认 `http://127.0.0.1:15173`。源码包含 `0001`–`0010` 迁移文件；这不表示主库已应用全部迁移。

真实调用需服务端开启、受保护凭据引用、端点受众绑定、经复核价格和预算。未配置时明确 Mock；真实故障不返回假结果。Key 只在本机环境配置，不发到聊天或前端。P3/P4 审批和沙箱策略继续强制执行。

本轮只整理、检查并上传源码，不运行应用或旧 Runner 诊断，不操作 `agentforge-p3-runner`、VMware、Docker 或数据库，不调用真实模型，不进入 P6。生命周期与 Runner 隔离验收、实际部署、真实供应商及计费验收、生产 IAM 和加密/保留治理仍需后续完成。

## 首次源码上传范围

发布副本以原仓库 `main` 的 `a7fe926b3ea8ee9c097fbd9314d7ae8c296a898c` 为基线，保留原有 12 个提交，再提交本次交付说明与排除规则。原目录的未提交工作和运行配置不参与整理。

- 上传 `backend/`、`frontend/`、`sandbox-image/`、`scripts/`、`tests/`、`docs/`、配置样例、依赖清单及锁文件、Compose/Docker 构建配置和迁移源码。
- 排除真实 `.env`、密钥、数据库与备份、运行数据、日志、依赖和构建产物，以及 `work/`、`NexusOps/` 和 Project-Sentinel 副本。`.env.example` 只包含占位配置。
- 本次检查覆盖基线全部可达历史文件与提交，进行本地已知秘密及常见编码比对、常见凭据格式检查和排除路径检查；未发现真实秘密进入待上传历史。测试中的虚构 URL 凭据用于脱敏断言。
- 首次源码上传时未配置 GitHub Actions，也未重跑应用测试。后续核心 CI 的环境、明确测试范围和未覆盖项见 [CORE_CI](docs/CORE_CI.md)；CI 不包含自动部署，不能解除运行验收阻塞。历史文档中的测试数字均属于原日期的记录。
