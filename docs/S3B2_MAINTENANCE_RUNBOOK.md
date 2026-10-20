# Runner 维护 Runbook（S3-B2基线＋S3-B3门禁修订，尚未批准执行）

日期：2026-10-18，Asia/Shanghai。项目固定为 `D:\AIProjects\AgentForge-AI`。

**PREPARATION_COMPLETE / DEPLOYMENT_BLOCKED**。本文件说明后续申请的操作顺序，不授予部署、停机、迁移、清理、恢复或模型调用权限。B2快照与旧计划保留；B3新增离线退场内核、历史禁止重放及迁移恢复验证，最新结果和逐项责任见[P5_LIVE_MAINT_S3B3_REPORT](P5_LIVE_MAINT_S3B3_REPORT.md)。主库仍0008；必须明确审阅0009及0010，执行窗口以本文件的依赖和停止条件为准。

## S3-B3 当前执行门禁

- 已有OfflineRetirementController：目标/代次和Stub端口提供的假Peer绑定、单次授权、OS锁、持久化意图、崩溃不重发；**仅限work/maint-s3b3和Stub端口，没有生产Docker/HTTP适配或主控制权限**，始终不授予真实退出/新Runner启动/部署授权。R02生产控制适配、身份交付和可信退出证明仍需验收。
- 已有数据库事实派生的历史隔离，覆盖Worker发布/认领/恢复/执行/迟到回调、Runner、批准和归属；无CID意图也阻止thaw。没有释放quarantine的flag，原14＋1和所有审计/预留不改写。主环境尚未加载，不等于主冻结已覆盖。
- 本轮实际合成备份/restore、DDL失败回滚/恢复通过，**主库新备份和迁移仍未执行**；R07–R10必须独立批准。最终测试归档仅TOC检查，不全部宣传为已restore。
- 两个本地Docker context实为同一daemon，17＋2仍BLOCKED。优先走**独立daemon预验收路径**：由人工提供已安装的专属Linux VM/Engine和目标访问授权，证明与主Engine隔离、SDK固定endpoint、旧主无控制能力；该路径可在不停止主Runner的情况下先做独立测试。不能创建context别名冒充隔离，不能自动安装Engine或修改Desktop全局配置。详细五步见B3报告。
- 若仍使用共享Engine，R06旧清理器退出/禁复起的实际证明不可省略，禁止蓝绿并行和旧版restore。两个路径均须先验收有限测试夹具，不能直接删RUN_SANDBOX/Playwright保护。

## 1. 固定目标与可信边界

14:45–14:47 +08只读观察，后续窗口必须重新核验，不能直接使用本快照执行操作：

| 对象 | 已观察身份与状态 |
| --- | --- |
| Docker daemon | a2353ec2-7b5f-4343-a16b-8a04bc95ec51 |
| 旧主Runner CID | f2da347b403e96ba640d806eb8924ca91e389237de7e445858bfc8bb69c445d7 |
| 镜像 | sha256:3e81842718ce5adf0d55a5fa82cd0f0505adf98faebdd1334c2c78e62b07ba5a |
| 来源/入口 | Compose agentforge-p1 / runner，working_dir为本项目；python -m uvicorn app.sandbox.main:create_app；无源码绑定、无reload |
| 运行 | running，StartedAt=2026-10-18T02:59:04.010046215Z，RestartCount=0，Linux State.Pid=1242 |
| 复起与控制面 | restart=unless-stopped；rw /var/run/docker.sock；127.0.0.1:18120 |
| 主PG CID | 7ea24834b4835bbb151257910a42d1891d7209c117eebc4e384fb7ce3e6c2d5d |
| 主数据库 | agentforge，实际0008_execution_permits；0009/0010未应用 |
| 主Redis CID | 3acee09cc7d0dd806c8b855cb8b280b1a4ead9aa1a3a2e91a6162abad587e5f1；pending=0、lag=0 |
| 旧测试Runner | b48610ba603aa7e1b81c59300ade1736b8502b865213e6e38976e7d3469a0046，exited / restart=no，仍有socket挂载 |
| 主API/Worker | API 18100 ConnectError；限定项目服务命令的Python候选0；两端Coder凭据存在性均UNVERIFIED |
| 生命周期 | 主清单version1/generation4仍保留；未接管；不能让v2工具自动认领或重写 |
| 历史 | 334条执行，14条needs_reconciliation；另1条launch_claimed但无CID；246个历史精确CID当前均明确不存在 |

