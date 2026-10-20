# DeepSeek Coder：本地无费用配置与 Permit 安全启动

## 0008 部署后的启动要求（2026-10-16 保护修复）

`scripts/start-coder-local.ps1` 已适配 Single-Use Execution Permit 和共享进程保护。用户在持有 Coder Key 的 PowerShell 中自行执行下方命令；测试入口遇到保护记录会拒绝，不再替换这些进程。此前一次收费授权已经结束，本启动操作不创建 Permit、不发送模型请求。

启动器仅检查环境变量名称；它显式设置 `SINGLE_USE_PERMITS_ENABLED=false`、`REAL_WORKER_MODE=deny`，并继续强制真实开关false、日/测试预算0、出口阻断和重试0。如果该PowerShell还含 `AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN`，脚本在任何重启前拒绝执行。请使用只含既有Coder模型凭据且不含签发凭据的专用PowerShell；脚本不读取、复制或清除这些凭据值。

`check-coder-local.py --before-restart` 只验证本地准备策略、主库版本0008、四槽Disabled、无非终态任务（含暂停任务）、无活动Permit及真实操作记录0，不要求旧API/Worker已经持有新变量。重启后的检查必须同时得到API和Worker的 **True** 凭据存在布尔值，并验证配置摘要、槽位版本、Permit关闭、Worker deny、价格、预算和精确DeepSeek凭据受众一致。False/False即使相互一致，也不算继承成功。True只代表变量名称存在，不验证Key内容、认证或余额。

影响：无冲突时创建受保护 API/Worker，已健康且身份/配置一致时只复用；旧进程、身份不符或配置冲突会拒绝。前端、数据库、Redis、Runner不重启。脚本不执行迁移，0007或未完成任务会在任何启动前阻塞；需要显式人工停止时见 LOCAL_LIFECYCLE_GUARD。

```powershell
Set-Location D:\AIProjects\AgentForge-AI
Test-Path Env:\AGENTFORGE_MODEL_CODER_KEY
Test-Path Env:\AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN
# 应分别只显示 True、False；不要显示变量值。
& .\scripts\start-coder-local.ps1
```

启动完成后，检查结果会包含 `migration_revision=0008_execution_permits`、两个Coder存在布尔值为true、`active_permits=0`；真实调用与Permit签发仍关闭，四槽仍停用。运行状态应以这次观察和部署报告为准。后续真实测试必须重新获得明确授权。

新增离线回归使用明确假值、数据库/HTTP测试替身；原生PowerShell `-PolicyOnly` 探针只执行启动器的非秘密策略前缀，不启动服务、不连接数据库、不读取dotenv或用户Key。原生完整假Key继承探针仍属于单独的受控服务测试，不能把策略前缀测试当成实际凭据继承证明。

2026-10-15，项目 `D:\AIProjects\AgentForge-AI`，HEAD仍为982e83e。本轮实际供应商模型调用 **0**；没有读取、打印或保存用户真实Key，没有充值或进入P6。

## 前次 Coder 配置阶段的历史状态

以下保留前次0007配置与验证记录，不代表0008部署后的当前服务状态。

| 检查项 | 结果 |
| --- | --- |
| Coder Provider | `openai_compatible` |
| Model / Base URL | `deepseek-flash` / `https://api.deepseek.com` |
| Credential Reference | `env:AGENTFORGE_MODEL_CODER_KEY`；env是引用方式，字面量 `env` 无法标识具体变量 |
| Thinking / effort | `disabled` / `high`；关闭思考时不发送reasoning_effort |
| 输出 / 槽位超时 | 64 Token / 30秒 |
| Coder状态 / 版本 | 已保存，enabled=false，version=2 |
| Planner / Researcher / Reviewer | 保持停用，未配置它们的真实模型凭据 |
| 当前API的Coder凭据变量存在 | **False** |
| 当前Worker的Coder凭据变量存在 | **False** |
| API/Worker配置一致 | True，含相同槽位版本、非秘密策略、域名/受众/价格摘要 |
| 实际全局模型主机名单 | 仅 `api.deepseek.com`，无通配符 |
| Coder凭据受众 | 仅 `AGENTFORGE_MODEL_CODER_KEY → [api.deepseek.com]` |
| 真实调用 / 出口门 | `REAL_CALLS_ENABLED=false` / `EXTERNAL_MODELS_BLOCKED=1` |
| 日费用 / 独立测试费用 | 0 USD / 0 USD |
| 日Token / 测试次数 | 8256 / 1；零费用策略仍阻止派发 |
| 自动重试 | 服务端 `REAL_MAX_RETRIES=0`；专用model_test也固定1次尝试 |
| 活动任务 / 持久化真实模型操作 | 0 / 0 |
| 数据库 | 0007_deepseek，未再迁移；模型配置更新仅修改本项目专属库 |

