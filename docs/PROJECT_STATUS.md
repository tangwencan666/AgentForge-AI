# AgentForge AI 项目状态

## 2026-10-19 G5 文档归档修正：运行验收仍阻塞

G1 `f9fdd3e`（42 文件）、G2 `c69ef53`（5 文件）、G3 `41d2257`（50 文件）已本地提交；G4 `e9ced78`（57 文件）已按 **Archive-only** 方式提交。G5 仍为精确 32 文档的修正与归档准备，未暂存或提交。Git 归档完成不代表 CI 全绿、运行安全验收通过或生产可部署；**RUNTIME_ACCEPTANCE：RUNTIME_BLOCKED**。

2026-10-18 G4 审查实际通过 852 项离线单元/HTTP，随后首项 `fake_coder_protected_start` 失败，原始错误为 `CONTROL_CHANNEL_UNVERIFIED`，静态位置 `scripts/lifecycle_v2.py:167`；其余 15 个生命周期场景未执行。原始 IPC cause 未取得，尚未完成可信诊断，不能改记为 PASS。默认 pytest 和 `scripts/test-offline.py` 仍包含该失败场景，本轮未重跑、跳过或修改测试。

| 运行前提 | 已有证据与未完成项 |
|---|---|
| B1 | PARTIAL：持久化认领、OS 锁和崩溃 UNKNOWN 的 Mock 验证已完成；真实人工签发、可信存储和固定进程派发尚未接通 |
| B2 | PARTIAL：用户报告的普通 PowerShell Token/TCP 只读核验成功仅覆盖当次会话；未来执行主体及其即时权限未验证，底层策略原因 UNKNOWN |
| B3 | PARTIAL：既有 ACL 的广泛写入/父目录替换风险未处置；同用户恶意进程不能靠当前用户 FullControl 隔离，未修改 ACL |
| B4 | FIXED_OFFLINE_ONLY：stderr 增量内容与脱敏已有构造验证，未取得真实 IPC 动态验收证据 |

2026-10-19 独立诊断工具的 49 项 Mock 专项通过不是原生命周期故障已修复的证明。真实 Sandbox 17 项集成＋2 项浏览器仍 **BLOCKED、未执行**，旧 Runner 的宽泛发现/清理和交接风险未解除。DeepSeek 真实 API 验收未完成，旧收费授权不延续。

本轮仅检查文件与 Git，没有核验主 API/Worker、数据库、Redis、Docker、凭据存在性、模型槽位、Permit 或预算的实时状态；这些当前值均为 **UNKNOWN / 未验证**，不得沿用历史 True/True、Protected 或零值为当前运行证明。最近主库版本证据为 S3-B3 时的 `0008_execution_permits`；0009/0010 已作为 G2 迁移代码提交、仅完成隔离测试库验证，未据此推断主库已部署。当前 P3 入口仍以 `S1_RUNNER_ISOLATION_BLOCKED` 拒绝，共享 Engine 不得启动第二个真实测试 Runner；后续运维、迁移、真实测试和收费调用分别需要独立批准。

本地 ignored 证据（不会随 G5 自动进入 Git）：`work/g4-git-delivery/20261018T124257Z/G4_SECURITY_TEST_REPORT.md` 及 `native.xml`；`work/g4-b2-evidence-archive/20261019-1bd4dba3-2055-43e7-93ea-f64bf8c8060a/G4_B2_ARCHIVE_REPORT.md`；`work/g4-b1-b3-closeout/20261019-98c1605f-2544-40ca-868a-bc65250cab2e/G4_B1_B3_CLOSEOUT_REPORT.md`；`work/g4-archive-only/20261019-0b00503c-981d-437c-b4bc-0e534d0625ff/G4_ARCHIVE_REVIEW_REPORT.md`。上述失败和限制在此保留必要结论，详细记录原样保留。

