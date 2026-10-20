# AgentForge AI P5 本地启动指南

> 2026-10-19 归档修正：G4 `e9ced78` 已 Archive-only 提交，运行验收仍 **RUNTIME_BLOCKED**，原 `fake_coder_protected_start` IPC 失败和 Sandbox 17＋2 阻塞见 [PROJECT_STATUS](PROJECT_STATUS.md)。本轮未实时核验主服务、数据库、Docker、凭据、模型槽位或 Permit/预算状态，均为 UNKNOWN / 未验证；旧 Protected/True/True 仅代表原日期观察。本文安装与运维命令是需另行批准和现场预检的条件示例，历史 Runner 操作不得用于当前共享 Engine；没有可直接接管主服务的授权。

> P5 SEAL-S1/S2/S3 修复后的入口和权限以 [MAINTENANCE_ENTRIES](MAINTENANCE_ENTRIES.md) 为准。首次部署、迁移、Runner 或维护命令不授权对现有实例执行。不要手工删状态、直接用 Compose 替换应用或绕过退役入口。修复代码仅在隔离目录验收，未自动重启服务；历史结果见 [P5_SEAL_FIX_REPORT](P5_SEAL_FIX_REPORT.md)。

2026 年 10 月 16 日原指南，2026-10-19 文档更正，Asia/Shanghai。已提交源码的安全默认及 Coder 启动策略要求真实调用/Permit 签发关闭、日/测试费用预算0、四槽停用、Worker deny、重试0及应用模型出口阻断；这不是本轮对运行中进程的观察。真实供应商验收仍 BLOCKED，未授权进入 P6。

## 1 环境与隔离

根目录固定为 `D:\AIProjects\AgentForge-AI`。原指南记录的验证环境为 Python 3.13.5、Node 24.14.1、Docker Engine 29.7.2、Compose v5.4.0；本轮未重测这些版本。Python 最低要求 3.11。后端精确依赖记录在 `backend/requirements.lock`，前端记录在 `frontend/package-lock.json`。锁文件锁定版本，不声明带完整供应链签名验证；P1 不支持生产部署。

数据库、Redis 仅发布到 127.0.0.1。容器名为 agentforge-p1-postgres、agentforge-p1-redis；卷为 agentforge-p1-postgres-data、agentforge-p1-redis-data。不要将环境变量连接地址改成其他项目，也不要使用全局 docker prune 或 Redis FLUSHALL。本项目的 Compose 数据网络允许普通开发网络，但无公网数据库端口；它不是代码沙箱网络。

以下安装示例面向另行批准的独立准备环境，不在本次归档中执行。历史依赖安装授权不自动延续到重装或系统配置调整。不要全局安装依赖。

```powershell
Set-Location D:\AIProjects\AgentForge-AI
New-Item -ItemType Directory -Path work/tmp,work/pip-cache,work/npm-cache -Force | Out-Null
$env:TEMP = (Resolve-Path work/tmp).Path
$env:TMP = $env:TEMP
if (-not (Test-Path .venv/Scripts/python.exe)) { python -m venv .venv }
./.venv/Scripts/python.exe -m pip install --cache-dir work/pip-cache -r backend/requirements.lock
./.venv/Scripts/python.exe -m pip install --cache-dir work/pip-cache --no-deps -e ./backend
Push-Location frontend
npm ci --ignore-scripts --cache ../work/npm-cache
Pop-Location
```

如果 .venv 已存在，直接复用，不覆盖已有环境。P3 Docker SDK 及已批准依赖按 backend/requirements.lock 安装到同一项目 .venv，不全局安装。依赖下载需要网络；安装器临时文件及缓存放在项目 work 下。

## 2 生成本地配置

```powershell
./.venv/Scripts/python.exe scripts/bootstrap_local.py
```

