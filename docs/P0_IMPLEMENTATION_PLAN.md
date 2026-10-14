# AgentForge AI 目录规划与实施路线图

本轮完成 P0 文档并暂停。P1 及后续阶段均为未来计划，未获得用户确认不得创建应用代码、测试代码、镜像或启动服务。项目目录固定为 `D:\AIProjects\AgentForge-AI`，不创建第二层同名目录，不修改其他已有项目。

## 1 规划目录

以下除 README.md 和 docs 中的 P0 文档外，全部是未来目录规划，不代表文件已存在。

```text
D:\AIProjects\AgentForge-AI\
├── README.md
├── docs/
│   ├── P0_ARCHITECTURE.md
│   ├── P0_CHANGES.md
│   ├── P0_IMPLEMENTATION_PLAN.md
│   ├── P0_ACCEPTANCE.md
│   ├── P0_REPORT.md
│   ├── adr/                         架构决策和变更记录
│   └── runbooks/                    部署、取消、恢复和清理操作说明
├── backend/
│   ├── pyproject.toml               依赖及兼容版本，P1 再生成锁文件
│   ├── app/
│   │   ├── api/v1/                  配置、任务、审批、SSE、查询
│   │   ├── core/                    配置、身份、日志、异常与租户上下文
│   │   ├── domain/                  实体、状态机、策略及纯业务规则
│   │   ├── services/
│   │   │   ├── models/              四角色 Router、Provider Adapter
│   │   │   ├── credentials/         单向秘密写入和 Secret Store 适配
│   │   │   ├── orchestration/       LangGraph、DAG、节点、检查点
│   │   │   ├── context/             Token 裁剪、来源、摘要和 RAG ACL
│   │   │   ├── approvals/           审批绑定、有效期与权限再校验
│   │   │   ├── tools/               Gateway、MCP、授权及幂等账本
│   │   │   ├── skills/              manifest、版本、依赖和审批
│   │   │   ├── sandbox/             受限 Runner 客户端，无任意 Docker API
│   │   │   └── observability/       usage、价格、预算、追踪和指标
│   │   ├── repositories/           PostgreSQL 事务和租户过滤
│   │   ├── workers/                Redis Streams、outbox、租约和恢复
│   │   └── schemas/                严格输入 Schema 与安全响应 DTO
│   └── migrations/                 业务表与图持久化部署协调
├── sandbox-runner/
│   ├── app/                        专用执行协议、Docker SDK、预热、watchdog
│   ├── images/                     批准镜像和只读可信 launcher
│   └── policies/                   安全策略、seccomp 和镜像 digest
├── frontend/
│   ├── src/pages/                  六个 Center 页面
│   ├── src/components/             轨迹、DAG、审批、Mock 标签
│   ├── src/api/                    HTTP 与 SSE 重连、安全 DTO
│   └── src/state/                  展示状态，不作为执行真相源
├── tests/
│   ├── unit/                       路由、政策、脱敏、成本
│   ├── contract/                   Provider、MCP、Runner 与 API
│   ├── integration/                PostgreSQL、Redis、真实 Docker
│   ├── fault_injection/            崩溃、失联、重复投递和取消竞态
│   └── e2e/                        页面、SSE、审批、真实与 Mock
├── deploy/                         开发和部署模板、监控、安全检查
├── .env.example                    只含占位符，P1 创建
└── .gitignore                      忽略秘密、产物、临时文件，P1 创建
```

应用代码不能跨层拿到原始 Docker 控制接口。Policy 和 Secret Store 依赖由可信服务装配，Agent、Skill 和前端不能替换实现。依赖安装、数据库迁移、镜像拉取或构建均留到相应阶段。

## 2 分阶段实施