README 是 2026-10-15 的 P5 快照，不属于 G5 32 文件；其中 0006 等旧状态不能代替本节。当前源码和操作限制另见 [GETTING_STARTED](GETTING_STARTED.md)、[MODEL_INTEGRATION](MODEL_INTEGRATION.md) 和 [维护 Runbook](S3B2_MAINTENANCE_RUNBOOK.md)。以下各节均为原日期的历史记录，其成功、运行观察及“当前/本轮”字样仅指对应时点。

2026-10-18 P5-LIVE-MAINT-S3B3：**项目内修复/隔离验收完成，DEPLOYMENT_BLOCKED，尚未READY_FOR_MAINTENANCE**。新增离线有限退场内核（单次目标/代次/Peer授权、真实OS锁、SQLite审计、意图先提交、崩溃不重发，无生产Docker/HTTP入口）；数据库事实派生历史禁止重放接入Worker发布/认领/恢复/执行/迟到回调及Runner/批准/归属，新增无CID意图阻止thaw，原14＋1不改。正常launch先issue归属并同事务提交；迁移文件未改。

本轮最终843单元/HTTP通过；整批非Sandbox集成191通过/1新增夹具失败，修正为running租约后7项专项全过，最终去重1035个不同Python用例分批通过、新增51，失败证据保留，不称整批一次全绿。专属PG实际合成备份/restore、0009/0010、DDL锁失败回滚/恢复通过。17＋2未执行，两个本地context实为同一daemon，不能启动第二个共享Engine Runner。新专属PG/Redis两容器及网络保留运行以保存测试历史，另有3份最终测试归档仅TOC检查，无数据/容器/网络删除；未恢复旧测试栈。

主库仍0008、旧主Runner未启停、API无法实时核验，凭据与预算/出口运行时UNVERIFIED，未读取Key/Issuer或改冻结配置；四槽Disabled、真实操作/Permit0的只读事实保留。实际部署还需可信生产适配/交付和旧入口隔离、历史人工签认、主库新备份与独立恢复、独立daemon及有限真实夹具。全部责任/最小动作/标准见[P5_LIVE_MAINT_S3B3_REPORT](P5_LIVE_MAINT_S3B3_REPORT.md)，操作卡更新在[S3B2_MAINTENANCE_RUNBOOK](S3B2_MAINTENANCE_RUNBOOK.md)。本轮不暂存/提交、不接管主服务、不调用真实模型、不进入P6。以下为历史记录。

2026-10-18 P5-LIVE-MAINT-S3B2准备：**PREPARATION_COMPLETE / DEPLOYMENT_BLOCKED**。只读复核HEAD982e83ef、起始66项tracked修改/106个untracked和空索引，291个源码候选建立排除凭据的哈希副本，未覆盖旧成果。新增逐步维护Runbook、172项逐文件五批Git计划及本轮报告；仅改文档。24项纯离线冻结/退场复测通过；984项为重新解析确认的B1历史结果，未重跑完整回归；17＋2真实Sandbox仍BLOCKED、0执行。

14:45–14:47 +08：旧主Runner CID/镜像/StartedAt不变，running、restart=unless-stopped；主库0008、23张业务表，0009/0010七表不存在。334条历史元数据与B1一致，14＋1保留，246历史CID当前明确缺席但结果不改写。四槽Disabled、非Mock模型操作/Permit0；API仍ConnectError、项目服务Python候选0，API/Worker凭据存在性及运行时配置均UNVERIFIED，未沿用历史True/True。4个已停止测试数据容器和2个网络原状保留。本轮服务启停/接管、主库写入、Docker创建/停止/删除、真实模型请求均0，未暂存/提交或进入P6。

实际部署仍缺：可信有限控制器/退场采集/proof交付、0008旧入口隔离及主version1保护交接、保留UNKNOWN处置、主库新备份/独立恢复、实际Runner隔离夹具。Runbook R00–R15分别标明操作/影响/验证/失败恢复/人工授权；禁止自动restore旧清理器或新旧蓝绿并行。详见[P5_LIVE_MAINT_S3B2_REPORT](P5_LIVE_MAINT_S3B2_REPORT.md)、[S3B2_MAINTENANCE_RUNBOOK](S3B2_MAINTENANCE_RUNBOOK.md)、[S3B2_GIT_DELIVERY_PLAN](S3B2_GIT_DELIVERY_PLAN.md)。以下为历史记录。

