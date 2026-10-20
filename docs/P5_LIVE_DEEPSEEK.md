# P5-LIVE：DeepSeek 兼容性准备与单次测试提案

> 2026-10-16封版提示：本文保留2026-10-15的历史提案与证据，不是当前可执行指南。本文旧 --roles coder 参数及直接开放额度的步骤已由0008 Single-Use Permit机制取代；当前脚本只有观测用 --permit-id，本次不运行它。当前Key存在标记True/True，四槽Disabled、真实/Permit关闭、费用预算0、Worker deny、出口阻断；DeepSeek认证/推理/计费未验证。封版源码缺口和待批准范围见LOCAL_LIFECYCLE_TEST_REPORT、P5_SEAL_MANIFEST。本次未执行本文历史命令，也未授权进入P6。

后续入口变更：本轮用户指定的openai_compatible+精确DeepSeek地址会强制路由至受审查DeepSeek档，取代本文历史上的通用provider拒绝规则。Coder配置及原生环境继承步骤见[DEEPSEEK_CODER_LOCAL](DEEPSEEK_CODER_LOCAL.md)。

2026-10-15，Asia/Shanghai。项目 `D:\AIProjects\AgentForge-AI`，基线 `982e83ef32b7d274e820d59ee63d6fb76bd8979e`，开始时工作区干净。本文以下为前一轮兼容性准备记录。后续无费用前置验收已完成备份与0007迁移、完整Python347项、浏览器14+1项及OS恢复，最新结论见[P5_LIVE_PREFLIGHT_REPORT](P5_LIVE_PREFLIGHT_REPORT.md)。实际四槽位、Key、域名/受众/价格和测试额度仍未配置，真实供应商验收 **NOT RUN / 待单独授权**，累计本阶段真实 API 请求 **0**，不进入 P6。

构建记录更正：后续复核发现新增浏览器测试存在TypeScript回调变量推断错误，已修复并实际通过类型检查及构建；下文前一轮“TypeScript通过”的表述应以此次更正和最新验收报告为准。

## 已实现

| 文件 | 行为 |
| --- | --- |
| backend/app/providers/deepseek.py | 独立 `deepseek` 配置档；只允许两个已复核模型及 api.deepseek.com 精确 HTTPS 根路径或 /v1；显式模式/强度与 max_tokens；验证缓存及推理用量一致性 |
| providers/openai_compatible.py | 复用固定公网IP、Host/TLS SNI、禁止重定向/代理的传输；跨片段 UTF-8/CRLF、保活注释、最终 choice 带 usage；严格错误/结束/输出边界；不保存或发出思考正文 |
| schemas/models.py、domain/entities.py、services/tasks.py | 四角色各自保存 thinking_mode / reasoning_effort，加入任务快照和版本授权；原角色、依赖、预算、审批不变 |
| providers/router.py | 注册 DeepSeek；通用适配器不得直接使用 DeepSeek 端点；价格明确 USD、max_tokens，旧 P5 USD 快照仍可规范化比较 |
| migrations/versions/0007_deepseek.py | 新增两个非秘密字段与检查约束，默认 disabled/high，不删除数据；本轮只验证离线 SQL，未应用现有 PostgreSQL |
| frontend/src/pages/ModelCenter.tsx | 独立 DeepSeek provider、思考模式与强度控件；关闭思考时强度控件不可用；切换普通 provider 复位这些专用字段 |
| .env.example、compose.yaml、config/deepseek-preparation.json | 精确域名许可、四个角色凭据引用、关闭的模板和峰值 USD 价目；补齐 API/Worker 白名单传递；未读取、修改或导入实际 .env/槽位/凭据 |
| scripts/test-offline.py、tests/fixtures/offline_guards.py | 只继承列明的操作系统变量；不继承服务凭据；拒绝项目 .env 读取及真实 DNS/socket。Windows 只放行 stdlib socketpair 自身回环，不能连接服务商 |
| frontend/playwright.offline.config.ts | 静态构建加完整假后端，所有站外请求中止；不加载原有读取 dotenv 的浏览器配置 |

