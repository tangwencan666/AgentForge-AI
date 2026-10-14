# AgentForge AI P2 本地启动指南

本项目完成 P1 基础与 P2 持久化协作，支持真实健康检查、四模型配置和显式 Mock 工作流。真实模型调用、Docker Sandbox、MCP/Skills 执行尚未开放；计划确认、取消、预算和 SSE 已实现。

## 1 环境与隔离

根目录固定为 `D:\AIProjects\AgentForge-AI`。当前验证环境为 Python 3.13.5、Node 24.14.1、Docker Engine 29.7.2、Compose v5.4.0；Python 最低要求 3.11。后端精确依赖记录在 `backend/requirements.lock`，前端记录在 `frontend/package-lock.json`。锁文件锁定版本，不声明带完整供应链签名验证；P1 不支持生产部署。

数据库、Redis 仅发布到 127.0.0.1。容器名为 agentforge-p1-postgres、agentforge-p1-redis；卷为 agentforge-p1-postgres-data、agentforge-p1-redis-data。不要将环境变量连接地址改成其他项目，也不要使用全局 docker prune 或 Redis FLUSHALL。本项目的 Compose 数据网络允许普通开发网络，但无公网数据库端口；它不是代码沙箱网络。

以下命令在项目目录 PowerShell 中执行。首次安装或系统配置调整必须经用户批准；本次项目内依赖安装已获批准。不要全局安装依赖。

```powershell
Set-Location D:\AIProjects\AgentForge-AI
New-Item -ItemType Directory -Path work/tmp,work/pip-cache,work/npm-cache -Force | Out-Null
$env:TEMP = (Resolve-Path work/tmp).Path
$env:TMP = $env:TEMP
python -m venv .venv
./.venv/Scripts/python.exe -m pip install --cache-dir work/pip-cache -r backend/requirements.lock
./.venv/Scripts/python.exe -m pip install --cache-dir work/pip-cache --no-deps -e ./backend
Push-Location frontend
npm ci --ignore-scripts --cache ../work/npm-cache
Pop-Location
```

如果 .venv 已存在，直接复用，不覆盖已有环境。依赖下载需要网络；安装器临时文件及缓存放在项目 work 下。

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

Alembic 保留 model_slots 并创建任务、检查点、事件、审批、调用和日额度表，当前 0003_tenant_limits。应用连接使用非超级用户 agentforge，管理密码与应用密码独立。Redis 配置 AOF 与认证，不初始化其他项目数据。

Docker 不可用时记录阻塞，不能宣称真实依赖已连通。不以 SQLite、fakeredis 或 Mock 代替 PostgreSQL/Redis 的验收。

## 4 启动前后端

```powershell
./scripts/start-local.ps1
```

启动脚本在后台隐藏窗口运行 API、Vite 和独立 Worker，只管理本项目进程；端口冲突时拒绝启动。进程信息保存到 work/dev-pids.json。也可在三个终端分别运行：

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

GET /api/v1/model-slots、POST /api/v1/model-slots/validate、PUT /api/v1/model-slots/{role} 使用本地管理 Bearer Token。Token 从受保护的 .env 读取，不写 URL 或浏览器缓存。本轮不提供浏览器登录表单。

role 为 planner/coder/researcher/reviewer。PUT 为完整配置替换并携带 expected_version；并发修改版本冲突返回 409。配置字段为 provider、base_url、model、credential_reference、temperature、max_tokens、timeout、enabled。原始 api_key 等额外字段一律拒绝且不回显。

credential_reference 只接受 `env:AGENTFORGE_MODEL_...` 引用，仍无秘密写入或真实模型调用。启用真实配置时校验引用；base_url 必须为批准 HTTPS 域名，无用户名密码/query/fragment/非 443 端口。工作流 Mock 快照独立，不覆盖这些配置。

## 6 自动化验证

