# S3-B1 部署准备、安全阻塞修复与离线验收

日期：2026-10-18，Asia/Shanghai。项目：D:\AIProjects\AgentForge-AI。

结论：**LOCAL_OFFLINE_PASS / DEPLOYMENT_BLOCKED**。本轮完成项目内冻结门禁、迁移兼容修复、历史只读对账及隔离验证。没有接管/启停主API、Worker、Runner，没有应用主库0009/0010，没有真实Sandbox执行或模型请求。**运行中的旧Runner不包含新门禁，不能证明全部已部署派发路径受冻结保护，因此实际维护升级继续BLOCKED。** 本报告不授权S3-B2或P6。

## 1. 基线与成果保护

HEAD=982e83ef32b7d274e820d59ee63d6fb76bd8979e，开始索引空、62个已跟踪修改、95个未跟踪文件。280个Git候选源码/文档保存到work/maint-s3b1/20261018/source-baseline，记录SHA-256；未复制主dotenv、真实Key、Issuer或数据库备份。P5-LIVE、S1、S2、S3-A、B0现有成果保留，没有reset/clean/add/commit/push。

本轮增量相对未提交基线保存为source-changes.json与b1-review.patch，不把包含多阶段改动的git diff HEAD误称B1独立补丁。新增源码与已存在未跟踪文件也单独审阅，不只检查tracked diff。收尾Git、凭据格式扫描和主资源核对见第8节。

## 2. 实际代码变更

| 路径 | 修改与原因 |
| --- | --- |
| backend/app/domain/sandbox_maintenance.py | 独立持久化状态、维护身份、单次解除授权、有限审计4表 |
| backend/app/services/sandbox_maintenance.py | 默认拒绝、SHARE/UPDATE事务协调、短派发窗口屏障、DRAINING/FROZEN、两身份proof及epoch/目标绑定的原子解除、拒绝审计 |
| backend/migrations/versions/0010_sandbox_maintenance.py | 独立增量迁移；缺状态默认拒绝；不种入OPEN，不修改0008/0009；有控制历史时拒绝降级 |
| backend/app/services/sandbox.py | 新建和批准恢复在业务写入前检查；取消/拒绝保留原独立安全流程 |
| backend/app/workers/engine.py | 冻结时不发布/认领/恢复Sandbox；重复消息无权限；认领后冻结的未派发任务安全延迟；UNKNOWN不变更为普通失败 |
| backend/app/services/orchestration/sandbox_graph.py | 实际LangGraph审批检查及Runner HTTP POST的短派发窗口 |
| backend/app/sandbox/engine.py、ownership.py、driver.py | Runner启动意图/归属/逐动作检查；create/start/sendall外部边界持有共享屏障，冻结排空不能越过已准入窗口；保留精确归属清理 |
| backend/app/api/v1/sandbox.py、sandbox/main.py | 只读maintenance状态与available=False的安全展示；没有解除/签发控制HTTP路由 |
| backend/app/sandbox/retirement.py | 无Docker动作的离线退场清单评估；即使观测满足也不返回实际退场或部署授权 |
| backend/app/services/execution_permits.py | 修复只接受0008的迁移兼容缺口；仅允许审查过8/9/10并核验0008约束、触发器、唯一索引；原策略/权限/调用数/预算算法不改 |
| backend/app/repositories/connections.py、migrations/env.py | 0010结构健康检查；可信进程内既有connection支持独立schema的真实迁移/恢复测试，不提供环境或公共URL旁路 |
| tests/fixtures/sandbox_database.py | 先验证专属数据栈/端点/测试上下文，每例独立schema、实际迁移；不删UNKNOWN来重新开放门禁 |
| tests/integration/test_sandbox_maintenance_db.py | 33项真实PG/Redis冻结、授权、HTTP/SDK Stub边界与Permit结构缺失拒绝 |
| tests/integration/test_sandbox_migrations_b1.py | 合成旧记录的实际备份、restore、0009/0010一致性和非空降级拒绝 |
| tests/integration/test_sandbox_ownership_db.py | 既有39项改用每例独立迁移schema及真实维护授权；避免前例UNKNOWN污染后例；保留其审计，不绕过生产门禁 |
| tests/unit/test_sandbox_maintenance.py、test_sandbox_runner_policy.py | 24项新离线故障/退场Stub测试；原P3 policy-only夹具明确提供空窗口替身，不冒充数据库或生产隔离证明 |
| 本报告、SANDBOX_MAINTENANCE_FREEZE.md、SANDBOX_HISTORY_RECONCILIATION.md、兼容/状态/原部署计划 | 机制、15条记录、部署阻塞与最新迁移范围 |

