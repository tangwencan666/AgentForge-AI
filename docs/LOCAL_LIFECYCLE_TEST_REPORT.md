# P5-LIVE 启动防覆盖修复验收

> **最新修复结论（2026-10-16）：PASS — THREE SEAL ISSUES FIXED AND VERIFIED。** 后续明确授权下已实际修复SEAL-S1/S2/S3，新增261项；最终去重600项通过、0失败、0跳过（最终离线588+本轮此前已通过且源码未变的12项生命周期）。Windows可信替身使用最新生命周期源码通过。原API/Worker保持运行、零费用门禁保持；没有真实模型请求或Git提交。完整记录见[P5_SEAL_FIX_REPORT](P5_SEAL_FIX_REPORT.md)。下文450项及只读BLOCKED为此前不同时间证据，不能冒充本轮成绩或当前源码状态。封版审计与提交仍待单独批准。

2026-10-16，Asia/Shanghai；项目 D:\AIProjects\AgentForge-AI。HEAD 保持 982e83ef32b7d274e820d59ee63d6fb76bd8979e，未重置、暂存或提交。本轮保留原有 P5-LIVE-SAFETY 未提交代码，不实施 P6，不使用真实模型凭据、不发送收费请求。

## 结论与证据

修复和本地无费用验收通过。最终两组 Python 共 **450 项通过，0失败，0跳过**，不累计重复执行：

| 范围 | 实际结果 | 证据 |
| --- | --- | --- |
| 单元/HTTP | 339通过，含12项生命周期验收、21项 Permit 子进程身份测试 | work/lifecycle-p5.xml |
| P5真实本机集成 | 59通过：依赖3、Provider Stub30、运行状态1、Permit25；含2项实际OS崩溃 | 同上；完整组398通过，290.80秒 |
| P3真实Docker | 16通过 | work/lifecycle-real-p3p4.xml |
| P4真实MCP/数据库 | 36通过 | 同上；完整组52通过，115.94秒 |
| PowerShell | 14份文件语法通过；旧身份谓词6项通过 | 本轮命令输出；旧谓词不再作为终止授权 |
| 前端 | TypeScript及Vite构建通过，60模块 | scripts/test-offline.py --frontend；使用现有依赖 |

首轮完整组为397通过、1失败，原证据保留 work/lifecycle-p5-first.xml。唯一失败是 P5 Coder → P3 真实沙箱 → Reviewer 的 AGENT_SANDBOX_FAILED：克隆 Runner28120未运行。当时为避免两个 Runner 对共享执行标签并发对账，只运行了主 Runner。确认零执行容器后，停止本项目主 Runner、启动既有克隆 Runner，再重跑完整398项全部通过；未修改业务代码、验收断言或降低安全规则。

一次 Alembic path_separator 弃用警告仍存在，不影响通过；本轮不扩大到修改迁移配置。未重跑浏览器E2E；没有前端源码变更，也没有为浏览器启动主服务。历史浏览器数量不计入450。

## 保护验收对应关系

tests/unit/test_lifecycle_manager.py 的12个隔离场景分别覆盖：有假Key启动、无Key维护拒绝、测试停止拒绝、finally拒绝覆盖、并发启动、过期/复用PID不误杀、已退出状态清理、无保护时Mock可启动、拒绝无业务副作用、秘密不进入证据、关闭门禁保持、P3/P4安全源码不被管理器改动。

其中 NativeBackend 实际启动链复制三份生产生命周期脚本到项目 work 子目录，通过真实 Windows venv转发进程、创建FILETIME、原生环境继承、一次启动claim、固定bootstrap和随机本地端口验证。API/Worker应用是明确的可信标准库 stub，仅用假Key；不是实际FastAPI/Worker或供应商认证。其余 FakeBackend 场景是明确逻辑替身。并发场景包含另一个OS进程争锁；锁释放、锁建立失败、错误创建时间、未知启动意图、人工确认与保护记录保留均验证，不宣称主动强制真实Windows复用某个PID或穷尽所有断电窗口。

拒绝无业务副作用的用例保存任务哨兵/manifest字节并安装禁止socket、SQLite和子进程的审计钩子，确认未导入SQLAlchemy/Redis业务模块；这是离线无调用证明，不冒充真实数据库事务对照测试。

