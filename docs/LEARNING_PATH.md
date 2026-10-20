# AgentForge AI P5 源码学习路径

> 2026-10-19 阅读提示：G4 `e9ced78` 仅 Archive-only 归档；原 IPC 故障和 B1/B2/B3 运行前提未解决，B4 仅离线修复，**RUNTIME_BLOCKED**。当前主服务、数据库/Docker、凭据和 Permit/预算状态本轮均未核验；本文件是源码阅读路径，不授权执行运维或测试命令。历史测试数与运行观察仅限原日期，当前结论先读 [PROJECT_STATUS](PROJECT_STATUS.md)。README 保留原 P5 快照，不能用其中0006描述推断现时主库。

S2历史阅读补充（2026-10-18）：先读[S2暂停报告](P5_LIVE_MAINT_S2_REPORT.md)和[Sandbox隔离设计](SANDBOX_ISOLATION_DESIGN.md)，理解当时为何“另一个数据库没有此记录”不是容器删除授权。work/maint-s2/readonly-precheck-20261018/stub-repro.py的Docker/数据库为替身，只证明错误决策可复现。后续S3-A/B1/B3源码已实现归属与冻结，但主Runner未据此获准升级，17项集成和2项浏览器仍BLOCKED；不能运行旧共享Runner测试来验证。

P5-LIVE DeepSeek准备阅读：从 providers/deepseek.py 的显式模式和参数选择，读到共享SSE解析和USD价格快照，再查看schemas/models.py、ModelSlot的两项字段及0007迁移。scripts/test-offline.py不加载本机dotenv，但仍会选择已知失败的生命周期测试，不能视为全绿。0007及后续0008的主库应用有历史记录；0009/0010仅提交和隔离验证，本轮不核验实时版本，真实供应商验收未完成。最初准备阶段的限制见P5_LIVE_DEEPSEEK.md，按其日期阅读。

下面路径均位于 `D:\AIProjects\AgentForge-AI`。先理解 P1 健康请求、P2 持久化协作、P3 可信 Runner，再跟随 P4 MCP Gateway 与 Skill 生命周期，最后阅读 P5 模型适配、预算和恢复。Mock 必须显式标记，真实故障不伪装 Mock；沙箱代码仅允许受审查 Docker 路径，无宿主执行回退。历史 P3 实测不代表当前17＋2已通过。

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

阅读 backend/migrations/env.py：它把异步数据库连接转入 Alembic 的同步迁移上下文。再阅读 migrations/versions/0001_model_slots.py：创建核心表并填入四个停用槽位。scripts/migrate.py 是受维护作用域保护的固定 upgrade/check/current 入口，upgrade 还需独立批准；不因命令存在就可对主库执行，迁移也不应在每个 HTTP 请求中执行。

deploy/init-app-role.sql 定义本地应用非超级用户；compose.yaml 定义专属卷、服务健康检查和回环端口。数据库和 Redis 的独立开发容器不是沙箱；P3 使用独立 Runner 和完全不同的执行容器权限边界。

## 5 阅读安全边界

backend/app/core/security.py 的 `require_admin` 进行固定时间 Token 比较，租户由服务端 Settings 决定，客户端不能用 tenant header 自授权。这是单个本地管理员入口，不是生产多用户身份系统。

backend/app/core/logging.py 的 `JsonFormatter` 采用事件和字段白名单，不序列化动态异常消息、request body、Authorization 或连接字符串；Uvicorn access log 关闭。main.py 的异常处理器只返回安全类型和字段名，不返回 Pydantic input 和 ctx。

scripts/bootstrap_local.py 只生成开发服务秘密，拒绝覆盖；scripts/check_secrets.py 的 `--no-local-secrets` 仅扫描常见凭据格式，不读dotenv或已知Key做比对，不能证明所有未知秘密不存在。默认已知秘密比对模式会读取本地配置，不能当作本轮无秘密读取命令。观察 .gitignore 对 .env、work、日志和依赖目录的忽略，不能仅靠页面遮挡保护秘密。

## 6 用测试理解行为

先看 tests/unit/test_config.py 和 test_logging.py，理解哪些输入必须拒绝。再看 tests/http/test_api.py 的显式 StubConnections，学习 HTTP 契约与故障响应；不要把测试替身当成连接证据。