2026-10-18 P5-LIVE-MAINT-S3B1：**项目内准备与离线验收完成 / 实际部署BLOCKED**。新增独立0010 Sandbox Maintenance Freeze：持久化DRAINING/FROZEN、真实PG事务/短派发窗口屏障、operator＋独立approver proof、目标代次/epoch绑定单次解除、UNKNOWN保留；已接入API/Agent/P4交接、Worker发布/认领/恢复、HTTP派发及Runner/Docker动作边界，尚未部署。修复Permit仅接受0008的兼容阻塞，明确允许经结构核验的8/9/10，原权限/预算/单次规则保留。最终800单元/HTTP＋184非Sandbox集成，共984个不同Python用例通过（含新增24＋33＋1）；原16项独立生命周期批次及浏览器未重跑，真实17＋2仍BLOCKED。合成旧数据在独立库实际备份/恢复、0009/0010迁移后23张原业务表一致，非空历史拒绝降级；不代表主库新备份验收。

14:29 +08只读复核：主库仍0008、0009/0010表不存在；334条执行元数据、14条待对账＋1条无CID意图、主容器身份/镜像/启动时间与本轮起点一致。246个历史CID当前全部明确不存在，未将未知改为成功/失败或补归属。主API仍ConnectError，项目Python服务候选0，API/Worker凭据存在性UNVERIFIED；四槽Disabled、真实模型操作/Permit0，CPU历史used2338/reserved0。主运行时开关/配置一致性不可实时核验，未沿用历史True/True。两个专属测试数据栈已归档5份测试数据库备份，4个PG/Redis容器仅按确认归属停止，容器与2个网络保留、未删除；测试清单标记RECOVERY_REQUIRED。主服务未接管/启停，主库未写入，外部真实模型请求0，不自动提交或进入S3-B2/P6。详见[P5_LIVE_MAINT_S3B1_REPORT](P5_LIVE_MAINT_S3B1_REPORT.md)、[SANDBOX_MAINTENANCE_FREEZE](SANDBOX_MAINTENANCE_FREEZE.md)、[SANDBOX_HISTORY_RECONCILIATION](SANDBOX_HISTORY_RECONCILIATION.md)。以下为历史记录。

2026-10-18 P5-LIVE-MAINT-S3B0：**审查完成 / 实际部署BLOCKED**。只读确认主Runner仍为旧镜像sha256:3e818427…、完整CID f2da347b…、StartedAt 02:59:04Z未变，存在全局策略标签清理和unless-stopped复起风险；未启停、替换或清理。主库实际为0008_execution_permits，0009三表不存在。334条旧Sandbox记录无普通活动执行，但14条needs_reconciliation保留未知结果；246个历史精确CID在当前daemon均明确不存在，另1条旧启动意图无CID、需核实。Outbox未发布0，Redis pending/lag=0，模型四槽Disabled，真实模型操作/Permit/费用及预留账本0。主API连接失败、项目API/Worker Python候选0，凭据存在性两端均UNVERIFIED，不能引用历史True/True；主version1生命周期保护记录未变，未接管。

本轮仅新增[P5_LIVE_MAINT_S3B_PLAN](P5_LIVE_MAINT_S3B_PLAN.md)，更新[SANDBOX_RUNNER_COMPATIBILITY](SANDBOX_RUNNER_COMPATIBILITY.md)及本状态。计划逐步列明准入冻结、未知记录处置、新备份恢复、旧清理器退出/禁复起证明、0009、可信身份交付、默认阻断部署、兼容签署、独立17+2验收及失败停留。当前缺少完整准入冻结/有限部署与proof交付/专项测试入口，主库新备份及14+1处置未完成；不具备直接部署或主服务接管条件。19项真实Sandbox测试本轮0执行、继续BLOCKED；926项Python/39项专项仅为S3-A历史离线结果。本轮外部模型请求0、主库迁移0、服务启停0，不自动提交Git、不进入S3-B实施或P6。以下为历史记录。

