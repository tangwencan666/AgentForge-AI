# P5 模型集成与凭据边界

> 2026-10-19 文档修正：当前结论以 [PROJECT_STATUS](PROJECT_STATUS.md) 顶部为准，**RUNTIME_BLOCKED**。本轮未核验主 API/Worker、凭据存在性、数据库、Docker、模型槽位或 Permit/预算实时状态，均为 UNKNOWN / 未验证；以下有日期的运行记录仅代表当次观察。G4 Archive-only 提交不证明原 IPC 故障、B1/B2/B3 或真实模型验收已通过。

2026-10-16只读封版历史观察：当时API/Worker的Coder变量存在标记均True、配置一致，四槽Disabled，真实调用/Permit关闭、费用预算0、Worker deny、出口阻断。保留这些原始事实，不作为现在的运行证明。变量存在不代表DeepSeek认证、模型标识或计费链路通过；该轮封版限制见LOCAL_LIFECYCLE_TEST_REPORT。

Coder本地配置收尾历史（2026-10-15）：openai_compatible可在精确DeepSeek端点下使用受审查DeepSeek参数档，保留端点/受众/模型/参数校验。`env`必须落实为 `env:AGENTFORGE_MODEL_CODER_KEY`。当时已登记Coder价格和名单，强制环境凭据、0重试、零费用及出口阻断；当时两个进程的存在标记均False。False/False 与后续 True/True 均仅指各自日期；本轮不从它们推断现时状态。

P5-LIVE前置验收历史记录（2026-10-15）：独立deepseek档、四角色thinking字段、0007、完整347项及15项浏览器已通过；当时实际槽位及许可/价格尚未配置。详见[P5_LIVE_PREFLIGHT_REPORT](P5_LIVE_PREFLIGHT_REPORT.md)。本轮Coder配置和兼容入口以上述最新文档为准，两个入口都强制使用DeepSeek档处理该精确端点。

2026-10-15 P5 原始记录，Asia/Shanghai：支持固定角色 planner、coder、researcher、reviewer，同一供应商可服务多个模型；当时缺少凭据和获批测试额度，实际外部调用0。真实外部 API 验收至今未完成，当前凭据存在性和运行额度本轮未核验，不能沿用当时“未配置”的原因代替即时检查。

## 配置与适配

Model Center / `/api/v1/model-slots` 支持 provider、base_url、model、credential_reference、temperature、max_tokens、timeout、enabled、priority 和版本并发校验。priority 范围 0–100，数值小的无依赖角色优先列入同批调度；它是调度偏好，不覆盖 DAG 依赖、固定角色或并发/预算上限，不保证抢占运行中的请求。

当前执行适配器为 `openai_compatible` 和 `deepseek`，实现受控 Chat Completions SSE。其他供应商标识只保留配置/扩展接口，未实现的协议明确拒绝，不假定 Anthropic/Google/Azure 原生协议与 OpenAI 相同。ProviderAdapter / ModelReply / ProviderFailure 隔离传输、输出、用量和错误；新增适配器必须在可信注册表登记，不能由模型输出指定模块。

`mock` 仅显式选择，is_mock=true；真实模式不回退到 Mock。P5 的四角色/单角色架构保留配置和价格快照能力，但当前普通 Real 协作、Real Chat 和模型测试创建路径均拒绝 MODEL_PERMIT_REQUIRED，槽位启用或价格齐全不是授权。只有独立 PermitService 的固定单次测试路径可进入受控真实派发；配置版本、启停或价格政策变化会阻止调用，不自动换模型。

核心源码：`providers/base.py`、`providers/router.py`、`providers/openai_compatible.py`、`schemas/models.py`、`services/models.py`、`services/orchestration/real_runtime.py`、`api/v1/inference.py`。

## 受保护本地配置

