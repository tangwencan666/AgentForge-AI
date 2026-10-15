# AgentForge AI P4 本地启动指南

2026 年 10 月 15 日，Asia/Shanghai。P4 已获开发授权，在 P3 真实 Docker 与 P2 持久化协作基础上增加受控 MCP Tool Gateway 和声明式 Skills Registry。模型回答和费用仍为明确 Mock。当前能力、实际验收和限制以 P4_REPORT、P4_CONTRACT 和 PROJECT_STATUS 为准；历史阶段证据保留。

## 1 环境与隔离

根目录固定为 `D:\AIProjects\AgentForge-AI`。当前验证环境为 Python 3.13.5、Node 24.14.1、Docker Engine 29.7.2、Compose v5.4.0；Python 最低要求 3.11。后端精确依赖记录在 `backend/requirements.lock`，前端记录在 `frontend/package-lock.json`。锁文件锁定版本，不声明带完整供应链签名验证；P1 不支持生产部署。

数据库、Redis 仅发布到 127.0.0.1。容器名为 agentforge-p1-postgres、agentforge-p1-redis；卷为 agentforge-p1-postgres-data、agentforge-p1-redis-data。不要将环境变量连接地址改成其他项目，也不要使用全局 docker prune 或 Redis FLUSHALL。本项目的 Compose 数据网络允许普通开发网络，但无公网数据库端口；它不是代码沙箱网络。

以下命令在项目目录 PowerShell 中执行。首次安装或系统配置调整必须经用户批准；本次项目内依赖安装已获批准。不要全局安装依赖。

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

默认端口：后端 18100、前端 15173、PostgreSQL 15432、Redis 16379。若冲突，启动前修改 .env 的 BACKEND_PORT、FRONTEND_PORT、POSTGRES_PORT、REDIS_PORT；变更数据库/Redis 端口时，同时更新 AGENTFORGE_DATABASE_URL、AGENTFORGE_REDIS_URL 中的端口。不要打印完整 .env 或不带 --quiet 的 Compose 展开配置。

## 3 启动数据库和 Redis

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

启动脚本在后台隐藏窗口运行 API、Vite 和独立 Worker，只管理本项目进程；端口冲突时拒绝启动。进程信息保存到 work/dev-pids.json。P3 另需第 10 节的独立可信 Runner，因此整体有 API、前端、Worker、Runner 四个组件。也可在三个终端分别运行本地应用部分：

```powershell
# 终端一，在项目根目录
./.venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 18100 --no-access-log
```

```powershell
# 终端二，在项目 frontend 目录
npm run dev
```

```powershell
# 终端三，在项目根目录
./.venv/Scripts/python.exe -m app.workers.main
```

访问：前端 http://127.0.0.1:15173，后端 http://127.0.0.1:18100，OpenAPI 文档 http://127.0.0.1:18100/docs。GET /health/live 只证明 API 活着；GET /health/ready 验证 PostgreSQL、Alembic 版本/核心表和 Redis PING。未就绪返回 HTTP 503，不返回密码、主机连接串或异常值。

Dashboard 通过 Vite 同源代理调用真实 /health/ready，每 15 秒刷新，并显示请求 ID。服务无法连接时显示“未确认”，不能复用旧成功状态。其他页面明确说明开发状态；Model Center 展示槽位定义且标注“未读取”，不是伪造数据库配置。

## 5 模型配置接口

GET /api/v1/model-slots、POST /api/v1/model-slots/validate、PUT /api/v1/model-slots/{role} 使用本地管理 Bearer Token。Token 从受保护的 .env 读取，不写 URL 或浏览器缓存。任务、计划审批和沙箱页面提供仅内存的本地开发授权输入，不是生产登录。

role 为 planner/coder/researcher/reviewer。PUT 为完整配置替换并携带 expected_version；并发修改版本冲突返回 409。配置字段为 provider、base_url、model、credential_reference、temperature、max_tokens、timeout、enabled。原始 api_key 等额外字段一律拒绝且不回显。

credential_reference 只接受 `env:AGENTFORGE_MODEL_...` 引用，仍无秘密写入或真实模型调用。启用真实配置时校验引用；base_url 必须为批准 HTTPS 域名，无用户名密码/query/fragment/非 443 端口。工作流 Mock 快照独立，不覆盖这些配置。

## 6 自动化验证

```powershell
./.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml tests/unit tests/http -q
./scripts/test-p3.ps1
./.venv/Scripts/python.exe scripts/migrate.py check
Push-Location frontend
npm run typecheck
npm run build
# 完整浏览器验证使用第 10 节的沙箱 opt-in 命令
Pop-Location
```

