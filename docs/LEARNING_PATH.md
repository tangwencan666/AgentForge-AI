# AgentForge AI P2 源码学习路径

下面路径均位于 `D:\AIProjects\AgentForge-AI`。先理解 P1 健康请求，再跟随 P2 的任务事务、独立 Worker、LangGraph 和 SSE。模型是明确 Mock，框架和持久化真实运行。

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

deploy/init-app-role.sql 定义本地应用非超级用户；compose.yaml 定义专属卷、服务健康检查和回环端口。数据库和 Redis 的独立开发容器不是沙箱，后续 P3 需要完全不同的权限和执行边界。

## 5 阅读安全边界

backend/app/core/security.py 的 `require_admin` 进行固定时间 Token 比较，租户由服务端 Settings 决定，客户端不能用 tenant header 自授权。这是单个本地管理员入口，不是生产多用户身份系统。

backend/app/core/logging.py 的 `JsonFormatter` 采用事件和字段白名单，不序列化动态异常消息、request body、Authorization 或连接字符串；Uvicorn access log 关闭。main.py 的异常处理器只返回安全类型和字段名，不返回 Pydantic input 和 ctx。

scripts/bootstrap_local.py 只生成开发服务秘密，拒绝覆盖；scripts/check_secrets.py 检查暂存区与前端构建产物中的已知秘密。观察 .gitignore 对 .env、work、日志和依赖目录的忽略。保护秘密需要入口、出口、日志和 Git 一起约束，不能仅靠页面遮挡。

## 6 用测试理解行为

先看 tests/unit/test_config.py 和 test_logging.py，理解哪些输入必须拒绝。再看 tests/http/test_api.py 的显式 StubConnections，学习 HTTP 契约与故障响应；不要把测试替身当成连接证据。

随后读 tests/integration/test_dependencies.py：真实 PostgreSQL/Redis、迁移、非超级用户、四槽位持久化与版本冲突。最后阅读 frontend/tests/smoke.spec.ts：实际代理联调、十页导航、明确的故障拦截测试和直接访问页面。自己停掉本项目 Redis，再刷新 Dashboard，可观察真实未就绪；实验只操作本项目服务，随后恢复。

## 7 下一步学习顺序

先掌握 Python async/await、FastAPI 依赖注入、Pydantic v2、SQLAlchemy 事务、Alembic、React hooks 与 TypeScript，再阅读 P0 中 LangGraph、检查点、outbox、租约和审批设计。backend/app/services/scheduling.py 只有 `SchedulerPort` 协议，尚无实现。

P2 已实现，继续按下列顺序阅读；不要自行接通真实模型、MCP 或不可信代码执行，P3 另需批准。

## 8 跟随 P2 任务

先看 schemas/tasks.py 的 TaskCreate，理解固定 Mock、期限和限额；再看 services/tasks.py 的 TaskService.create：指纹、幂等锁、任务和 outbox 同事务。domain/tasks.py 映射实际表，迁移 0002/0003 管理结构。

阅读 workers/engine.py：publish 发布未投递的 outbox，claim 原子领取租约和 fencing，tick 消费 Streams，sweep 处理 deadline、取消、失效租约与丢失通知。进程入口 workers/main.py 关闭外部追踪并运行异步循环。

随后读 orchestration/graph.py 的 build_graph 和 validate_plan。无依赖用两个并行分支和汇聚；有依赖用串行边；Reviewer 反馈通过 increment 回到调度，但 Runtime.begin_round 和业务额度限制循环。审批节点 interrupt 不执行副作用，客户端恢复值仅是唤醒，授权来自数据库。

orchestration/runtime.py 的 operation 用稳定 role/round/attempt 标识去重；_attempt 在任务和租户日额度行锁内预留，完成后结算。services/usage.py 管共享 UTC 窗口；跨午夜用 reservation_day。Mock 单位是 JSON UTF-8 字节，不能当成真实 tokenizer。

orchestration/checkpoints.py 的 PostgresTaskSaver 实现 LangGraph 异步保存和 pending writes。理解业务账本与检查点的不同用途：检查点帮助恢复位置，账本防止重复计量。写入前检查 owner/fence，旧进程不可覆盖新进程。

最后读 api/v1/tasks.py 的 SSE、frontend/src/api/tasks.ts 的游标与重连、pages/Tasks.tsx 和 Approvals.tsx 的真实 UI 操作。LocalAuth.tsx 只在内存保留本地 Token。tests/integration/test_workflows.py 验证真实数据库/Redis、接管、预算竞争和回放；scripts/p2-recovery-probe.py 验证真实进程重启。