完整门禁状态、并发语义及覆盖矩阵见[SANDBOX_MAINTENANCE_FREEZE](SANDBOX_MAINTENANCE_FREEZE.md)。P3 policy.py、P4 Tool Gateway/审批、permit_authority、0008/0009迁移、Compose、DeepSeek冻结配置、生命周期入口和原S1测试保护未修改；依据基线源码摘要检查。

## 3. 冻结安全性与并发结果

初始化为FROZEN；freeze提交DRAINING后新准入拒绝，排他屏障取得后才封存FROZEN。它只证明短派发窗口排空，不证明旧Runner/运行容器已退出。FOR SHARE准入与FOR UPDATE冻结竞争；HTTP和Docker有界动作持共享advisory事务锁，事务不覆盖完整执行/输出流。

实际数据库竞争测试观察到：准入持锁时冻结等待；已获准IO窗口存续时freeze返回DRAINING，新窗口被拒；窗口退出后seal才返回FROZEN。并发消费同一解除授权只有一个成功。这里是**真实PostgreSQL会话竞争**，IO由事件/虚拟Transport控制；未执行真实Docker create/start/kill。

普通API没有解除/签发路由；operator与独立approver通过不同随机proof认证，grant绑定deployment、epoch、指定操作员、Runner/generation、daemon和兼容证据，有效期上限60秒。过期、重放、错误角色、伪造proof、撤销、旧epoch、目标变更拒绝；环境标志和Redis OPEN键不供给权限。

运行/取消/UNKNOWN三种记录在冻结恢复扫描后保持状态和预留。拥有精确合法归属的清理仍可执行，原审批撤销/预算检查不被放宽；缺状态/数据库失败拒绝新派发。解除拒绝遗留needs_reconciliation和未确认/新版未知意图，当前历史阻塞不被忽略。没有模型Key/Issuer参与维护身份。

可信部署控制面、实际身份交付和旧清理器退出证明尚未交付为可运行主维护工具；内部原语不等于普通PowerShell可获得权限。数据库/daemon管理员属于可信边界，未声称防御恶意管理员或外部exactly-once。

## 4. 实际测试结果与层次

最终证据：work/maint-s3b1/20261018/unit.xml、integration.xml、test-summary.json。

| 层次 | 实际结果 | 不能替代的项目 |
| --- | --- | --- |
| 单元/HTTP完整离线批次 | **800通过，0失败/错误/跳过**；含24项新增故障/退场用例及P3/P4/Permit回归 | 排除原16项独立生命周期manager/native批次；本轮不称其复测通过；使用原生IPC及明确Stub |
| 完整非Sandbox集成 | **184通过，17项真实Sandbox排除**；245.68秒，0失败/错误 | 真实PG/Redis、受控MCP子进程、实际OS Permit Worker崩溃恢复；供应商是虚拟Transport，Docker是Stub |
| 新增冻结专项 | 最终集成包含 **33通过** | 包含真实DB并发、Redis重复消息、API/Agent/HTTP节点、三个Docker动作授权及精确清理Stub、非法解除/UNKNOWN/迁移结构故障 |
| 既有归属专项 | 最终集成包含 **39通过**；单独批次也通过 | 未运行真实Runner进程/Engine隔离 |
| 新迁移备份恢复 | 最终集成包含 **1通过**，用合成数据实际restore | 不是主数据库新备份或主库恢复验收 |
| 去重 | **984个不同Python用例最终通过**（800＋184）；新增58项=24＋33＋1 | 不累加20项首批、39项重跑或重复XML |
| 真实Sandbox/浏览器 | **17＋2继续BLOCKED，0执行** | 本轮没有浏览器运行；没有真实执行容器、Runner部署或模型连通性测试 |

保留的中间结果：

