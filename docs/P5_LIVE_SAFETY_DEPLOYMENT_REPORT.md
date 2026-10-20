# P5-LIVE-SAFETY 部署与最终预检

日期：2026-10-15，Asia/Shanghai。项目 `D:\AIProjects\AgentForge-AI`，HEAD `982e83ef32b7d274e820d59ee63d6fb76bd8979e`。本轮仅专属开发环境部署、无费用配置及离线验证；没有真实模型调用，不延续旧收费授权，不进入 P6。

## 用户反馈重载后的最终只读复核

2026-10-15 **23:05 +08:00**：用户反馈已运行启动脚本并通过，但实时API/Worker均仍报告Coder凭据存在 **False**，因此结论仍为 **BLOCKED_CREDENTIAL_RELOAD，尚不能标记READY_FOR_APPROVAL**。API PID8048启动于22:52:59，Worker PID19680启动于22:53:07，仍是此前维护启动的进程。本地 `coder-state.json` 中True/True的记录最后写于21:20:51，且没有0008版本字段，是历史证据，不能证明当前进程已加载Key。

| 最终要求 | 实际核验 |
| --- | --- |
| API Credential Present | False，来自当前运行进程的变量名称存在性观察 |
| Worker Credential Present | False，来自新鲜Worker心跳，非Codex进程猜测 |
| API/Worker配置一致 | True，槽位版本、策略和完整公开配置摘要一致 |
| Migration Version | 0008_execution_permits；20张原业务表指纹仍不变 |
| Permit Isolation Status | 当前源码复核通过；认领/身份/绑定/预算/普通Chat及其它Worker/角色拒绝有既有434项回归证据，本轮未重跑测试或签发Permit |
| Active Real Tasks / 待恢复任务 | 0；全部非终态任务0、未发布Outbox0、Redis pending/lag均0 |
| External Calls | 本轮0；主库真实ModelOperation0，Permit及审计表为空 |
| Safety Gate Status | 真实/Permit开关false、四槽Disabled、日/测试预算0、出口阻断、重试0，Worker=deny |
| Git Status | HEAD未变，41项tracked修改、45个新增文件，暂存区为空；差异/新增文件/凭据格式扫描通过 |

Coder版本2，openai_compatible/deepseek-flash，https://api.deepseek.com，env:AGENTFORGE_MODEL_CODER_KEY，thinking disabled；本地构造请求不含冲突reasoning_effort或工具。精确主机和凭据受众均仅api.deepseek.com。登记价格与模板及两端价格摘要一致：USD输入0.30/百万、输出1.20/百万，版本ds-20261015-peak-v1；8192+64的预留重算为USD0.00253440。本轮没有做价格变更、供应商认证/健康探测或实际预留。

本轮只读查询服务/数据库/Redis/容器，更新非秘密证据与文档；没有重启进程、改写凭据或配置Issuer Token。秘密检查采用不读取dotenv/已知Key值的格式扫描；它不能替代任意格式秘密的值比对。当前Git快照已刷新，不能把该快照当作独立的上轮源码哈希证明。此前434项及15+1浏览器结果属于上一轮实测，本轮是源码与证据复核。

需要用户在实际持Key的PowerShell成功重启本项目API/Worker后，再观察两端True。即使随后满足READY_FOR_APPROVAL，也只表示可以申请全新收费授权；旧授权不复用，真实开关不会自动开启。

## 主库迁移

已于 **22:45:08 +08:00** 将主库从 `0007_deepseek` 升级到 `0008_execution_permits`。执行前核验 Compose 项目 `agentforge-p1`、项目根目录、数据库 `agentforge`、本机端口15432和连接角色agentforge。API/Worker停止派发，空闲主Runner暂停，活动任务、未发布Outbox、真实模型操作均为0。

新备份：`work/p5-live-preflight/permit-deployment/before-0008-20261015144429.dump`，1,048,659字节，SHA256：

`3684b1ebf6301b0ebb94214740fba1a03346c5610210c4688e023d4ebca11ca8`

先验证pg_restore目录，再恢复到本项目唯一命名临时克隆库，比较原21表（含版本表）的列及全量行指纹，演练0008升级/空历史降级，确认原数据不变，最后移除本次临时克隆。备份保留在受保护且Git忽略的work目录；没有覆盖主库或其他项目数据库。

主库迁移后20张原业务表的结构与行指纹完全一致，仅版本表变化。新增 `trusted_model_workers`、`execution_permits`、`permit_audit` 三表，均为空。固定角色/模型/凭据/额度检查约束、单次认领计数、活动Permit唯一索引、审计序号唯一索引及单调状态触发器通过检查；Alembic metadata无差异，PostgreSQL/Redis正常。若已有Permit/审计历史，0008降级会主动拒绝，不能删除未知费用记录强行回退。

部署脚本 `scripts/deploy-permit-database.py` 将备份、应用及只读验证分开，要求固定项目/数据库、关闭费用与出口、停止派发、已验证备份及原数据一致。拒绝使用会取消安全断言的Python优化模式。最终服务核验使用 `scripts/verify-permit-deployment.py`。

## 凭据继承与配置

`scripts/start-coder-local.ps1` 已适配0008：显式设置 Permit签发false、Worker模式deny、真实总开关false、日/测试预算0、出口阻断、重试0。仅探测Coder变量名称；如果存在独立签发凭据或其他角色Key变量，在重启之前拒绝。`check-coder-local.py` 要求0008、四槽停用、无活动任务/Permit和真实操作、精确域名/受众、正确价格与版本；重启后的API与Worker必须分别报告True。