脚本生成项目 .env 和 work/redis.conf，随机产生 PostgreSQL 管理密码、应用密码、Redis 密码和本地管理 Token，均不显示值。已存在文件拒绝覆盖。P2 Mock 不需要真实模型 API Key。不要将 .env、work 文件、密钥或启动日志提交到 Git。

默认端口：后端 18100、前端 15173、PostgreSQL 15432、Redis 16379。生命周期管理器的应用端口读取调用终端的 BACKEND_PORT、FRONTEND_PORT；若需改端口，先在该终端显式设置，并同步项目 .env 的对应配置及代理目标。数据库/Redis 端口同时更新 AGENTFORGE_DATABASE_URL、AGENTFORGE_REDIS_URL。不要打印完整 .env 或不带 --quiet 的 Compose 展开配置。

## 3 启动数据库和 Redis（需独立批准）

下列为初始化入口示例，不证明当前数据库健康或允许主库升级。最近已记录的主库为历史 `0008_execution_permits`；G2 提交的0009/0010只在隔离库验证。主库备份、恢复验证与迁移须按 [维护 Runbook](S3B2_MAINTENANCE_RUNBOOK.md) 单独批准，不得直接复制 `upgrade` 更新当前主库。

```powershell
docker version
docker compose config --quiet
docker compose up -d --wait postgres redis
./.venv/Scripts/python.exe scripts/migrate.py upgrade
./.venv/Scripts/python.exe scripts/migrate.py check
./.venv/Scripts/python.exe scripts/migrate.py current
```

Alembic 保留 P1/P2 表；P3 的 0004_sandbox 增加沙箱表，P4 的 0005_capabilities 继续增加工具、审批、审计、Skill 和受管笔记表。用 current/check 确认本项目当前迁移，不能仅改文档宣称升级成功。应用连接使用非超级用户 agentforge，管理密码与应用密码独立。Redis 配置 AOF 与认证，不初始化其他项目数据。

从 P2 升级时，已有健康 PostgreSQL/Redis 容器及卷应继续复用，不重建、清空或轮换其配置。先检查 `docker compose ps`，如果已运行，不必再次启动数据服务；只对本项目执行迁移。后续 Runner 使用 `--no-deps` 启动，避免修改现有数据容器。

Docker 不可用时记录阻塞，不能宣称真实依赖已连通。不以 SQLite、fakeredis 或 Mock 代替 PostgreSQL/Redis 的验收。

## 4 启动前后端

```powershell
./scripts/start-local.ps1
```

启动脚本在后台隐藏窗口运行 API、Vite 和独立 Worker，只管理本项目登记实例。普通入口要求终端没有模型/Issuer 凭据；端口冲突、未登记进程、身份不符、锁竞争或受保护记录均拒绝。work/lifecycle/manifest.json、稳定 OS 锁及审计替代旧 work/dev-pids.json 的管理权；不能删除状态文件绕过保护。P3 另需第 10 节的独立可信 Runner。不要直接运行 uvicorn/Worker 来绕过共享管理器。

Coder 由用户在自己的持 Key PowerShell 中运行 scripts/start-coder-local.ps1；它只创建或复用受保护的 API/Worker，不启动前端。已存在的不匹配实例需按 LOCAL_LIFECYCLE_GUARD 的人工流程处理，不能自动覆盖。前端尚未运行时该入口不会使15173自动可访问。

访问：前端 http://127.0.0.1:15173，后端 http://127.0.0.1:18100，OpenAPI 文档 http://127.0.0.1:18100/docs。GET /health/live 只证明 API 活着；GET /health/ready 验证 PostgreSQL、Alembic 版本/核心表和 Redis PING。未就绪返回 HTTP 503，不返回密码、主机连接串或异常值。

Dashboard 通过 Vite 同源代理调用真实 /health/ready，每 15 秒刷新，并显示请求 ID。服务无法连接时显示“未确认”，不能复用旧成功状态。Model Center 的已提交实现读取真实槽位、非秘密配置状态、policy 与指标；接口不可用时不能伪造已读取或已认证，页面能力不代表本轮主后端健康。