Permit的25项使用独立克隆PostgreSQL25432/Redis26379及假凭据/虚拟HTTP。两个OS案例确实终止绑定句柄的fixture进程、等待真实租约到期并启动新的恢复进程：CLAIMED → ABORTED且派发0，DISPATCH_COMMITTED → UNKNOWN且派发1，均不重发。work/permit-process-tests 下本轮evidence.json保留双进程身份及0外部请求；旧测试的业务断言未删除或改为skip。

## Docker、MCP与清理

P3实际执行验证Python输出、无网络、UID10001、只读根、seccomp2、NoNewPrivs1、capabilities全零、无敏感环境名及Socket、宿主非敏感标记不可读、CPU实际节流、受限内存/PIDs、超时/取消、输出截断、跨任务隔离、幂等与并发、不可用daemon安全失败。P4实际启动受控MCP子进程和真实数据库事务，验证授权/审批/租户/Schema/审计失败、幂等回执及Skills生命周期；故障注入仍明确为故障测试。

Docker Desktop Linux VM结果不证明Windows/VM逃逸绝对不可能；不可信执行容器无Socket，可信Runner仍拥有daemon管理权限，残余风险见SANDBOX_SECURITY。未下载镜像、安装组件、改全局配置或执行宿主不可信代码。

专用故障Runner已删除，执行标签查询为空；无生命周期/Permit测试子进程残留。克隆Runner/PG/Redis均已停止，全部数据卷保留。主PG15432/Redis16379健康，主Runner18120恢复；主API、Worker及前端没有启动。

收尾只读核对曾正确阻断：P3容量测试留下4条 cancel_requested 父任务，执行已终态且容器已清理。按精确ID、创建时间、固定测试代码哈希、执行终态及清理状态确认归属后，仅调用既有Worker.sweep收敛为cancelled，保留事件和审计；未initialize/tick/publish/execute或启动守护进程。证据 work/lifecycle-test-state-cleanup.json。仍保留19条本轮终态测试任务的未发布Outbox，不删除、不强制发布；后续正常Worker处理时受终态/幂等检查约束。这些不是待执行的活动任务，也不能据此宣称数据库完全没有本轮测试记录。

## 最终门禁与使用

work/lifecycle-final-state.json只读确认主库0008、四槽Disabled、活动任务/活动Permit/真实模型操作0、日/测试预算0、真实及Permit开关false、Worker deny、重试0、出口阻断。实际执行 check-coder-local.py --before-restart通过；没有读取真实Key/Issuer值。主应用未运行，故不宣称当前API/Worker凭据观察为True，用户另一个PowerShell的存在状态不能替代运行时观察。

已覆盖受支持的全部本地脚本入口；旧P2/P3/P5恢复探针及非PolicyOnly原生继承探针安全拒绝。手工Docker app profile、直接uvicorn/python、操作系统终止和同用户修改代码不在合作式脚本保护边界内；未知实例安全拒绝，不能删锁/manifest解锁。Worker进程存活不等于业务就绪，真实Coder应用启动及环境存在观察留待用户执行。

用户可在已持Key且无Issuer的专用PowerShell中自行运行 scripts/start-coder-local.ps1；脚本仍会重新做全部前置检查。已匹配健康实例只复用；新Key重载/不匹配实例需独立人工停止流程，不自动替换。收费认证未验收、费用未开放，不进入P6。使用及实现说明见LOCAL_LIFECYCLE_GUARD、GETTING_STARTED和LEARNING_PATH第18节。

## 本轮文件范围

核心：scripts/lifecycle_manager.py、lifecycle.py、managed_service.py、lifecycle_regression.py、lifecycle-entry.ps1、stop-coder-local.ps1、check-coder-local.py。

入口：scripts/start-local.ps1、start-coder-local.ps1、stop-local.ps1、stop-worker.ps1、restart-worker.ps1、test-p2.ps1、test-p3.ps1、test-p4.ps1、test-p5.ps1；安全禁用scripts/p2-recovery-probe.py、p3-worker-recovery-probe.py、p5-worker-recovery-probe.py。