用户另一个PowerShell中的Key映射不会传播到Codex或现有进程。本轮没有连接那个PowerShell，也没有把该Key复制到当前会话。上面的False来自**运行中的API/Worker自身**的环境变量名称存在性观察，不是根据Codex环境猜测。True也只能证明名称存在，不能证明非空、格式有效、余额或认证成功。

## 适配器兼容处理

按本轮要求保存 `provider=openai_compatible`。精确DeepSeek端点会强制选择既有受审查DeepSeek参数档，仍校验模型ID、路径、端口、thinking、max_tokens及价格；不会使用通用适配器默认参数或绕过域名/受众校验。`provider=deepseek`仍保留。先前报告中“通用provider直接拒绝DeepSeek”的历史行为已被本轮这个受限兼容入口替代。

四角色架构和版本校验保留，原生工具调用仍拒绝，所有工具提案仍走P4 Gateway及P3独立审批/受限执行。没有改动这些安全限制。

## 官方价格登记

2026-10-15再次核对[DeepSeek官方模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)：Flash峰时缓存未命中输入 **US$0.30/百万Token**，输出 **US$1.20/百万Token**。注册键为 `openai_compatible/deepseek-flash`，价格版本 `ds-20261015-peak-v1`，currency=USD，input_upper_bound=8192、output_upper_bound=4096、token_parameter=max_tokens。

本项目使用上述峰时未命中价作为保守预算估算，不提前扣除谷价或缓存折扣，不把人民币价格当美元，不换汇或充值。64输出时的预算预留估算为US$0.00253440，不是实际扣款承诺。当前预算仍为0，没有发生收费请求，也没有实际Token/账单数据。

非秘密模板在 `config/deepseek-coder-local.json`。实际服务策略已经写入原受保护维护目录 `work/p5-live-preflight/.env`，没有模型Key；该目录仅当前Windows SID可访问且Git忽略。原根目录 `.env` 和用户凭据未修改。本轮保存前的公开槽位配置在维护目录 `coder-slots-before.json`。

## 当前环境怎样加载配置

1. 本轮运行方式为Windows本地venv中的FastAPI和独立Worker；Docker仅运行本项目PostgreSQL、Redis及可信Runner，没有启用Compose app服务。
2. `Settings`在进程中读取并缓存环境/所选dotenv，进程环境的非秘密策略优先。当前API/Worker都使用 `AGENTFORGE_SETTINGS_FILE=项目/work/p5-live-preflight/.env`。
3. 用户启动脚本强制 `MODEL_CREDENTIALS_ENV_ONLY=true`；模型凭据只允许来自新进程环境，不回退到dotenv。启动和状态检查只检查变量名称存在性，不做凭据解析或认证。
4. 本机子进程原生继承调用终端环境；另一个终端设置变量不会更新旧服务。2026-10-16 起由共享生命周期管理器创建或复用受保护实例，配置/身份不符拒绝，不静默替换。现行规则见 LOCAL_LIFECYCLE_GUARD。
5. Compose的 `environment:` 从**调用Compose的进程**及其选定dotenv进行插值，仅传入显式映射的变量；不会获取其他PowerShell的变量。已有容器restart不会刷新创建时环境，必须受控recreate才会变化。本轮只核对Compose映射，未把Key放入容器、构建参数或镜像。无需为此切换到Compose app部署。

## 在已持有Key的那个PowerShell中执行

影响：无冲突时创建本项目受保护 API/Worker，已健康且配置一致时只复用；未登记旧实例或不匹配实例会拒绝。脚本先检查0008、无活动任务/Permit、四槽停用和零费用门禁，不迁移、清空或重置数据库。前端、PostgreSQL、Redis、Runner不重启；前端不会从该PowerShell新继承Key。

仅在**已经完成Key映射的同一个PowerShell**执行以下命令；不需要再次粘贴Key：

```powershell
Set-Location D:\AIProjects\AgentForge-AI
Test-Path Env:\AGENTFORGE_MODEL_CODER_KEY
# 上一行应只显示 True；不要显示变量值。
& .\scripts\start-coder-local.ps1
```

专用脚本会：

