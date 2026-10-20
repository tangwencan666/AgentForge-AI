# S3-B2 部署前准备审查报告

日期：2026-10-18，Asia/Shanghai。项目：`D:\AIProjects\AgentForge-AI`。

结论：**PREPARATION_COMPLETE / DEPLOYMENT_BLOCKED**。完成成果保护、当前资源只读核验、分阶段Git清单、可信退场/安全交接/迁移/恢复Runbook及24项离线复测。**尚不满足直接申请S3-B2实际部署的技术条件**，不能因文档齐全而跨过尚未交付的可信控制面、历史处置与测试夹具。

本轮主服务启停/接管0，主库写入/迁移0，Docker创建/停止/删除容器或网络0，真实外部模型请求0。没有使用已结束的收费授权，没有签发模型Permit或进入P6。

## 1. 成果保护和Git审计

HEAD=982e83ef32b7d274e820d59ee63d6fb76bd8979e。开始时索引空、66项tracked修改、106个untracked文件；291个Git候选源码/公开配置示例/测试/文档逐个保存SHA-256及排除凭据的源码副本，另保存tracked差异。证据在被Git排除的work/maint-s3b2/20261018，未复制dotenv、实际Key、Issuer或数据库备份。

P5-LIVE/Permit、封版修复、S1/S2/S3-A/B0/B1所有原文件保留，不reset/clean/add/commit/push。本轮不修改任何Python、PowerShell、TS或迁移/配置源码。新增三份文档、追加四份既有文档，最终起始291文件中仅4份预期文档变化；其余287份字节一致，主生命周期manifest/audit/lock内容及mtime不变。

审计范围是完整文件清单/哈希、Git差异、关键Permit/预算/派发/清理/维护路径、迁移及既有阶段证据；本轮不是对所有累积代码重新逐行验收，也不是重新运行全部984项或真实生命周期/Engine测试。没有用文档审查替代运行时安全证明。

逐项分批清单见[S3B2_GIT_DELIVERY_PLAN](S3B2_GIT_DELIVERY_PLAN.md)：起始172项分别归功能39、迁移5、Windows/维护入口49、测试51、文档28；新增本轮3份文档归文档批次。公共文件包含多个阶段改动，保留最终安全整体，不伪称每批独立可部署。所有批次待用户审核后在Windows CMD手动提交；提交不授权部署。

## 2. 本轮实际观察

主要只读观察时间14:45–14:47 +08；随后补查主库结构。证据：history-observation.json、runtime-observation.json、database-metadata.json、process-observation.json；主API使用现有只读GET观察器，不执行模型健康探测。

14:55 +08收尾再次只读观察：主Runner/PG/Redis及旧测试资源的身份、启动时间、重启计数和状态未变，334条历史元数据仍逐条一致；API仍ConnectError，主服务/本轮pytest进程候选0。最终观察另存final-observation，不覆盖B1或本轮初始证据。

| 项目 | 实际结果与限制 |
| --- | --- |
| daemon | a2353ec2-7b5f-4343-a16b-8a04bc95ec51 |
| 主Runner | f2da347b403e96ba640d806eb8924ca91e389237de7e445858bfc8bb69c445d7；镜像sha256:3e81842718ce5adf0d55a5fa82cd0f0505adf98faebdd1334c2c78e62b07ba5a；running，StartedAt=2026-10-18T02:59:04.010046215Z，RestartCount=0 |
| 归属/配置 | Compose agentforge-p1/runner、本项目working_dir、rw Docker socket、无源码bind/reload、restart=unless-stopped、18120；仍是旧宽泛清理器 |
| 实际旧源码 | 内存读取固定driver/engine/policy文件，仅记录摘要；与B1相同，不把工作区新实现视作已部署 |
| 主数据库 | 固定PG CID与来源核验；agentforge/owner=agentforge，READ ONLY事务；0008_execution_permits，23张业务表；0009/0010七张新表均不存在 |
| 主Redis | 固定CID只读XPENDING/XINFO；pending=0、lag=0，未消费/ACK/删除消息 |
| API/Worker | 18100 ConnectError；限定项目服务命令的Python候选0；**两端Coder Key存在性均UNVERIFIED**，没有沿用历史True/True，也不能报告False/False |
| 维护保护 | 主version1/generation4清单保留、未接管；没有调用会建立锁/审计的生命周期status或维护入口获取状态 |
| 模型账本 | enabled_slots=0，非Mock模型操作0、ExecutionPermit0、trusted_model_workers0、非Sandbox活动真实任务0 |
| 冻结配置 | 现有安全配置字节未变；本轮未打开真实调用/模型出口、提高预算或启用槽位；**运行时开关、API/Worker预算/重试及配置一致性因接口离线不可实时证明** |
| Docker socket持有容器 | 本轮全容器mount元数据观察到主旧Runner运行、旧测试Runner已退出；这不证明Windows/远端编排复起来源不存在 |
| 测试残留 | 之前4个PG/Redis容器仍exited、restart=no；2个网络保留，无连接容器；RECOVERY_REQUIRED不改写、不恢复、不删除 |

