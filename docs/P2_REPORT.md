# AgentForge AI P2 完成报告

2026 年 10 月 14 日，Asia/Shanghai。项目根目录：`D:\AIProjects\AgentForge-AI`。

P2 持久化异步协作已完成。LangGraph、PostgreSQL、Redis、审批、取消、SSE 和 Worker 进程真实运行；模型输出与费用仅为显式 Mock。没有真实模型调用、沙箱代码执行、MCP/Skills 执行或生产发布。P3 未开始。

## 核心实现

| 路径 | 类与职责 |
| --- | --- |
| backend/app/domain/tasks.py、schemas/tasks.py | 任务、事件、outbox、审批、操作、额度、检查点及严格契约 |
| backend/app/services/tasks.py | TaskService：幂等创建、租户过滤、取消、审批与事件读取 |
| backend/app/services/orchestration/graph.py | build_graph、validate_plan：Planner、分支/汇聚、中断、Reviewer 有限反馈 |
| backend/app/services/orchestration/runtime.py | Runtime：四角色 Mock 路由、原子预留、重试与迭代控制 |
| backend/app/services/orchestration/checkpoints.py | PostgresTaskSaver：异步检查点和 pending writes，写入前检查租约/fencing |
| backend/app/workers/ | 独立 Worker：outbox、Streams、续租、期限扫描、失效接管和有限恢复 |
| backend/app/services/context.py、usage.py、tool_policy.py | 脱敏/裁剪与来源、共享日额度锁、高风险权限公共规则；无工具执行器 |
| backend/app/api/v1/tasks.py | 鉴权任务、审批、取消和 SSE API |
| backend/migrations/versions/0002_workflows.py、0003_tenant_limits.py | 真实迁移，保留 P1 模型配置数据 |
| frontend/src/pages/Tasks.tsx、Approvals.tsx | 创建 Mock 任务、计划确认、取消、轨迹与模拟用量 |
| frontend/src/api/tasks.ts、components/LocalAuth.tsx | 鉴权 HTTP/SSE 回放；Token 只在页面内存 |
| scripts/test-p2.ps1、restart-worker.ps1、stop-worker.ps1 | 本项目进程和测试隔离，不按全局进程名停止程序 |
| scripts/p2-recovery-probe.py、p2-compose-probe.py | 实际 OS 进程重启和 Docker Worker 验证，不输出秘密 |

## 行为与安全边界

创建必须明确 execution_mode=mock，real 请求拒绝，无自动 Mock 回退。四个 Mock 配置快照独立于 Model Center 配置，每个调用、结果、事件和 UI 都标记 Mock。

任务与 outbox 同事务提交。租户范围 Idempotency-Key 的重复同载荷请求返回同任务，不同载荷冲突；数据库锁处理并发重复创建。调用账本使用 task_id、role、round、attempt 稳定标识，恢复已完成结果不重复计量。检查点写入校验 owner/fence，不声称外部 exactly once，本轮没有外部副作用。

总 deadline 包含审批。迭代、调用、Token、Decimal 预算在服务端限制并原子预留，任务和租户日额度同时校验。UTC 日窗口默认 1000000 模拟 Token 与 10 模拟 USD，跨午夜结算绑定 reservation_day。mock-usd-v1 的单位价是模拟规则，Token 按 UTF-8 JSON 字节数计数，不是供应商 tokenizer 或实际账单。

审批绑定租户、任务、计划 hash、政策版本与期限；恢复以服务端记录为准，不接收客户端图状态/跳转。单管理员允许确认普通 Mock 计划；高风险工具仍需权限和独立审批，Sandbox/MCP/Skills 执行不可用。Reviewer 不授予权限。

数据库/Redis 不可用时不发起新调用；数据库 outbox 可恢复队列通知，Worker 可重建消费组。SSE 使用授权 fetch、Last-Event-ID、持久化回放，拒绝超前游标；断线不会重执行任务。

没有请求用户真实 API Key。已知秘密和 Key 模式不得存入公开模型字段；目标进入状态前脱敏，检查点仅含计划、操作引用与控制状态。日志不写请求体、异常值、任意 URL 或自定义 HTTP 方法内容；LangSmith 外部追踪关闭。

## 实际验证

| 验证 | 结果 |
| --- | --- |
| 单元与 HTTP | 54 passed |
| 真实 PostgreSQL/Redis 集成 | 20 passed，其中 P2 工作流 17 项 |
| Python 总计 | 74 passed，0 failed，0 skipped |
| 浏览器 | 6 passed，含真实健康、十页、创建/审批/SSE、Mock 标识、刷新清除授权 |
| TypeScript 与 Vite | 类型检查及构建通过 |
| Alembic | 当前 0003_tenant_limits，upgrade/check 成功，无 ORM 差异 |
| 实际进程重启 | 审批等待时重启 Worker，恢复完成四角色；Planner 只调用一次 |
| Docker | API、前端、独立容器 Worker 在真实 PostgreSQL/Redis 上完成四角色 Mock 任务 |
| Git 门禁 | 提交时执行 diff/换行及已知秘密、前端产物、项目日志扫描 |

共 80 个 pytest/浏览器用例通过；构建、迁移、实际进程重启和 Compose 验证另计。覆盖路由、并发/依赖、审批恢复、失败与重试、限额、超时取消、重复投递、fencing、在途接管、预算竞争、跨租户拒绝、SSE 回放和秘密不回显。

证据位于 work/p2-all.xml、work/p1-e2e.json、work/p2-workflow.png 和构建日志，Git 忽略。HTTP 单元替身和浏览器故障拦截单独标注，不作为真实服务连通证据。

锁定安装版本：LangGraph 1.2.15、LangChain 1.4.5、langchain-core 1.6.10、langgraph-checkpoint 4.3.0。浏览器有 Node 终端颜色提示，不是失败；P1 TestClient 的 httpx 弃用提示在依赖新增 httpx2 后不再出现。

## 当前运行与限制

本地前端 http://127.0.0.1:15173，后端 http://127.0.0.1:18100，文档 /docs。本地 Worker 和项目 PostgreSQL/Redis 保持运行。完整 Compose 的应用/Worker 验证后停止，基础卷保留，沿用 agentforge-p1 基础命名，新增 agentforge-p2-worker，不修改其他项目。

模型规划是确定性两 Worker Mock 示例，无真实推理、检索/RAG、实际费用或代码执行。未知供应商价格未被当作免费接通。仍是单管理员开发身份，无生产 OIDC/RLS。自动保留期清理、完整监控和生产容量门禁待后续；当前记录没有自动清理。脱敏不能识别所有未知秘密，用户不得粘贴机密文件。

手动轮换管理员 Token 后，旧幂等指纹可能变化，需用新 key；生产需独立稳定的指纹密钥。Worker 停机时状态可能滞后，恢复后先检查 deadline 再执行，过期任务不能重新开跑。本轮公共工具权限规则与计划审批不能替代 P3/P4 的完整执行权限和沙箱验收。

本报告随 P2 提交，ID 用 `git log -1 --format=%H` 查询。P3 需另行批准并先验证 Docker Linux 安全机制、批准镜像和受限执行协议；禁止自动进入或宿主机回退。