随后读 tests/integration/test_dependencies.py：真实 PostgreSQL/Redis、迁移、非超级用户、四槽位持久化与版本冲突。最后阅读 frontend/tests/smoke.spec.ts 的隔离联调和故障拦截。停止 Redis 的故障实验只可在另行批准且已证明归属的独立环境进行；本轮不停止主服务，也不自动恢复它们。

## 7 下一步学习顺序

先掌握 Python async/await、FastAPI 依赖注入、Pydantic v2、SQLAlchemy 事务、Alembic、React hooks 与 TypeScript，再阅读 P0 中 LangGraph、检查点、outbox、租约和审批设计。backend/app/services/scheduling.py 仍是 `SchedulerPort` 协议；实际 PostgreSQL Outbox + Redis Streams 调度在 P2 Worker 中，不应因该端口文件没有实现就认为没有任务队列。

P2 已实现，继续按下列顺序阅读；P3 已获开发授权，但所有不可信代码都必须通过受限服务端审批与 Docker 执行。不可信代码不得在 Windows 宿主机执行；MCP/Skills 仅通过本轮已批准的 P4 控制面使用。P5 已授权按保护策略实现，真实供应商验收依赖本地凭据及获准额度；P6 尚未授权。

## 8 跟随 P2 任务

先看 schemas/tasks.py 的 TaskCreate，理解固定 Mock、期限和限额；再看 services/tasks.py 的 TaskService.create：指纹、幂等锁、任务和 outbox 同事务。domain/tasks.py 映射实际表，迁移 0002/0003 管理结构。

阅读 workers/engine.py：publish 发布未投递的 outbox，claim 原子领取租约和 fencing，tick 消费 Streams，sweep 处理 deadline、取消、失效租约与丢失通知。进程入口 workers/main.py 关闭外部追踪并运行异步循环。

随后读 orchestration/graph.py 的 build_graph 和 validate_plan。无依赖用两个并行分支和汇聚；有依赖用串行边；Reviewer 反馈通过 increment 回到调度，但 Runtime.begin_round 和业务额度限制循环。审批节点 interrupt 不执行副作用，客户端恢复值仅是唤醒，授权来自数据库。

orchestration/runtime.py 的 operation 用稳定 role/round/attempt 标识去重；_attempt 在任务和租户日额度行锁内预留，完成后结算。services/usage.py 管共享 UTC 窗口；跨午夜用 reservation_day。Mock 单位是 JSON UTF-8 字节，不能当成真实 tokenizer。

orchestration/checkpoints.py 的 PostgresTaskSaver 实现 LangGraph 异步保存和 pending writes。理解业务账本与检查点的不同用途：检查点帮助恢复位置，账本防止重复计量。写入前检查 owner/fence，旧进程不可覆盖新进程。

最后读 api/v1/tasks.py 的 SSE、frontend/src/api/tasks.ts 的游标与重连、pages/Tasks.tsx 和 Approvals.tsx 的真实 UI 操作。LocalAuth.tsx 只在内存保留本地 Token。tests/integration/test_workflows.py 验证真实数据库/Redis、接管、预算竞争和回放；旧 scripts/p2-recovery-probe.py 已禁用，不能再用于重启主服务。

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
10. `backend/app/sandbox/engine.py`：新版 `SandboxRunner.dispatch()` 在 Docker 前提交意图；`_authorize_boundary()` 重验权限；`_monitor()` 观察 deadline/取消；`_finish()` 脱敏结算；`reconcile()` 结合可信归属记录、实际CID和代次限制管理范围，UNKNOWN 不重放。此为已提交源码，不是旧主Runner已经加载的新行为；旧宽泛清理风险见兼容报告。
11. `backend/app/sandbox/main.py` 与 `compose.yaml`：独立控制面 API、内部 Token、loopback 端口和 daemon Socket。可信 Runner 有高权限；实际执行容器无 Socket。Runner 不能作为模型工具或公共 API 暴露。
12. `frontend/src/api/sandbox.ts`、`frontend/src/pages/Sandbox.tsx`：复用管理员内存授权，独立审批者 Token 只用于 source/decision；源代码哈希核对、状态轮询、关联任务 SSE、真实输出和清理。对比 Tasks.tsx 的显式 Mock 标签，不混淆真实代码执行和真实模型推理。

## 10 用测试验证安全边界