PID、容器名称、标签、端口、普通JSON、Redis键或人工勾选均不能单独证明身份/授权。宿主Windows PID与容器Linux PID属于不同命名空间。后续可信工具须绑定Windows SID、项目解释器/控制进程创建时间、OS独占锁、daemon ID、完整CID、镜像摘要、StartedAt及服务归属；锁内在每个不可逆动作前重新核验。daemon或任一目标变化，原授权立即失效。

本项目合作脚本与可信Docker/数据库管理员是信任边界。项目锁不能阻挡管理员绕过脚本直接使用Docker；无权修改系统服务权限来伪造这一保证。无法排除外部编排或控制来源时保持BLOCKED。

## 2. 开始窗口之前必须交付的生产工具

以下是生产入口的**待交付/验收规格，不是现成可执行入口**。B3已有离线有限内核和Stub验证，不替代真实控制适配；不要用临时PowerShell或SQL绕过既有保护：

1. 有限维护控制器：只允许既定目标的冻结、禁复起、停止、观察、固定版本迁移和新版默认阻断部署；每步使用独立单次授权，绑定目标代次、操作、期限、前置证据和可信操作员。没有任意命令、Force、SkipGuard或无条件restore。
2. 可信退场采集器：从实际Docker/CIM/连接/项目控制面采集并交叉验证，不接受客户端声称的“已停止/已冻结”。持久化动作意图、结果及不确定状态；控制器崩溃后只对账，不自动重做外部动作。
3. Runner身份与维护operator/approver proof的分权交付：使用独立受保护本地通道/存储，公开记录只有身份、摘要和审计引用。不能借用模型Key、模型Permit Issuer、环境布尔值、命令行或普通manifest取得控制权限。实际proof不进入本报告、Git或子进程日志。
4. 主API/Worker version1保护记录的显式恢复/交接流程。当前接口离线，不能假设无Key，也不能调用start-local覆盖；需要独立用户授权和实时存在性复核。
5. 新版真实Runner测试夹具：在任何写入、Redis消费、容器创建或finally动作前验证全部资源归属，拒绝主端点及旧自动restore；见第7节。
6. 保留UNKNOWN的历史隔离处置方案：当前thaw会拒绝14条needs_reconciliation；没有获批的隔离方案时不得开放主Sandbox。不得添加忽略历史开关。

`backend/app/sandbox/retirement.py`只做离线清单评估：即使SATISFIED，也返回physical_exit_proven=False、deployment_authorized=False。`sandbox_maintenance.py`的私有原语不等于主环境已有可信部署控制面。

## 3. 维护授权和证据包

每次人工批准必须列明步骤ID、单次action ID、operator/独立approver、项目、daemon、完整目标CID/镜像/StartedAt、数据库/卷、instance/generation、维护epoch、到期时间、影响范围和证据引用。窗口批准不等于所有后续解除权限；收费授权始终为无。

证据包应保存在被Git排除、访问受限的项目维护目录：基线与制品清单、入口盘点、历史15项清单摘要、停机意图/返回/实际状态、复起来源、两轮观测及连接归属、备份摘要/恢复报告、迁移前后结构/业务指纹、身份交付回执、测试清单和最终资源状态。仅哈希与有限元数据可进入文档；审计关联ID不是授权。不得保存完整环境、Authorization头、实际Key/Issuer/proof或业务正文。

证据失效条件：目标或daemon变化、清理器复起、未知新增容器/控制请求、制品变化、维护锁丢失、授权过期或已使用、数据库/队列身份变化。失效后停止后续动作、保持已建立的隔离，不重放旧授权。

## 4. 旧Runner可信退场和防复起

### 4.1 先解决0008的冻结引导问题

0008主库没有0010状态；旧二进制也不执行新检查。API当前不在线、Redis pending=0都不能证明入口被冻结。迁移之前必须先在**另获批准的项目控制边界**隔离全部写入/派发者：API/Worker/恢复调度器、MCP/Agent Sandbox交接、直接Runner dispatch入口及现有启动/回归入口；阻止其他终端或编排重建旧Runner。需要中断API/Worker或修改项目运行策略的动作均独立确认。

不能先直接写0010表来保护仍运行的旧二进制，也不能仅停一个Worker就宣称完成冻结。项目维护锁和入口隔离要覆盖后续备份、停旧版、迁移、验证的整个窗口。无法实际封闭旧入口时，停在此处，**不要停Runner来掩盖入口缺口**。

