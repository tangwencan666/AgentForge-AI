# P3 沙箱执行协议

本文件描述 P3 实现的协议与控制边界。模型回答仍使用 P2 显式 Mock；沙箱中的 Python 是真实 Docker 执行，`is_mock=false`。本阶段不调用真实模型，不接入 MCP、Skills 或 P4。

本阶段实施与实际验证跨 2026 年 10 月 14–15 日（Asia/Shanghai），当前策略为 `p3-python-v2`。本文件依据源码与已确认执行行为描述协议；最终测试数量、运行证据和提交由 `P3_REPORT.md` 汇总，接口本身不等于所有隔离能力已证明。

## 1. 公共创建请求与内部执行契约

浏览器调用 `POST /api/v1/sandbox/executions`，提供管理员 Bearer Token 和 UUID 格式的 `Idempotency-Key`。公共请求使用 `SandboxCreate`，仅接受以下字段：

```json
{
  "language": "python",
  "code": "print('hello sandbox')",
  "timeout_seconds": 10,
  "resource_limits": {
    "cpu": 0.5,
    "memory_mb": 128,
    "pids": 32
  }
}
```

| 字段 | 服务端约束 |
| --- | --- |
| `language` | 固定 `python`；不接受 shell 或任意解释器 |
| `code` | 非空，UTF-8 编码后最多 64 KiB；使用 `SecretStr` 防止对象 repr 回显；发现已知凭证或常见密钥模式时拒绝 |
| `timeout_seconds` | 整数，1–120 秒；公共默认值 30 秒 |
| `resource_limits.cpu` | 只允许 0.25、0.5 或 1.0 核额度 |
| `resource_limits.memory_mb` | 整数，64–512 MiB，默认 128 MiB |
| `resource_limits.pids` | 整数，8–64，默认 32 |

未声明字段被拒绝。调用者不能提交镜像、网络模式、用户、挂载、Docker Socket、capabilities、seccomp、`privileged`、entrypoint 或 Docker 参数。P3 仅支持内联代码，不接受任意 URL、宿主机路径或代码引用下载。

服务端生成 `task_id`、`execution_id` 和 `approval_reference`，租户来自认证上下文。`SandboxExecutionRequest` 在 `backend/app/schemas/sandbox.py` 中补充这些 UUID 字段，表示经过服务端关联的完整执行请求；不是开放给浏览器覆盖业务身份的创建载荷。

Worker 调用独立 Runner 时，实际传输 `RunnerDispatch`：

```json
{
  "task_id": "服务端生成的 UUID",
  "execution_id": "服务端生成的 UUID",
  "owner": "当前 Worker 所有者",
  "fence": 1
}
```

Runner 从 PostgreSQL 读取代码、资源、审批和固定镜像，重新校验 Worker 租约与 fencing；不接受 Worker 或模型转交的任意 Docker 配置。代码只在容器检查与运行时校验通过后，通过容器 stdin 发送一次。

## 2. 角色、权限与审批绑定

| 角色 | 允许的操作 | 凭据边界 |
| --- | --- | --- |
| 本地管理员 | 读取策略、创建、列表、详情、取消、读取任务 SSE | `AGENTFORGE_ADMIN_TOKEN`，浏览器当前内存 |
| 独立沙箱审批者 | 读取受控源代码、批准或拒绝执行 | `AGENTFORGE_SANDBOX_APPROVER_TOKEN`，浏览器沙箱页面当前内存 |
| 可信 Worker | 带租约和 fence 调度已批准的执行 | `AGENTFORGE_SANDBOX_RUNNER_TOKEN`，仅服务端 |
| 模型 / Reviewer | 没有 Docker API、Runner Token 或直接执行权限 | 审查意见不代替服务端鉴权 |

三种控制面凭据必须不同、至少 32 字符。它们不是模型 API Key。当前身份为本地开发的固定角色；P3 不声称提供生产级独立人员身份、OIDC 或多租户身份管理。