2026-10-18 P5-LIVE-MAINT-S3A：**项目内代码/离线验收PASS，共享Engine部署仍BLOCKED**。已实现Ownership Protocol v1、可信注册/代次/proof、逐执行归属和精确ID审计；缺记录/伪造标签/过期身份/代次冲突拒绝，未知create不按名称清理，旧未派发执行不自动采用。0009仅在专属测试库升降级，主库未迁移。最终分批去重926个Python用例通过（775单元/HTTP、149非Sandbox集成、2项后续新增）；归属专项39项用真实PG与Docker Stub，最后补测业务执行缺失为显式DB Stub，17项真实Sandbox＋2项浏览器仍未执行。5个测试数据栈已精确清理；外部真实模型请求0。主Runner仍旧镜像，主容器身份/启动时间未变，主API当前ConnectError、API/Worker凭据UNVERIFIED；未接管/启停主服务或修改收费门禁。不具备直接升级/接管条件，可申请后续维护方案审查；不进入P6。详见[P5_LIVE_MAINT_S3A_REPORT](P5_LIVE_MAINT_S3A_REPORT.md)、[SANDBOX_OWNERSHIP_PROTOCOL](SANDBOX_OWNERSHIP_PROTOCOL.md)、[SANDBOX_RUNNER_COMPATIBILITY](SANDBOX_RUNNER_COMPATIBILITY.md)。下文为历史记录。

2026-10-18 P5-LIVE-MAINT-S2：**BLOCKED — RUNNER_CROSS_INSTANCE_CLEANUP_UNSAFE**。只读核对实际主Runner镜像，确认全局策略标签/名称与“本库无记录即可能清理”的跨实例缺口；内存Stub复现，未启动测试Runner。按用户停止条件暂停协议/标签/清理改造，17项Sandbox集成及2项浏览器均未执行、继续BLOCKED。生命周期本轮仅静态复核，S1的891项Python/14项浏览器为历史证据。主API当前ConnectError，API/Worker凭据存在均UNVERIFIED；主PG/Redis/Runner ID和启动时间未变，未接管或重启主服务。真实模型请求0，未改收费/预算/Permit或P3/P4配置；不具备主服务接管条件。详见[P5_LIVE_MAINT_S2_REPORT](P5_LIVE_MAINT_S2_REPORT.md)、[SANDBOX_ISOLATION_DESIGN](SANDBOX_ISOLATION_DESIGN.md)。后续Runner隔离/兼容部署及主服务恢复须单独授权；下文为历史时点记录。

2026-10-16 P5三项封版缺口实际修复：**PASS — THREE SEAL ISSUES FIXED AND VERIFIED**。SEAL-S1严格查询/身份不确定拒绝；SEAL-S2统一维护入口、独立审批、导出helper白名单和异步归属；SEAL-S3Issuer不进入维护配置或子进程。新增261项，最终去重600通过、0失败、0跳过：最新非原生588项+本轮已通过且源码未变的12项生命周期；不是历史450项。最新Windows可信标准库替身/假Key启动链已通过，无真实模型请求。详情见[P5_SEAL_FIX_REPORT](P5_SEAL_FIX_REPORT.md)、[MAINTENANCE_ENTRIES](MAINTENANCE_ENTRIES.md)。