先读 `tests/http/test_sandbox_api.py`、`tests/unit/test_sandbox_runner_policy.py` 和 `tests/unit/test_sandbox_runner_http.py`，理解额外参数、镜像、缺权限、审批变化、运行时报告不匹配、Docker 故障和不确定创建必须怎样拒绝。客户端或连接安全替身只是契约/故障测试，不能作为真实 Docker 运行证据。

再读 `tests/integration/test_sandbox.py`：真实 PostgreSQL/Redis、独立 Runner 和 Docker，使用有界代码验证正常输出、无网络、非 root、只读根、专用宿主标记不可读、CPU/内存/PIDs 限额、超时取消、输出上限、跨任务无状态泄露、重复消息和 Worker 恢复。测试使用本项目无敏感标记，不读取真实凭证或进行破坏性攻击。

当前 `scripts/test-p3.ps1` 经共享入口到 `lifecycle_regression.py` 后直接拒绝 S1_RUNNER_ISOLATION_BLOCKED，不启用真实集成或创建/清理故障Runner；pytest同样拒绝 RUN_SANDBOX=1，常规Playwright排除sandbox.spec.ts。真实批准/拒绝用例源码保留，但17＋2执行须独立隔离与新授权，不能以 opt-in、skip 或旧P3报告计为通过。

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

当前 test-p2/p3/p4/p5 分别选择阶段集成，均带单元/HTTP；P4 不再隐含执行 P3，需要分别运行。P5 强制专用 permit-test 配置，否则提前拒绝。所有入口均不自动恢复主服务。P4 历史数量见 P4_REPORT，现行入口见 LOCAL_LIFECYCLE_GUARD。

## 13 四个槽位如何连接真实 API

先读 MODEL_INTEGRATION 和 P5_REPORT。看 schemas/models.py 的 priority/credential_reference，再看 services/models.py：列表只返回引用和配置状态，实际 Key 在 providers/router.py 的调用边界解析。比较全局主机白名单与单凭据受众绑定，两者都需要满足。

接着读 providers/base.py 的 ProviderAdapter/ModelReply/ProviderFailure，再跟随 openai_compatible.py：DNS 全地址检查、固定 IP + Host/SNI、TLS、无代理/重定向、有界 SSE、终止标志与 usage。MockTransport 只验证协议处理，当前没有真实供应商连通验收。

## 14 顺着一次 P5 协作读代码

TaskService.create 保存角色/价格快照 → Redis/Worker领取租约 → RealRuntime.operation 原子预留 → Provider Adapter 调用 → Pydantic AgentPlan/Answer/Review → 持久化安全结果和用量 → LangGraph依赖分支/汇聚 → AgentToolGateway → Reviewer有限反馈。

重点比较 ModelOperation 逻辑标识、PostgresTaskSaver 检查点与 AgentToolOperation：已完成模型结果复用，未知真实派发不自动重计费；工具用稳定 key/任务/fence 绑定，不因模型重试而重复。P4 控制面和 P3 Runner 都再次校验权限与父任务。存在冲突会强制修订，Reviewer不能批准高风险执行。

暂停为协作式，当前请求先完成并保存，下一节点暂停；取消/期限关闭模型流并阻止新步骤。RealDailyUsage 与原 Mock 额度分开，未知费用不释放为零。看 real_runtime.py 的 reserve/settle 与 Worker.release_reservations 的 Mock/Real 区分，再读取消、租约恢复与单独测试额度。

## 15 通过测试区分真实能力与替身证据

test_model_adapter.py 使用 MockTransport；test_real_agents.py 的独立资源集成使用 PostgreSQL/Redis/LangGraph 和 Provider Stub，P3 Docker 相关真实测试仍受隔离阻塞。旧 p5-worker-recovery-probe.py 已禁用；两项 Permit OS 崩溃恢复的克隆库历史证据见 test_execution_permits.py 和 lifecycle_permit_child.py，不代表本轮重跑。真实模型验收需新授权；test-real-models.py 仅观察已有独立Permit，不签发或派发。

前端读 ModelCenter.tsx 的安全引用/连接测试、Tasks.tsx 的 Real/Mock/DAG/工具/预算、Chat.tsx 的持久化历史与 SSE。密钥只在本地受保护环境设置。完成本阶段后暂停，P6 需要新授权。

## 16 无模型费用的完整验收