`operation_digest()` 对以下内容做排序 JSON 的 SHA-256：`code_hash`、语言、超时、资源限制、固定 `image_id`、`policy_version`。`code_hash` 是原代码 UTF-8 字节的 SHA-256。审批记录关联租户、任务、操作哈希、策略版本、有效期和决定者。

代码、镜像、限制或策略版本变化后，旧批准不能授权新操作。安全策略的代码变更必须由维护者审查、升级策略版本并重新审批；版本号不是自动计算的全部策略源码摘要。v1 到 v2 的最小 FIOCLEX 兼容性修正采取新执行 UUID 与新审批验证，原诊断执行不重放。镜像/策略轮换前应确认旧版本执行容器为零。

审批者应先调用受限 `/source` 接口，复查真实代码以及资源、超时和哈希。前端只有完成代码读取和绑定哈希检查后才能勾选确认并批准。拒绝不需要先读取代码。页面上的确认框只是交互辅助，服务端始终独立鉴权与校验。

管理员不能使用自己的 Token 批准高风险代码执行。批准需 `sandbox-reviewer` 独立角色，并且不能与 `local-admin` 发起者相同。审批过期、已取消、哈希不匹配或检查点尚未保存时不能执行。

## 3. 公共接口

公共响应沿用 `ApiResponse`：`success`、`data`、`error` 和 `request_id`。代码和凭据不进入普通列表、结果 DTO 或校验错误详情。

| 方法与路径 | 权限 | 返回或行为 |
| --- | --- | --- |
| `GET /api/v1/sandbox/policy` | 管理员 | 固定策略、允许资源、并发限制、预热关闭、configured 及真实 runner_status |
| `POST /api/v1/sandbox/executions` | 管理员 | HTTP 202，持久化记录；尚未执行代码 |
| `GET /api/v1/sandbox/executions` | 管理员 | 当前租户最近 100 条执行记录 |
| `GET /api/v1/sandbox/executions/{execution_id}` | 管理员 | 当前持久化状态与结果 |
| `POST /api/v1/sandbox/executions/{execution_id}/cancel` | 管理员 | 持久化取消意图；运行中的任务由 Runner 终止并确认清理 |
| `GET /api/v1/sandbox/executions/{execution_id}/source` | 独立审批者 | 受控 `language`、`code`、`code_hash` 和 `operation_hash`；`Cache-Control: no-store` |
| `POST /api/v1/sandbox/executions/{execution_id}/decision` | 独立审批者 | `decision: approved/rejected` 与当前 `operation_hash`；批准后创建 outbox 通知 |
| `GET /api/v1/tasks/{task_id}/events` | 管理员 | 复用 P2 SSE、`Last-Event-ID` 事件回放 |

创建需要 UUID 幂等键。同一租户、同一键和同一操作返回原执行；载荷冲突返回 409。浏览器请求失败后复用相同键重试，成功后新请求使用新键。当前请求指纹还依赖管理员 Token 的 HMAC；管理员凭据轮换后不能把旧键当作稳定的跨轮换去重协议。

独立 Runner 控制面为 `POST /internal/executions/{execution_id}/dispatch`，HTTP 202；使用 `X-AgentForge-Runner-Token`，无公共 OpenAPI 页面。本地仅绑定 loopback，Compose 通过项目控制网络通信。它不供浏览器、Agent 或外部用户直接调用。

同一内部 Token 可读取 `GET /internal/status` 的 `available`、`blocked` 和本 Runner `active_executions`。公共 policy 由后端短时探测此状态后返回；无法取得时 available=false、blocked=true、活跃数为空。`configured` 仅代表配置登记，不证明 Docker 就绪；活跃数属于当前单 Runner，不是跨进程全局并发指标。`/health/live` 仅证明进程存活。

常见拒绝原因如下，完整行为以源码与 HTTP 测试为准：