## 5 模型配置接口

GET /api/v1/model-slots、POST /api/v1/model-slots/validate、PUT /api/v1/model-slots/{role} 使用本地管理 Bearer Token。Token 从受保护的 .env 读取，不写 URL 或浏览器缓存。任务、计划审批和沙箱页面提供仅内存的本地开发授权输入，不是生产登录。

role 为 planner/coder/researcher/reviewer。PUT 为完整配置替换并携带 expected_version；并发修改版本冲突返回 409。配置字段为 provider、base_url、model、credential_reference、temperature、max_tokens、timeout、enabled、priority、thinking_mode、reasoning_effort。原始 api_key 等额外字段一律拒绝且不回显。

credential_reference 只接受 `env:AGENTFORGE_MODEL_...` 引用，仍无秘密写入或真实模型调用。启用真实配置时校验引用；base_url 必须为批准 HTTPS 域名，无用户名密码/query/fragment/非 443 端口。工作流 Mock 快照独立，不覆盖这些配置。

## 6 自动化验证

以下仅列已有入口，不在本轮运行。`scripts/test-offline.py` 仍包含已知失败的生命周期场景，不能用“离线”名称宣称全绿。P3 入口在 `lifecycle_regression.py` 直接拒绝 `S1_RUNNER_ISOLATION_BLOCKED`，没有自动启动或清理故障 Runner 的现行流程。

```text
./.venv/Scripts/python.exe -B scripts/test-offline.py
# test-p3.ps1 当前拒绝；不要启用 RUN_SANDBOX 绕过。
./.venv/Scripts/python.exe scripts/migrate.py check
Push-Location frontend
npm run typecheck
npm run build
# 真实 Sandbox 浏览器验收仍 BLOCKED；第 10 节旧命令仅为历史。
Pop-Location
```

现行维护入口要求主实例保护检查和实际独立资源证明；有冲突即拒绝，不停止并恢复主服务。`tests/conftest.py` 拒绝 `AGENTFORGE_RUN_SANDBOX=1`，Playwright 常规配置排除 `sandbox.spec.ts`。17＋2 真实测试必须先证明独立 daemon/资源和 Runner 归属，并另获执行授权；不能在旧 Runner 仍可能宽泛清理的共享 Engine 上派发第二个真实测试 Runner。失败或 skip 不能算验收通过。

普通浏览器真实联调要求已验证的独立 API/Worker、数据库/Redis、端口、manifest/settings 与租约；不回退主服务。当前没有获准启用真实 Sandbox E2E 的操作命令。浏览器使用已有 Edge；变更或下载浏览器需另批。

HTTP 单元测试的 StubConnections 是显式测试替身，不代表真实连通。浏览器故障测试通过拦截请求验证“无法连接”展示，它与真实健康联调测试分别报告。

提交前：`git diff --stat`、`git diff --check` 及对应 cached 检查，并通过无凭据 wrapper 运行 `scripts/check_secrets.py --no-local-secrets`。此模式不读取 dotenv/已知 Key 值，只扫描常见凭据格式，不等同于已知秘密比对或识别所有机密。

## 7 停止与数据保留

下列为历史停止入口示例，本轮不执行。主 Runner 停止/禁复起/退出证明与主 API/Worker 接管均须单独维护授权，不能仅凭名称执行 Compose 命令。

```text
./scripts/stop-local.ps1
docker compose --profile sandbox stop runner
```

stop-local.ps1 的源码仅允许停止身份可确认的非保护实例；受保护实例的独立 scripts/stop-coder-local.ps1 需要交互式短时一次性 challenge。停止前检查整个范围，终止时在同一 Windows 句柄上重验 FILETIME；人工停止保留保护记录，不授予无 Key 重建权限。这些源码规则不证明当前实例可以安全接管。旧 Runner 的清理风险未解除，停止也不能作为容器已清理或历史结果已知的证明。

