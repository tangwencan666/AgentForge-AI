# AgentForge AI P3 验收报告

2026 年 10 月 15 日，Asia/Shanghai。实施与验收跨 10 月 14–15 日，项目根目录 `D:\AIProjects\AgentForge-AI`。

P3 已完成本地开发验收：真实 Docker Sandbox、独立可信 Runner、人工审批、持久化执行与恢复、真实 Sandbox Center 已实现。最终 153 项 Python 测试及 8 项浏览器测试全部通过，0 失败、0 跳过。P3 完成后暂停，等待 P4 单独批准；真实模型 API、MCP/Skills 和生产发布没有实施。

Docker 容器不是绝对安全边界。本报告说明本机实际验证的能力和未充分验证的风险，不把模型 Mock、Docker 配置检查或故障替身当作真实隔离证据。

## 1. 基线、授权与提交

最初核验 HEAD 为 P2 提交 `1f6dd0159bf4a91c96bbe6a4fad95bd947ceb25d`，工作区干净。依据 P2 源码、迁移和测试记录，仅修复 `docs/PROJECT_STATUS.md` 中队列、前端执行页面和迁移版本三个事实：PostgreSQL Outbox + Redis Streams、真实任务/审批 API、0003_tenant_limits。

文档修复独立提交：`cc486d9503a4d102b6ee014413f050c7a998a7e2`，消息 `docs: reconcile P2 project status`。提交成功且工作区干净后才继续已授权的 P3。P0、P1、P2 历史报告没有改写。

项目内 Docker SDK 安装已获用户批准。实际安装 docker 7.2.0 及项目内依赖，未改 Windows 全局 Python 或 Docker Desktop 配置。锁文件为 pywin32 保留 Windows 平台条件，Linux Runner 构建通过。

P3 使用单独的功能提交，提交 ID 以阶段完成时的 Git 历史和最终汇报为准。本报告与实现纳入同一提交，不预填自己的提交哈希；可在项目中运行 `git log -2 --format="%H %s"` 核对两次提交。

## 2. 本阶段实现

- 独立可信 Runner：只有受保护服务端接口可调度，Worker 派发执行 ID、租约 owner 和 fence；Runner 从 PostgreSQL 重读代码、审批、预算与策略。模型和浏览器没有 Docker API 权限。
- 默认拒绝：严格 Schema、租户身份、每日 CPU 额度、独立审批、代码/资源/镜像/策略绑定哈希，在创建、启动和注入边界重新校验。管理员不能使用管理员 Token 批准代码。
- 固定安全策略 `p3-python-v2`：批准的不可变镜像 ID、网络 none、UID/GID 10001、只读根、drop ALL capabilities、no-new-privileges、自定义 seccomp、CPU/内存/PIDs、无 Socket/宿主机挂载、受限 tmpfs。调用者不能覆盖 Docker 配置。
- 有界执行：Python 源码最多 64 KiB；执行 1–120 秒；CPU 0.25/0.5/1 核、内存 64–512 MiB、PIDs 8–64；全局 4/租户 2 并发；输出流上限 1 MiB，每路摘要 4096 字符。到期、取消或输出超限均终止并确认移除容器。
- 持久化与恢复：任务、执行、审批、事件、日额度、启动意图、Runner 租约和清理状态保存到 PostgreSQL；复用 P2 outbox、Redis Streams、LangGraph 检查点与 SSE。幂等创建、重复消息和 Worker 恢复不重复注入代码。
- 不确定结果：启动意图一旦提交就不自动重放；状态未知保留 needs_reconciliation。清理未确认时阻断新执行；确认删除后允许后续任务，但不将原结果改写成成功。
- 真实 Sandbox Center：创建、代码复核、独立批准/拒绝、资源、状态、取消、脱敏摘要、清理结果和历史，全部来自后端 API；授权值仅存页面内存，不进入浏览器持久存储。
- 一次性容器：执行后销毁，不回池。预热默认关闭，尝试启用被配置校验拒绝。本轮没有实现并启用预热池；尚无独立验证的池生命周期与隔离证明，因此不开放复用。

## 3. 目录、核心类与阅读顺序

以下路径均相对项目根目录，完整路径为 `D:\AIProjects\AgentForge-AI\<路径>`。