先按第 10 节复用已登记镜像并启动 Runner，再执行 test-p3.ps1。它暂停本项目后台 Worker，设置真实集成与沙箱 opt-in，自动启动仅本项目的无 Socket `runner-unavailable` 故障服务，运行 Python 测试，finally 只清理该故障服务并恢复 Worker。不要并行运行该脚本或另一个 Docker Worker。真实测试留下本项目审计记录，并创建后销毁本项目执行容器，不操作其他项目数据。未满足条件时须如实记录失败或 skip，不能将 skip 计为 Docker 验收通过。

浏览器真实联调测试要求前后端、Worker、数据库/Redis 和 Runner 已运行；第 10 节给出明确启用沙箱 E2E 的命令。浏览器测试使用机器上已安装的 Edge；没有 Edge 时需批准使用其他已有浏览器或在项目内下载测试浏览器。

HTTP 单元测试的 StubConnections 是显式测试替身，不代表真实连通。浏览器故障测试通过拦截请求验证“无法连接”展示，它与真实健康联调测试分别报告。

提交前：`git diff --cached --stat`、`git diff --cached --check`，并运行 `./.venv/Scripts/python.exe scripts/check_secrets.py`。扫描会检查本地已知秘密及常见编码，不打印秘密；它不等同于识别所有未知机密。

## 7 停止与数据保留

```powershell
./scripts/stop-local.ps1
docker compose --profile sandbox stop runner
```

终端前台运行方式可在各自终端 Ctrl+C 停止。stop-local.ps1 核对可执行文件/命令所属项目后才停止记录中的 PID，防止 PID 重用误杀其他程序。Runner 正常退出会终止自己管理的活动执行并确认清理；异常退出后的不确定记录仍需核对，不能把服务停止当成清理已完成。

以上停止方式保留 PostgreSQL/Redis 和所有卷。若确实需要停止本项目数据服务，单独执行 `docker compose stop postgres redis`；不停止其他项目。不要执行全局 `docker prune`、`docker system prune`、`docker volume prune` 或 `docker compose down -v`。

## 8 可选全 Compose 启动

本地 npm/Python 方式和 Compose app profile 不要占用相同端口。先停止本地前后端，再执行：

```powershell
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

test-p2.ps1 暂停本项目后台 Worker，运行真实 Python 集成，再恢复 Worker，避免测试与演示任务竞争；不要同时运行 Docker Worker。E2E 要求本地 Worker 正常，测试启动器把浏览器临时目录放在项目 work 下。要验证 OS 重启可运行 scripts/p2-recovery-probe.py；它只重启本项目 Worker。

默认每任务 15 分钟、8 轮、32 次尝试、100000 模拟 Token、1 模拟 USD；UTC 租户日限额为 1000000 模拟 Token、10 模拟 USD，可由服务器环境参数 DAILY_MOCK_TOKEN_LIMIT/DAILY_MOCK_BUDGET_USD（加 AGENTFORGE_ 前缀）收紧或管理。Agent 不能提高上限。

## 10 启动 P3 沙箱控制面

前提：现有 Docker Engine 可用、项目依赖安装已批准且完成、P2 数据服务健康。不能修改 Docker Desktop 全局配置；Docker 不可用时停止实际执行验证并记录阻塞，绝不在 Windows 宿主机直接运行待执行代码。

### 已登记项目的日常启动

当前项目已登记并验收批准镜像、控制凭据和 0004_sandbox 迁移。日常启动直接复用，不重新 build、bootstrap 或覆盖镜像登记；现有服务已健康时无需重复执行：

```powershell
Set-Location D:\AIProjects\AgentForge-AI
docker compose config --quiet
docker compose --profile sandbox up -d --no-deps runner
./scripts/start-local.ps1
```

上述命令要求既有项目 PostgreSQL/Redis 已运行，不重建其容器和卷。镜像缺失则执行安全失败，不可擅自换 tag 或登记其他镜像。

### 仅首次配置或获批准的镜像发布

先审阅 `sandbox-image/Dockerfile`、`sandbox-image/launcher.py` 与 `docs/SANDBOX_SECURITY.md`。以下仅用于首次建立新的本项目环境；已有批准镜像不应每次重构或覆写。Dockerfile 固定基础镜像 digest，本地 tag 只用于查找刚构建的产物，Runner 登记和运行不可变镜像 ID：

```powershell
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

如果本地 API/Worker 在 P3 配置登记前已运行，应只重启本项目进程加载新配置：

```powershell
./scripts/stop-local.ps1
./scripts/start-local.ps1
docker compose --profile sandbox ps runner
```

默认 Runner 为 `http://127.0.0.1:18120`，由 SANDBOX_RUNNER_PORT 配置；端口修改须同步本项目 AGENTFORGE_SANDBOX_RUNNER_URL，不修改系统网络。`/health/live` 只证明进程存活，不证明 Docker/镜像/清理状态就绪。受保护 `/internal/status` 检查 Runner 可用状态；不要将 Runner Token 放入浏览器、聊天、URL 或命令行展示。