### 4.2 自动复起路径逐项台账

| 路径 | 当前事实 | 后续受控措施与验证 |
| --- | --- | --- |
| 主容器restart策略 | 实际unless-stopped | 获授权后按完整CID改为no；重读实际策略及计数；仅stop返回不能代替禁复起 |
| compose.yaml runner / runner-unavailable | runner配置沿用unless-stopped；另有备用服务 | 审阅项目级维护配置和调用点；不得以up/down整栈操作代替精确动作；项目启动控制入口持锁拒绝恢复旧版 |
| permit-test-runner-isolation.py | pause/restore仍有按名称操作及was_running恢复逻辑，外层有生命周期保护 | **从升级/测试/finally路径排除**；原保护不是协议升级授权，绝不执行restore旧镜像 |
| bootstrap、test-p2至p5、recovery probe、人工终端 | 合作脚本已有维护保护，但不等于外部控制已全部关闭 | 清点实际调用者与进程、版本及持锁状态，冻结窗口内禁止启动；不得运行可能触及主资源的测试 |
| 旧测试Runner | 当前exited/restart=no，但保留socket | 保持停用；每轮验证完整CID、实际非running；不能按曾停止推定永不复起 |
| Windows任务/服务、其他终端、远端Docker控制、daemon重启后项目自动启动 | 本轮未证明全部不存在 | 维护负责人只读核对本项目相关来源并形成完整台账；不改系统权限/全局Docker配置；无法排除即BLOCKED |

### 4.3 停止边界和退出确认

有限控制器锁内重新验证身份并持久化单次“禁复起/停止”意图，才可调用Docker的精确CID update(restart=no)、stop(timeout有界)动作。这里列出的是未来受控动作，**本轮没有执行，也不提供绕过现有保护的直接启动/停止命令**。未知返回先观察实际状态，不能再次stop、扩大kill范围或按名称重试。

停止确认必须共同具备：

- 所有已识别旧清理器的完整CID非running、State.Pid=0、退出时刻可信、RestartCount稳定、restart=no；核对退出码/信号与动作审计，容器外控制进程也已确认退出/隔离。
- 旧主18120不再提供旧控制入口，无对应旧PG连接或可继续控制Docker的本项目旧进程；不能误把PG/Redis健康检查连接算作Runner连接。
- 所有已准入Docker请求/SDK线程的结果或不确定边界已对账；容器退出不能保证daemon已接收的create请求不继续执行。无法确认的资源/在途操作阻止切换。
- 持续入口隔离；跨原5秒扫描周期和原30秒有界请求时间，至少两轮间隔60秒观察。**等待时长与日志安静本身不是退出证明**，须与实际进程、控制通道、连接、精确资源及受限事件证据交叉核对。
- 宿主重启、daemon变化或旧版重新出现均立即作废退场/兼容证据，不自动恢复新旧任何一侧。

旧协议容器只登记原CID/镜像/标签和未知状态，不补新归属、不改标签、不自动删除。对无法证明所有权的资源只保留、报告；不扫描后批量清理来满足计数。

## 5. 新旧交接、迁移与恢复的逐步操作卡

“人工授权”指未来单独批准；本轮仅R00/R01的只读及文档工作在现有授权内。每步失败均停止后续步骤；未建立的冻结不能被报告成已生效。