| 路径 | 核心职责 / 阅读入口 |
| --- | --- |
| backend/app/schemas/sandbox.py | ResourceLimits、SandboxCreate、SandboxExecutionRequest、RunnerDispatch、SandboxExecutionResult；先读请求允许范围 |
| backend/app/domain/sandbox.py | SandboxExecution、SandboxDailyUsage；执行审计字段、状态与预算 |
| backend/migrations/versions/0004_sandbox_sandbox.py | 新增沙箱执行和日额度表，保留既有业务表 |
| backend/app/services/sandbox.py | SandboxService.create/decide/cancel/policy、execution_dto、settle_budget；创建、审批、取消与结算 |
| backend/app/api/v1/sandbox.py | 管理员与独立审批者接口，受控源码查看、真实 Runner 状态 |
| backend/app/services/orchestration/sandbox_graph.py | build_sandbox_graph；持久化审批中断、受限派发、结果查询 |
| backend/app/workers/engine.py | Worker.execute；P2 Mock 与 P3 真实沙箱分流、超时取消与恢复 |
| backend/app/sandbox/policy.py | operation_digest、validate_execution、create_options、verify_container、verify_attestation、assert_runner_lease |
| backend/app/sandbox/engine.py | SandboxRunner.dispatch、_authorize_boundary、_monitor、_finish、reconcile；启动意图、租约、对账 |
| backend/app/sandbox/driver.py | DockerDriver.run/remove；实际 Docker 生命周期、输出、资源与强制清理 |
| backend/app/sandbox/main.py | 独立内部 FastAPI Runner，受保护 dispatch/status，无公共文档 |
| sandbox-image/Dockerfile、launcher.py | 固定镜像、可信 attest/main、容器内 watchdog；不在 Windows 主机运行不可信代码 |
| frontend/src/api/sandbox.ts、pages/Sandbox.tsx、sandbox.css | 真实页面与 API、源代码复核、内存 Token、SSE、执行历史 |
| scripts/bootstrap-sandbox.py、freeze-lock.py | 项目内凭据/镜像登记与跨平台依赖锁定 |
| scripts/test-p3.ps1、p3-worker-recovery-probe.py | 真实测试入口与实际 OS Worker 重启探针 |
| tests/integration/test_sandbox.py、test_sandbox_failures.py | 真实 Docker、容量、故障 Runner 和租约过期；与 unit 故障替身分开 |

同时更新配置、Compose、HTTP/回归测试和学习文档。`SANDBOX_SECURITY.md` 详述威胁边界，`SANDBOX_EXECUTION_PROTOCOL.md` 详述接口、角色、状态和审计字段，`LEARNING_PATH.md` 提供分阶段源码阅读顺序。

## 4. 最终自动化结果

最终统一执行，不累加调试和重复试跑。

| 验证 | 实际结果 | 证据 / 说明 |
| --- | --- | --- |
| Python 单元与 HTTP | 117 passed，0 failed，0 skipped | 包含 49 项 Runner 策略/故障单元测试；明确使用替身的测试不作为实际 Docker 证明 |
| 既有 PostgreSQL/Redis 集成 | 20 passed，0 failed，0 skipped | 保留 P1/P2 真连接、四角色 Mock、审批、限额、取消、恢复与 SSE |
| P3 真实沙箱服务集成 | 16 passed，0 failed，0 skipped | 实际 PostgreSQL、Redis、独立 Runner、Docker Desktop Linux 容器；包含不可用 daemon 的独立故障服务 |
| Python 合计 | **153 passed，107.03 秒** | work/p3-all-final.xml；其中真实集成总数 36 |
| Playwright 浏览器 | **8 passed，28.2 秒，0 failed，0 skipped** | 真实沙箱批准执行/拒绝 2 项，既有核心 6 项；work/p3-e2e.json |
| TypeScript 与 Vite | 通过，51 modules | npm run build 包含类型检查；使用真实 API，不填充虚构运行数据 |
| Alembic | upgrade/current 为 0004_sandbox，check 无新增模型差异 | 项目专属真实 PostgreSQL |
| Python 依赖 | pip check 通过 | 项目 .venv，无全局安装 |
| 实际 OS Worker 重启 | 单独探针通过，不纳入 161 用例计数 | scripts/p3-worker-recovery-probe.py；中途结束自建可信 Worker 并重启，同启动意图、同容器 ID、一次输出、确认清理 |
| 清理 | 任务执行容器为零 | docker ps -a 按 agentforge.sandbox.execution 标签检查，覆盖全部策略版本；仅移除专用故障 Runner |
| 安全与提交检查 | diff、暂存文件、构建产物与项目日志的已知凭据扫描通过 | .env、work、.venv、node_modules 不提交；不记录凭据值 |

