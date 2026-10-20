# S3-B3 部署阻塞收敛验收

日期：2026-10-18，Asia/Shanghai。项目：`D:\AIProjects\AgentForge-AI`。

**本轮项目内修复与隔离验证完成；真实部署仍BLOCKED。当前不具备直接申请主Runner维护执行窗口的全部技术条件。** 已把四项阻塞分解为有证据的代码结果与必须由人工完成的运行边界，未将Stub或文档标为真实部署通过。没有为取得PASS删除UNKNOWN或降低P3/P4/Permit门禁。

## 1. 成果保护和实际修改

起点HEAD=982e83ef32b7d274e820d59ee63d6fb76bd8979e，66项tracked修改、109个untracked，索引空。起始294个Git候选文件逐项保存SHA-256和排除凭据的源码副本，work/maint-s3b3/20261018保存基线和本轮增量；不覆盖B1/B2源码副本、旧测试XML、备份及报告。主dotenv、真实Key、Issuer不读、不复制、不输出。

| 实际文件 | 修改及原因 |
| --- | --- |
| backend/app/sandbox/retirement_control.py（新） | 有限离线退场内核：目标项目/实例/代次/daemon/CID/镜像/StartedAt绑定，独立operator/approver的Peer绑定、<=60秒单次授权、OS文件锁、SQLite FULL同步审计、动作意图先提交、UNKNOWN不可重放/恢复不重发；目录限定work/maint-s3b3，只有显式OfflineBoundary，没有真实Docker/HTTP/shell或生产CLI |
| backend/app/sandbox/retirement.py | 拒绝布尔/负数/字符串冒充计数、错误类型和非有限观测；清单仍不能授予真实退场/部署权限 |
| backend/app/sandbox/history.py（新） | 从持久化旧启动意图、未知结果和ownership状态导出隔离；不新建可随意解除的flag，不修改原结果/费用/审计，输出有限缺证据清单 |
| backend/app/workers/engine.py | publish、sweep两段、claim、execute、heartbeat、finish一致禁止重放；重复Redis、旧回调、租约恢复不能改写或结算隔离历史 |
| backend/app/sandbox/engine.py、ownership.py、services/sandbox.py | Runner派发、注册归属、批准入口同样拒绝隔离历史；正常请求先注册归属，再设置launch字段，两者同事务提交，Docker仍在提交后 |
| backend/app/services/sandbox_maintenance.py | thaw增加“已有launch但无CID且无ownership”的拒绝条件，覆盖原14条之外的1条无CID意图，不再仅依赖needs_reconciliation |
| backend/app/sandbox/daemon_isolation.py、scripts/check-sandbox-daemons.py（新） | 比较两个已配置本地named-pipe的实际daemon ID；只读，不切context、不探测远端、不安装组件；不同daemon也只给候选、不给Runner启动权限 |
| tests/fixtures/retirement_boundary.py、retirement_control_worker.py（新） | 假Peer/Runner边界；真实Windows子进程竞争及os._exit崩溃，全部效果仅写隔离Stub日志，无Docker调用 |
| tests/unit/test_retirement_control_b3.py、test_sandbox_history_b3.py（新） | 状态顺序、重放/过期/代次/PID身份变化、原始意图保留、异常/清理循环/在途请求、目录逃逸、daemon别名拒绝 |
| tests/integration/test_sandbox_history_db_b3.py（新） | 真实专属PG/Redis、合成14＋1、重复消息/恢复/旧回调、审批/Runner/归属拒绝及正常派发原子意图 |
| tests/integration/test_sandbox_migration_recovery_b3.py（新） | 新测试schema中实际DDL锁超时→事务回滚→恢复升级，原表/数据不变，不删旧数据 |
| tests/integration/test_sandbox_migrations_b1.py | 每次实际备份/restore使用当前已证明测试run的新目录，不再覆盖B1历史证据 |
| tests/integration/test_sandbox_ownership_db.py | 新请求测试夹具与生产同序：先issue再写launch，同事务；不绕过历史门禁 |
| 本报告、PROJECT_STATUS、S3B2_MAINTENANCE_RUNBOOK、S3B2_GIT_DELIVERY_PLAN、SANDBOX_HISTORY_RECONCILIATION、SANDBOX_MAINTENANCE_FREEZE、SANDBOX_RUNNER_COMPATIBILITY | 单一验收表、精确Git清单、当前边界及人工步骤；保留旧报告 |

0007/0008/0009/0010迁移文件、P3 policy.py、P4 Tool Gateway/Skills/审批、Permit权限/预算/模型适配器和冻结配置不改。主库无新表/数据写入，主Runner没有加载本轮源码。