| 步骤 | 前置条件 | 动作 / 影响范围 | 验证和证据 | 失败停止条件 / 恢复策略 | 人工授权 |
| --- | --- | --- | --- | --- | --- |
| R00 成果封存 | 当前工作区只读 | 哈希和排除凭据的源码副本；审阅所有tracked/untracked；不暂存 | HEAD/索引/文件清单/增量审查相符 | 发现意外改动或敏感候选停止提交准备，不覆盖 | 本轮已批准 |
| R01 目标核验 | 固定daemon、完整CID及只读DB事务 | 观察旧Runner/PG/Redis/API/队列/334条记录；不启停 | 新时间戳、版本、镜像、归属和历史差异清单 | 目标变化/未知控制来源即BLOCKED；保持原状 | 本轮已批准 |
| R02 工具准入 | 第2节工具实际完成隔离验收、制品固定 | 负责人核对有限控制器、身份交付、可信采集与新测试夹具 | 真实Windows竞争/身份/重放及故障证据；不是Stub替代 | 工具或证明不完备不进入停机窗口 | **是：先开发/验收，再另批窗口** |
| R03 外部入口隔离 | R02，全部生产者清单和项目维护锁 | 隔离旧API/Worker/调度/Runner控制与项目恢复入口；可能影响API/Worker | 实际各入口拒绝新派发，无新Outbox/认领/直接HTTP；重启路径关闭 | 任一路径不可信即停，不能声称全量冻结；保持已建立隔离 | **是：明确API/Worker中断及保护交接** |
| R04 排空与历史签认 | R03真实生效 | 观察运行/取消/UNKNOWN和在途请求；14＋1仅审阅保留 | 无新执行；每项历史有缺证据/人工结论，不改结果、不释放未知预算 | 活动/在途/资源身份不明则不迁移或派发；保留证据 | **是：取消/隔离处置另批；只读签认不改状态** |
| R05 禁复起与停旧版 | R03–04；精确目标单次授权；锁仍持有 | 第4节有限动作；**中断主Runner**，不停止PG/Redis | 实际restart=no、退出/连接/控制进程与审计互证；旧测试Runner仍停用 | 停止结果不确定只对账；不按名称重试、不自动restore | **是：单独批准Runner中断和项目策略变更** |
| R06 退出证明 | R05已确认，控制入口持续隔离 | 两轮实际观察与在途边界对账；旧版继续停用 | 第4.3节全部通过，人工独立复核兼容证据 | 任一复起/未知资源/控制进程即失效；不开始新Runner | **是：接受本次退场证据** |
| R07 新备份和副本演练 | R06；所有主库写入者已停止/隔离，主库0008 | 专属主库custom备份→独立已证明归属的恢复目标→0009/0010副本演练；主库只读 | 第6节全项，备份排除Git且可实际恢复 | 不一致停止；主库不迁移，旧Runner保持停用/隔离 | **是：备份与独立恢复目标；不含覆盖主库** |
| R08 主库0009 | R07通过，有限迁移者，固定0008 | 精确升级到0009_sandbox_ownership，新增3表；可能短DDL锁 | 实际revision/3表/约束与旧23表数据、事件/Permit指纹一致 | 超时/断连停止，检查事务和实际revision；不盲目重跑head | **是：主库0009写入** |
| R09 主库0010 | R08通过，旧版仍停用 | 精确升级到0010_sandbox_maintenance，新增4表；未配置状态时拒绝准入 | revision正确，新控制表结构与默认拒绝、旧数据不变 | 未完成/未知则保持外部隔离；不删表/历史硬通过 | **是：主库0010写入** |
| R10 安装FROZEN控制 | R09，可信分权交付已验收 | 私有安装原语建立FROZEN及operator/approver；不签发模型Permit | 有持久化epoch/有限审计；proof不进普通终端/日志 | proof/交付不可信或状态未知即停，保持外部隔离 | **是：明确新增维护身份/控制记录** |
| R11 新版阻断部署 | R06仍有效；制品/DB/Runner身份已固定 | 单独部署新Runner，restart=no、无兼容clearance、不准派发；API/Worker更新须另批 | 未配置/无clearance安全失败；无容器创建；旧版仍非running | 新版不可信则按其固定身份停留/受控停止；绝不启动旧版回退 | **是：新版Runner；API/Worker若涉及另列** |
| R12 签认兼容/单实例 | R11，独立复核退场和控制面 | 可信工具写入绑定daemon/实例/代次的兼容证据，允许该Runner认领；当前启动只claim一次，必要受控重启单列授权 | 一个process_owner有效租约，所有权账本准确；仍FROZEN、没有业务派发 | claim/重启未知只对账；旧授权不重放；租约过期不代替物理退出 | **是：兼容签认和必要新版重启** |
| R13 独立真实Engine验证 | 测试夹具/独立资源已批准；共享Engine须R06全部旧清理器不可复起，独立daemon须证明主清理器不可访问 | 先跨实例/崩溃归属验证，再17＋2；独立daemon可另批先行而不停止主Runner；不消费主Redis/主库、不使用真实模型 | 第7节逐项证据、不同实际daemon ID/控制边界（独立路径）、19项结果和精确归属清理回执 | 任何跨界/UNKNOWN保持隔离；不依据context名或环境变量放行；禁止旧restore/finally广域清理 | **是：具体daemon/数据栈/端口、19项及精确清理范围** |
| R14 主业务解除 | R13通过，历史阻塞已有另外批准的保留式处置；全部入口新版 | approver签发<=60秒绑定epoch/目标的单次thaw，由operator消费；恢复主Sandbox准入 | 仅目标身份可用；模型出口/四槽/预算/Permit仍关闭；审计完整 | 当前14条使thaw拒绝，必须停；不得删除UNKNOWN或绕过查询 | **是：主业务准入恢复独立授权** |
| R15 收尾 | 不再需要执行；所有资源已明确归属 | 有限工具清理授权范围的测试资源，核验主服务/历史/账本，归档报告 | 无额外执行容器/未知在途；安全门禁/备份/审计保留 | 清理失败记录精确ID，禁止扩大扫描；身份不明不删 | **是：容器/网络删除须明确包含；本轮禁止** |