以上历史停止方式保留 PostgreSQL/Redis 和所有卷。停止数据服务也需独立批准、确认资源归属及影响，不能在本轮执行 `docker compose stop postgres redis`。不要执行全局 `docker prune`、`docker system prune`、`docker volume prune` 或 `docker compose down -v`。

## 8 可选全 Compose 启动

全 Compose 为手工运维方式，不在本地进程保护范围；不应与受保护原生实例并行运行，即使端口不同也会竞争共享队列。以下仅保留独立环境的条件示例，未经本轮验证；原生实例、数据库和 Runner 的维护授权不能由此替代。本轮不执行 app profile、迁移或模型凭据容器注入：

```text
docker compose --profile app build
docker compose --profile app run --rm --no-deps backend python -m alembic upgrade head
docker compose --profile app --profile sandbox up -d --wait --no-deps backend frontend worker runner
```

前提是第 10 节已登记批准镜像，项目 PostgreSQL/Redis 健康且迁移完成。frontend 通过 Nginx 同源代理访问 backend；容器 app 服务连接项目数据库与 Redis。API/Worker 应用镜像不是代码执行镜像；只有独立 Runner 创建受限执行容器。退出用 `docker compose --profile app --profile sandbox stop backend frontend worker runner`，保留数据服务与卷。

首次创建数据库卷才执行 init-app-role.sql；以后修改应用密码时不能只编辑 .env 期待自动改数据库用户密码，必须单独设计批准的密码轮换操作。

## 9 使用 P2 工作流

进入前端 /tasks，读取本机项目 .env 中的 AGENTFORGE_ADMIN_TOKEN 到密码输入框；不要将其发到聊天或日志。Token 只在页面内存，刷新后清除，生产登录尚未实现。

提交目标时必须明确 Mock。默认计划需人工确认；无依赖 Worker 并发，选择依赖模式则按顺序执行。点击批准计划后查看状态、SSE 轨迹和模拟用量；批准计划不授予沙箱或高风险工具权限。真实模型支出为零，显示的 Mock 费用不是供应商账单。

API 新增 POST /api/v1/tasks（HTTP 202，UUID Idempotency-Key），GET /tasks、GET /tasks/{id}、POST /tasks/{id}/cancel、GET /approvals、POST /approvals/{id}/decision、GET /tasks/{id}/events。均需要 Bearer Token，不通过 URL 传凭据。SSE 支持 Last-Event-ID，断线不取消任务。

test-p2.ps1 经共享锁检查后运行依赖/P2 集成，不停止或恢复主 Worker；运行实例或受保护记录会阻断。E2E 要求单独准备专用应用环境。旧 scripts/p2-recovery-probe.py 已安全禁用，不再用于主服务重启验收。

默认每任务 15 分钟、8 轮、32 次尝试、100000 模拟 Token、1 模拟 USD；UTC 租户日限额为 1000000 模拟 Token、10 模拟 USD，可由服务器环境参数 DAILY_MOCK_TOKEN_LIMIT/DAILY_MOCK_BUDGET_USD（加 AGENTFORGE_ 前缀）收紧或管理。Agent 不能提高上限。

## 10 启动 P3 沙箱控制面

**本节保留 P3 阶段历史流程及153/8项验收记录，不是当前共享 Engine 的运行指南。** 旧主 Runner 尚未升级，宽泛发现/清理和自动复起风险仍在；新版 Ownership/Freeze 源码和0009/0010迁移已提交，不代表主环境已加载。真实17＋2验收继续 BLOCKED。以下 Runner 启停、镜像登记、恢复及 opt-in 命令不得用于当前主环境；后续步骤以另获批准的 [维护 Runbook](S3B2_MAINTENANCE_RUNBOOK.md) 为准。

前提：现有 Docker Engine 可用、项目依赖安装已批准且完成、P2 数据服务健康。不能修改 Docker Desktop 全局配置；Docker 不可用时停止实际执行验证并记录阻塞，绝不在 Windows 宿主机直接运行待执行代码。