测试记录：Python 单元/HTTP **240/240 通过，0跳过**（8.20秒，work/p5-live-offline.xml）；新增 DeepSeek/隔离/迁移/快照测试60项，原180项包含 P3/P4 单元安全回归。前端 TypeScript/Vite 构建通过（60 modules），隔离浏览器 **1/1** 通过，覆盖四槽位、模式/强度保存、测试额度拒绝及切回 Mock。证据 work/p5-live-browser-offline.json、p5-live-deepseek-offline.png。

首次测试隔离器拦截了 Windows asyncio 的内部 socketpair；已限定例外到该标准库回环调用。普通沙箱下的异步/PowerShell运行受限，最终以具体测试权限运行，仍保留凭据与外网隔离器。失败尝试不计作通过。

不运行 test-p5.ps1、真实API测试脚本、现有浏览器配置或数据库迁移，因为它们会加载现有 dotenv；本轮不读取真实密钥。没有重新验收真实 PostgreSQL/Redis/Runner、Docker 执行或供应商网络；历史 P5/P3/P4 的通过记录不能代替本轮实际结果。

## 协议复核

当前官方模型名称为 `deepseek-flash`（DeepSeek-V4.1-Flash）和 `deepseek-v4-pro`（DeepSeek-V4-Pro-0813）。两者均可切换思考模式。项目不自动接受旧别名，也不开放 Anthropic、Responses、Beta、Vision 或原生工具接口。

项目默认显式 `thinking_mode=disabled`，不依赖服务商默认开启的模式。开启时发送顶层 `thinking={"type":"enabled"}` 和 reasoning_effort=low/high/max，省略 temperature；关闭时发送 disabled 和配置的 temperature，不发 reasoning_effort。项目 HTTP 调用不使用 SDK extra_body 包裹。无 tools 的请求不需要回传 reasoning_content，项目只使用最终 content，并继续以受校验 JSON 提案进入 Gateway。

SSE 支持最终 choice 同时带 finish_reason=stop 与 usage，不假定存在独立 usage-only 块；通用适配器仍接受其原有 usage-only 格式。思考内容不发布至 delta、结果、SSE、检查点或日志；TTFT 表示首个可见回答片段，包含此前思考等待时间。completion_tokens 已包含 reasoning_tokens，不重复相加。缓存细分缺失时不伪造缓存命中率；完整用量缺失则保留 unknown 及预留。

401/403、402余额不足、422参数错误不自动重试；429、5xx、网络/超时由原有 Runtime 在调用/Token/费用限额内最多额外2次。首次专用测试 max_calls=1，第二次尝试在派发前被拒绝。断流、错误帧、无正文、截断、无效用量和原生工具调用均不能冒充成功，错误中不包含供应商正文。

## 峰谷价格与 USD 预算

以下为复核日官方价格，单位 USD/百万Token，非模型实测账单：

| 模型 | 缓存命中 谷/峰 | 缓存未命中 谷/峰 | 输出 谷/峰 |
| --- | --- | --- | --- |
| deepseek-flash | 0.003 / 0.006 | 0.15 / 0.30 | 0.60 / 1.20 |
| deepseek-v4-pro | 0.022 / 0.044 | 0.66 / 1.32 | 1.98 / 3.96 |

峰时为周一至周五 UTC 01:00–04:00、06:00–10:00，中国法定节假日除外；北京时间为09:00–12:00、14:00–18:00。其余为谷时，谷价为峰价一半。项目**不自动判断节假日或承诺谷价**，始终按峰时缓存未命中单价预留和展示保守估算，不提前扣除缓存折扣，避免跨时段低估。

费用估算 = (输入Token × 峰时输入单价 + 输出Token × 峰时输出单价) / 1000000；Decimal 向上取整到8位。预留先用登记输入上界及配置输出上限，收到可信 usage 后结算保守估算，实际峰谷/缓存账单另行核对。官方表已经是 USD，直接使用，不进行人民币汇率换算；PricePolicy 拒绝 currency=CNY，不能把人民币单价误当 USD。其他币种账户展示需独立核对，不自动充值或换汇。

config/deepseek-preparation.json 是非秘密、不会自动导入的关闭模板。两个价格条目分别使用 peak-cache-miss 单价，版本 ds-20261015-peak-v1，input_upper_bound=8192、output_upper_bound=4096；项目仍保留原有更小的任务总Token和费用上限，不自动扩大到供应商最大窗口。