新旧清理器不存在已验证的蓝绿并行方式。R06之前不能启动任何新版真实执行容器；R11以后旧镜像仍禁止恢复。新镜像失败的安全状态是入口隔离、旧版禁复起、新版阻断、数据库和审计保留，服务中断应明确报告。

## 6. 0008 → 0009 → 0010与备份验收卡

已审查迁移是增量DDL：0009新增identities/ownership/audit三表，0010新增maintenance/authorities/thaw_grants/audit四表；不回填旧归属、不改业务结果、不自动设OPEN。0009外键关联原task/execution，未来删除受约束；有身份或审计后不能当作可任意降级。

未来R07–R10必须逐项记录，不能用B1合成恢复结果替代：

1. 重新证明PG完整CID、镜像、Compose项目/目录、专属卷agentforge-p1-postgres-data、数据库agentforge/owner、0008及所有写入者；未证明目标不备份/迁移。
2. 建立写入一致的冻结快照，保存旧23张业务表结构、计数和排序后行指纹、334条执行及14＋1元数据、P4审批、0008 Permit/费用/审计、Outbox和Redis游标基线。只输出摘要，不输出任务代码、回答正文或凭据。
3. custom-format专属数据库备份写到访问受限且Git排除的项目目录，不dump集群全局角色，不输出密码、环境或proof；记录工具/服务端版本、文件大小、SHA-256、完成时间和TOC。证明没有备份另一项目。
4. **实际restore到独立、已证明归属的空库/实例**；校验所有原表/列/行指纹、序列及约束/索引、关键数据和UNKNOWN。不把TOC可读当作恢复成功；不能指向主PG/Redis做“副本”测试。
5. 在副本逐个升到0009、0010，比较全部旧业务内容；新表/约束、FK与唯一CID、Permit trigger/关键CHECK/唯一索引通过。空新表可降级回放；写入合成身份/审计后必须拒绝直接downgrade。
6. 主库动作仅精确revision，独占迁移者、短lock_timeout与statement_timeout、受控连接；事务失败/断连检查实际落点。避免DDL和未停止旧Runner写入竞争。主库不做破坏性的downgrade演练。
7. 0010无控制行时继续默认拒绝；首次安装只能FROZEN。没有维护身份或凭据交付时不能手写OPEN，也不能直接更新兼容clearance。
8. 非空0009/0010降级会拒绝；不能删除维护/归属审计来降级。故障优先前向修复；覆盖主库恢复须新授权，保留备份后增量/未知审计和账本，离线验证，所有服务继续隔离。防止恢复旧OPEN、USED授权或代次回退带来重放。

本轮主库备份/实际恢复/迁移均**未执行**。B1用合成0008记录实际恢复过独立副本，证明代码路径，不证明当前主库备份可用。保留的5份测试归档只验证过TOC，不能一并宣传为逐份实际恢复成功。

## 7. 17＋2真实Sandbox测试准备卡

当前19项全部BLOCKED，本轮0执行。现有conftest/preflight明确拒绝RUN_SANDBOX，S1应用夹具固定0008且runner_test=BLOCKED，Playwright忽略sandbox.spec.ts；不要直接删保护或切环境变量。