## 2. 四项阻塞逐项门禁

PASS仅指该行标注的证据层次；BLOCKED/PARTIAL不能解释为可部署。

| 门禁 | 状态/实际证据 | 缺少什么 | 可由项目代码继续解决？ | 是否需真实维护授权 | 最小解除动作与客观标准 |
| --- | --- | --- | --- | --- | --- |
| 1a 退场有限状态/审计/并发/崩溃内核 | **PASS（离线）**：真实OS锁、SQLite及子进程竞争/崩溃，容器动作Stub；意图持久化后不自动重发；不提供restore或START_NEW | 无离线内核验收缺项；不是生产身份/IPC/退场证明 | 生产适配仍可开发 | 本行测试不需；实际stop需要 | 内核结果始终deployment_authorized=False；实际控制面另按1b验收 |
| 1b 主Runner可信退场和交接 | **BLOCKED**：内核与当前身份只读证据已具备，旧主仍running/unless-stopped | 适用于主version1保护记录的可信生产控制适配、operator/approver分权交付、完整复起来源台账、全部旧入口隔离与实际退出/在途收敛证明 | **是**：有限生产适配/可信采集/交付可编码；真实边界不能靠Stub证明 | **是**：API/Worker保护交接、禁复起和主Runner中断分别批准 | 先在确认独立daemon完成真实适配验收，再接受目标绑定窗口；锁内重验，旧版restart=no/非running/Pid0/循环退出，无旧控制连接/进程/在途动作，两轮观测及审计一致；新版不得同时管理旧资源 |
| 2a 历史禁止重放 | **PASS（合成PG/Redis集成）**：合成14＋1原状态、事件、预留和Outbox保留；重复消息/恢复/迟到finish均不派发或改写 | 主部署尚未加载本轮规则 | 已完成本轮规则；生产加载属于部署 | **是**：实际交付，当前不写主库 | 加载经审阅版本后，对真实历史只读导出hold元数据并做无派发负向验证；不得以普通approval解除 |
| 2b 历史结果及主准入恢复 | **BLOCKED**：真实334条只读保留；原14＋1缺证据仍在 | 历史daemon/Runner身份、create/注入/退出/结算边界；保留UNKNOWN的人工签认和未来隔离处置授权 | 证据不能由代码制造；未来保留式隔离流程可实现，但本轮没有解除入口 | **是**：任何主库处置/主thaw均独立批准 | 人工逐项核对15条，证据不足继续UNKNOWN；当前thaw保持拒绝。不能用清零/删审计/伪造FAILED解决；未知保留方案未获批前不恢复主准入 |
| 3a 0008→0009→0010合成迁移/备份恢复 | **PASS（独立PG）**：custom备份＋实际独立restore，旧23表一致；DDL失败回滚后可恢复，非空降级拒绝 | 不代表当前主库备份可恢复 | 本轮没有迁移代码新增需求 | 本行测试无需主维护；不授权主库写入 | 保留测试归档/实际restore报告和错误批次；主库按3b重新做 |
| 3b 主库新备份及迁移 | **BLOCKED**：主库仍0008，未创建本轮主库备份 | 写入者隔离后的新备份、访问保护、独立恢复目标和当时数据指纹 | 主要是受控运维；已有迁移本轮不改 | **是**：主备份/独立恢复、0009、0010逐步批准 | 完成Runbook R07实备份/restore与全旧表/14＋1/P4/Permit/账本校验，再批R08–R10；不以测试合成档替代 |
| 4 独立真实Runner测试环境 | **BLOCKED**：default和desktop-linux两context实际ID相同，均为a2353ec2-7b5f-4343-a16b-8a04bc95ec51 | 经人工确认、归属独立且可访问的另一个Linux daemon/VM，有限测试Runner夹具和proof通道真实验收 | 身份比较/夹具可编码；独立Engine不能由业务代码产生 | **是**：环境供应/访问权限及真实测试范围 | 人工提供独立已安装daemon/专属VM；实际Engine ID与主不同，管理边界/数据目录/目标归属证明；再审有限夹具、跨实例/崩溃及17＋2，成功后仅清理已证明资源 |
| 17 Sandbox集成＋2浏览器实际验收 | **NOT_TESTED**（准入受门禁4阻塞） | 上一行隔离条件；当前共享Engine旧清理器仍运行 | 不能通过移除保护解决 | **是**：19项和精确资源清理另批 | 实际19项逐项结果、真实容器限制/取消/超时/恢复、跨实例不误清理、无遗留已确认资源；Mock不能代替 |
| 主安全运行时存在性 | **PARTIAL**：四槽Disabled、非Mock操作/Permit0；API离线 | API/Worker凭据/预算/重试/出口实时状态无法从离线进程核验 | 需先解决受保护启动交接，不能覆盖旧记录 | **是**：恢复API/Worker另批 | 只读接口实时核验；不沿用历史True/True、不读取Key/Issuer、不为维护终端配置Issuer |