- 最初受限Windows执行边界在首个异步用例未继续推进，终止该测试会话；随后保留offline插件在原生IPC可用边界完整重跑。未据此启动主服务或关闭网络保护。
- 首批冻结20、归属39及单元/HTTP795通过；随后新增5项退场输入检查和后续数据库/入口故障用例，最终以上述XML为准。
- 第一次合并集成 **156通过、25失败、17排除**。复用测试栈已是0009，PermitService严格等于0008而拒绝签发，暴露实际迁移兼容缺口；失败XML/log保留为integration-first。修复有限版本＋关键结构验证，没有修改签发策略、旧Permit账本或迁移0008。
- 为最终复核创建第二个全新数据栈，保留第一栈记录而不删除UNKNOWN来复测；最终184通过。另加真实数据库用例确认禁用触发器、缺CHECK或未审阅版本仍拒绝。
- 有既有Alembic path_separator弃用提示，未为消除提示修改其他配置。

## 5. 历史记录对账

已只读检查全部334条元数据，事件计数与task_event_seq均相等；精确查询246个历史CID，在当前daemon全部明确不存在、无其他错误。主库仍0008，无新版归属账本；14条needs_reconciliation和1条旧failed/not_created但缺CID的启动意图均保留。**容器缺席不能确定历史结果。**

每条重点记录已列execution_id、task_id、原状态、CID、协议缺失、旧runner_owner、最后控制/任务事件序号与时间、Docker观察、预留及缺失证据，见[SANDBOX_HISTORY_RECONCILIATION](SANDBOX_HISTORY_RECONCILIATION.md)。未输出代码/回答正文、凭据或完整请求头；没有改写状态、删审计、补新代次归属或重发。

人工核对仍需历史daemon及Runner实际身份、create/注入/退出边界、租约/fence时序和受限控制日志。无法核实时仍UNKNOWN。新门禁会继续拒绝解除，后续保留UNKNOWN的隔离处置需要独立审阅与授权，不能临时加忽略参数。

## 6. 0009与0010准备

0009保持原字节内容：只新增三张归属表及索引，旧P3/P4/Permit无数据转换，不回填历史归属；非空历史拒绝降级。0010独立新增四张控制表，同样不迁移旧历史、初始不开放。

在专属测试PG创建独立源schema，以三条合成旧执行（含needs_reconciliation和无CID意图）及原模型槽位模拟0008数据；pg_dump custom格式→校验TOC→实际恢复到独立新数据库→逐表数据/列结构指纹比较。0009升级后原 **23张业务表** 一致，新3表/关键CHECK/FK/CID唯一约束正确；空历史降回0008再升级通过，注册后降级拒绝。0010升级后初始化FROZEN，非空控制历史降级拒绝，原UNKNOWN及所有旧表指纹保留。证据migration-restore.json、synthetic-0008.dump均在被Git排除的work目录。

主库未执行这些动作。**主库新备份/恢复演练尚未完成**；实际维护窗口需按当时数据重新备份和恢复验证，不用合成结果替代。0010也是未来部署范围，须明确批准，不能仅升0009后假定冻结可用。

## 7. 旧Runner安全退场与下次维护清单

本轮只有retirement.py纯离线策略及Stub测试，无停止/重启/恢复Runner的方法。所有观测满足也只返回offline_checklist=SATISFIED，deployment_authorized和physical_exit_proven仍False。宿主/远端控制进程、复起脚本和在途Docker动作没有靠Stub变成生产已验证。

下一窗口强依赖顺序如下；每一步均需后续明确范围授权及绑定目标的受控操作，不提供通用Force/SkipGuard：