最初进程宽筛选短暂包含本轮只读观察脚本，不是API/Worker；随后按实际服务命令类别复核为0，未据此终止任何进程。没有读取容器Config.Env、实际模型Key或Issuer内容，没有输出完整命令行/敏感请求头。

## 3. 14＋1历史记录完整保留

逐条复核334条执行元数据，和B1最终快照完全一致：14条needs_reconciliation及1条缺CID启动意图仍保留原状态/原事件；246个历史完整CID在当前daemon均明确不存在，无其他inspect错误，当前P3策略候选0。这些观察不证明历史执行结果，也不构成自动清理或状态改写授权。

详细15项清单仍见[SANDBOX_HISTORY_RECONCILIATION](SANDBOX_HISTORY_RECONCILIATION.md)。无CID项8270a5b0-37d0-4410-b412-50507495c660原为failed/not_created、DOCKER_UNAVAILABLE，但create边界无法追溯，不能推断绝未创建。没有补新归属、修改成功/失败、删除审计或重发。

当前thaw实现明确检查needs_reconciliation/cleanup unconfirmed及新版UNKNOWN/CREATE_COMMITTED/CLEANUP_INTENT；14条会继续阻止解除。无CID的旧failed/not_created项仍需人工边界审阅，不能声称它已被每一条SQL检查单独覆盖。缺少保留未知结果的受控隔离处置方案时，主业务解除继续BLOCKED。

## 4. 迁移、备份和交接审查

0009新增3张归属表，0010新增4张维护表，不转换旧历史、不回填归属、不初始化OPEN；迁移文件本轮未改。0009/0010存在新记录/审计后，降级保护会拒绝删除历史。不能用删账本、重置状态或回滚到旧清理器来恢复。

本轮重新读取B1迁移测试源码与恢复报告，确认当时是合成0008旧记录的真实备份/独立实际restore，原23表数据与列结构一致、空历史可回放、非空降级拒绝。**没有创建当前主库新备份、没有对主库restore/升级、没有重跑真实PG迁移测试**。保留5份测试归档不等于五份都做过实际restore。

Runbook明确顺序：可信工具先交付→外部隔离旧入口→排空/未知签认→禁复起和精确停止旧清理器→证明物理退出及daemon在途请求收敛→主库新备份/独立恢复演练→0009→0010→FROZEN安装→新版默认阻断部署→兼容签认→独立真实隔离/17＋2→另批主业务解除。旧版不认识冻结表，不能用迁移替代入口隔离；不能新旧同时运行做蓝绿切换。

有限控制器、实际退场采集器、proof分权交付与主version1保护交接尚未交付。旧pause/restore仍有按名称和was_running自动恢复路径，明确禁止用于升级回退/finally。自动复起策略、Compose备用服务、测试/恢复脚本、其他终端/任务/远端控制来源须逐个核验，不能只改restart=no就宣称全覆盖。每个实际变更都需新授权，具体动作/影响/验证/停止条件/恢复/人工授权见[S3B2_MAINTENANCE_RUNBOOK](S3B2_MAINTENANCE_RUNBOOK.md)。