**申请判断：尚未READY_FOR_MAINTENANCE。** 可以申请独立测试环境及有限生产适配的后续验收范围；不能跳到主Runnerstop、主库迁移或主thaw。本报告没有把“需人工真实操作”伪装成新代码已PASS，也不再通过新增通用设计文档延长门禁。

## 3. 测试结果与证据层次

最终数量由本轮unit.xml / integration.xml去重记录，见work/maint-s3b3/20261018/test-summary.json；针对性及迁移重复批次不重复累计。

| 批次/层次 | 实际结果 | 说明 |
| --- | --- | --- |
| 最终完整单元/HTTP离线批次 | **843通过**，0失败/错误/跳过，73.70秒 | 含新增43项；原16项独立生命周期manager/native批次未重跑，不冒充完整Windows主实例验收 |
| 完整非Sandbox集成批次 | **191通过、1失败、17排除**，257.68秒 | 唯一失败是新增正向测试只设置租约而未设running，check_lease正确拒绝；保留integration.xml/log |
| 修正夹具后的历史专项 | **7通过**，0失败/错误/跳过，11.81秒 | 包含上行失败用例；只改合成夹具task.status，不改服务端安全校验；其余191项生产源码未再改变 |
| 迁移/备份恢复专项 | **2通过**，8.01秒 | 真实专属PG、custom备份/实际restore、0009/0010和DDL锁失败回滚；与整批重复不累计 |
| 初始离线专项 | **61通过**，2.70秒 | 后续补6个类型/路径用例已进入843项；不重复计数 |
| 最终去重 | **1035个不同Python用例最终通过，新增51项** | 843单元/HTTP＋192个最终通过的集成（分批）；不是“192项整批一次全绿”。目标XML空classname按明确源模块归一后去重；无未解决失败 |
| 实际Runner/浏览器 | **17＋2未执行、继续BLOCKED** | Docker动作Stub，只有PG/Redis和受控MCP/测试子进程是真实集成；没有真实模型请求 |

Windows竞争使用真实子进程/OS文件锁/SQLite，但Peer和Runner是明确Stub；没有证明真实主进程身份或Docker停止有效。控制器限定离线目录，没有真实Docker适配器/HTTP控制端点；所有返回都拒绝真实部署/启动授权。真实主控制面的验证仍是门禁1b。

历史规则使用原DB字段派生隔离，不新建可被普通客户端重置的布尔状态或释放入口。对已隔离的迟到任务回调保持原任务状态，可能呈现旧running/过期lease，必须人工核对；不为美化状态而修改结果或预算。正常新请求归属与launch意图同事务、外部IO在提交后，已加独立正向集成用例。

初次完整单元837通过后，补充6项类型/路径测试和Worker迟到回调、正常派发检查，再执行最终批次；保留unit-first证据。没有把重复通过累加。迁移测试输出目录修复防止重跑覆盖B1报告；所有测试数据schema/审计保留，不drop数据库或清空UNKNOWN。

## 4. 真实历史和人工核对流程

本轮只读读取全部334条白名单元数据，14条needs_reconciliation及1条failed/not_created但缺CID启动意图保留；246个历史精确CID当前明确缺席不证明过去结果。与本轮起点及B2快照逐条对比，未改结果、审计或资源归属。

人工操作顺序固定：按[15条清单](SANDBOX_HISTORY_RECONCILIATION.md)核对原execution/task/CID/事件序号与时间→关联历史daemon及Runner真实身份→核对create/注入/退出/结算边界→独立复核者签认缺失证据和“禁止重放/不准自动清理”→无法确认则继续UNKNOWN。人工备注与业务结果分离；任何未来主库附加记录需要新授权，不回填新Runner归属、不凭当前容器缺席作结论。

无CID意图已被新增thaw条件覆盖；当前隔离不是“解除全局冻结后忽略15条”，也没有IgnoreUnknown/Force或普通客户端解除方法。主库仍未应用0009/0010，主运行二进制未加载这些规则，主准入恢复不能据离线测试放行。

## 5. 独立daemon所需人工步骤

