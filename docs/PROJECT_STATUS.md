# AgentForge AI 项目状态

2026 年 10 月 14 日，Asia/Shanghai。项目路径：`D:\AIProjects\AgentForge-AI`。

P0 已确认。P1 基础骨架完成并通过本轮验证；P2 尚未开始，等待用户另行批准。P0 报告保留当时状态，本文件与 P1_REPORT 记录当前状态。

| 领域 | 当前实际状态 |
| --- | --- |
| FastAPI | 模块化 API、统一响应与异常、UUID 请求 ID、安全 JSON 日志、OpenAPI 已实现 |
| 配置 | 环境变量校验、SecretStr、项目受保护 .env、本地生成秘密、Git 忽略已实现 |
| PostgreSQL | 项目专属真实容器、非超级用户应用连接、model_slots 持久化、Alembic 0001_model_slots 已验证 |
| Redis | 项目专属真实容器、认证、AOF、PING 已验证；没有任务队列实现 |
| React | 十个页面、响应式导航、实际 /health/ready 状态展示已实现；执行页面为明确占位 |
| 模型槽位 | 四角色、严格 Schema、管理 Token 保护、端点与凭据引用校验、version 并发修改已实现 |
| 模型调用 | 尚未实现，不生成真实或模拟答案，不报告调用成功或成本数据 |
| Agent/LangGraph/SSE | 尚未实现；SchedulerPort 仅为未来协议 |
| Docker Sandbox/预热 | 尚未实现；开发基础容器不能执行用户代码 |
| MCP/Skills/人工审批 | 尚未实现，仅占位页面，无执行入口 |
| Observability | 请求日志和依赖状态可用；模型 Token、成本、延迟聚合尚未实现 |
| Docker Compose | 基础服务与可选 app profile 已构建并真实启动验证；数据库/Redis 无公网监听 |
| 自动化测试 | 39 Python 用例、4 浏览器用例通过；类型检查、构建、迁移检查通过 |

## 当前运行方式

本地前端与后端保持运行，PostgreSQL/Redis 容器保持健康。app profile 的后端和前端容器已停止，避免与本地方式重复运行；对应镜像保留，已验证其独立启动能力。

默认本地地址：前端 http://127.0.0.1:15173；后端 http://127.0.0.1:18100；API 文档 http://127.0.0.1:18100/docs。地址状态是本轮验证结果，不保证电脑重启或手动停止后仍运行；按 GETTING_STARTED 重启。

## P2 准备条件

用户明确批准 P2。再确认任务和审批数据模型、LangGraph/LangChain 兼容版本、PostgreSQL 检查点与迁移策略、Redis 调度契约、预算计价数据、上下文权限和 SSE 契约。真实付费模型接入前需确定供应商和秘密注入方式，不在聊天或 Git 提供 Key。

P3 真正的沙箱尚未到位，P2 的执行工具不得降级到宿主机运行不可信代码；需要沙箱的真实任务必须返回未实现/不可用，显式测试替身只能用于协议测试。