## 精确许可和四槽位

Provider 均为 `deepseek`，Base URL 均为 `https://api.deepseek.com`；模板四槽位暂用 deepseek-flash、64输出、30秒、思考关闭、enabled=false。pro 可在后续独立批准后替换，必须采用其自身价格条目。64输出仅用于连通性，不足以代表完整规划与代码质量测试。

| 角色 | credential_reference |
| --- | --- |
| Planner | env:AGENTFORGE_MODEL_PLANNER_KEY |
| Coder | env:AGENTFORGE_MODEL_CODER_KEY |
| Researcher | env:AGENTFORGE_MODEL_RESEARCHER_KEY |
| Reviewer | env:AGENTFORGE_MODEL_REVIEWER_KEY |

全局 ALLOWED_MODEL_HOSTS 必须含 api.deepseek.com，每个选中的凭据名还需在 MODEL_CREDENTIAL_HOSTS 显式绑定该精确主机；不能使用 *.deepseek.com、私网或任意反代。示例全局名单保留既有兼容供应商，但凭据默认仍不注入实际值。真实Key只能由用户在本地受保护环境中设置，不发到聊天、配置接口或Git。本轮未获取已有凭据是否存在，也未修改已保存配置。

## 真实测试提案：等待单独批准

建议只批准 **Coder槽位 / deepseek-flash / 关闭思考 / 1次请求**，不运行四角色协作，不调用任何工具。

1. 先检查没有其他在途真实任务；在收费开关关闭时，由用户或下一轮获准流程将数据库升级到0007、重启项目 API/Worker，再保存选中槽位的安全引用及模板。不得重跑已有不明派发。
2. 由用户本地配置 Coder Key；确认价格、精确域名、真实余额和测试额度。不得把凭据发送到聊天。其他真实槽位保持停用。
3. 本次提议日预算和独立测试预算均为 **US$0.005**，测试次数1，日Token限额8256。只有批准后才开启 REAL_CALLS_ENABLED。测试专用计数不是全系统维护开关；窗口内暂停普通 Real Chat/任务，避免其他任务消耗额度。
4. max_tokens=64、thinking_mode=disabled、timeout=30秒；测试任务 max_calls=1、max_iterations=1、期限60秒，提示只回答 connected。最坏预留估算 (8192×0.3 + 64×1.2)/1000000 = **US$0.00253440**，不承诺供应商最终账单。
5. 批准后只运行 `./.venv/Scripts/python.exe scripts/test-real-models.py --roles coder` 一次。核对真实任务、可见回答、SSE结束、usage、TTFT及供应商控制台；停止后关闭开关、保留未知预留，不自动续测或加额。

当前脚本只检查任务成功状态，验收还须人工核对回答是否为 connected；其 actual_calls 字段来源于账本尝试数，不是供应商独立账单。PASSED 不代表完整协作或模型质量验收。失败/超时/usage缺失均停止核查，不自动追加测试、清零预留或充值。

本轮迁移尚未应用，线上槽位状态和端到端供应商连接未验证。P3 Sandbox、P4 MCP、Skill及独立审批源码未放宽。代码安全扫描使用 --no-local-secrets：只检查当前源码/暂存区/构建产物及本轮记录中的凭据格式，没有读取本机真实Key做值比对，不能宣称覆盖所有未知格式秘密。

## 复核来源和无费用命令

- [DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- [Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)
- [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)

```powershell
Set-Location D:\AIProjects\AgentForge-AI
./.venv/Scripts/python.exe scripts/test-offline.py
./.venv/Scripts/python.exe scripts/test-offline.py --frontend
./.venv/Scripts/python.exe scripts/test-offline.py --browser
./.venv/Scripts/python.exe scripts/check_secrets.py --no-local-secrets
git status --short
git diff --check
git diff
git ls-files --others --exclude-standard
```

git diff --check通过，已跟踪差异及10个新增文件分别复核（路径、UTF-8、Python语法、空白和单独diff），记录在work/p5-live-tracked.diff、p5-live-untracked.diff及p5-live-untracked-review.json。截图已检查，无真实凭据。

未操作Git暂存/提交或.git权限，HEAD保持982e83e。准备完成后暂停，等待明确的单次真实测试批准，不进入P6。
