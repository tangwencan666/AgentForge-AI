# AgentForge AI P4 源码学习路径

下面路径均位于 `D:\AIProjects\AgentForge-AI`。先理解 P1 健康请求，再跟随 P2 的任务事务、独立 Worker、LangGraph 和 SSE，再阅读 P3 的可信 Runner 与受限容器，最后跟随已授权 P4 的 MCP Gateway 与 Skill 生命周期。模型回答保持明确 Mock；沙箱 Python 为真实 Docker 执行，其实际验收状态以 P3_REPORT 为准。

## 1 从运行入口开始

先阅读 README.md、docs/P1_SCOPE.md 和 docs/GETTING_STARTED.md，再打开 backend/app/main.py 的 `create_app`。它是应用工厂，装配 Settings、路由、异常处理和 lifespan；lifespan 初始化连接池，退出时释放连接，没有在启动时偷偷创建表。配置失效时报安全错误，不打印环境变量内容。

运行 GET /health/live，再运行 GET /health/ready，比较两者。API 存活不等于数据库就绪。统一响应包含 success、data、error、request_id；HTTP 503 与 response.success=false 一起表达真实依赖未就绪。

## 2 跟随真实健康请求

阅读 backend/app/core/middleware.py 的 `RequestContextMiddleware.__call__`：它生成或校验 UUID 请求 ID，通过 ContextVar 关联日志和响应头。用户原始 URL、query 和 body 不进入默认日志。

接着阅读 backend/app/repositories/connections.py 的 `Connections`。构造函数创建 SQLAlchemy AsyncEngine、async_sessionmaker 和 Redis 客户端；`_postgres_status` 检查 SELECT 1、Alembic 版本与核心表；`_redis_status` 使用真实 PING；`readiness` 并发探测，但这里不是 Agent 并发调度；`close` 关闭资源。

前端链路依次阅读 frontend/src/api/health.ts 的 `fetchReadiness`、frontend/src/components/HealthPanel.tsx 的 `refresh` 和 frontend/vite.config.ts 的同源代理。组件从真实 HTTP 200/503 响应显示状态，失败显示“无法连接”，中断旧请求并避免显示旧成功。Vite 配置只读取端口用于代理，不把秘密变量注入浏览器。

## 3 学习配置和模型约束

backend/app/core/config.py 的 `Settings` 使用 Pydantic Settings 加载 AGENTFORGE_ 前缀和项目 .env。数据库/Redis URL 与管理员 Token 使用 SecretStr，并不进入 repr；配置校验限制项目库名、协议、端口与环境。`validate_model_endpoint` 校验 HTTPS、域名批准范围和禁止私有地址。

backend/app/schemas/models.py 的 `ModelRole` 是四角色枚举；`ModelConfig` 是严格模型配置；`ModelUpdate` 添加 expected_version。注意 extra=forbid 与校验错误出口的作用：额外 api_key 被拒绝，而且不返回请求原值。

backend/app/services/models.py 的 `validate_configuration` 检查批准端点和服务端 env 凭据引用；`slot_dto` 只序列化非秘密配置；`list_slots` 过滤服务端租户；`update_slot` 用数据库 version 条件做并发修改校验。此模块不调用 AI 模型。

## 4 理解数据库迁移

backend/app/domain/entities.py 的 `Base` 与 `ModelSlot` 定义 ORM。复合主键 tenant_id+role 限制租户槽位，数据库 CheckConstraint 提供参数约束。

阅读 backend/migrations/env.py：它把异步数据库连接转入 Alembic 的同步迁移上下文。再阅读 migrations/versions/0001_model_slots.py：创建核心表并填入四个停用槽位。scripts/migrate.py 提供 upgrade/check/current 安全命令；迁移不应在每个 HTTP 请求中执行。

deploy/init-app-role.sql 定义本地应用非超级用户；compose.yaml 定义专属卷、服务健康检查和回环端口。数据库和 Redis 的独立开发容器不是沙箱；P3 使用独立 Runner 和完全不同的执行容器权限边界。

## 5 阅读安全边界

backend/app/core/security.py 的 `require_admin` 进行固定时间 Token 比较，租户由服务端 Settings 决定，客户端不能用 tenant header 自授权。这是单个本地管理员入口，不是生产多用户身份系统。

backend/app/core/logging.py 的 `JsonFormatter` 采用事件和字段白名单，不序列化动态异常消息、request body、Authorization 或连接字符串；Uvicorn access log 关闭。main.py 的异常处理器只返回安全类型和字段名，不返回 Pydantic input 和 ctx。