### P3 历史：已登记项目的启动

P3 当时已登记并验收批准镜像、控制凭据和 0004_sandbox 迁移；下面保留当时的复用命令，不能作为现在服务健康或获准启动的证明：

```text
Set-Location D:\AIProjects\AgentForge-AI
docker compose config --quiet
docker compose --profile sandbox up -d --no-deps runner
./scripts/start-local.ps1
```

上述命令要求既有项目 PostgreSQL/Redis 已运行，不重建其容器和卷。镜像缺失则执行安全失败，不可擅自换 tag 或登记其他镜像。

### P3 历史：首次配置或获批准的镜像发布

先审阅 `sandbox-image/Dockerfile`、`sandbox-image/launcher.py` 与 `docs/SANDBOX_SECURITY.md`。以下仅用于首次建立新的本项目环境；已有批准镜像不应每次重构或覆写。Dockerfile 固定基础镜像 digest，本地 tag 只用于查找刚构建的产物，Runner 登记和运行不可变镜像 ID：

```text
Set-Location D:\AIProjects\AgentForge-AI
docker build --tag agentforge-p3-python:local ./sandbox-image
if ($LASTEXITCODE -ne 0) { throw 'Sandbox image build failed' }
$sandboxApprovedImageId = docker image inspect agentforge-p3-python:local --format '{{.Id}}'
if ($LASTEXITCODE -ne 0 -or $sandboxApprovedImageId -notmatch '^sha256:[a-f0-9]{64}$') {
    throw 'A reviewed immutable sandbox image ID is required'
}
./.venv/Scripts/python.exe scripts/bootstrap-sandbox.py --image-id $sandboxApprovedImageId
if ($LASTEXITCODE -ne 0) { throw 'Sandbox registration failed; do not replace the existing approved image' }
./.venv/Scripts/python.exe scripts/migrate.py upgrade
./.venv/Scripts/python.exe scripts/migrate.py check
docker compose config --quiet
docker compose --profile sandbox up -d --build --no-deps runner
if ($LASTEXITCODE -ne 0) { throw 'Trusted Runner startup failed' }
```

以上 PowerShell 变量只保存公开镜像 ID，不保存或打印凭据。bootstrap-sandbox.py 仅向项目 .env 补充随机 Runner/独立审批者 Token 与批准镜像 ID，不显示值；不同批准镜像已存在时拒绝覆盖，需要另行审查镜像更新及审批失效流程。

以下是当时加载新配置的重启示例，不授权现在替换 API/Worker。现有实例归属和代次未知或旧版保护记录未交接时必须拒绝：

```text
./scripts/stop-local.ps1
./scripts/start-local.ps1
docker compose --profile sandbox ps runner
```

默认 Runner 为 `http://127.0.0.1:18120`，由 SANDBOX_RUNNER_PORT 配置；端口修改须同步本项目 AGENTFORGE_SANDBOX_RUNNER_URL，不修改系统网络。`/health/live` 只证明进程存活，不证明 Docker/镜像/清理状态就绪。受保护 `/internal/status` 检查 Runner 可用状态；不要将 Runner Token 放入浏览器、聊天、URL 或命令行展示。

Compose Runner 是可信控制面，拥有 Docker Socket 和 daemon 管理权限；它不是不可信执行容器。即使只发布 loopback，也不要将其通过公网、反向代理或模型工具开放。真正的代码容器无 Socket、无宿主机挂载、非 root、只读根、网络 none、受限 cgroup、seccomp/no-new-privileges。清理未确认时 Runner 全局拒绝新任务；未知执行若已确认 removed，可接收新任务，但原执行不重跑。

### 沙箱页面与独立审批

进入 `http://127.0.0.1:15173/sandbox`，使用 .env 中本地管理员 Token 授权，读取真实策略后提交 Python 代码和降低后的资源限额。服务端生成任务/执行/审批 ID；受理 HTTP 202 不等于执行成功。

