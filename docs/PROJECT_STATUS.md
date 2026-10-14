# AgentForge AI 项目状态

2026 年 10 月 15 日，Asia/Shanghai。项目路径：`D:\AIProjects\AgentForge-AI`。

P0–P3 已完成，P3 通过真实 Docker 与核心端到端验收，现暂停等待 P4 单独批准。历史报告保留原阶段记录，当前状态以本文件和 P3_REPORT 为准。

| 领域 | 当前实际状态 |
| --- | --- |
| FastAPI | 模块化 API、统一响应与异常、UUID 请求 ID、安全 JSON 日志、OpenAPI 已实现 |
| 配置 | 环境变量校验、SecretStr、项目受保护 .env、本地生成秘密、Git 忽略已实现 |
| PostgreSQL | 项目专属真实容器、非超级用户应用连接、模型/任务/沙箱记录 Schema 持久化；Alembic 当前版本 0004_sandbox 已验证 |
| Redis | 项目专属真实容器、认证、AOF、PING 已验证；P2 已实现 PostgreSQL Outbox + Redis Streams 异步任务调度 |
| React | 任务中心与人工审批页接入真实后端 API；Sandbox Center 的真实提交、独立代码复核、批准/拒绝、状态和清理结果通过浏览器验收 |
| 模型槽位 | 四角色、严格 Schema、管理 Token 保护、端点与凭据引用校验、version 并发修改已实现 |
| 模型调用 | 仅执行明确 Mock，四角色快照不覆盖 Model Center 配置；真实调用未开放 |
| Agent/LangGraph/SSE | 真实 LangGraph、PostgreSQL 检查点、独立 Worker、Streams/outbox、租约/fencing、SSE 回放已实现 |
| Docker Sandbox/预热 | 独立可信 Runner、批准固定镜像、p3-python-v2 策略、一次性容器、资源与输出限额、超时取消、恢复和清理实际验证；默认预热关闭，无宿主机执行回退 |
| MCP/Skills/人工审批 | MCP/Skills 执行未开放；P2 Mock 计划确认保留，P3 独立角色沙箱代码审批已实际验证，管理员不能代替审批者 |
| Observability | 任务调用轨迹、模拟 Token/费用及原子额度可查；完整观测页面留到 P5 |
| Docker Compose | 既有基础服务与 app profile 历史验证保留；P3 Runner 实际运行，数据库/Redis 和 Runner 只发布 loopback；隔离故障 Runner 已清理 |
| 自动化测试 | Python 153/153：单元/HTTP 117、既有真实集成 20、真实沙箱服务集成 16；浏览器 8/8（沙箱批准/拒绝 2、原核心 6），0 失败、0 跳过 |

## 当前运行方式

本地前端、后端和 Worker 保持运行，PostgreSQL/Redis 容器保持健康，可信 Runner 18120 已实际可用。app profile 的应用及 Worker 保持停止，避免重复运行。任务页 /tasks、审批页 /approvals 和沙箱页 /sandbox 使用仅存内存的管理员 Token；沙箱源代码复核与决定另需独立审批者 Token。

默认本地地址：前端 http://127.0.0.1:15173；沙箱页 http://127.0.0.1:15173/sandbox；后端 http://127.0.0.1:18100；API 文档 http://127.0.0.1:18100/docs。可信 Runner http://127.0.0.1:18120 仅供内部 Token 控制，不是公开接口。地址状态是本轮验证结果，不保证电脑重启或手动停止后仍运行；按 GETTING_STARTED 重启。

## P3 验收与阶段门禁

项目内 Docker SDK 安装已获批准并完成。最终 16 项真实沙箱服务集成验证正常 Python、无网络、未授权宿主标记不可读、非 root、只读根、CPU/内存/PIDs、超时、取消、输出截断、并发、拒绝、重复消息、无状态泄露、不可用 Docker 与受控 Runner 租约过期。专用故障 Runner 没有 Socket，未停止或修改共享 Docker daemon；验证后仅清理自己的故障服务。

TypeScript 检查与 Vite 构建（51 modules）、Alembic 0004_sandbox upgrade/check、pip check、实际 OS Worker 重启均通过。阶段结束检查跨策略版本的执行标签无遗留容器。真实 Worker 重启保持唯一启动意图、同容器、一次输出和确认清理，不以模型 Mock 或替身代替 Docker 证据。

P3 完成后已暂停，不进入 P4。文档修复提交与 P3 提交记录见 P3_REPORT 和 Git 历史；本文件不预填尚未生成的提交 ID。

## 已知限制与 P4 准备条件

Docker 不可用或清理未确认仍 Fail Closed，禁止 Windows 宿主机直接执行不可信代码。预热池未实现，默认关闭；执行过不可信代码的容器不复用。已确认删除的未知结果任务不重放，未确认清理全局阻断。

真实 OS Worker 重启与受控 Runner 租约过期已经验证，但未专门强杀 Runner OS 进程覆盖全部崩溃恢复窗口。Docker Desktop 共享 Linux VM 内核；本轮不能证明逃逸不存在，也不能充分证明 Windows 宿主/VM、AppArmor/SELinux 或生产身份隔离。可信 Runner 持有 daemon Socket，源代码在 PostgreSQL 业务字段明文保存，生产权限、加密与保留治理尚未发布。

进入 P4 前先明确并另行批准 MCP Tool Gateway 与 Skills 范围、生产身份/权限设计、工具白名单和依赖/权限声明及安装启用审批。真实 Provider/RAG 和模型账单仍未接通，Mock Token/费用只能标为模拟。任何系统或 Docker Desktop 全局配置变更继续需要单独确认。