已提交源码默认 MODEL_CREDENTIALS_ENV_ONLY=true，Coder 专用启动策略也固定为true；模型 Key 只允许来自经批准的服务进程环境，专用PowerShell原生继承不写dotenv。本轮不确认这些进程当前是否存在或已加载策略。数据库只存 `env:AGENTFORGE_MODEL_PLANNER_KEY` 等引用。不要把实际 Key 放到聊天、前端表单、Git、URL、任务目标或工具参数。凭据至少16字符、无空白，不能复用管理/审批/Runner/MCP服务凭据。MODEL_PRICES、MODEL_CREDENTIAL_HOSTS是非秘密策略变量，不能作为凭据引用。

当前默认配置安全关闭：

```dotenv
AGENTFORGE_REAL_CALLS_ENABLED=false
AGENTFORGE_REAL_DAILY_BUDGET_USD=0
AGENTFORGE_REAL_DAILY_TOKEN_LIMIT=100000
AGENTFORGE_REAL_TEST_BUDGET_USD=0
AGENTFORGE_REAL_TEST_MAX_CALLS=1
AGENTFORGE_MODEL_PRICES={}
AGENTFORGE_MODEL_CREDENTIAL_HOSTS={}
```

这些是安全默认配置示意，不是当前进程状态。任何临时真实调用、额度或出口调整都需要新的独立明确授权及完整预检；仅配置 Key、开启 real_calls 或提高额度均不能绕过任务级 Permit。旧一次收费授权已经结束，本轮不设置任何额度、签发或调用。前端不能更改这些服务端策略。

每个凭据名还必须在 MODEL_CREDENTIAL_HOSTS 显式绑定允许的主机列表；全局 ALLOWED_MODEL_HOSTS 也必须允许该主机。以下仅示意配置结构，不是已批准模型/价格：

```json
{"AGENTFORGE_MODEL_PLANNER_KEY":["api.openai.com"]}
```

MODEL_PRICES 按 `provider/model` 索引，值由人工复核供应商价格和能力后登记：input_per_million、output_per_million（Decimal USD）、input_upper_bound、output_upper_bound、version、token_parameter（max_completion_tokens 或 max_tokens）。不内置猜测的实时价目或假定所有模型支持同一参数。参数由适配器能力决定：DeepSeek thinking=enabled 时发送 reasoning_effort、不发 temperature；disabled 时发送 thinking.disabled 和配置 temperature，不发 reasoning_effort，保存的 high 不会作为冲突 HTTP 参数发送。DeepSeek价格策略要求 max_tokens；协议/价格登记不是供应商实际验收。

本地 Python 支持受保护环境中的 AGENTFORGE_MODEL_* 引用；Compose 为标准四个角色 Key 显式注入，其他引用需部署管理员明确注入对应服务环境。Runner 和受控执行容器不获得模型 Key。日志/SSE/检查点仅含安全结果和引用，不含凭据值。前端只显示引用是否存在、是否测试及安全状态，存在不等于已通过认证。

## 出口与流式处理

所有实际调用只允许批准的 HTTPS 主机/443，无 URL 凭据、query/fragment。解析 DNS 后所有地址均须为 global；连接固定到校验过的 IP，并保持原 Host 与 TLS SNI/证书验证，禁止重定向和环境代理，避免二次 DNS 解析绕过。默认不支持 loopback、metadata、私网模型或任意代理。

请求有任务剩余 deadline 与槽位 timeout 双重上限；单响应总量 256 KiB、单帧 64 KiB、输出 64 KiB。要求完整结束标志，拒绝错误帧、原生工具调用、截断输出和无效用量。只处理受控 JSON 工具提案，不执行供应商返回的原生工具命令。

Chat 从供应商 SSE 接收增量并记录实际观测的首 Token 延迟。为避免秘密跨传输片段泄漏，先缓冲完整行并脱敏再保存 model_delta；短的单行回答可能在完成后一次发布，不承诺逐 Token 无延迟显示。SSE 事件持久化，可按游标回放，重连不重新发模型请求。

## 预算与统计