scripts/bootstrap_local.py 只生成开发服务秘密，拒绝覆盖；scripts/check_secrets.py 检查当前已跟踪/未跟踪源码、前端产物、日志和测试报告中的已知秘密。观察 .gitignore 对 .env、work、日志和依赖目录的忽略。保护秘密需要入口、出口、日志和 Git 一起约束，不能仅靠页面遮挡。

## 6 用测试理解行为

先看 tests/unit/test_config.py 和 test_logging.py，理解哪些输入必须拒绝。再看 tests/http/test_api.py 的显式 StubConnections，学习 HTTP 契约与故障响应；不要把测试替身当成连接证据。

随后读 tests/integration/test_dependencies.py：真实 PostgreSQL/Redis、迁移、非超级用户、四槽位持久化与版本冲突。最后阅读 frontend/tests/smoke.spec.ts：实际代理联调、十页导航、明确的故障拦截测试和直接访问页面。自己停掉本项目 Redis，再刷新 Dashboard，可观察真实未就绪；实验只操作本项目服务，随后恢复。

## 7 下一步学习顺序

先掌握 Python async/await、FastAPI 依赖注入、Pydantic v2、SQLAlchemy 事务、Alembic、React hooks 与 TypeScript，再阅读 P0 中 LangGraph、检查点、outbox、租约和审批设计。backend/app/services/scheduling.py 仍是 `SchedulerPort` 协议；实际 PostgreSQL Outbox + Redis Streams 调度在 P2 Worker 中，不应因该端口文件没有实现就认为没有任务队列。

P2 已实现，继续按下列顺序阅读；P3 已获开发授权，但所有不可信代码都必须通过受限服务端审批与 Docker 执行。不可信代码不得在 Windows 宿主机执行；MCP/Skills 仅通过本轮已批准的 P4 控制面使用。真实模型和 P5 尚未授权。

## 8 跟随 P2 任务

先看 schemas/tasks.py 的 TaskCreate，理解固定 Mock、期限和限额；再看 services/tasks.py 的 TaskService.create：指纹、幂等锁、任务和 outbox 同事务。domain/tasks.py 映射实际表，迁移 0002/0003 管理结构。

阅读 workers/engine.py：publish 发布未投递的 outbox，claim 原子领取租约和 fencing，tick 消费 Streams，sweep 处理 deadline、取消、失效租约与丢失通知。进程入口 workers/main.py 关闭外部追踪并运行异步循环。

随后读 orchestration/graph.py 的 build_graph 和 validate_plan。无依赖用两个并行分支和汇聚；有依赖用串行边；Reviewer 反馈通过 increment 回到调度，但 Runtime.begin_round 和业务额度限制循环。审批节点 interrupt 不执行副作用，客户端恢复值仅是唤醒，授权来自数据库。

orchestration/runtime.py 的 operation 用稳定 role/round/attempt 标识去重；_attempt 在任务和租户日额度行锁内预留，完成后结算。services/usage.py 管共享 UTC 窗口；跨午夜用 reservation_day。Mock 单位是 JSON UTF-8 字节，不能当成真实 tokenizer。

orchestration/checkpoints.py 的 PostgresTaskSaver 实现 LangGraph 异步保存和 pending writes。理解业务账本与检查点的不同用途：检查点帮助恢复位置，账本防止重复计量。写入前检查 owner/fence，旧进程不可覆盖新进程。

最后读 api/v1/tasks.py 的 SSE、frontend/src/api/tasks.ts 的游标与重连、pages/Tasks.tsx 和 Approvals.tsx 的真实 UI 操作。LocalAuth.tsx 只在内存保留本地 Token。tests/integration/test_workflows.py 验证真实数据库/Redis、接管、预算竞争和回放；scripts/p2-recovery-probe.py 验证真实进程重启。

## 9 按一次 P3 执行读源码

先阅读 docs/SANDBOX_EXECUTION_PROTOCOL.md 与 SANDBOX_SECURITY.md，再按下面顺序追踪“提交 → 独立审批 → 真实 Docker → 清理 → 结果”。源码的创建配置不是隔离证明，最后必须对照真实测试证据。