Compose Runner 是可信控制面，拥有 Docker Socket 和 daemon 管理权限；它不是不可信执行容器。即使只发布 loopback，也不要将其通过公网、反向代理或模型工具开放。真正的代码容器无 Socket、无宿主机挂载、非 root、只读根、网络 none、受限 cgroup、seccomp/no-new-privileges。清理未确认时 Runner 全局拒绝新任务；未知执行若已确认 removed，可接收新任务，但原执行不重跑。

### 沙箱页面与独立审批

进入 `http://127.0.0.1:15173/sandbox`，使用 .env 中本地管理员 Token 授权，读取真实策略后提交 Python 代码和降低后的资源限额。服务端生成任务/执行/审批 ID；受理 HTTP 202 不等于执行成功。

由独立审批者在沙箱页输入 AGENTFORGE_SANDBOX_APPROVER_TOKEN，点击“读取待审批代码”，核对实际代码、代码哈希、操作哈希、固定策略、超时和资源，再批准或拒绝。管理员 Token 不能代替独立审批。批准后查看真实 Docker 状态、脱敏输出、采样资源及 `cleanup_status=removed`；拒绝时不得创建代码执行容器。

两种 Token 均不进浏览器持久存储。管理员授权保存在应用内存，SPA 页面导航期间保留，刷新或退出授权后清空；独立审批者 Token 与受控源码属于沙箱页面内存，离开沙箱页面或刷新后清空。审批源代码不进入 SSE。不要提交真实模型 API Key 或敏感文件。Model Center 仍只有配置基础；P2 四角色任务的回答/Token/美元费用仍为 Mock，与真实 Docker 资源用量分开。

### 完整测试与清理检查

```powershell
./scripts/test-p3.ps1
./.venv/Scripts/python.exe scripts/migrate.py current
./.venv/Scripts/python.exe scripts/migrate.py check
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
docker ps -a --filter 'label=agentforge.sandbox.execution' --format '{{.Names}} {{.Status}}'
./.venv/Scripts/python.exe scripts/check_secrets.py
```

test-p3.ps1 明确启用真实 PostgreSQL/Redis 与 Docker 集成，并自动创建与最终删除自身的专用故障 Runner 服务；不停止共享 daemon 或删除其他容器。浏览器沙箱测试默认 skip，只有 AGENTFORGE_RUN_SANDBOX=1 才执行真实批准/拒绝流程。没有 opt-in 的绿灯不能算作沙箱 E2E 通过。

P3 历史验收 Python 153/153 通过（单元/HTTP 117，真实集成 36，其中沙箱服务 16）；浏览器 8/8 通过（真实沙箱批准/拒绝 2，原核心 6），0 失败、0 跳过。类型检查、51 modules 构建、迁移与 pip check 通过。真实 OS Worker 重启探针通过；未专门强杀 Runner OS 覆盖全部恢复窗口，不能与受控租约测试混淆。详细证据与限制见 P3_REPORT。

最后一条 Docker 查询使用 execution 标签检查所有策略版本，只查询、不删除容器。本轮结束时已确认无遗留执行容器；未来发现遗留应检查精确名称、执行 ID、租约与清理状态，由受限 Runner 对账。禁止全局批量删除，也不能把未知结果自动重新执行。预热关闭，执行过不可信代码的容器永不回池。P3 约束继续适用；P4 范围与验证见下一节。

## 11 P4 工具与 Skill 操作

用户已单独批准 P4。无需增加全局或项目依赖，复用现有 Python 环境。先启动已有 Docker Desktop，再在项目 PowerShell 中运行：

```powershell
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

```powershell
# 准备和更新可信 Runner，仅操作本项目；复用已批准的固定 Python 沙箱镜像。
docker compose --profile sandbox build runner
docker compose --profile sandbox up -d --no-deps --no-build runner
# 包括真实 MCP、数据库、原 P2 和 P3 安全回归；专用故障 Runner 在 finally 中清理。
./scripts/test-p4.ps1
$env:AGENTFORGE_RUN_INTEGRATION='1'
$env:AGENTFORGE_RUN_SANDBOX='1'
Push-Location frontend
npm run build
npm run test:e2e
Pop-Location
./.venv/Scripts/python.exe scripts/check_secrets.py
git status --short
git diff --check
git diff
git ls-files --others --exclude-standard
```

测试报告位于 work/p4-all.xml、work/p4-e2e.json，前端截图为 work/p4-mcp.png、work/p4-skills.png。缺失 opt-in 产生的 skip 不算验收通过。敏感信息检查覆盖当前已跟踪和新增未跟踪源码、前端产物、项目日志及测试报告，不依赖 git add。测试需要访问本机数据库、Docker 管道和无头浏览器；沙箱拒绝时按工具权限流程申请具体测试，不改 Git 或系统权限。

本轮不操作 git add/commit，不改 .git 权限；完成后由用户在 CMD 手动提交。不进入 P5。