每次尝试在 PostgreSQL 事务中锁定任务/租户 UTC 日额度，先预留已登记的保守输入上界 + max_tokens 及 Decimal 费用，检查任务最大调用数/Token/费用/deadline和租户日额度后才请求。并行分支共享同一余额。提示 UTF-8 字节加开销必须处于登记输入上界内；上界依赖供应商核实的 token 计量约定，不能保证任意兼容服务的最终账单。

返回合法 usage 时保存输入/输出/总 Token，以固定价格版本结算估算费用，缓存/推理折扣没有登记时使用普通输入/输出单价，不把估算称为实际扣款。usage 缺失/超时/断流/取消或崩溃结果不明时标 unknown/pending 并保留预算上界，不释放为零，不伪造精确 Token。供应商超出登记上界会终止后续调用并保留事实，最终账单仍需外部核对。

`/models/metrics` 按角色/供应商/模型/Mock 标识统计最近 2000 次尝试的次数、成功/超时/错误率、已报告 Token、未知用量、费用估算、未决上界、延迟及可用 TTFT；明确窗口，不当作全量账单。任务页面另显示自身额度、调用账本和未决预留。缺用量的成功内容也不显示“零真实成本”。

已提交默认及 Coder 启动策略 real_max_retries=0，单次Permit路径不自动追加请求。通用适配器保留受配置约束的重试算法，不等于当前进程已加载或获准开放重试。已完成逻辑节点复用原结果；恢复遇到结果不明的真实派发进入 needs_reconciliation，不自动重新计费或重放副作用。

## 单独真实 API 验收

0008后普通真实Chat/Agent及模型测试按钮不能替代独立Single-Use Permit；零测试额度先返回 MODEL_TEST_BUDGET_BLOCKED，额度非零也不豁免 MODEL_PERMIT_REQUIRED。本轮不改变源码要求的零预算、Disabled槽位和关闭出口，不把这些要求冒充当前运行观察；任何收费验收都需要新的单独授权。

应用服务端 Permit 的源码边界（不同于 G4 诊断工具的 Mock 授权）：

- 独立签发权限与普通管理员/模型隔离；服务端生成并绑定 task/execution、固定 Coder/provider/model、槽位版本、端点/凭据引用、请求指纹、可信 Worker 身份及有效期，不接受普通客户端任意改写。
- PostgreSQL 事务原子认领，单次 `max_attempts=1`；`CLAIMED` 同时预留调用数、8256 Token（8192输入上界＋64输出）及登记价格计算出的费用，须满足应用单次/日/测试上限 US$0.005。此数值是现有固定测试协议，不是本轮消费授权或供应商绝对账单保证。
- 外部 HTTP 前先提交 `DISPATCH_COMMITTED` 派发意图；不持数据库事务等待整个响应。成功、明确失败和 UNKNOWN 分开审计；可能已派发而结果未知时保留必要预算，不自动清零、重发或重置授权。
- 可信 Worker 来自服务端引导及 proof，不是客户端 worker_id。Issuer 不应进入普通 PowerShell/Worker 环境。主服务启停、0009/0010主库迁移、Permit签发和收费执行各需独立批准；代码提交和历史隔离测试不构成部署证据。详见 [P5_LIVE_PERMIT_DESIGN](P5_LIVE_PERMIT_DESIGN.md)。

当前 scripts/test-real-models.py 仅观测一个已由独立权限签发的Permit，不签发、不派发、不解析Key、不重试。唯一可选身份参数为 --permit-id；旧 --roles all/coder 已移除。即便观测，脚本仍会写本地报告，因此也不属于本次纯只读执行清单。协议与批准流程见P5_LIVE_PERMIT_DESIGN；此处不提供开放开关或发起推理的操作步骤。

DeepSeek Key认证、deepseek-flash实际模型可用性、真实推理、供应商DNS/TLS及计费链路尚未验证。Stub/MockTransport与450项历史测试不能替代真实供应商验收，也不能代替P6。

协议参考：[Create chat completion](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)、[Streaming events](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events)。实现请求 stream_options.include_usage，并按官方协议将缺失用量保留为未知；协议兼容不代表具体供应商已验收。