凭据恢复需在用户原本已持有Key的PowerShell执行；Codex维护环境不具有该Key，无法从另一进程自动继承。操作仅替换本项目API/Worker，API短暂不可用，前端及数据库不重启。脚本不读取/输出/写入Key值，也不发起供应商请求：

```powershell
Set-Location D:\AIProjects\AgentForge-AI
Test-Path Env:\AGENTFORGE_MODEL_CODER_KEY
# 仅上一行返回True时继续；不要显示变量值。
& .\scripts\start-coder-local.ps1
```

True只说明环境变量名称存在，不证明密钥有效、余额或认证成功。任何收费验证都必须另行取得明确授权。

## 本轮验证与最终状态

**部署与离线验收PASS；最终凭据前置验收BLOCKED，等待用户PowerShell重载。** 最后服务观察：2026-10-15 22:55:49 +08:00。API Coder Credential Present=False，Worker=False。不得把False/False的配置一致当作凭据恢复成功。

| 检查 | 本轮结果 |
| --- | --- |
| 全量Python | **434通过、0失败、0错误、0跳过**，249.84秒；`work/p5-all.xml`，开始22:47:08 +08:00 |
| Permit专项 | **25项**包含在434中；真实PostgreSQL/Redis，Provider Stub/本地虚拟HTTP |
| 全部真实后端浏览器 | **15通过**，43.4秒；`work/p5-e2e.json` |
| 独立Mock浏览器 | **1通过**，5.6秒；无供应商网络 |
| 前端类型与构建 | TypeScript/Vite通过 |
| 主库数据一致性 | 20张原业务表结构及行指纹不变；新增三表为空，迁移0008与metadata一致 |
| PostgreSQL/Redis/API/Worker/前端/Runner | 就绪，API/Worker配置摘要及槽位版本一致；仅一个有效Worker心跳 |
| 待派发/恢复 | 非终态任务0、未发布Outbox0、Redis pending/lag均0、主库Permit0 |
| 真实模型 | 实际外部请求0，主库真实ModelOperation0；无收费或未知结算记录产生 |
| 泄露/Git | 凭据格式及已知服务秘密扫描通过；不读取真实模型Key作值比较；diff --check通过，45个新增文件单独检查 |

全量比此前421项增加13项启动/凭据检查用例。只有一条既有Alembic `path_separator` 弃用提示，没有测试失败。子代理另一次辅助离线运行已中断，不计验收；以本轮完整434项结果为准。

并发测试实际观察两个独立PostgreSQL backend PID550、551同时等待锁，只有一个认领、一个ModelOperation和一次USD0.00253440预留。真实OS崩溃测试：CLAIMED阶段PID20288→23364，恢复ABORTED，dispatch=0；虚拟HTTP派发边界PID22812→5480，恢复UNKNOWN，dispatch上界1、USD0.00253440预留保留。两者都不重发，真实外部请求0。证据：`work/p5-live-permit-concurrency.json`、`work/permit-process-tests/*/evidence.json`。

普通Chat/其它角色、未绑定Worker、伪造身份、重复Redis消息、已消费/撤销/过期Permit、版本/请求指纹变化、入口绕过、并发预算、HTTP边界失败、未知结果及状态重置拒绝均由回归覆盖。P3/P4审批、工具权限与受限执行回归通过，核心生产安全代码没有差异。回归确实在隔离栈执行了获准的本地P3/P4测试；没有把这些测试冒充模型工具调用，主库业务指纹保持不变。

按已登记价格重新计算8192输入+64输出预留为USD0.00253440，Token总预留8256；这是Stub中的应用估算验证。主库没有签发Permit或创建真实预留。当前实际日预算和测试预算仍为0。

最终关闭状态：REAL_CALLS_ENABLED=false、Permit签发false、Worker模式deny、独立签发凭据未配置、四槽Disabled、日/测试预算0、出口阻断开启、自动重试0；无活动真实任务、无执行容器、无充值操作。隔离测试栈已停止，卷和证据保留，主API18100/前端15173/Worker/Runner恢复。Coder版本2及精确域名/受众保持不变。

恢复凭据后只运行 `scripts/verify-permit-deployment.py --require-credential` 作本地只读核验，并记录新的True/False状态；未经该观察，不能宣布本次最终预检全部PASS。即使凭据为True，真实收费验收仍未执行，也需全新授权。

## Git交付

未重置、覆盖、暂存或提交现有改动。工作区保留此前DeepSeek兼容准备和Permit修复；共享文件有交叉变更，建议作为一项独立P5-LIVE交付审查，避免只提交迁移而遗漏门禁。用户可在Windows CMD手动执行：

```bat
cd /d D:\AIProjects\AgentForge-AI
git diff --check
git status --short
git add .env.example compose.yaml backend config docs frontend scripts tests
git diff --cached --check
git diff --cached --stat
git diff --cached
git commit -m "feat(p5-live): enforce single-use permits and deploy schema 0008"
```

不要添加`.env`、work、数据库备份或真实凭据。新增文件单独检查清单与完整差异保存在 `work/p5-live-untracked-review.json`、`work/p5-live-tracked.diff`、`work/p5-live-untracked.diff`。

## 剩余边界

本地可信进程和数据库owner仍属信任边界。UNKNOWN保留预留与审计，不自动重发或结算；真实DeepSeek DNS/TLS、Key有效性、SSE用量和账单未验证。应用侧预算仅为估算限制，不是供应商账单绝对保证。独立签发权限未配置、所有收费门禁保持关闭，不能据本报告直接发起请求。
