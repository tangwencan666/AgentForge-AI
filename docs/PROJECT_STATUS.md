# AgentForge AI 项目状态

2026 年 10 月 14 日，Asia/Shanghai。项目路径：`D:\AIProjects\AgentForge-AI`。

P0、P1 和 P2 已完成，P3 尚未开始。历史报告保留原阶段记录，当前状态以本文件和 P2_REPORT 为准。

| 领域 | 当前实际状态 |
| --- | --- |
| FastAPI | 模块化 API、统一响应与异常、UUID 请求 ID、安全 JSON 日志、OpenAPI 已实现 |
| 配置 | 环境变量校验、SecretStr、项目受保护 .env、本地生成秘密、Git 忽略已实现 |
| PostgreSQL | 项目专属真实容器、非超级用户应用连接、model_slots 与任务核心状态持久化；Alembic 当前版本 0003_tenant_limits 已验证 |
| Redis | 项目专属真实容器、认证、AOF、PING 已验证；P2 已实现 PostgreSQL Outbox + Redis Streams 异步任务调度 |
| React | 十个页面、响应式导航、实际 /health/ready 状态展示已实现；任务中心与人工审批页面已经接入真实后端 API |
| 模型槽位 | 四角色、严格 Schema、管理 Token 保护、端点与凭据引用校验、version 并发修改已实现 |
| 模型调用 | 仅执行明确 Mock，四角色快照不覆盖 Model Center 配置；真实调用未开放 |
| Agent/LangGraph/SSE | 真实 LangGraph、PostgreSQL 检查点、独立 Worker、Streams/outbox、租约/fencing、SSE 回放已实现 |
| Docker Sandbox/预热 | 尚未实现；开发基础容器不能执行用户代码 |
| MCP/Skills/人工审批 | MCP/Skills 执行未开放；持久化计划确认和公共工具权限规则已实现 |
| Observability | 任务调用轨迹、模拟 Token/费用及原子额度可查；完整观测页面留到 P5 |
| Docker Compose | 基础服务与可选 app profile 已构建并真实启动验证；数据库/Redis 无公网监听 |
| 自动化测试 | 74 Python 用例、6 浏览器用例通过；另有实际进程重启和 Docker Worker 验证 |

## 当前运行方式

本地前端、后端和 Worker 保持运行，PostgreSQL/Redis 容器保持健康。app profile 的应用及 Worker 验证后停止，避免重复运行。任务页 /tasks 和审批页 /approvals 使用仅存内存的本地管理员 Token。

默认本地地址：前端 http://127.0.0.1:15173；后端 http://127.0.0.1:18100；API 文档 http://127.0.0.1:18100/docs。地址状态是本轮验证结果，不保证电脑重启或手动停止后仍运行；按 GETTING_STARTED 重启。

## P3 准备条件

用户明确批准 P3。先核验 Docker Linux、seccomp/cgroups、资源限制，确定批准镜像 digest、受限 Runner 协议、执行审批、输入/产物边界、清理和一次性预热池。计划批准不能代替代码或高风险工具授权。

P3 真正的沙箱尚未到位，P2 的执行工具不得降级到宿主机运行不可信代码；需要沙箱的真实任务必须返回未实现/不可用，显式测试替身只能用于协议测试。

P2 仍是本地开发：未发布生产身份/多用户权限、真实 Provider/RAG、自动保留期清理及生产门禁。不可把 Mock 结果或模拟费用称为真实模型回答和账单。