1. `backend/app/schemas/sandbox.py`：`ResourceLimits` 限制 CPU/内存/PIDs，`SandboxCreate` 限制代码与超时且禁止额外字段；`SandboxExecutionRequest` 补充服务端执行身份，`RunnerDispatch` 只传任务/执行 ID、owner、fence。区别公共 API 载荷与可信内部派发。
2. `backend/app/domain/sandbox.py` 与 `backend/migrations/versions/0004_sandbox_sandbox.py`：`SandboxExecution` 保存源代码、哈希、审批、启动意图、Runner 租约、结果和清理状态；`SandboxDailyUsage` 保存资源预留。代码是受控业务输入，不默认写应用日志，普通结果 DTO 不返回代码。
3. `backend/app/api/v1/sandbox.py`：管理员负责提交、查看、取消，`require_approver()` 只允许独立审批者读取 `/source` 和决定。前端按钮不是权限边界；源代码读取必须服务端授权，Token 不进 URL。
4. `backend/app/services/sandbox.py`：`SandboxService.create()` 核对代码大小/秘密、按租户锁定幂等键、预留 CPU 秒、关联任务/审批/outbox；`decide()` 核对操作哈希、期限和图检查点，批准后排队、拒绝不执行；`cancel()` 保存取消并让 Runner 清理。跟随 `execution_dto()` 理解安全返回字段。
5. `backend/app/services/orchestration/sandbox_graph.py`：`build_sandbox_graph()` 的 approval 节点用 LangGraph interrupt 持久化等待，执行节点通过内部 Token 派发并查询原结果；恢复值仅唤醒，不授予权限。该图不调用四个模型。
6. `backend/app/workers/engine.py`：`execute()` 依据受控 workflow 分流 P2 Mock 图与 P3 沙箱图，继续使用 PostgreSQL 检查点、outbox、Redis Streams、租约与 fence。Worker 重启不代表容器必须重新启动；任务租约与 Runner 租约用途不同。
7. `backend/app/sandbox/policy.py`：`operation_digest()` 将代码哈希、镜像 ID、超时、资源和 policy_version 绑定审批；`validate_execution()` 重新验证数据库记录、独立批准和资源预留；`create_options()` 生成固定 Docker 配置；`verify_container()` 与 `verify_attestation()` 分别校验 daemon 创建结果和代码注入前的容器内状态。
8. `sandbox-image/Dockerfile` 与 `sandbox-image/launcher.py`：固定基础镜像与非 root 身份，`attest()` 输出 UID、seccomp、capabilities、cgroup 与网络接口；`main()` 等待有界输入、写容器 tmpfs，再启动 `python -I -S` 子进程和独立超时 alarm。不要在 Windows 宿主机运行此 launcher 来执行待审代码。
9. `backend/app/sandbox/driver.py`：`DockerDriver.health()` 只查询固定已批准镜像，不自动 pull；`run()` 创建、inspect、握手、单次代码注入、限制输出、采样资源、超时终止；`remove()` kill/remove 后再查询确认不存在。查看 finally 路径，不以正常退出代替清理。
10. `backend/app/sandbox/engine.py`：`SandboxRunner.dispatch()` 在 Docker 前提交启动意图，数据库锁控制跨进程并发；`_authorize_boundary()` 在启动和代码注入前重复权限检查；`_monitor()` 观察 deadline 与取消；`_finish()` 脱敏摘要和结算；`reconcile()` 只清理确定归属的本项目容器，未知结果进入 needs_reconciliation，不能重跑。
11. `backend/app/sandbox/main.py` 与 `compose.yaml`：独立控制面 API、内部 Token、loopback 端口和 daemon Socket。可信 Runner 有高权限；实际执行容器无 Socket。Runner 不能作为模型工具或公共 API 暴露。
12. `frontend/src/api/sandbox.ts`、`frontend/src/pages/Sandbox.tsx`：复用管理员内存授权，独立审批者 Token 只用于 source/decision；源代码哈希核对、状态轮询、关联任务 SSE、真实输出和清理。对比 Tasks.tsx 的显式 Mock 标签，不混淆真实代码执行和真实模型推理。

## 10 用测试验证安全边界

先读 `tests/http/test_sandbox_api.py`、`tests/unit/test_sandbox_runner_policy.py` 和 `tests/unit/test_sandbox_runner_http.py`，理解额外参数、镜像、缺权限、审批变化、运行时报告不匹配、Docker 故障和不确定创建必须怎样拒绝。客户端或连接安全替身只是契约/故障测试，不能作为真实 Docker 运行证据。