测试：tests/unit/test_lifecycle_manager.py、test_lifecycle_permit_child.py；tests/fixtures/lifecycle_acceptance.py、lifecycle_dummy.py、lifecycle_permit_child.py、coder-startup-probe.ps1；tests/integration/test_execution_permits.py。

文档：本报告、LOCAL_LIFECYCLE_GUARD、GETTING_STARTED、LEARNING_PATH、DEEPSEEK_CODER_LOCAL和PROJECT_STATUS。work内新增本轮诊断、XML和清理证据均被Git忽略，不包含真实模型秘密。未修改P0–P5历史阶段报告、业务实现、迁移、依赖清单或锁文件。本轮开始已有的大量这些目录下未提交变更仍保留，不能把整个git diff归因于本轮。

最终Git检查：49个已跟踪修改、57个未跟踪条目，索引为空，HEAD不变，git diff --check及cached检查通过；P0–P5历史报告无差异。该计数包含原有未提交改动。本轮源码/入口/测试/文档实际涉及32个文件。work/lifecycle-git-review.json保存非秘密摘要。凭据格式扫描243个工作文件、索引、前端产物和报告通过；使用--no-local-secrets，未读取dotenv或已知Key值，因此不等同于已知秘密比对。Runner最终认证状态available=true、blocked=false、active_executions=0，见work/lifecycle-infrastructure-final.json。

## P5最终封版只读复核（2026-10-16）

**BLOCKED — P5 SAFETY OR INTEGRITY ISSUE**

本节是用户批准的安全审计、只读验证、文档整理和待审批清单，不是再次开发或测试执行。此前450项通过的结果保留；本节发现的未覆盖缺口阻止“安全封版”。本轮不修改业务/生命周期源码、环境配置、预算、数据库、迁移、容器、进程或Git索引。没有执行start/stop/restart、维护测试、Worker初始化/sweep/publish/tick、真实模型请求或认证探测。

### A. 运行状态和真实启动证据

用户已在持Key的独立PowerShell完成真实应用启动。本轮11:40:15 +08:00重新验证当前事实；没有替用户再次启动。通过只读manifest解析、Windows进程创建FILETIME、实际可执行身份、固定bootstrap路径及实例UUID核对，再独立使用终止错误模式的CIM/TCP查询确认正常查询没有被误当空结果。没有调用会打开共享锁或写manifest的生命周期CLI。manifest在检查前后字节不变。

| 项目 | 本轮只读观察 |
| --- | --- |
| API | PID9872；2026-10-16 11:34:04.883913 +08创建；Protected/coder/running |
| API实例 | 470eba73-7284-4916-a2dc-e84b16234659；FILETIME134365952448839137 |
| Worker | PID17228；2026-10-16 11:34:10.425434 +08创建；Protected/coder/running |
| Worker实例 | df4e3e97-a984-456f-9fa0-c72ada1802fc；FILETIME134365952504254344 |
| 项目身份 | 两端固定D:\AIProjects\AgentForge-AI\scripts\managed_service.py路径和登记UUID匹配；不是仅按PID文件确认 |
| 监听 | 127.0.0.1:18100，OwningProcess9872 |
| GET /health/ready | HTTP200，data.status=ready；PostgreSQL/Redis均up |
| 数据库 | 只读REPEATABLE READ事务确认0008_execution_permits；未执行迁移 |
| Coder变量存在 | API=True、Worker=True；只读取已有运行状态布尔标记，不读取/打印/哈希/导出Key |
| 配置一致 | configuration_consistent=true，credential_presence_consistent=true；Worker观察在12秒有效期内 |
| 活动状态 | 全库非终态任务0，活动Permit0；未发布Outbox0 |

服务认证仅使用既有本机服务配置引用在内存中发送到固定loopback GET接口；不展示凭据、不读取模型Key或进程环境块。HTTP读取限健康及models/runtime-status；该GET仅查询数据库、Redis和环境变量名称成员关系，不派发模型请求。源代码和SQL均已先读审。没有把维护检查子进程的策略当作API/Worker策略，实际门禁值来自两个运行进程的观察。