12:40:41 +08只读收尾：原API9872/Worker17228创建身份与UUID不变、Protected，18100归属9872，HTTP200/ready，PG/Redis UP、主库0008，API/Worker Key存在True且配置一致。四槽Disabled，真实/Permit关闭、预算0、Worker deny、出口阻断；活动任务/Permit、真实模型账本/派发、待发布Outbox0。7个保护metadata未变；隔离测试进程/执行容器0，没有改主Runner、业务、配置或生命周期状态。当前服务未加载新源码；真实Docker/MCP数据库集成及收费链路本轮未重跑。全部原有Git改动保留，HEAD982e83ef/main、索引空；可重新申请封版审计，未提交/Tag/Push，不进入P6。以下均为历史时点记录。

2026-10-16 P5最终封版只读审计：**BLOCKED — P5 SAFETY OR INTEGRITY ISSUE**。11:40:15至11:50:13 +08复核API9872（11:34:04创建）/Worker17228（11:34:10创建）均Protected且身份未变；端口18100归属9872，健康HTTP200/ready，PG/Redis UP、主库0008。两端Coder Key存在标记True、配置一致，四槽Disabled，真实调用/Permit关闭、日/测试预算0、Worker deny、出口阻断；活动任务/Permit/真实模型操作/派发及待发布Outbox均0。本轮未读取模型Key值，未执行模型请求、生命周期测试、服务或数据库修改。

450项为此前398+52的真实历史XML，本轮仅解析核对。源码审计发现：SEAL-S1进程/端口查询的非终止错误可被误当空结果；SEAL-S2三类遗留维护脚本未纳入共享维护保护；SEAL-S3preflight prepare可能从dotenv/环境复制Issuer权限到维护文件。未发现当前实例已被覆盖或本轮发生秘密落盘；缺口未获修复授权，保持现状并阻止封版。指南过时参数已仅作文字纠正。详见[LOCAL_LIFECYCLE_TEST_REPORT](LOCAL_LIFECYCLE_TEST_REPORT.md)及[P5_SEAL_MANIFEST](P5_SEAL_MANIFEST.md)。HEAD仍982e83ef/main、索引空，所有提交/Tag/Push均未执行。以下均为历史观察。

2026-10-16 P5-LIVE启动防覆盖修复：**代码及本地无费用验收PASS**。共享Windows OS锁、实例UUID/创建FILETIME、受保护记录、一次启动引导与独立交互停止已接入本地起停/Worker重启/P2–P5维护测试；测试不再finally恢复主服务，旧通用恢复探针安全禁用。最终Python **450通过、0失败、0跳过**（398含单元/HTTP339和P5本机集成59；P3/P4真实Docker/MCP52）；首轮397通过1失败因克隆Runner未启动，保留证据并恢复正确测试基础设施后完整复测通过。类型/构建、PowerShell语法与身份谓词检查通过。详情见[LOCAL_LIFECYCLE_TEST_REPORT](LOCAL_LIFECYCLE_TEST_REPORT.md)及[LOCAL_LIFECYCLE_GUARD](LOCAL_LIFECYCLE_GUARD.md)。

当前实际：主库0008、PG/Redis健康、主Runner恢复，主API/Worker及前端未启动；未使用真实Key，运行时凭据继承仍待用户在持Key PowerShell自行执行start-coder-local。四槽Disabled，真实/Permit关闭、费用预算0、Worker deny、出口阻断、重试0、活动任务/Permit/真实模型操作0，实际外部模型请求0。4条本轮容量测试取消任务已用既有终态sweep收敛且保留审计；19条终态测试Outbox保留未强制派发。故障Runner/执行容器/测试子进程均无残留，克隆服务已停、卷保留。HEAD仍982e83ef，保留既有P5-LIVE-SAFETY未提交改动，未暂存/提交，未进入P6。以下全部为历史观察，不能当作当前运行状态。

最终只读复核（2026-10-15 23:05 +08:00）：用户反馈已重载，但实时API/Worker凭据存在仍为False/False；运行PID仍为22:53左右的维护进程，True/True本地记录最后更新于21:20:51。**保持BLOCKED_CREDENTIAL_RELOAD，未达到READY_FOR_APPROVAL**。0008、Permit源码与既有回归证据、配置一致、零活动/待恢复任务、精确域名/受众/价格、关闭门禁及Git格式扫描均通过；外部请求0。本轮没有重启服务或读取Key/Issuer值，不延续收费授权，不进入P6。详见[P5_LIVE_SAFETY_DEPLOYMENT_REPORT](P5_LIVE_SAFETY_DEPLOYMENT_REPORT.md)顶部更新。