由独立审批者在沙箱页输入 AGENTFORGE_SANDBOX_APPROVER_TOKEN，点击“读取待审批代码”，核对实际代码、代码哈希、操作哈希、固定策略、超时和资源，再批准或拒绝。管理员 Token 不能代替独立审批。批准后查看真实 Docker 状态、脱敏输出、采样资源及 `cleanup_status=removed`；拒绝时不得创建代码执行容器。

两种 Token 均不进浏览器持久存储。管理员授权保存在应用内存，SPA 页面导航期间保留，刷新或退出授权后清空；独立审批者 Token 与受控源码属于沙箱页面内存，离开沙箱页面或刷新后清空。审批源代码不进入 SSE。不要提交真实模型 API Key 或敏感文件。P3 当时的 Model Center 仅有配置基础；现行源码的槽位/状态/指标能力见第5/12节，不能把 Mock 费用或页面存在当真实模型验收。

### P3 历史：完整测试与清理检查（当前禁止执行）

```text
./scripts/test-p3.ps1
./.venv/Scripts/python.exe scripts/migrate.py current
./.venv/Scripts/python.exe scripts/migrate.py check
# 维护测试不恢复应用。仅无凭据、无保护记录的独立 Mock 环境可另行启动：
./scripts/start-local.ps1
Push-Location frontend
$sandboxPreviousOptIn = $env:AGENTFORGE_RUN_SANDBOX
try {
    $env:AGENTFORGE_RUN_SANDBOX = '1'
    npm run typecheck
    npm run build
    npm run test:e2e
} finally {
    $env:AGENTFORGE_RUN_SANDBOX = $sandboxPreviousOptIn
    Pop-Location
}
./scripts/stop-local.ps1
docker ps -a --filter 'label=agentforge.sandbox.execution' --format '{{.Names}} {{.Status}}'
./.venv/Scripts/python.exe scripts/check_secrets.py
```

上述创建故障 Runner 和 opt-in 是 P3 历史流程。**当前 test-p3.ps1 直接拒绝，既不启动也不清理故障 Runner；RUN_SANDBOX=1 同样被 pytest 前置守卫拒绝，常规浏览器配置排除真实 Sandbox。** 不得删除保护或按旧 pause/restore、recovery probe、work 临时脚本恢复 Runner。17＋2 需要新的隔离证明和独立授权，不能把 skip 或旧通过数记作新验收。

P3 历史验收 Python 153/153 通过（单元/HTTP 117，真实集成 36，其中沙箱服务 16）；浏览器 8/8 通过（真实沙箱批准/拒绝 2，原核心 6），0 失败、0 跳过。类型检查、51 modules 构建、迁移与 pip check 通过。真实 OS Worker 重启探针通过；未专门强杀 Runner OS 覆盖全部恢复窗口，不能与受控租约测试混淆。详细证据与限制见 P3_REPORT。

最后一条历史 Docker 查询只读、不删除容器；当时“无遗留执行容器”的结论不代表现在。本轮未查询 Docker，当前容器状态 UNKNOWN。未来对账必须核验可信账本、实际 CID、实例代次及授权，不能仅凭名称或标签清理；UNKNOWN 不重放，禁止全局批量删除，预热与不复用约束保留。

## 11 P4 工具与 Skill 操作

本节保留当时单独获批的 P4 交付步骤。历史授权不延续为当前操作许可；以下启动、迁移、测试命令均为历史文本，不能用来更新旧主 Runner 或替换主实例：

```text
./.venv/Scripts/python.exe scripts/bootstrap-p4.py
./.venv/Scripts/python.exe scripts/migrate.py upgrade
./.venv/Scripts/python.exe scripts/migrate.py check
# 已运行的旧 API 需按项目归属安全停止，再启动以加载代码和新的 P4 凭据。
./scripts/stop-local.ps1
./scripts/start-local.ps1
```