此前报告中的“主应用未启动”和19条Outbox是上次收尾的历史事实；本次已观察用户启动后的服务及Outbox0，不推测或改写用户启动过程，本轮没有清理这些记录。

### B. 生命周期机制与审计缺口

已实现机制仍完整保留：稳定operation.lock使用Windows OS排他字节锁；同进程同线程仅在实际获锁后可重入；整个生命周期检查/审批消费/起停/清理持锁。实例用UUID、角色、真实Windows创建FILETIME和可执行身份绑定，venv转发父子分别核对；固定bootstrap验证启动意图、管理器创建身份和一次claim。停止使用同一OpenProcess句柄核对创建时间并终止/等待；保护记录在退出和人工停止后保留。普通维护/测试及finally不再自动恢复主服务；人工停止另行交互确认，没有force参数。

这些机制不能证明所有错误分支已默认拒绝。以下缺口为静态可达路径，不表示当前Protected实例已经被覆盖；本轮严格只读身份查询成功，服务保持正常。没有在受保护实例上执行故障注入。

| ID | 证据与影响 | 封版处置 |
| --- | --- | --- |
| SEAL-S1 | scripts/lifecycle_manager.py:217-234的_rows未强制CIM终止错误，忽略stderr，退出0时把空stdout转成[]；363-374的_listeners使用SilentlyContinue，也未区分查询失败与无监听 | 必须修复明确的查询成功/失败协议并隔离验证后复审；本次未修 |
| SEAL-S2 | scripts/p5-live-state-check.py --stop可直接暂停所有租户非Mock、非Sandbox未终态任务并清owner/lease、增加fence；configure-deepseek-coder.py直接运行可改槽位和维护配置；permit-test-runner-isolation.py pause/restore可直接起停主Runner；均未使用共享维护保护 | 需要将遗留一次性写入口纳入保护、审批或明确封存，并审查租户范围；本次未执行/修复 |
| SEAL-S3 | core/config.py:25-29的凭据分类排除Issuer名称，而p5-live-preflight.py:22把Issuer设置字段纳入allowed；prepare可从根dotenv或os.environ读取该签发权限，最终写入维护dotenv | 需要把Issuer权威凭据从两条准备路径明确拒绝并补隔离验收；本次没有执行prepare，也未检查真实Token值 |

S1的只读语义佐证：独立PowerShell执行可信的合成Write-Error随后ConvertTo-Json，返回码0、JSON[]、stderr存在；未调用CIM或任何生命周期函数。结合源码可证“只检查退出码”不能保证查询成功。已有Protected记录仍独立阻止普通Mock/stop/restart/maintenance，不能据此声称当前保护被直接绕过；未登记旧实例或普通Mock可能越过空发现结果的门禁，人工停止路径还可能错误标stopped而实际进程仍活。

S2不直接终止API/Worker，但可以干扰其任务、配置或依赖Runner，因此不能声称全部项目维护路径已共享保护。当前指南未推荐直接运行这些一次性写入口；遗留文件仍应在安全交付前作出明确处置。S3是具备Issuer的环境下的条件风险；未发现本轮发生复制，也没有为验证而读取秘密。

另有操作说明漂移：旧--roles all/coder参数和普通按钮测试说明已在本轮文档中更正。当前test-real-models.py只接受--permit-id观测，不签发/派发；它仍会写报告，本轮也没有运行。旧历史提案正文保留，并添加“不可作为当前操作指南”的说明。

### C. 零费用安全基线

API与Worker运行观察均为real_calls_enabled=false、permit_issuance_enabled=false、permit_required=true、daily_budget_usd=test_budget_usd=0、real_worker_mode=deny、external_calls_blocked=true、real_max_retries=0、credentials_env_only=true。数据库四槽planner/coder/researcher/reviewer全部Disabled；版本分别53/2/1/1。

主库真实模型操作账本0、Permit派发意图合计0、活动Permit0；本轮模型请求0。此“累计0”依据本应用数据库账本和派发计数，不是供应商独立账单或对机器全部网络流量的证明。Docker Engine只读查询29.7.2，execution标签容器查询为空；没有启动、停止或删除容器。