## 5. 本轮测试和证据层次

| 层次 | 本轮结果 | 证据/限制 |
| --- | --- | --- |
| 纯离线冻结/退场复测 | **24通过，0失败/错误/跳过，0.62秒** | tests/unit/test_sandbox_maintenance.py；Provider/DB/Docker均无真实连接；offline_guards拒绝网络，保留Windows标准库自管道例外 |
| 首次受限边界 | 50秒超时，没有通过结论 | 保留offline-restricted-timeout.log；异步Windows自管道受限后在原生IPC边界重跑，网络拒绝插件未移除；没有为此启停主服务 |
| S3-B1完整历史结果 | XML重新解析去重：800单元/HTTP＋184集成=**984个不同用例**，0失败/错误/跳过 | 历史证据保留，**本轮未重跑完整984**；中途失败批次也保留，不计为最终通过 |
| 生命周期真实Windows竞争 | 本轮未重跑 | 不用24项Stub退场用例宣传主实例身份/接管验收 |
| 主运行环境 | 只读实测 | 固定Docker/CID/PG/Redis/接口/进程观察，不是部署/恢复测试 |
| 迁移/恢复 | 源码和B1历史证据审阅 | 本轮没有真实迁移、备份、restore |
| 17真实Sandbox集成＋2浏览器 | **BLOCKED，0执行** | 旧Runner运行；新版Runner夹具未交付；现有conftest/preflight/Playwright保护保留 |

本轮没有创建任何Docker资源或使用遗留测试数据栈。测试进程退出，保留的旧测试容器/网络原状；不声称本轮清理了它们。所有真实模型请求仍0。

## 6. 19项执行前置与风险

需要独立API/Worker/Runner实例身份和代次、PG、Redis/Stream、全部端口（含故障Runner）、目录/日志/PID、浏览器目标、Docker namespace与可信归属账本；全程持隔离租约并拒绝主资源。旧清理器必须先被可信停止并阻断复起；新标签不能隐藏于旧全局扫描。

现有真实测试的标签查询仅作发现；finally中的service.cancel只有在目标已证明独立、归属持续有效时才安全。不能直接打开RUN_SANDBOX、删Playwright testIgnore、复用主URL或在失败后restore旧主Runner。先做实际跨实例/崩溃归属验证，再执行19项业务/浏览器验收；后续容器和网络删除必须明确列入授权。

剩余风险：可信操作工具/退场证据缺失、0008引导隔离未建立、主API/Worker离线及旧清单、外部复起渠道尚未穷尽、14＋1历史未决、主库新备份未验收、实际Engine隔离未验证。没有靠降低门禁把任何一项改为PASS。

## 7. 变更与最终校验

本轮新增：S3B2_MAINTENANCE_RUNBOOK.md、S3B2_GIT_DELIVERY_PLAN.md、本报告。追加：P5_LIVE_MAINT_S3B_PLAN.md、SANDBOX_RUNNER_COMPATIBILITY.md、SANDBOX_HISTORY_RECONCILIATION.md、PROJECT_STATUS.md。其余源码/配置/测试/迁移保持原字节。

最终Git为66项已跟踪修改、109个未跟踪文件，索引空、HEAD不变。git diff --check通过；294个工作候选文件、索引、既有前端bundle及P5-LIVE报告的凭据格式扫描通过，未跟踪文件另作内容/空白审查。Markdown本地链接、增量文件/主metadata/容器/网络核对结果见work/maint-s3b2/20261018/verification-final.json。凭据扫描只验证常见格式，不读取dotenv或进行真实Key比对，不能证明不存在任意格式秘密。

## 8. 申请结论

**不具备直接申请实际部署的完整前置条件，保持BLOCKED。** 已有可审阅的逐步维护卡和全部文件交付清单。下一次应先申请有限控制面/可信采集与proof交付、保留UNKNOWN处置、新Runner测试夹具的项目内开发及隔离验收；完成后按Runbook逐段申请主服务中断、备份迁移和部署/测试授权。

本轮完成后暂停，不接管主服务、不自动进入实施或P6。之前一次收费调用授权不延续。