| 阶段 | 工作范围 | 前置条件 | 可验收成果与退出条件 |
| --- | --- | --- | --- |
| P0 本轮 | 架构、差异、选型、目录、路线图、测试规格 | 本次最新需求 | 文档一致、十项原始验收有映射；报告后暂停 |
| P1 基础与模型 | 工程初始化、身份/租户权限、配置/Secret Store、四槽位 Router、Provider、明确 Mock、基础计量 | 用户明确确认 P0 并允许进入 P1 | 路由、Key 不泄露、模型错误、初步成本测试通过；不提供宿主机代码执行 |
| P2 异步工作流 | LangGraph DAG、PostgreSQL 检查点、Redis Streams、outbox、租约/fencing、上下文、SSE、取消、审批、预算预留 | P1 契约与凭据隔离通过 | 重启可恢复，无依赖并发，超时/取消/额度有效，重复请求不重复副作用 |
| P3 Docker 执行 | 独立 Runner、固定策略、单次容器、输入导出限制、watchdog、审计、清理和有限预热池 | Gateway 受限执行契约和可验证 Linux Docker 环境 | 真实 Docker 隔离、无状态泄露、故障安全失败、并发租约和清理测试通过 |
| P4 MCP 与 Skills | 白名单、协议鉴权、参数与语义校验、配额审计、高风险审批、Skill 注册安装启用 | P2 权限/审批及 P3 执行隔离 | 无权和审批绕过被拒；候选惰性；升级重新审批；依赖闭包验证 |
| P5 六页面与观测 | 完整页面、DAG 轨迹、Sandbox 状态、工具权限、Skill 审批、成本与错误指标 | 后端资源授权与各领域 API 稳定 | UI E2E、SSE 重连、Mock 标识、错误可解释、成本聚合不跨租户 |
| P6 发布验收 | 完整门禁、真实适配烟测、故障注入、恢复演练、部署与运维文档 | 各组件退出条件完成 | 所有强制自动化项通过，未决执行/清理和安全阻断为零；报告环境和限制 |

P1 同时设计核心领域 Schema 和安全 DTO，不能先做不鉴权演示再补权限。P2 可用明确的 Runner 测试替身验证编排契约，但这不代表拥有真沙箱；在 P3 完成前 sandbox.execute 对真实任务返回不可用。P4 的 MCP 白名单和审批设计在 P0 确定，P2 先实现共享 Gateway/审批基础，P4 扩展真实 MCP 和 Skill 生命周期。

每阶段完成报告说明改动、测试结果、局限和下一阶段；不能用 P0 确认推定已允许生产发布、破坏性数据迁移或秘密外传。阶段范围变化必须更新基线和验收项。

## 3 执行顺序和关键依赖

先实现身份与租户隔离、秘密存储和安全 DTO，再接入真实模型。先实现持久化状态、操作账本和审批绑定，再接入有副作用的工具。先完成一次性 Docker 隔离和清理测试，再开启预热池；预热关闭时仍使用同样安全的一次性容器。先完成预算原子预留，再允许 Coder/Researcher 并发付费调用。

SSE、成本、审计和 trace_id 在领域功能实现时同步接入，不留到最后追补。前端可以依据稳定契约逐步实现，但不得用模拟轨迹替代真实执行记录。RAG 的文档 ACL 和上下文预算先于全量文档接入。

## 4 参数与环境检查计划

P1 只读核对 Python/Node 版本、供应商接口能力、数据库/Redis 和秘密注入方式，然后生成版本锁定方案。模型名称和价格以实际选择为准，用户尚未指定供应商与 Key，本轮不配置真实凭据；不以此阻断架构文档完成。

P3 核对 Docker Linux 容器、seccomp、cgroups、无 swap、非 root、只读根、pids、none 网络与 Runner 权限隔离。不满足条件则阻止执行部署，保留 Model/Task Center 的不可用状态提示；不降低策略“让演示跑起来”。镜像依赖预先审核并离线放入运行镜像，沙箱内默认不能联网安装包。

初始部署规模按 4 个活跃沙箱加 2 个预热容器估算，预留执行节点与控制面资源。实际池大小、资源额度和 deadline 在真实测量后仅由管理员调整；测量不授权突破安全硬约束。

## 5 风险与对应工程工作

| 风险 | 实施对策与验收证据 |
| --- | --- |
| Docker 共享内核和 Runner daemon 权限 | 隔离执行节点、批准镜像、固定策略、更新机制、真实负面测试；不承诺绝对安全 |
| 模型供应商协议与计费不一致 | 能力登记、契约测试、Decimal 与价格版本、缺失 usage 不记零 |
| Redis 投递或 Worker 崩溃引发重放 | PostgreSQL outbox、租约/fencing、稳定操作 ID、未决对账 |
| 并发预算超卖 | 数据库原子预留和租户上限；竞争测试 |
| 人工审批后权限或参数变化 | 哈希绑定、有效期、版本、执行前再鉴权 |
| 日志与流式输出泄密 | 安全 DTO、入口/出口脱敏、有界缓冲、高敏输出禁存、金丝雀测试 |
| 预热残留或容量失控 | 单次租约、使用即销毁、生命周期 TTL、隔离容器仍占容量 |
| Prompt injection 与跨租户 RAG | 数据可信度标签、服务端政策、ACL 前后校验、租户缓存 key |

## 6 P0 确认后才能开始的工作

进入 P1 后需确认实际部署资源、首个供应商适配和秘密注入方式；未指定时可先实现协议与显式 Mock，不猜测真实 Key 或收费模型。用户确认前，当前项目仅保持 README 和 P0 文档。