读 scripts/p5-live-preflight.py 的服务配置白名单、凭据名称检查、零预算及子进程环境；再看 core/config.py 的受限维护dotenv、providers/openai_compatible.py 的DNS前出口门、tests/fixtures/preflight_guards.py 的测试网络限制。只看MockTransport通过不能证明真实供应商可用。

读 scripts/p5-live-database-check.py 的历史备份、临时库恢复、升降级及指纹比较实现；旧 backup/演练入口已经退役，不能按阅读顺序实际执行。347项回归、14+1浏览器及OS重启是[P5_LIVE_PREFLIGHT_REPORT](P5_LIVE_PREFLIGHT_REPORT.md)原日期证据，不能当本轮结果。再读 execution_permits.py 的签发、事务认领/预算预留、HTTP前意图和UNKNOWN结算；TaskService拒绝普通real任务。维护wrapper不授予收费或绕过维护门权限，不在聊天传Key。

## 17 进程继承、存在性与认证是不同证据

读 start-coder-local.ps1：只用 Test-Path 检查名字，经共享管理器创建或复用身份与配置一致的受保护 API/Worker，原生继承父 PowerShell 环境，前端不重启。不匹配实例不会静默替换。再读 model_runtime_status.py 的存在布尔观察、带有效期的 Worker 状态与配置摘要；True 不代表认证通过，另一个终端的 True 也不代表当前服务 True。看 test_coder_local.py 的“不读变量值”测试和 LOCAL_LIFECYCLE_GUARD 的现行操作；DEEPSEEK_CODER_LOCAL 中旧 False/False 为历史观察。所有真实调用仍需独立授权。

## 18 本地生命周期保护的阅读顺序

先读 LOCAL_LIFECYCLE_GUARD 和 LOCAL_LIFECYCLE_TEST_REPORT。随后依次读 scripts/lifecycle-entry.ps1 → lifecycle.py → lifecycle_manager.py 的 operation_lock、_check、start/stop、manual_stop、maintenance_session。重点比较普通维护与人工停止的不同授权，以及 protected 记录为何在进程死亡后仍保留。

再读 NativeBackend.launch/terminate 和 managed_service.py：启动意图、一次 claim、UUID、实际 Windows FILETIME、venv 转发父子进程、同一终止句柄、应用导入前固定关闭门禁。Worker 的进程存活不等于数据库或模型就绪，专用 check-coder-local.py 另核对0008和实际 runtime PID。

最后读 lifecycle_regression.py、tests/unit/test_lifecycle_manager.py、tests/fixtures/lifecycle_acceptance.py。FakeBackend 是逻辑替身；NativeBackend 链使用实际 Windows 进程，但应用是可信标准库 stub、随机端口及假 Key。lifecycle_permit_child.py 的双身份清理用于克隆库的真实 OS Permit 崩溃测试，模型仍是虚拟传输。不要将这些证据称为真实供应商认证或绝对进程安全。

## 19 三项封版缺口修复

先读 [MAINTENANCE_ENTRIES](MAINTENANCE_ENTRIES.md) 与 [P5_SEAL_FIX_REPORT](P5_SEAL_FIX_REPORT.md)。S1 从 NativeBackend._query → _rows/_identity/inspect/_listeners 阅读：显式成功 envelope、查询异常、成功空集和身份不确定分别处理；再看 lifecycle_permit_child._rows 对同一协议的复用。

S2 读 maintenance_policy 的 maintenance_operation、_logical_owner、cli_gate、maintenance_action 和 authorize_maintenance_command：比较 CLI、导入调用、异步 Task、独立审批及内部 helper 的权限来源。对照 scripts/p5-live-state-check.py 的当前租户筛选、退役迁移/恢复入口，理解为什么不能恢复旧 finally 行为。

S3 读 p5-live-preflight.py 的 credential_name、prepare、require_service_only_file、trusted_command、run，再读 configure-deepseek-coder.py 的解析前与写出前检查。Issuer 是独立权限，不能仅依赖模型引用分类器；维护子进程白名单与 Coder 服务合法原生继承是不同调用链。

最后读新增 test_seal_s1_queries、test_seal_s1_fixture_query、test_seal_s2_maintenance、seal_s2_probe、test_seal_s3_issuer。测试使用假凭据和独立状态；最新完整数字见修复报告，历史450项不能当成本轮成绩。旧备份/升降级脚本只用于阅读历史实现，默认退役，不应照旧执行。