```powershell
./.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml tests/unit tests/http -q
./scripts/test-p2.ps1
./.venv/Scripts/python.exe scripts/migrate.py check
Push-Location frontend
npm run typecheck
npm run build
npm run test:e2e
Pop-Location
```

集成测试只对项目服务运行；包含真实连接、权限、四槽位及版本持久化验证，会恢复测试前的配置参数但保留递增版本。浏览器真实联调测试要求前后端和数据库/Redis已运行。浏览器测试使用机器上已安装的 Edge；没有 Edge 时需批准使用其他已有浏览器或在项目内下载测试浏览器。

HTTP 单元测试的 StubConnections 是显式测试替身，不代表真实连通。浏览器故障测试通过拦截请求验证“无法连接”展示，它与真实健康联调测试分别报告。

提交前：`git diff --cached --stat`、`git diff --cached --check`，并运行 `./.venv/Scripts/python.exe scripts/check_secrets.py`。扫描会检查本地已知秘密及常见编码，不打印秘密；它不等同于识别所有未知机密。

## 7 停止与数据保留

```powershell
./scripts/stop-local.ps1
docker compose stop postgres redis
```

终端前台运行方式可在各自终端 Ctrl+C 停止。stop-local.ps1 核对可执行文件/命令所属项目后才停止记录中的 PID，防止 PID 重用误杀其他程序。docker compose stop 保留容器和卷；docker compose down 只移除本项目服务/网络并保留卷。不要加 -v，除非明确授权删除本项目持久数据。

## 8 可选全 Compose 启动

本地 npm/Python 方式和 Compose app profile 不要占用相同端口。先停止本地前后端，再执行：

```powershell
docker compose --profile app build
docker compose --profile app run --rm --no-deps backend python -m alembic upgrade head
docker compose --profile app up -d --wait
```

frontend 通过 Nginx 同源代理访问 backend；容器 app 服务连接项目数据库与 Redis。应用镜像不是 Docker Sandbox，也不能用于执行用户代码。退出使用 `docker compose --profile app stop`，仍保留数据。

首次创建数据库卷才执行 init-app-role.sql；以后修改应用密码时不能只编辑 .env 期待自动改数据库用户密码，必须单独设计批准的密码轮换操作。

## 9 使用 P2 工作流

进入前端 /tasks，读取本机项目 .env 中的 AGENTFORGE_ADMIN_TOKEN 到密码输入框；不要将其发到聊天或日志。Token 只在页面内存，刷新后清除，生产登录尚未实现。

提交目标时必须明确 Mock。默认计划需人工确认；无依赖 Worker 并发，选择依赖模式则按顺序执行。点击批准计划后查看状态、SSE 轨迹和模拟用量；批准计划不授予沙箱或高风险工具权限。真实模型支出为零，显示的 Mock 费用不是供应商账单。

API 新增 POST /api/v1/tasks（HTTP 202，UUID Idempotency-Key），GET /tasks、GET /tasks/{id}、POST /tasks/{id}/cancel、GET /approvals、POST /approvals/{id}/decision、GET /tasks/{id}/events。均需要 Bearer Token，不通过 URL 传凭据。SSE 支持 Last-Event-ID，断线不取消任务。

test-p2.ps1 暂停本项目后台 Worker，运行真实 Python 集成，再恢复 Worker，避免测试与演示任务竞争；不要同时运行 Docker Worker。E2E 要求本地 Worker 正常，测试启动器把浏览器临时目录放在项目 work 下。要验证 OS 重启可运行 scripts/p2-recovery-probe.py；它只重启本项目 Worker。

默认每任务 15 分钟、8 轮、32 次尝试、100000 模拟 Token、1 模拟 USD；UTC 租户日限额为 1000000 模拟 Token、10 模拟 USD，可由服务器环境参数 DAILY_MOCK_TOKEN_LIMIT/DAILY_MOCK_BUDGET_USD（加 AGENTFORGE_ 前缀）收紧或管理。Agent 不能提高上限。