| 资源 | 后续必须证明的隔离 |
| --- | --- |
| API/Worker/Runner | 独立instance/generation/可信身份、解释器/创建时间及OS独占锁；不接管主version1清单 |
| 数据库 | 独立PG实例/库、0009/0010结构及FROZEN控制；manifest不是唯一证明；拒绝主15432/固定CID/卷及URL别名绕过 |
| Redis | 独立实际Redis实例/端点、任务Stream、消费者组；不能仅改组名后消费主16379 |
| 端口与工作目录 | 独立保留的API/前端/Runner/故障Runner端口、日志/PID/报告目录；故障端口也须显式保留，不能盲取port+1 |
| Docker | daemon经核验，独立project/runner/generation/namespace，CID/实际容器身份/持久化账本/审批和当前授权共同验证；标签或名称仅发现线索 |
| 浏览器 | 独立前端baseURL和API代理；拒绝主18100/18120/15173及非证明目标；无真实Key/Issuer继承 |
| finally | 只允许当前清单且锁内重新证明的精确资源；失联/代次变化保留UNKNOWN，不扫描批量删除、不restore旧主Runner |

既有17项：test_sandbox.py的13项、test_sandbox_failures.py的3项、test_real_agents.py中实际P3工具执行/Reviewer证据的1项（模型仍ProviderStub）；浏览器sandbox.spec.ts两项。需按实际资源限制、超时、取消、重复消息/Worker恢复、网络/根文件系统/身份/资源配额和审批拒绝逐项出具结果，不能仅运行名称类似的Stub。

旧测试中按execution标签查询容器的断言只可用来发现，不授予清理权限。test_sandbox_failures的finally通过服务cancel，只有在夹具已证明独立DB/Runner并全程持隔离租约时才可运行；其“Root stops demo Worker”说明不构成停止主Worker授权。多Agent场景需要假模型，不能为测试启用真实槽位或模型Permit。

R13前先验证：两个新版Runner的实际跨实例资源不可误管、真实create边界崩溃/恢复、Docker不可用拒绝、身份/代次变化及finally失败安全。19项业务测试不能替代这些所有权预检。旧主Runner仍运行时，即使标签不同也不得在**共享Engine**启动测试执行容器；经独立授权和实际控制边界验证的另一daemon按上文独立路径处理。

当前两个S1数据栈4个容器仍exited、2个网络保留，清单RECOVERY_REQUIRED；本轮没有恢复、停止或删除。它们不是可立即用于19项的READY环境，不能直接修改清单状态恢复运行。后续新建/恢复/清理均需批准并重新验明归属。

## 8. 失败恢复决策表

| 失败位置 | 安全停留状态与允许的后续申请 |
| --- | --- |
| 尚未隔离入口 | 保持原状、报告未建立冻结；不能宣称安全窗口已开始 |
| 入口已隔离、旧版尚未停 | 保持隔离，重新取得绑定目标授权；不启动新版或真实测试 |
| 禁复起或停止结果未知 | 只观察精确旧CID、控制进程和在途动作，停止后续；不得以重试stop/update或启动新版获得确定性 |
| 旧版已退出、备份/迁移失败 | 入口继续隔离、旧版继续禁用；核验实际revision/事务，申请前向修复或受审恢复，绝不自动restore旧清理器 |
| 新版启动/claim失败 | 保持FROZEN；精确记录其CID/generation/租约和UNKNOWN；受控停新版须另批，不回滚到旧宽泛清理 |
| 测试失败或清理不确定 | 停新测试，保留精确资源和审计，不清空主数据、不删除未知容器/网络 |
| 历史阻止thaw | 继续FROZEN，保留14＋1；申请保留式历史处置设计；不重置状态、不改结果、不清零费用 |
| 维护锁/证据丢失或daemon重启 | 所有未执行授权失效；重新对账所有身份与在途边界，保持原隔离；不自动续跑 |

## 9. 本轮结论与下一授权拆分

Runbook和证据清单已准备，**尚不满足直接申请实际部署的技术前置条件**。优先申请第2节有限控制器/可信采集器、proof交付、保留UNKNOWN处置与真实Runner夹具的项目内开发及隔离验收；通过后再单独申请：主API/Worker保护交接与入口中断、旧Runner禁复起/停止、主库新备份与0009/0010、新版部署/兼容签认、真实17＋2及精确资源清理、主业务解除。任何一次授权都不包含收费模型或P6。

关联：[本轮报告](P5_LIVE_MAINT_S3B2_REPORT.md)、[Git交付计划](S3B2_GIT_DELIVERY_PLAN.md)、[冻结机制](SANDBOX_MAINTENANCE_FREEZE.md)、[15条历史记录](SANDBOX_HISTORY_RECONCILIATION.md)、[归属协议](SANDBOX_OWNERSHIP_PROTOCOL.md)。