| 步骤 | 前置/动作与影响 | 验证、失败停止与恢复 |
| --- | --- | --- |
| 1 制品与权限 | 固定HEAD增量/镜像摘要、daemon、主容器完整CID/StartedAt、主DB/卷及维护epoch；先完成有限部署控制面、proof分权交付和旧控制通道隔离开发 | 任一身份不明则不进入窗口；不根据名称或普通manifest认领 |
| 2 主入口冻结 | 另获API/Worker保护接管授权后，冻结新建/批准恢复/Agent/P4/Outbox/Worker/Runner；旧二进制不能假定理解新表 | 验证所有现存生产者/消费者及控制端点，重启亦默认拒绝；无法覆盖则BLOCKED；API/Worker可能中断需单列人工确认 |
| 3 排空与历史 | 读取运行/取消/UNKNOWN与精确资源，完成14＋1受控处置；保留审计和未知预留 | 未确认或在途动作存在则维持冻结，不清零、不重发、不按名称清理 |
| 4 新备份 | 专属主库重新证明0008并冻结写入，创建受保护备份、实际恢复副本，复核0009/0010及旧业务指纹 | 备份/恢复不一致立即停，主库不迁移；恢复覆盖主库需另行授权 |
| 5 旧清理器退出 | 独立批准主Runner中断，有限工具精确禁止本项目自动复起并停止全部旧清理器，旧测试Runner保持停用 | 实际进程Pid=0/非running、restart=no、旧连接/控制进程/请求退出、两次跨周期观测及入口冻结互证；只看日志安静不够 |
| 6 迁移与新身份 | 获准后在维护态应用明确0009＋0010，生成新注册/代次/独立proof；先无兼容放行、FROZEN默认拒绝 | 原表及P4/0008安全结构一致；身份/审计/事务未知则停；不删历史强行降级，不自动拉起旧镜像 |
| 7 新Runner与真实隔离验收 | 签署物理退出/兼容证据并受控认领唯一新Runner；先可信状态及双新版实例隔离，再另获17＋2真实验收授权 | 独立PG/Redis/端口/进程/namespace/精确CID资源证明；测试finally只处理本例确认资源，不能恢复旧Runner或批删未知容器 |
| 8 收尾停留/业务恢复 | 核对审计、未知/费用、测试资源；正式API/Worker/Sandbox恢复须再确认保护和当前凭据状态 | 任一不一致维持冻结、旧版禁用；模型false、预算0、四槽Disabled、Permit签发关闭、deny、出口blocked、重试0；不自动进入P6 |

第5/7步会中断或替换主Runner，第2/8步可能影响API/Worker，必须单独明确。PG/Redis和Docker Desktop全局配置无重启/调整计划。失败恢复保持冻结与旧清理器禁用，优先修复前进；只有空历史才可另行批准无损降级，有历史不能删除记录再回退。

17＋2执行前还缺可信Runner专项夹具（当前S1 conftest/网络guard/Playwright仍明确阻止）、真实Engine并发/进程崩溃窗口验证、主服务保护接管以及所有旧清理器退出证明。原B01–B14细表保留于[P5_LIVE_MAINT_S3B_PLAN](P5_LIVE_MAINT_S3B_PLAN.md)，其0009步骤必须按最新范围补0010。

## 8. 收尾与剩余风险

14:29 +08最终只读复核：

- 主Runner仍为f2da347b403e96ba640d806eb8924ca91e389237de7e445858bfc8bb69c445d7、镜像sha256:3e81842718ce5adf0d55a5fa82cd0f0505adf98faebdd1334c2c78e62b07ba5a，running、restart=unless-stopped，StartedAt=2026-10-18T02:59:04.010046215Z；主PG/Redis身份、镜像、启动时间与本轮起点一致，旧Runner三份源码摘要一致。没有主启停/部署。
- 主库实际0008，sandbox_ownership和sandbox_maintenance均不存在；334条白名单执行元数据与首轮完全相同，14＋1保留，246个精确CID当前全部明确不存在。CPU历史used=2338.000、reserved=0.000。真实模型操作/Permit/Enabled槽位/未发布Outbox均0；主库未写入。14:35补充只读计数确认普通活动Sandbox任务、非Sandbox真实任务均0，主Redis pending=0，协议标签容器候选0；未查询旧Runner内存active字典，数据库/资源观察不能替代完整退场证明。
- 主API仍ConnectError，本项目Python服务/测试进程候选0；API/Worker Coder Key存在状态均UNVERIFIED。运行时收费开关、重试、预算和配置一致性不能实时核验，未用历史值代替；相应冻结配置文件未改，没有打开出口、启用模型或提高预算。
- 两个数据测试栈分别为632e5de9-ac4d-4578-a2f9-8052564524c8（59474/59475）与ad270747-d979-466c-829d-971484752250（57390/57391）。全部测试结束后，先在各自OS锁下重验归属并归档5份合成测试数据库备份、校验TOC/长度/SHA-256，再按精确ID停止4个PG/Redis测试容器。**没有删除容器、网络或数据卷**；4个exited容器与2个网络保留，清单标记RECOVERY_REQUIRED，不再误报READY。受保护归档/停止审计见parked-data-stacks.json、park-actions.jsonl及retained-test-backups。此批归档只作测试历史保全；实际restore验收是第6节的合成迁移用例，不宣称5份归档均额外做过restore。
- 本轮未启动任何真实Runner、Sandbox执行容器、主API/Worker或浏览器。两个独立PG/Redis栈是无P3策略标签、无Docker socket的可信数据服务，不是Sandbox执行容器；原17＋2继续BLOCKED。没有真实模型请求、主库迁移或充值；主库未签发Permit，回归仅在隔离库使用假Issuer/虚拟Transport验证模拟Permit。
- Git仍原HEAD，索引空，**66个已跟踪修改、106个未跟踪文件**。B1增量27路径（16个既有文件合并修改、11个新增；含6份文档），原280个候选无丢失，其余264个既有文件内容摘要未变。主manifest/audit/operation.lock内容/大小/mtime均与基线一致；既有未提交改动未重置覆盖。
- git diff --check通过；独立新增文件及完整B1增量补丁另行检查，Python AST解析无错误。291个Git候选、索引、既有bundle/P5报告凭据格式扫描通过，另342个B1证据文件格式扫描无发现；没有真实.env/备份/key/pem候选，work与本地dotenv被Git排除。未读取真实Key逐值比较，扫描不保证发现所有未知秘密格式。Permit原_policy、issue、claim、commit_dispatch、execute、register_worker函数AST保持一致，兼容修改仅require_schema及相关导入。