最终 Python + 浏览器合计 **161 项通过**。SSE/模型回归中的 Token 和费用仍是明确 Mock，不能据此声称真实模型或账单联通。

## 5. Docker 实际隔离验证

| 能力 | 实际执行证据 |
| --- | --- |
| 正常代码 | 容器内 print 输出返回，exit_code=0，非 Mock，检查点存在，容器已移除 |
| 网络 | 容器直接 TCP 连接 1.1.1.1:80 返回 Linux ENETUNREACH=101；接口仅 lo，没有访问目标服务；不是只核对 network_mode 字段 |
| 未授权宿主文件 | 项目 work 下专门生成的非敏感标记，在 D 路径及 Docker Desktop 两种宿主映射路径均不可读；不读取真实敏感文件 |
| 权限与根文件系统 | 实际 UID 10001；Seccomp=2、NoNewPrivs=1、capability 集合为零；对镜像内 0666 canary 写入返回 EROFS，区别于文件权限 EACCES |
| 凭据与 Socket | 不可信进程环境无 TOKEN/PASSWORD/AGENTFORGE/DATABASE/REDIS 键，容器内不存在 Docker Socket；已知凭据源码提交被拒绝 |
| CPU | 0.25 核的有限 2 秒计算，实际 CPU/墙钟比小于 0.55；同时核验 cgroup v2 限额 |
| 内存 | 64 MiB 限制下有限 128 MiB 分配非零退出/被容器限额终止，没有进行宿主机 OOM 攻击 |
| PIDs | pids=8，最多尝试 12 个子进程，仅允许有限数量且命中上限，没有无限 fork |
| 超时、取消 | 真实运行中超时或取消，整个容器终止，记录清理确认，而非只改变 API 状态 |
| 输出 | 2 MiB 输出触发 output_limit，摘要截断到限额，容器清理；自然退出与 kill 竞态也有回归覆盖 |
| 并发 | 同时运行租户 2/全局 4 个实际容器，第 3/第 5 次派发返回 429，未创建新的启动意图 |
| 无状态泄露 | 第一任务写临时标记，后续新容器不存在标记；容器从未回池 |
| 审批与重复执行 | 拒绝后无容器；重复消息与新 Worker 使用同执行 ID/启动意图/容器 ID，输出只有一次 |
| Docker 不可用 | 独立故障 Runner 无 Socket、指向不存在的 daemon，实际返回 503，无启动意图、无容器、无宿主机执行回退；共享 Docker daemon 保持运行 |
| 租约失效 | 实际运行容器的 Runner 租约受控过期，Worker 租约仍有效；拒绝续活、needs_reconciliation、保留原启动意图与容器 ID、确认移除，不重放 |
| 执行结束 | 正常、失败、输出超限、超时、取消与对账之后逐项检查没有对应容器，阶段最终全标签检查为空 |

镜像白名单、无权限、篡改与审批绑定另有 Schema/HTTP/策略拒绝测试；这些拒绝测试不能单独证明容器隔离。没有通过破坏性逃逸或访问其他项目来做验收。

## 6. 失败记录与修复

开发试跑确实发生失败；最终通过不抹去这些记录。诊断 XML/日志保留在 Git 忽略的 work 中。

