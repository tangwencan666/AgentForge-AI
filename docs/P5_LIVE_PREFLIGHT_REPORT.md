# P5-LIVE：DeepSeek 真实测试前置验收

后续说明：本报告保留前一轮检查时的实际缺项；后来已经完成Coder非秘密配置及精确许可/价格登记，新的凭据继承与现状见[DEEPSEEK_CODER_LOCAL](DEEPSEEK_CODER_LOCAL.md)。仍未执行收费测试。

2026-10-15，Asia/Shanghai。工作目录 `D:\AIProjects\AgentForge-AI`，HEAD `982e83ef32b7d274e820d59ee63d6fb76bd8979e`。本报告是本轮实际执行记录；此前兼容性准备报告中的“尚未应用迁移、未重跑完整环境”属于上一轮历史状态。

**结论：无费用工程回归通过，但第一次 DeepSeek 真实测试的全部前置条件尚未满足，状态 BLOCKED。实际外部模型调用 0 次。** 缺少实际槽位、模型凭据、运行配置中的域名许可/凭据受众/价格登记，以及单独批准的收费测试额度。当前维持维护模式，暂停等待后续配置与单次真实测试授权，不进入 P6。

## 1. Git、凭据与运行隔离

- 检查已跟踪差异、新增未跟踪文件及暂存区；HEAD 未变化，没有暂存或提交操作，没有修改 `.git` 权限。
- 四个预期凭据名称 `AGENTFORGE_MODEL_{PLANNER,CODER,RESEARCHER,REVIEWER}_KEY` 在当前进程环境中均不存在，在原项目 dotenv 中也均未声明。只匹配名称，不解析、校验、复制或输出模型凭据值；未修改原 `.env` 或已有模型凭据。
- 新增 `scripts/p5-live-preflight.py`：生成 `work/p5-live-preflight/.env`，仅包含维护所需的服务配置和非秘密策略，不包含模型 Key。数据库/Redis/管理员/审批/Runner 等服务凭据仅在本机服务间使用，不打印。
- 维护目录取消继承，仅为当前 Windows SID 授权；备份和维护 dotenv 均被 Git 忽略。备份可能含业务内容，不能提交或公开。
- API/Worker 通过受限于项目 `work` 的 `AGENTFORGE_SETTINGS_FILE` 启动；子进程不继承模型 Key。维护策略强制 `REAL_CALLS_ENABLED=false`、日费用和测试费用均为 0、测试次数上限 1。
- 新增独立传输门 `AGENTFORGE_EXTERNAL_MODELS_BLOCKED=1`；两个适配器在 DNS/HTTP 之前拒绝派发。完整 Python 回归额外禁止原 `.env` 读取及非本机 socket/DNS；只有明确 MockTransport 用例可替换传输门，真实网络仍受测试隔离器约束。
- 未运行 `scripts/test-real-models.py`，未访问真实模型推理端点、充值或查询模型账户。只读取了 DeepSeek 公开静态文档。

安全扫描两种模式均通过：当前代码、未跟踪文件、Git 暂存内容、前端 bundle、日志及测试记录未发现常见 Key 格式或维护环境已知服务秘密及其常见编码。模型 Key 不做真实值比对，不能把格式扫描解释为覆盖所有未知秘密格式。

## 2. 数据库 0007：备份、演练、应用

目标归属已验证：容器 `agentforge-p1-postgres` 的 Compose 项目为 `agentforge-p1`，工作目录为本项目，发布的 PostgreSQL 端口与维护数据库 URL 匹配，实际数据库为 `agentforge`。未迁移其他数据库或其他项目。

迁移 `0007_deepseek` 仅向 `model_slots` 增加 `thinking_mode`、`reasoning_effort` 两列，默认 `disabled/high`，非空且分别有枚举检查约束；不删除、重命名或覆盖已有字段/业务行。版本从 `0006_real_models` 升至 `0007_deepseek`。

| 项目 | 实际结果 |
| --- | --- |
| 迁移前备份 | `work/p5-live-preflight/agentforge-before-0007-20261015110827.dump` |
| 格式/大小 | PostgreSQL custom archive，971631 bytes |
| SHA256 | `8e1f0825d77e2c3e4cda70369093d059140462071b65f98a12104ebc93131617` |
| 恢复验证 | 在本项目实例的独立临时数据库恢复成功，原表行数/原列内容指纹一致 |
| 升降级演练 | 临时库应用 0007、验证默认值、降级后原列内容指纹仍一致；临时库已删除 |
| 实际迁移 | `scripts/migrate.py upgrade` 成功，`check` 通过 |
| 原业务数据 | 实际迁移后、回归写入前，20 张业务表原列的行数和内容指纹与备份一致 |
| 最终版本 | 重启后查询及 readiness 均确认 `0007_deepseek` |