P5-LIVE-SAFETY部署（2026-10-15 22:53 +08:00）：**主库0008部署和离线回归PASS，凭据恢复前置检查BLOCKED**。新备份恢复及升降级演练通过，20张原业务表结构/行指纹不变。完整Python **434通过**，浏览器 **15+1通过**，并发与实际OS崩溃恢复、P3/P4、构建、秘密和Git检查通过。主服务已恢复，API/Worker配置一致，Coder凭据存在均False，等待用户持Key的原PowerShell运行新版安全启动脚本。四槽停用、真实/Permit开关false、预算0、出口阻断、重试0、任务/待派发/真实操作/执行容器0；实际外部模型请求0。未暂存提交，不延续旧收费授权，不进入P6。见[P5_LIVE_SAFETY_DEPLOYMENT_REPORT](P5_LIVE_SAFETY_DEPLOYMENT_REPORT.md)。以下为历史记录。

P5-LIVE-SAFETY（2026-10-15 22:32 +08:00）：**离线修复验收PASS，真实调用验收仍BLOCKED**。已实现单次Permit、独立签发身份、可信Worker证明、原子认领/预算、HTTP前派发意图和UNKNOWN不重发。所有现有真实入口均受门禁；四角色配置架构保留。完整Python **421通过**，含293单元/HTTP、25项Permit及P3/P4；浏览器 **15+1通过**，实际OS重启、并发数据库竞争、迁移恢复、秘密及Git差异检查通过。0008仅新增3表，副本升降级完成，主库仍0007且21表指纹未变。主API/Worker/前端/Runner恢复健康，隔离栈已停止；API/Worker Coder凭据存在均False（无Key维护重启），四槽停用、真实/Permit开关False、预算0、出口阻断、重试0、真实任务/账本/执行容器0。须先确认主库0008部署与凭据安全重载，再申请全新的单次收费授权；不延续旧授权、不进入P6。见[P5_LIVE_PERMIT_TEST_REPORT](P5_LIVE_PERMIT_TEST_REPORT.md)及[P5_LIVE_PERMIT_DESIGN](P5_LIVE_PERMIT_DESIGN.md)。以下均为历史阶段记录。

首次DeepSeek收费验收前置检查（2026-10-15 21:23 +08:00）：API/Worker均检测到Coder凭据名称，预算预留重算US$0.00253440通过，但现有全局开关无法将唯一请求绑定本次专用任务/Worker，普通Chat仍可能竞争开放窗口。因此按用户明确停止条件报告 **BLOCKED**；外部尝试0，未开放收费开关或额度，四槽位Disabled、出口阻断及0重试保持，账本未删除。只新增验收文档，不修改生产代码。详见[P5_LIVE_FIRST_CALL_REPORT](P5_LIVE_FIRST_CALL_REPORT.md)。以下Coder收尾时False为当时历史状态。

DeepSeek Coder本地配置收尾（2026-10-15）：已保存openai_compatible/deepseek-flash/完整Coder env引用/关闭thinking，版本2且停用；精确主机及受众、官方USD峰值价格已登记。API/Worker配置摘要和版本一致，当前凭据变量存在均False；真实Key仍在用户独立PowerShell中。专用安全继承启动脚本已用明确假变量验证两端True后恢复False。真实开关false、日/测试额度0、出口阻断、自动重试0、其余角色停用，实际供应商调用0。本轮260单元/HTTP、34本机Stub集成、1隔离浏览器和构建通过。使用步骤与本轮事实见[DEEPSEEK_CODER_LOCAL](DEEPSEEK_CODER_LOCAL.md)。以下前置检查为此前历史状态。