| 情况 | 状态 / 静态错误码 |
| --- | --- |
| 公共管理员授权缺失或错误 | 401 |
| 无独立审批权限 | 403 `SANDBOX_APPROVAL_FORBIDDEN` |
| Schema、额外字段、UUID、代码大小不合法 | 422 / `CODE_SIZE_INVALID` |
| 输入含已知凭证或密钥模式 | 422 `SENSITIVE_CODE_REJECTED` |
| 幂等键载荷冲突 | 409 `IDEMPOTENCY_CONFLICT` |
| 审批哈希变化、审批失效 | 409 `APPROVAL_MISMATCH` / `APPROVAL_INACTIVE` |
| 审批检查点尚在保存 | 409 `APPROVAL_CHECKPOINT_PENDING`，允许有限重试 |
| 租户资源预算不足 | 409 `SANDBOX_BUDGET_EXCEEDED` / `SANDBOX_BUDGET` |
| Runner 并发已满 | 429 `SANDBOX_CAPACITY` |
| 未配置、Runner 不可用或清理无法确认 | 503 `SANDBOX_UNAVAILABLE` / `RUNNER_UNAVAILABLE` |
| 执行不存在或不属于当前租户 | 404 `EXECUTION_NOT_FOUND` |

Docker 失败也可能在已接受任务的异步执行结果中体现为静态 `failure_reason=DOCKER_UNAVAILABLE`。HTTP 202 只表示受理，不表示已审批、已运行或成功。

## 4. 持久化状态与恢复

`sandbox_executions` 与 P2 `agent_tasks`、`task_approvals`、outbox、图检查点关联。PostgreSQL 是真相源；Redis Streams 只投递通知。

执行经历 `waiting_approval`、`queued`、`starting`、`running`，最后进入 `succeeded`、`failed`、`rejected`、`cancelled`、`timed_out`、`output_limit` 或 `needs_reconciliation`。待审批阶段关联 P2 任务 `waiting_approval`。取消意图与执行记录清理状态分别保存，不能将“请求取消”当作容器已经消失。

审批和排队计入任务总 deadline，当前总窗口 900 秒；代码运行有独立 1–120 秒超时。Worker 重启从 LangGraph 检查点恢复。Runner 独立租约及监控不依赖 Worker 长期在线；Worker 恢复后查询原执行结果，不能因为重复消息启动第二份代码。

Runner 在调用 Docker 前，将 `launch_claimed_at` 和所有者持久化。提交过启动意图的执行不重新注入代码。启动后的结果未知时设 `needs_reconciliation` 并核对本项目容器，不能把未知结果当作失败后自动重跑。若清理仍 `unconfirmed` 则全局阻断；确认 `removed` 后保守结算原额度，可接受新任务，但原执行仍保留未知结果，不重跑也不改成成功。

Runner 租约与 Worker 租约独立。已经过期的 Runner 租约不允许在监控或注入边界续活，晚到的完成者不能发布成功。重复消息与真实 Worker OS 重启已验证唯一启动意图、同容器 ID、一次输出及清理；受控 Runner 租约过期用例也已通过，Worker 租约仍有效时原执行不续活、不重放且实际容器清理。本轮没有专门强杀 Runner OS 并覆盖全部恢复窗口，不能将 Worker 重启验证代称 Runner 崩溃验证。

这种保守策略提供“同一执行最多一次启动意图/代码注入”，会牺牲可用性，不声称分布式外部副作用 exactly once。需要人工重新提交时，应先核对旧执行结果、清理和副作用，再创建新的执行 ID 与审批。

预算是每日 UTC 租户 CPU 秒资源额度，创建时预留 `cpu × timeout_seconds` 上限，默认每日 3600 CPU 秒。它不是供应商 Token 或美元费用。提交启动意图后按预留上限保守结算，未启动的取消/拒绝释放预留；未确认清理保留额度，确认清理后结算一次。实际资源采样用于观测，可能错过短时峰值，不作为零消耗或精确账单依据。

## 5. 结果、日志和前端

`SandboxExecutionResult` 包含：