降级会移除新增加的两项 thinking 设置，因此已使用新字段后的回退需要先保存这些设置；原字段/原业务行的保留已通过演练验证。完整备份的恢复演练提供迁移前状态恢复依据，不能盲目在含后续新数据的运行库上覆盖恢复。浏览器回归后来生成的测试记录不属于“迁移破坏数据”；槽位配置已恢复，乐观锁版本按正常更新递增。

证据：维护目录 `backup.json`、`migration.json`。备份与证据保留本机，不纳入建议提交。

## 3. 本轮完整回归

| 验证 | 实际结果 | 证据 |
| --- | --- | --- |
| Python 全部测试 | **347/347，0失败、0跳过**，188.59 秒；unit 206、HTTP 39、integration 102 | `work/p5-all.xml` |
| 维护模式单元/HTTP 预验证 | 245/245，0跳过 | `work/p5-live-preflight-unit.xml`，包含在完整347项内，不重复累计 |
| 全部真实后端浏览器测试 | **14/14**，0跳过、0 flaky，52.7 秒 | `work/p5-e2e.json` |
| DeepSeek 全假后端浏览器测试 | **1/1**，0跳过，9.2 秒 | `work/p5-live-browser-offline.json` |
| TypeScript / Vite | 类型检查和构建通过，60 modules | 本轮命令输出及 `frontend/dist` |
| 实际 OS Worker 重启 | 通过；PID 6188 → 24240，任务 succeeded，Planner 仅1次，四角色共4次明确 Stub 调用 | `work/p5-worker-restart.json` |
| 秘密检查 | 已知服务秘密/编码比对及无本地秘密格式扫描均通过 | `scripts/check_secrets.py` 两种模式 |
| 最终本机健康 | API live/ready、前端 readiness 代理、MCP Tools 均 HTTP200；PG/Redis up；Runner available、未阻断、活动执行0 | `work/p5-live-preflight/health.json` |

347项覆盖四角色路由、结构化计划、并行/依赖/冲突修订、预算原子预留、取消/暂停/超时、未知用量、SSE、恢复不重复计费；也覆盖 P4 MCP schema、权限撤销、独立审批、幂等副作用、Skills 生命周期及真实 MCP subprocess；P3 使用真实 Docker 验证网络隔离、身份、宿主文件不可读、CPU/内存/PID/输出限制、取消/超时及清理。Coder → Gateway → 独立审批 → 真实 P3 执行 → Reviewer 真实执行证据的回归通过。

模型协议测试使用明确 MockTransport，工作流和 OS 恢复使用明确 Provider Stub；PostgreSQL、Redis、MCP 和受限 Docker 执行是真实环境。以上均不代替供应商认证、DNS/TLS、模型输出或账单验收。

本轮修复了新增浏览器测试的 TypeScript 回调变量推断问题。一次 Runner 缓存重建因包索引暂时不可用失败，重试后成功；没有安装系统组件、修改 Docker Desktop 全局配置或放宽 P3/P4。最终专用故障 Runner 已删除，仅保留本项目 PG、Redis 和可信 Runner。

依赖记录：Python3.13.5、FastAPI0.143.0、LangGraph1.2.15、SQLAlchemy2.0.54、Alembic1.20.0、httpx0.28.1、pytest9.1.1。

## 4. DeepSeek 协议与实际配置的差距

2026-10-15 再次读取[官方模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)及[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)：OpenAI 格式基础地址为 `https://api.deepseek.com`，模型 ID 为 `deepseek-flash` 和 `deepseek-v4-pro`。适配器支持精确主机/HTTPS443/根路径或 `/v1`，固定追加 `/chat/completions`，不允许任意反代或原生工具执行。

适配器显式发送 `thinking.type=disabled/enabled`；开启时使用 `reasoning_effort=low/high/max` 并省略 temperature，关闭时发送 temperature。项目通过原始 HTTP JSON 发顶层参数，不使用 SDK 的 extra_body 包裹。SSE、最终 usage、缓存/推理用量一致性和安全错误处理均已通过离线测试，尚无真实响应证明。

四个实际保存槽位当前完全相同：provider/base_url/model/credential_reference 均为空，enabled=false，thinking_mode=disabled、reasoning_effort=high，max_tokens=4096、timeout=60、priority=50。它们**没有对应任何已启用 DeepSeek 模型**，不能把示例 JSON 视为运行配置。

| 角色 | 待配置的引用名称 | 当前状态 |
| --- | --- | --- |
| Planner | `env:AGENTFORGE_MODEL_PLANNER_KEY` | 槽位未配置，变量不存在 |
| Coder | `env:AGENTFORGE_MODEL_CODER_KEY` | 槽位未配置，变量不存在 |
| Researcher | `env:AGENTFORGE_MODEL_RESEARCHER_KEY` | 槽位未配置，变量不存在 |
| Reviewer | `env:AGENTFORGE_MODEL_REVIEWER_KEY` | 槽位未配置，变量不存在 |

当前原项目配置显式覆盖了新版默认主机列表，因此实际全局名单**不含** `api.deepseek.com`；四凭据的域名受众映射均为空；Flash/Pro 价格条目均未登记。`config/deepseek-preparation.json` 仅为关闭模板，未自动导入，也未更改现有凭据或槽位。