P5-LIVE前置验收（2026-10-15）：HEAD保持982e83e。0007已在专属数据库备份、恢复及升降级演练后应用，迁移前20张业务表原数据校验一致。完整Python **347/347**、全部真实后端浏览器 **14/14**、DeepSeek隔离浏览器 **1/1**、类型/构建、秘密扫描及实际OS Worker恢复均通过。维护服务重启健康，外部模型出口阻断、费用额度0，真实调用0、活动真实任务0。**首次真实测试仍BLOCKED**：四槽位/Key未配置，实际DeepSeek主机许可、受众和价格未登记，收费额度未单独批准。暂停，不进入P6。详见[P5_LIVE_PREFLIGHT_REPORT](P5_LIVE_PREFLIGHT_REPORT.md)及上一轮[P5_LIVE_DEEPSEEK](P5_LIVE_DEEPSEEK.md)。以下为已提交P5基线历史结果，历史版本/HEAD不代表本轮状态。

2026-10-15，Asia/Shanghai。路径 `D:\AIProjects\AgentForge-AI`。P4 基线 `3c3963931eae43fce8f4201fdcac946681a95623`，初始工作区干净。

P5 实现与本地验证已完成，现暂停。**真实外部 API 验收 BLOCKED：缺少真实模型凭据与获准收费测试额度，外部调用0次，P5尚未全部验收通过。** 不将 Stub/MockTransport 当真实供应商验收，不进入 P6。

| 领域 | 实际状态 |
| --- | --- |
| 四模型 | 固定角色独立配置/版本/priority；可同供应商多模型；已实现 OpenAI 兼容适配，其余协议明确未开放 |
| 安全 | 环境/凭据引用、端点/受众双白名单、DNS/IP固定/TLS、无重定向代理、输出/日志/SSE脱敏；Key不入数据库或前端 |
| 协作 | 持久化LangGraph、真实/明确Mock、有界结构化DAG、并行/依赖、Reviewer反馈与冲突、取消/暂停/deadline、租约恢复 |
| 预算 | 任务与UTC日Token/调用/Decimal费用上界，独立测试额度；用量缺失/未知结果保留预留，估算不作账单 |
| MCP/Sandbox | Agent稳定提案经P4 Gateway；独立高风险批准；P3独立代码复核和固定受限Docker；父任务/fence/许可再次验证 |
| 数据库 | 0006_real_models已应用，2新表与用量/父任务关联字段；ORM检查通过，P1–P4数据保留 |
| 前端 | Model Center、Tasks与AI Chat连接真实API；Mock/Real明确，历史/安全状态/SSE/计划/预算/审批可查看 |
| 验证 | Python281/281（0跳过），浏览器14/14，实际OS Worker更换PID且Planner不重放（明确Provider Stub）；迁移/依赖/构建/秘密扫描/已跟踪与25个新增文件差异检查通过 |
| 未验收 | 真实供应商认证/模型参数/DNS-TLS/usage/费用；生产IAM、加密保留、额外协议/RAG/外网检索及P6 |

服务默认前端 `http://127.0.0.1:15173`，后端 `http://127.0.0.1:18100/docs`，Runner `127.0.0.1:18120`只供可信控制面。重启方法见GETTING_STARTED第12节；地址不保证主机重启后自动可用。

P3/P4核心安全边界保留，预热关闭，无宿主不可信代码执行回退。单本地管理员身份、业务字段明文、Docker共享内核和可信Runner daemon权限等原有风险仍存在。本轮不安装系统组件、不修改Docker Desktop全局设置或其他项目。

Git只读操作，不改.git权限、不暂存提交；HEAD仍为P4基线。最终报告给出CMD手动提交建议。真实验收缺口关闭且获得新授权前，不进入P6。

详情：[P5_REPORT](P5_REPORT.md)、[MODEL_INTEGRATION](MODEL_INTEGRATION.md)、[MULTI_AGENT](MULTI_AGENT.md)。P0–P4报告保留历史事实。