bootstrap-p4 仅补充两个独立随机凭据，不覆盖已有配置，不打印值。`AGENTFORGE_MCP_SERVER_TOKEN` 是可信服务端内部凭据，不输入浏览器；`AGENTFORGE_CAPABILITY_APPROVER_TOKEN` 用于独立复核 P4 操作，管理员和 P3 审批 Token 均不能代替它。当前 .env 已补充，无需重新生成。前端密码输入仅保存在内存，离开页面/刷新后丢弃。

1. 打开 `/mcp`，使用管理员 Token 授权页面。先为精确的工具名和资源 ID 保存授权（例如 notes.write / project-notes），默认没有任何资源权限。
2. 选择工具和资源，准备调用。写入先进入 awaiting_approval；未经批准执行会收到 TOOL_APPROVAL_REQUIRED。独立 P4 审批者读取完整操作、核对哈希并批准后，管理员执行，页面显示真实数据库结果。
3. 超时或连接丢失时查看 needs_reconciliation。点击“核对受控服务回执”只核对已提交结果，不重放调用。无回执仍未知，应保留账本，不换 key 假定可安全重试。
4. 打开 `/skills`，提交严格 Manifest（页面提供示例），可以标记为 Agent 候选。登记后申请安装，独立批准得到 installed_disabled；再次申请启用并独立批准才成为 enabled。
5. 启用版本可在同页发起工具调用，但仍须有相应工具/资源授权；写工具仍需单次高风险审批。停用/撤销立即阻止新调用。升级另建版本；依赖需精确 version/content_hash，依赖停用再启用后父版本也要重新审批启用。

P4 的安装只安装本地声明式清单，不联网下载包、不运行 hook、不执行说明文字。任意代码仍通过 P3 受限沙箱。完整 HTTP 契约和时序见 P4_CONTRACT。

```text
# 准备和更新可信 Runner，仅操作本项目；复用已批准的固定 Python 沙箱镜像。
docker compose --profile sandbox build runner
docker compose --profile sandbox up -d --no-deps --no-build runner
# 分阶段运行，均要求主 API/Worker 停止且没有受保护记录。
./scripts/test-p2.ps1
./scripts/test-p3.ps1
./scripts/test-p4.ps1
# 仅独立、无保护记录的 Mock 环境，不能覆盖 Coder 实例。
./scripts/start-local.ps1
$env:AGENTFORGE_RUN_INTEGRATION='1'
$env:AGENTFORGE_RUN_SANDBOX='1'
Push-Location frontend
npm run build
npm run test:e2e
Pop-Location
./scripts/stop-local.ps1
./.venv/Scripts/python.exe scripts/check_secrets.py
git status --short
git diff --check
git diff
git ls-files --others --exclude-standard
```

测试报告位于 work/p4-all.xml、work/p4-e2e.json，前端截图为 work/p4-mcp.png、work/p4-skills.png。缺失 opt-in 产生的 skip 不算验收通过。敏感信息检查覆盖当前已跟踪和新增未跟踪源码、前端产物、项目日志及测试报告，不依赖 git add。测试需要访问本机数据库、Docker 管道和无头浏览器；沙箱拒绝时按工具权限流程申请具体测试，不改 Git 或系统权限。

以上为 P4 历史交付步骤；当时未进入 P5。当前 P5 按第12节的单独授权实施，仍不操作 git add/commit、不改 .git 权限，完成后由用户在 CMD 手动提交。

## 12 P5 模型、任务和 Chat

P5 历史功能已实现；P3/P4 约束不变。最近主库证据为历史 0008_execution_permits；本轮未查询当前版本，0009/0010不能因代码已提交而视为已部署。下面仅保留无凭据独立 Mock 环境的条件示例，本轮不执行；有保护记录、身份或数据归属未验证时拒绝：

```text
./.venv/Scripts/python.exe scripts/migrate.py upgrade
./.venv/Scripts/python.exe scripts/migrate.py check
./scripts/stop-local.ps1
./scripts/start-local.ps1
```