| 字段 | 含义 |
| --- | --- |
| `execution_id`、`status`、`exit_code` | 真实执行身份、状态、容器退出结果；未执行时退出码为空 |
| `stdout_summary`、`stderr_summary` | 先脱敏再裁剪，每个最多 4096 字符 |
| `duration_ms` | Runner 记录的运行阶段耗时；尚无结果时为空 |
| `resource_usage` | 采样 CPU 秒、内存/PIDs 采样峰值、OOM、输出字节数及截断状态；未知字段为空 |
| `container_id` | 已创建容器的审计 ID；容器删除后仍保留 ID |
| `failure_reason` | 静态原因码；不回显底层异常、环境变量或源代码 |
| `cleanup_status` | `not_created`、`pending`、`removed` 或 `unconfirmed` |

累计 stdout/stderr 上限 1 MiB；超限终止执行并标记 `output_limit`。Docker 日志驱动为 `none`，结果摘要通过受限 attach 流采集。默认不保存原始完整输出、请求正文、凭据、源代码到应用日志或 SSE。源代码作为业务输入单独持久化，保密与留存限制见安全文档。

输出脱敏在有界线程工作中完成，再进入数据库业务行锁，避免大输出的处理耗时阻塞取消或检查点。对未知秘密的检测仍有限，不能据此允许提交真实 API Key。

前端 Sandbox Center 读取实际策略、历史、详情、审批和结果，每 2 秒刷新，并订阅关联任务的 SSE。轨迹只展示允许的元数据，不输出代码或任意事件载荷。管理员和独立审批者 Token 均不进 URL、localStorage 或 sessionStorage。管理员授权保存在应用内存，SPA 页面导航期间保留，刷新或退出授权后清空；独立审批者 Token 与受控源码属于沙箱页面内存，离开沙箱页面或刷新后清空。

P2 任务页保持 `is_mock=true` 的模型回答和模拟计量；Sandbox Center 的执行为 `is_mock=false`。两种模式必须分开说明，不将真实 Docker 执行宣传为真实模型生成或推理。

## 6. 源码阅读顺序

以下路径均相对于 `D:\AIProjects\AgentForge-AI`：

1. `backend/app/schemas/sandbox.py`：`ResourceLimits`、`SandboxCreate`、`SandboxExecutionRequest`、`RunnerDispatch`、`SandboxExecutionResult`。
2. `backend/app/domain/sandbox.py`：`SandboxExecution`、`SandboxDailyUsage`；`backend/migrations/versions/0004_sandbox_sandbox.py` 创建对应表。
3. `backend/app/api/v1/sandbox.py`：`require_approver()` 与公共接口；`backend/app/services/sandbox.py`：`SandboxService.create()`、`decide()`、`cancel()`。
4. `backend/app/services/orchestration/sandbox_graph.py`：`build_sandbox_graph()` 中的持久化审批与受限派发；`backend/app/workers/engine.py`：`Worker.execute()` 工作流分流与恢复。
5. `backend/app/sandbox/policy.py`：`operation_digest()`、`validate_execution()`、`create_options()`、`verify_container()`、`verify_attestation()`。
6. `backend/app/sandbox/engine.py`：`SandboxRunner.dispatch()`、`_authorize_boundary()`、`_monitor()`、`_finish()`、`reconcile()`；`driver.py`：`DockerDriver.run()` 和 `remove()`。
7. `sandbox-image/launcher.py`：仅在容器内运行的 `attest()` 与 `main()`，不得在 Windows 宿主机运行不可信代码。
8. `frontend/src/api/sandbox.ts` 与 `frontend/src/pages/Sandbox.tsx`：真实接口、内存授权、代码复核、SSE 与结果页面。

协议、权限和恢复测试与真实 Docker 隔离测试必须分别计数；HTTP 测试使用安全替身时不能据此宣称 Docker 隔离通过。`tests/integration/test_sandbox.py` 已运行正常代码、权限/网络/只读、资源、超时取消、输出、跨任务和重复消息验证；`test_sandbox_failures.py` 的真实容量及专用故障 Runner 验证不操作共享 Docker daemon；`scripts/p3-worker-recovery-probe.py` 验证实际 OS Worker 重启。首次失败、修复后的新执行和最终统一计数见 `SANDBOX_SECURITY.md` 与 `P3_REPORT.md`，不累加诊断重复运行。