1. 指定现有独立Linux测试主机/VM及负责人，确认Engine已安装；若没有，由用户另行安排并批准组件安装。本轮不安装Engine、不改Docker Desktop全局配置。
2. 明确允许访问的测试Engine、网络与专属账号/证书交付方式；不用模型Key/Issuer，证书不进入Git或聊天。远端连通检查和Docker资源操作均另获明确目标授权。
3. 只读比较实际daemon ID、宿主/数据目录/管理边界及上下文端点。新context名称或第二个pipe不等于另一个Engine；不同ID也只是候选，仍需目标归属核验。
4. 在批准目标创建新的测试PG/Redis/Runner/端口/目录/浏览器目标，证明旧主清理器无能力访问该daemon；防止环境DOCKER_HOST指回主Engine，SDK客户端固定已批准endpoint，每个实际动作前重验daemon ID。
5. 审查全程隔离租约和精确归属的有限测试夹具，先跨实例/崩溃，再19项；失败保持UNKNOWN，不自动restore主旧Runner。删除容器/网络须独立纳入范围。

如果暂时不能提供独立daemon，现有共享Engine路径只能等待另获授权的旧Runner可信退场；在此之前绝不启动第二个真实Runner。

## 6. 主库新备份和维护清单

Runbook R03–R10仍是未来授权动作：证明固定主PG CID/镜像/项目卷/数据库owner/0008→隔离所有写入者和旧清理器→新custom备份置受保护、Git排除目录→文件大小/SHA/TOC→实际恢复到已证明归属的独立目标→全部23张旧表、14＋1、事件/P4/Permit/预算/账本/序列/约束和索引一致→副本0009/0010与故障恢复→明确批准主库精确revision。主库不执行downgrade演练；有新历史时不能删审计降级，故障保持隔离，不恢复旧宽泛清理镜像。

本轮专属数据栈ID=5c8c3bfe-e109-4cb8-aefc-7232d1e13003，PG/Redis端口57963/57964；没有Runner容器或Docker socket，未使用主端点。新合成备份只属于该测试栈，不能用作主库恢复源。

本轮测试PG完整CID=bf09c114222fd86831dca3efd7b2ad78efc50f8efa8c2932ef0d9a732f34999d，Redis=ed308ec4bb1484c8bc765e68ee985a57e291e9bba178441a18e899dc0fd026b6。完成后无测试客户端，两个数据容器及其独立网络**保留运行**，没有停止或删除；避免丢失tmpfs中的测试审计。另将3个测试数据库生成最终归档并校验TOC，存入被Git排除的retained-test-backups；这些最终整库归档未逐份实际restore，不冒充迁移专项中已完成的合成副本恢复。之前4个已停止数据容器/2个网络也原状保留。任何后续清理须明确批准并重新验证归属。

15:22 +08收尾只读复核：主Runner/PG/Redis和旧保留资源的完整身份、启动时间、重启计数不变；334条执行元数据与起点/B2一致，14＋1和246个历史CID观察不变。主库agentforge/owner=agentforge仍0008，七张0009/0010表均不存在，非Mock模型操作/Permit/enabled槽位均0；未改主配置。API仍ConnectError，主服务和本轮测试进程候选0，API/Worker Key存在性及预算/重试/出口运行时仍UNVERIFIED。主version1保护清单/audit/lock内容和mtime未变，不把离线配置当作实时True/True或运行时预算0的证明。

## 7. Git与交付

没有暂存/提交/重置/清理。正式源码、迁移、测试、文档与忽略的临时产物/备份分开审阅；完整最终文件清单及本轮增量见[S3B2_GIT_DELIVERY_PLAN](S3B2_GIT_DELIVERY_PLAN.md)的S3-B3附录。仍建议G1功能安全整体、G2迁移、G3维护入口、G4测试、G5文档顺序人工审阅；所有批次组成同一不可拆分部署版本。

最终HEAD不变，索引空，66项tracked修改、120个untracked；本轮增量25个路径（14份现有文件修改、11份新增），未删除起始成果。完整186项分批为G1=42、G2=5、G3=50、G4=57、G5=32，临时产物/备份不在清单内。git diff --check及305个候选文件/索引/既有bundle/报告凭据格式扫描通过；新增未跟踪文件另查内容/语法/空白，未触及.git权限。

待提交内容只含公开配置/credential_reference，真实Key/Issuer/备份不进Git；扫描不读取dotenv或真实值。凭据格式扫描PASS不是任意格式秘密不存在的绝对证明。最终完整性、Git diff --check、未跟踪文件、主metadata和运行资源核对见work/maint-s3b3/20261018/verification-final.json。

S3-B3完成后暂停。真实模型请求0，未打开收费/模型出口、提高预算、启用模型槽位、签发Permit、控制主Runner或向主库写入。不自动部署，不进入P6。