DeepSeek Key能否通过服务端认证、deepseek-flash标识是否实际可调用、真实推理质量/协议兼容和计费链路均**尚未验证**。本轮没有DNS/TLS认证探测，没有费用额度授权；Key存在不等于有效。P5离线/本地安全证据不能代替P6或真实模型测试，不能据此开启槽位、预算、Permit或出口。

### D. 450项历史证据及版本关联

本轮只读取XML元数据和用例名称，没有执行P2–P5测试、构建或OS崩溃测试。此前398+52=450，通过0失败0跳过；398含339单元/HTTP及59本机集成，52含16真实Docker和36真实MCP/数据库。前端类型/构建、14份PowerShell语法与6个旧谓词结果也仅属前次记录，不计入本轮执行。

| 本机保留证据 | 起始时间（+08） | 结果 | SHA256 |
| --- | --- | --- | --- |
| work/lifecycle-p5.xml | 2026-10-16 10:56:17 | 398/398，290.798秒 | 1d4284953f0b74f589427b895823ce2504018e0f41de1372a0396594d5c60f40 |
| work/lifecycle-real-p3p4.xml | 2026-10-16 10:47:32 | 52/52，115.937秒 | 2935579abe060da830cf781e51cc13a9a7372c52783db23193452625ef3b974e |
| work/lifecycle-p5-first.xml | 2026-10-16 10:50:23 | 397通过、1失败；故障证据保留 | f304f6e7973f42509157e7020e54f349952d56ccb40420f2af2bf0a4d0b04703 |

全部450个case名称可对应当前测试源；最终测试窗口内两份Native测试副本的lifecycle.py/lifecycle_manager.py/managed_service.py与当前字节哈希一致，两项Permit OS证据也在该窗口。XML没有完整Git树/源码指纹绑定，因此不把982e83ef这个旧提交称作包含450通过的新封版提交。本轮候选和非文档源码指纹记录于P5_SEAL_MANIFEST，不能倒称为历史指纹。450历史通过与当前发现的未覆盖故障路径分别记录。

### E. Git安全审计与提交准备

本轮起始真实根目录D:/AIProjects/AgentForge-AI，当前Codex会话位于项目外的Codex工作目录（不把个人用户目录写入交付）；所有Git/项目检查显式指定D项目，未切换、合并或复制旧工作树。分支main、原HEAD982e83ef32b7d274e820d59ee63d6fb76bd8979e。起始49个跟踪修改+57个status未跟踪条目；config/展开两文件，实际107文件。候选分类如下，不将既有改动归因于本轮：

| 分类 | 跟踪修改 | 未跟踪文件 |
| --- | --- | --- |
| 后端/迁移 | 17 | 8 |
| 根部署/公开配置 | 2 | 2 |
| 前端 | 7 | 3 |
| scripts | 13 | 19 |
| tests | 6 | 17 |
| docs | 4 | 9 |

逐项内容与P5/Permit/生命周期安全关联，未发现明确无关用户文件；关联不代替人工选择。git diff --check及cached check通过，索引为空。P0–P5既有阶段报告没有被本轮改写。候选没有数据库/备份/日志、二进制构建产物、意外个人Users路径；固定D项目路径属于明确部署约定。两个字面量凭据候选均有明确fake/test标识，未输出原值。

只读凭据格式扫描覆盖243个工作文件、索引、前端产物和历史报告；另对107候选扩展私钥头、提供商/GitHub/AWS标记及个人路径检查，无命中。使用--no-local-secrets，不读取本机真实Key做比对、不打印任何秘密原文；格式扫描有盲区，不能证明所有未知格式秘密均不存在。S3描述源码未来复制风险，不与“候选未检出秘密”混为一谈。

.gitignore已核对：实际.env/.env.local、work下manifest/备份/Redis配置、.venv、node_modules、dist、测试产物均被忽略；没有已跟踪的真实.env、日志、数据库、dump或work运行材料。所有备份/XML/日志/Outbox均保留不删除，work证据不提交。规则并不保证任意目录的新备份或秘密自动被忽略。

明确提交候选见P5_SEAL_MANIFEST，新增该文件后共108个候选（49跟踪、59未跟踪文件；status显示58未跟踪条目）。SEAL-S1/S2/S3的5个源码文件标HOLD；整个安全封版保持阻断，不通过只排除缺口文件给其余依赖代码打安全Tag。当前没有批准提交，未执行git add、commit、tag或push；同名Tag查询为空。