价格模板按官方 USD 峰时缓存未命中单价保守估算，Flash 输入0.30/输出1.20、Pro输入1.32/输出3.96 USD/百万Token；不提前扣除谷价或缓存折扣，不作人民币换汇。费用是估算而非实际扣款，详情见兼容性准备报告。

## 5. 预算、重试、审计及停止状态

- 当前实际服务策略：真实调用关闭；独立传输阻断开启；日预算=测试预算=0 USD；测试次数上限1；日Token上限100000。前端显示收费测试 BLOCKED。
- 服务端 PostgreSQL 事务锁在每次派发前强制检查任务调用次数、Token、费用和期限，以及租户日额度、独立测试次数/费用；并行不能超卖预留，重启/重复按钮不重置额度。
- 本轮将 `model_test` 的 Runtime 尝试上限明确固定为1，429/5xx/超时/格式错误也不自动重试，并保留原始失败代码。普通协作仍保留原有最多3次受控尝试；未知派发不自动重放，工具副作用不随模型重试重复执行。
- 新增4项单元参数案例验证测试不重试，新增传输阻断案例；新增真实 PG/Redis 集成案例证明429只有1个 Stub尝试、未知费用保留、`node_started` 含 model_test/retry_policy/call_limit/token_limit/budget_limit_usd。全套原有预算与安全案例同时通过。
- 真实调用账本在维护开始和全部测试/OS重启后均为0条且一致；活动真实模型任务0。Stub集成使用独立租户并清理，不能作为真实调用记录或实际计费。
- API、前端、Worker 已在维护配置下重启。最终库为0007、21张公开表（20业务表加版本表），依赖健康，Runner活动执行0。模型列表保留四槽位架构，P3/P4安全和独立审批保留。

证据：`work/p5-live-preflight/preparation.json`、`ledger-before.json`、`state-after.json`、`health.json`。

## 6. 第一次真实测试仍需完成的条件

1. 在本地受保护配置中设置 Coder Key，只保存 `env:AGENTFORGE_MODEL_CODER_KEY` 引用；不把 Key 发到聊天。其他真实槽位保持停用。
2. 配置 Coder 为 deepseek / `https://api.deepseek.com` / deepseek-flash / disabled thinking / 64输出Token / 30秒；保存版本并核对实际 DTO。
3. 将精确主机加入实际全局名单，并将 Coder 凭据受众绑定至该主机；登记模板中经复核的 USD 价格和保守用量上界。
4. 单独批准仅1次、日预算与测试预算各 **US$0.005**、日Token上限8256。最坏预留估算为 `(8192×0.30+64×1.20)/1000000 = US$0.00253440`；不保证最终供应商账单。不得自动充值或追加尝试。
5. 只有上述配置和授权完成后，再对选中测试进程受控解除维护阻断并重启 API/Worker；核对其他真实任务仍停止。现有维护 wrapper 固定零额度且阻断出口，不能直接拿它执行收费验收。
6. 后续获准时仅用专用脚本 `scripts/test-real-models.py --roles coder` 一次（60秒任务期限、1调用、无工具），核对 connected、SSE、usage/TTFT和供应商账单；失败或用量不明立即停止，保留预算预留。该脚本 actual_calls 来自任务账本，不能解释为独立供应商请求计数。

本轮未配置上述缺项，未执行该脚本。真实连通性、认证、供应商运行时参数/流式用量及实际收费仍为 NOT RUN，不能宣称已验收。

## 7. 独立提交建议

建议一个独立提交 `feat(p5-live): prepare DeepSeek and verify zero-cost preflight`，包含本轮维护隔离、迁移/检查工具和上一轮尚未提交的完整 DeepSeek 兼容变更。核心范围：provider/模型字段/迁移、预算审计与测试不重试、前端 Model Center、关闭配置模板、离线与完整测试脚本、测试及文档。

已检查 `git diff --check`、完整 tracked diff、暂存区及逐个新文件的独立 diff/UTF-8/Python语法/空白。工作区有28个已跟踪文件修改及16个新增文件，暂存区为空；已确认维护dotenv、数据库备份和前端dist被Git忽略，没有遗留执行容器。复核材料在 `work/p5-live-tracked.diff`、`p5-live-untracked.diff`、`p5-live-untracked-review.json`。不提交 `work`、备份、原 `.env`、维护 `.env` 或构建产物。

用户可在 Windows CMD 中自行执行：

```cmd
cd /d D:\AIProjects\AgentForge-AI
git add -- .env.example compose.yaml backend config docs frontend scripts tests
git diff --cached --check
git diff --cached --stat
git diff --cached
git commit -m "feat(p5-live): prepare DeepSeek and verify zero-cost preflight"
```

本轮未执行以上暂存/提交命令。完成后暂停；首次收费测试与 P6 均未获本轮授权。