仍未解决：旧Runner实际全局清理器仍在运行；新冻结覆盖的是待部署源码，尚非全部运行路径；14＋1历史证据不完整；主API/Worker保护接管及凭据实时验证未完成；可信部署/分权交付/兼容签署与真实Runner隔离夹具尚缺；主库当次新备份/恢复未做；真实Engine/进程崩溃/17＋2未验收。4个停止测试容器与2个网络需未来单独授权后按精确归属处理，不能运行通用清理。

因此目前可审阅项目内实现并规划后续准备，**不具备直接执行主Runner维护升级或解除主准入的条件**。保持BLOCKED，完成后暂停，等待下一次明确授权，不自动进入S3-B2/P6，也不复用旧收费授权。

## 9. 分阶段Git提交建议（不执行）

共同文件包含多阶段未提交内容，先组织依赖，再分块审阅，不能将整个工作区当一个B1补丁。

| 顺序 | 功能代码 | 数据库迁移 | 测试 | 文档 |
| --- | --- | --- | --- | --- |
| P5-LIVE DeepSeek准备 | providers/deepseek、OpenAI参数/usage/价格、Model Center | 0007 | DeepSeek/adapter/runtime | MODEL_INTEGRATION、DeepSeek与首次验收 |
| P5-LIVE-SAFETY | Permit authority/service/API、Worker单次门禁、审计/预算 | 0008 | Permit/HTTP/并发/恢复 | Permit设计、测试与部署报告 |
| S1 | 生命周期v2、Windows IPC、统一入口、独立测试栈 | 无 | 生命周期/封版/隔离fixture | Lifecycle、MAINTENANCE_ENTRIES、S1 |
| S2 | 本阶段为只读发现及设计 | 无 | 区分历史与未执行 | S2、Sandbox隔离设计 |
| S3-A | Runner归属/精确ID动作边界 | 0009 | Ownership/P3适配 | 协议、兼容、S3-A |
| S3-B0 | 无功能部署 | 无 | 仅只读/静态审查 | B0计划与状态增量 |
| S3-B1 | Freeze服务/覆盖边界、退场纯策略、Permit兼容结构核验 | 0010，与功能同一可审阅变更集或严格依赖提交 | 新24＋33＋1；旧39独立schema适配 | 本报告、Freeze、历史对账、兼容/计划/状态 |

每阶段先核对git status --short、git diff --check与未跟踪文件；已有共享文件用git add -p --逐块选择，新增文件仅在审阅后git add --明确路径。再次git diff --cached --check与git diff --cached后由用户手动commit。本轮不运行这些写Git操作、不修改.git权限。

B1建议标题：feat: add fail-closed Sandbox maintenance admission and guarded thaw。报告/测试记录可作后续独立docs提交；0010不能早于0009依赖部署，空缺状态会使Sandbox默认拒绝。work内备份/测试凭据/日志不可纳入提交。