### F. 本轮实际文件改动与审批边界

仅文档：docs/LOCAL_LIFECYCLE_TEST_REPORT.md追加本节并前置最新结论；docs/PROJECT_STATUS.md追加当前状态；docs/LOCAL_LIFECYCLE_GUARD.md标注审计限制；docs/MODEL_INTEGRATION.md纠正运行观察、零重试及Permit专用观测说明；docs/P5_LIVE_DEEPSEEK.md给历史提案加非当前指南提示；新建docs/P5_SEAL_MANIFEST.md逐路径清单。未删除历史证据或源码内容，未改其他项目。

封版前需另行授权处置三项源码缺口，并在不影响当前Protected实例的隔离环境补足验收及源码版本绑定；之后再请求用户明确批准最终路径暂存、单个提交和Tag。建议提交消息chore(p5): finalize lifecycle safety and zero-cost acceptance；建议Tag p5-lifecycle-safe-baseline。Push另行批准，不包含P6或收费授权。本次停在审查交付点，不请求批准存在已知安全缺口的封版，不进行任何修复或生命周期操作。

收尾复核（2026-10-16 11:50:13 +08）：同一PID/UUID/创建时间的API9872和Worker17228仍Protected，健康HTTP200、PG/Redis UP、两端Key存在True、配置一致，四槽Disabled，关闭门禁/零费用保持；活动任务、Permit、真实模型操作、派发及Outbox均0。文档落盘后再次核对：49跟踪修改、58个未跟踪status条目（59文件），索引空，108文件与提交清单精确一致，非文档源码指纹未变；diff检查及最终244工作文件格式扫描通过，扩展108候选无秘密格式/私钥/个人路径命中。未提交、创建Tag或Push。本次仅6份文档有内容修改，最终封版结论仍BLOCKED。

## 三项缺口实际修复复验（后续授权，2026-10-16）

S1已统一严格CIM/TCP成功协议、候选元数据与两次创建身份核验，连同Permit fixture查询拒绝异常空结果；S2新增共同维护策略、独立审批、导出helper上下文/参数白名单及跨Task保护，完整入口清单见MAINTENANCE_ENTRIES；S3拒绝Issuer从父环境、dotenv或已有污染配置进入维护输出，查询及维护子进程只接收明确环境白名单，合法Coder服务继承保留。

新增261项：S1 83、S2 111、S3 65、镜像替换参数缩写2。完整596项在274.13秒通过、参数2项通过后，最终审查补齐精确Permit只读查询2项并复跑所有相关非原生588项，60.98秒全部通过；12项明确deselected，不是skip。这12项在本轮前组已通过、依赖的生命周期源码未变，合最终去重600项/0失败/0跳过；此前450不计入。首轮Windows替身寿命90秒导致1失败，身份检查正确拒绝；只延长可信替身寿命及场景等待，保留native.xml后复验通过。完整XML、指纹及初轮修正记录见P5_SEAL_FIX_REPORT。

12:40:41 +08再次只读确认原API9872/Worker17228的PID、原始FILETIME、UUID均不变且Protected，端口18100属9872，HTTP200/ready、PG/Redis UP、主库0008；两端Key存在布尔True、配置一致。四槽Disabled，真实/Permit关闭、预算0、Worker deny、出口阻断，活动任务/Permit、真实操作、Permit派发及待发布Outbox0。7个保护metadata内容、mtime、大小均与本轮起点一致；没有故障注入到主实例、业务写入或生命周期调用。12:35清点隔离测试进程0，执行标签容器0，主Runner保持Up、克隆栈保持Exited。真实Docker/MCP数据库及Permit崩溃集成本轮未重跑，原证据保留。

当前进程不会自动加载本次源码；健康仅证明未被本轮影响。DeepSeek认证、模型标识、实际推理/usage/计费及P6仍未验证、未授权。源码修复达到重新申请P5封版审计条件，未授权封版本身。Git工作和逐路径清单保留，未暂存/commit/tag/push。