再读 `tests/integration/test_sandbox.py`：真实 PostgreSQL/Redis、独立 Runner 和 Docker，使用有界代码验证正常输出、无网络、非 root、只读根、专用宿主标记不可读、CPU/内存/PIDs 限额、超时取消、输出上限、跨任务无状态泄露、重复消息和 Worker 恢复。测试使用本项目无敏感标记，不读取真实凭证或进行破坏性攻击。

`scripts/test-p3.ps1` 负责测试时暂停本项目后台 Worker并恢复，显式启用真实集成与沙箱 opt-in。`frontend/tests/sandbox.spec.ts` 使用真实后端批准/拒绝流程；AGENTFORGE_RUN_SANDBOX 未置 1 时会 skip，skip 不是验收通过。测试不写密码到 trace；最终数量及实际运行证据见 P3_REPORT。

完成测试后学习 `reconcile()` 的 ownership、标签、固定命名与租约检查：只可清理自己的容器，不能使用 Docker 全局 prune。默认预热关闭，运行过不可信代码的容器不回池；Docker 不可用没有宿主机执行回退。Docker Desktop 的 Linux VM 结果不能证明 Windows/VM 逃逸、生产身份或 AppArmor/SELinux 全部安全，相关残余风险需保留。

## 11 跟随 P4 的真实 MCP 调用

先读 P4_CONTRACT，再依次阅读：

1. `schemas/tools.py`：固定工具名、严格输入/输出 Schema、slug 资源、版本与 manifest。先尝试把 resource 改为路径或添加 approved，理解为什么客户端声明不能变成能力。
2. `domain/tools.py` 和迁移 `0005_capabilities_capabilities.py`：区分 ToolPermission、ToolCall、CapabilityApproval、CapabilityAudit、SkillVersion 和 ManagedNote。回执是业务事实，不是 JSON-RPC 回应的别名。
3. `services/tool_gateway.py`：create 只准备，execute 在事务中重新鉴权、扣额度并保存派发意图和审计，提交后才启动 MCP。比较成功重复请求、dispatched 和 needs_reconciliation 三种恢复路径。
4. `services/capabilities.py`：操作哈希、租户串行锁、完整依赖闭包、权限 generation 和独立审批。这些检查由可信 Server 在副作用事务中重复执行。
5. `mcp/client.py`：固定命令、最小环境、MCP 生命周期、目录 Schema 比对、短期 HMAC 能力、64 KiB 帧和总超时。它不接收模型给定的 endpoint 或启动命令。
6. `mcp/server.py`：在同一数据库事务中重验能力和权限、写 notes、消费批准、保存回执及审计。然后模拟丢失响应，观察为何 Gateway 只能核对回执而不能重新写一次。
7. `api/v1/capabilities.py` 与前端 `pages/McpTools.tsx`：管理员和独立 P4 审批者分别做什么；复核内容从真实服务端获取，按钮或 Reviewer 文本都不能授权。

## 12 理解 Skill 注册与生效的区别

阅读 `services/skills.py` 的 candidate → register → install → enable。candidate 保存文字和 manifest，不执行内容；installed_disabled 只表示声明式安装验证完成，不代表可以用工具。每个安装、启用动作各自绑定人工批准。

再读 `enabled_skill()`：Skill 声明只能缩小权限，不能替代资源授权；检查根版本及传递依赖已启用并核对 generation。依赖停用后再启用，其内容虽未变化，生命周期已变化，父版本必须重新审批。升级创建新版本，不继承旧批准。

前端依次读 `api/capabilities.ts`、`components/CapabilityApproval.tsx`、`components/ToolComposer.tsx` 和 `pages/SkillsCenter.tsx`。特别观察 DTO 只发送必要的 Skill 身份字段，复核 Token 不进浏览器持久存储，切换身份会丢弃受保护状态。

最后读 `tests/unit/test_mcp_policy.py`、`tests/http/test_capabilities_api.py`、`tests/integration/test_capabilities.py` 和 `frontend/tests/capabilities.spec.ts`：分别验证 Schema/签名、角色边界、真实数据库/子进程与真实浏览器。传输丢失和审计故障使用显式故障注入，不能把它们当成独立远程服务器验收；正常读写链路确实启动项目 MCP Server。

运行 `scripts/test-p4.ps1` 会同时执行 P3 Docker 安全回归。最终数量、修复与限制见 P4_REPORT。完成 P4 后停在本阶段，不继续 P5。