- 只检查Coder变量名存在；若其他三个角色的模型变量也存在，拒绝启动，让用户选择仅含预期Coder凭据的终端；不会删除或复制那些变量。
- 重新固定零费用开关、出口阻断、0重试、8256日Token和1次测试上限；从非秘密JSON登记价格，并固定精确主机和Coder受众，避免继承旧的非秘密策略覆盖准备结果。
- 显式关闭Permit签发并固定Worker deny；有独立签发凭据的终端会在任何重启前被拒绝。
- 使用原生进程继承启动API与Worker，不访问Coder变量值、不拼入参数、不写dotenv、日志或构建参数，不新建Agent任务。
- 调用本机健康/受认证的runtime-status/槽位接口，比较两个进程的配置摘要、槽位版本、预算、价格摘要和凭据存在布尔值。

预计输出含 `api_coder_credential_present=true`、`worker_coder_credential_present=true`、`configuration_consistent=true`，但真实开关仍false、两项预算0、Coder仍停用。若False、Worker不可用或摘要不同，保持收费开关关闭，先核对启动结果，不能把“配置保存成功”当成继承成功。

随后可在同一PowerShell重复只读检查：

```powershell
& .\.venv\Scripts\python.exe .\scripts\check-coder-local.py
```

不要用 `p5-live-preflight.py run` 执行用户的Key继承启动：那个隔离器故意丢弃全部模型凭据。不要输出完整环境、dotenv、Compose解析配置或Docker环境检查结果，它们可能包含秘密。无需系统级环境设置、执行策略修改、权限放宽或重新提供Key。

仅停止这两个本地服务时，可运行：

```powershell
& .\scripts\stop-coder-local.ps1
```

独立人工停止要求在交互终端确认本次 UUID 范围及短时一次性 challenge；没有静默跳过参数。停止后保护记录仍保留，普通维护/测试不能接管。不要手工删除 work/lifecycle 状态。当前修复验证见 LOCAL_LIFECYCLE_TEST_REPORT；以下是2026-10-15的历史证据。

## 历史验证和发现

- 无真实凭据/真实网络的单元与HTTP：**260/260**，0跳过。
- 本机PG/Redis + 明确Provider Stub的P5/依赖/状态集成：**34/34**，0跳过，含Coder工具经独立审批后的P3真实受限Docker回归；没有启动真实供应商Agent任务。
- TypeScript及Vite构建通过；隔离全假后端浏览器 **1/1**，包含Coder openai_compatible别名、thinking disabled、完整env引用及停用状态保存。
- 用**明确假变量**执行原生PowerShell启动继承验证：API/Worker均True；随后替换为无模型凭据的维护进程，当前均False。证据 `work/p5-live-preflight/coder-inheritance-proof.json` 仅有布尔值和0外部请求声明，不含变量值。
- 已修复Windows PowerShell读取PID JSON数组导致复用旧API的启动问题。首次验证返回404时没有算作成功；修复后核验了新接口和两个新进程的一致性，并确保前端登记保留。
- Stub集成初次因运行白名单已收紧到DeepSeek而拒绝其测试专用api.openai.com地址（29失败、4通过）；将**测试租户自身**的Stub白名单和重试策略显式化后34项通过，没有放宽实际运行白名单。
- 原P3/P4完整安全回归及14项真实后端浏览器的上轮结果见前置验收报告；本轮没有重跑全部完整套件，不把历史数量冒充本轮数量。
- 最终秘密扫描两种模式均通过，覆盖210个工作文件、暂存区、bundle及日志/记录；没有读取真实模型Key做值比对。扫描器最初把公开日Token上限8256当成秘密，已将认证Token字段判断收紧至`_TOKEN`后缀，仍保留密码、模型凭据、URL及常见编码/Key格式检测。未通过的初次扫描不算成功。

证据：`work/p5-live-offline.xml`、`work/p5-live-coder-integration.xml`、`work/p5-live-browser-offline.json`、`work/p5-live-preflight/coder-state.json`。只读Git差异、逐个新文件及秘密扫描在本轮交付前复核；不暂存或提交，不修改.git权限。

## 第一次收费测试前置结论

**仍不具备立即执行收费测试的全部条件。** 非秘密槽位、参数、精确许可、价格和API/Worker一致性已就绪；真实Key尚未由用户终端传递到当前运行服务，也尚未认证。Coder保持停用、全局开关false、预算0、出口阻断、重试0，均为本轮要求的安全状态。

用户完成上述启动后，只能证明变量名继承；启用Coder、打开真实调用/出口门及批准一次收费额度仍需下一轮单独授权。本轮不执行这些动作，不运行test-real-models.py，不自动追加次数或充值。完成后暂停，不进入P6。