Model Center `/models` 支持四槽位配置、priority/thinking、状态和指标。当前安全默认 MODEL_CREDENTIALS_ENV_ONLY=true，模型 Key 只能来自经独立批准的服务进程环境；Coder 专用入口通过用户 PowerShell 原生继承，不将 Key 写入 .env。表单仅接受 env 引用，不把 Key 放入聊天、日志或命令参数。Mock 必须显式标记；真实模式失败不得回退伪装 Mock。REAL_CALLS_ENABLED 默认 false、测试额度0是源码策略，不是本轮实时观察。

真实 API 需新的单次明确授权及 [MODEL_INTEGRATION](MODEL_INTEGRATION.md) 所述可信 Permit 全链验证。普通模型测试按钮、Real Chat/Agent 不能签发或替代 Permit：零测试额度先返回 MODEL_TEST_BUDGET_BLOCKED，即使额度存在，普通 real 创建路径仍拒绝 MODEL_PERMIT_REQUIRED。预算和全局开关不是任务级授权；本轮不开放任一门禁。

Agent Tasks `/tasks` 的 P5 界面提供 Mock/Real、调用/Token/费用/deadline、计划、SSE 和工具记录；当前服务端普通 real 路径受 Permit 门禁拒绝，不能因四槽可用便启动真实协作。AI Chat `/chat` 的单角色历史与 SSE 也不授予真实调用权限。真实能力未完成供应商验收，不得伪装成功。

若 Coder 提议执行 Python，先在 MCP Tools 选择 sandbox.execute / python 精确授权，再到 Sandbox Center 用独立 P3 审批 Token 复核绑定代码；不允许宿主执行或放宽 Docker 策略。notes.write 继续使用独立 P4 审批。计划确认或 Reviewer 意见不能代替这些批准。

```text
# 已单独准备的 Permit 克隆栈必须就绪；不能同时运行共享执行标签的主/克隆 Runner。
# 下列 wrapper 丢弃模型凭据。维护保护先检查主实例；有保护记录仍拒绝。
./.venv/Scripts/python.exe -B scripts/p5-live-preflight.py run --settings-file work/p5-live-preflight/permit-test/.env -- python -B scripts/lifecycle.py maintenance-run --phase p5
# 本轮不运行收费验收。格式扫描不读取模型 dotenv/已知秘密值。
./.venv/Scripts/python.exe -B scripts/p5-live-preflight.py run -- python -B scripts/check_secrets.py --no-local-secrets
```

旧 p3-worker-recovery-probe.py、p5-worker-recovery-probe.py 及非 PolicyOnly 的 coder-startup-probe.ps1 已安全禁用。当前 Permit OS 崩溃测试使用 tests/fixtures/lifecycle_permit_child.py，在专属克隆数据库/Redis上启动固定可信 fixture，以启动句柄和创建身份清理；模型传输为虚拟，不接触真实 Key。历史 work/p5-live-recovery.ps1 不能用于恢复当前 Coder 实例。

历史证据：work/p5-all.xml、p5-e2e.json、p5-worker-restart.json、p5-real-api.json，截图 p5-models.png/p5-chat.png。这些本地记录不证明当前凭据存在或获准测试；本轮凭据状态未核验，供应商验收仍 BLOCKED。最新归档和运行限制见 PROJECT_STATUS，不进入 P6。


## P5-LIVE 启动保护

已提交源码将本地启动/停止统一到生命周期管理器，目标是拒绝普通维护覆盖持 Key 实例且不自动恢复主 API/Worker；G4 的真实生命周期失败仍未完成可信诊断，不能据此宣称当前实例保护已动态验收。先读 [LOCAL_LIFECYCLE_GUARD](LOCAL_LIFECYCLE_GUARD.md) 的旧实例拒绝、维护批准及保护记录保留规则。专用 Coder 启动也须独立批准和即时预检，本轮不启动。
