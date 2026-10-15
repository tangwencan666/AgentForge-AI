# P5 模型集成与凭据边界

2026-10-15，Asia/Shanghai。支持固定角色 planner、coder、researcher、reviewer，同一供应商可服务多个模型。当前真实外部 API 验收 **BLOCKED**：本机未配置模型凭据和已批准测试额度，实际外部调用 0 次。

## 配置与适配

Model Center / `/api/v1/model-slots` 支持 provider、base_url、model、credential_reference、temperature、max_tokens、timeout、enabled、priority 和版本并发校验。priority 范围 0–100，数值小的无依赖角色优先列入同批调度；它是调度偏好，不覆盖 DAG 依赖、固定角色或并发/预算上限，不保证抢占运行中的请求。

当前执行适配器仅 `openai_compatible`，实现 Chat Completions SSE。其他供应商标识只保留配置/扩展接口，未实现的协议明确拒绝，不假定 Anthropic/Google/Azure 原生协议与 OpenAI 相同。ProviderAdapter / ModelReply / ProviderFailure 隔离传输、输出、用量和错误；新增适配器必须在可信注册表登记，不能由模型输出指定模块。

`mock` 仅显式选择，is_mock=true；真实模式不回退到 Mock。Real 协作要求四个槽位均启用并有已登记协议、凭据、价格；Real Chat 只要求选中的角色。创建任务保存非秘密配置/价格快照，之后不自动换模型；配置版本、启停或价格政策变化会阻止后续调用，凭据值在调用边界重新取用。

核心源码：`providers/base.py`、`providers/router.py`、`providers/openai_compatible.py`、`schemas/models.py`、`services/models.py`、`services/orchestration/real_runtime.py`、`api/v1/inference.py`。

## 受保护本地配置

实际 Key 只能存服务端环境或被忽略的项目 `.env`，例如 `AGENTFORGE_MODEL_PLANNER_KEY`。数据库只存 `env:AGENTFORGE_MODEL_PLANNER_KEY` 引用。不要把实际 Key 放到聊天、前端表单、Git、URL、任务目标或工具参数。凭据至少 16 字符、无空白，不能复用管理/审批/Runner/MCP 服务凭据。MODEL_PRICES、MODEL_CREDENTIAL_HOSTS 是策略变量，不能作为凭据引用；脱敏与扫描会排除这些非秘密配置，避免把默认 `{}` 误替换并破坏模型 JSON。

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

操作员另行确认真实供应商、模型、允许端点和收费测试金额/次数后，在本地设置实际密钥、适当额度并开启 real_calls。开发授权没有提供具体测试金额，因此本轮保留 0 元测试额度。前端不能更改这些服务端策略。

每个凭据名还必须在 MODEL_CREDENTIAL_HOSTS 显式绑定允许的主机列表；全局 ALLOWED_MODEL_HOSTS 也必须允许该主机。以下仅示意配置结构，不是已批准模型/价格：

```json
{"AGENTFORGE_MODEL_PLANNER_KEY":["api.openai.com"]}
```

MODEL_PRICES 按 `provider/model` 索引，值由人工复核供应商价格和能力后登记：input_per_million、output_per_million（Decimal USD）、input_upper_bound、output_upper_bound、version、token_parameter（max_completion_tokens 或 max_tokens）。不内置猜测的实时价目或假定所有模型支持同一参数。当前 temperature 按配置发送，不支持该参数的模型须通过独立适配能力扩展，不宣称兼容。

本地 Python 支持受保护环境中的 AGENTFORGE_MODEL_* 引用；Compose 为标准四个角色 Key 显式注入，其他引用需部署管理员明确注入对应服务环境。Runner 和受控执行容器不获得模型 Key。日志/SSE/检查点仅含安全结果和引用，不含凭据值。前端只显示引用是否存在、是否测试及安全状态，存在不等于已通过认证。

## 出口与流式处理

所有实际调用只允许批准的 HTTPS 主机/443，无 URL 凭据、query/fragment。解析 DNS 后所有地址均须为 global；连接固定到校验过的 IP，并保持原 Host 与 TLS SNI/证书验证，禁止重定向和环境代理，避免二次 DNS 解析绕过。默认不支持 loopback、metadata、私网模型或任意代理。

请求有任务剩余 deadline 与槽位 timeout 双重上限；单响应总量 256 KiB、单帧 64 KiB、输出 64 KiB。要求完整结束标志，拒绝错误帧、原生工具调用、截断输出和无效用量。只处理受控 JSON 工具提案，不执行供应商返回的原生工具命令。

Chat 从供应商 SSE 接收增量并记录实际观测的首 Token 延迟。为避免秘密跨传输片段泄漏，先缓冲完整行并脱敏再保存 model_delta；短的单行回答可能在完成后一次发布，不承诺逐 Token 无延迟显示。SSE 事件持久化，可按游标回放，重连不重新发模型请求。

## 预算与统计

每次尝试在 PostgreSQL 事务中锁定任务/租户 UTC 日额度，先预留已登记的保守输入上界 + max_tokens 及 Decimal 费用，检查任务最大调用数/Token/费用/deadline和租户日额度后才请求。并行分支共享同一余额。提示 UTF-8 字节加开销必须处于登记输入上界内；上界依赖供应商核实的 token 计量约定，不能保证任意兼容服务的最终账单。

返回合法 usage 时保存输入/输出/总 Token，以固定价格版本结算估算费用，缓存/推理折扣没有登记时使用普通输入/输出单价，不把估算称为实际扣款。usage 缺失/超时/断流/取消或崩溃结果不明时标 unknown/pending 并保留预算上界，不释放为零，不伪造精确 Token。供应商超出登记上界会终止后续调用并保留事实，最终账单仍需外部核对。

`/models/metrics` 按角色/供应商/模型/Mock 标识统计最近 2000 次尝试的次数、成功/超时/错误率、已报告 Token、未知用量、费用估算、未决上界、延迟及可用 TTFT；明确窗口，不当作全量账单。任务页面另显示自身额度、调用账本和未决预留。缺用量的成功内容也不显示“零真实成本”。

401/403不重试；限流、暂时5xx、网络/超时最多额外2次，格式修复最多额外1次，均占调用/Token/预算，重试不重置期限。已完成逻辑节点复用原结果；恢复遇到 reserved/pending 的真实派发进入 needs_reconciliation，不自动重新计费或重放副作用。

## 单独真实 API 验收

模型测试按钮需要独立测试额度，默认关闭。测试额度按租户 UTC 日累计，次数与费用在派发前原子预留，不能靠多点按钮、重启或换幂等键重置。测试任务 max_calls=1；同一服务商可以配置四个不同模型。

```powershell
./.venv/Scripts/python.exe scripts/test-real-models.py
# 仅在已批准足够次数、金额并配置全部角色时：
./.venv/Scripts/python.exe scripts/test-real-models.py --roles all
```

结果保存 `work/p5-real-api.json`；BLOCKED 返回 2，实际调用 0 次，不算通过。当前记录为缺少启用策略和获准测试额度，模型凭据检查也为空。Stub/MockTransport 用于适配器和工作流测试，不能替代此项。没有通过本轮实际 DNS/TLS、供应商认证、具体模型参数兼容、流式 usage 与真实账单验证。

协议参考：[Create chat completion](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)、[Streaming events](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events)。实现请求 stream_options.include_usage，并按官方协议将缺失用量保留为未知；协议兼容不代表具体供应商已验收。