1. Linux Runner 初次构建遇到 Windows pywin32 锁定依赖；补充 sys_platform 条件及 freeze-lock 脚本后构建通过。Docker SDK 不接受 create 的 stop_timeout 参数，删除该参数，超时仍由 Driver 和容器 watchdog 控制。
2. 初期 seccomp 阻止 CPython 打开脚本的 close-on-exec ioctl。核对 CPython/Linux 定义，仅允许 FIOCLEX=0x5451，策略从 v1 升为 v2；未关闭 seccomp，未放行任意 ioctl。重新审批使用新的执行 UUID，原启动意图不重放。
3. 输出洪泛导致 URL 脱敏正则耗时并持有业务行锁。停止本项目测试和 Runner 后对账；修正为有界线性匹配，脱敏在线程及行锁外完成，增加 1 MiB 性能回归。未知执行保留对账状态，不重新运行。
4. 网络探针最初使用 settimeout 触发未开放的 FIONBIO，并误用 Windows errno 与 Linux 结果比较。改为受整体超时控制的 direct connect 与 Linux 101 断言；未放宽网络或 ioctl 策略。首次隔离试跑 13 项为 12 通过、1 失败，后续新执行及最终统一 16 项通过。
5. Docker 容器自然退出与 kill 409 存在竞态，曾覆盖已知 output_limit 或误报清理。统一 stop_container，必须重新确认已停止/删除；未知清理继续阻断，已知主终止原因保留。新增回归后最终套件通过。
6. 已确认未创建的失败记录曾占用并发名额，修正计数仅包含待启动或清理未确认记录；保留全部审计历史。租约单元测试时间改为测试内计算，避免整套运行耗时影响，实际租约仍为 15 秒。
7. 最终审查补齐 test-p3.ps1 在故障 Runner 启动失败时的限定清理，以及清理/恢复失败时仍还原环境变量和工作目录的 finally。脚本语法解析及现有进程归属单元测试再次通过；没有为文档收尾重复运行整套或累加测试数量。

## 7. 当前实际运行

- Sandbox Center：http://127.0.0.1:15173/sandbox；前端：http://127.0.0.1:15173。
- FastAPI：http://127.0.0.1:18100；OpenAPI：http://127.0.0.1:18100/docs。
- 内部可信 Runner：http://127.0.0.1:18120，需要仅服务端 Token；不公开给模型。
- PostgreSQL agentforge-p1-postgres，127.0.0.1:15432；Redis agentforge-p1-redis，127.0.0.1:16379，两者真实连接且健康。
- 本地 API、Vite、独立 Worker 保持运行；Compose app profile 的重复应用/Worker 保持停止。可信 agentforge-p3-runner 运行；agentforge-p3-unavailable-runner 已清理。
- 本机 Docker Engine 29.7.2、Compose v5.4.0，Linux cgroup v2/seccomp 可用；Windows Docker Desktop 全局设置没有修改，其他项目容器和卷没有删除或改动。

上述是验收时状态，电脑重启后需按 GETTING_STARTED 重启。每日额度保留测试的真实审计记录，未清空数据库来美化演示。

## 8. 限制、残余风险与 P4 条件

Docker 共享 Linux 内核与 Docker Desktop VM/宿主集成，仍有内核、daemon、hypervisor 与供应链风险。本轮不能充分验证 Windows 主机逃逸防护、AppArmor/SELinux、生产身份隔离或专用 Linux 执行节点；不能声称绝对安全。

可信 Runner 持有高权限 daemon Socket，被攻陷可能影响整个 Docker 环境。当前仅在可信控制面使用，任务无挂载；生产需要独立执行节点和受限控制面审计。本机不同角色 Token 仅是逻辑身份，不能证明不同人员职责分离；尚未发布生产 OIDC/RBAC/RLS。

审批源码以 64 KiB 上限存于 PostgreSQL 业务表，默认列表、事件和日志不包含完整代码；受控审批查看允许源码返回。生产加密、保留期治理和更完整访问审计待另行设计。已知秘密过滤不能保证识别任意未知机密，使用者不应把秘密写进待执行代码。

实际 OS Worker 重启、重复消息、Runner 租约失效和清理已验证；本轮没有专门强杀 Runner OS 进程并覆盖全部崩溃窗口，不能将 Worker 重启代称完整 Runner 崩溃验收。未知结果保守停留对账状态，非自动成功，清理确认后不阻塞独立新任务。

预热没有启用，容器全部一次性。仅支持批准 Python 镜像与标准库，不支持任意镜像、外网下载、宿主挂载或产物导出。资源峰值为采样，部分字段可为空；预算采用 CPU×超时预留上界保守结算，不是金额或供应商 Token 账单。

P4 准备条件：用户单独批准 MCP Tool Gateway/Skills 的开发范围；明确工具白名单、身份/权限、Schema、调用额度/超时/审计和高风险审批；Skills 候选生成与安装启用人工审批；保持 P3 回归和 Fail Closed。生产身份、专用执行节点和任何系统/Docker Desktop 设置变更需要另行评审和授权。当前暂停，不自动进入 P4。
