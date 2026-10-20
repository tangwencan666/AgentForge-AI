# 新旧 Runner 兼容与分阶段部署

## S3-B3 阻塞收敛（2026-10-18，未部署）

新增有限OfflineRetirementController与持久化单次意图/真实OS锁及进程竞争、崩溃不重发测试，全部Docker动作Stub，始终不授予真实部署权；生产控制适配/主version1保护交接/分权proof及实际退出证明仍未验收。历史数据库事实派生隔离覆盖Worker和Runner，原14＋1保持，另补无CID意图thaw拒绝；正常新launch与归属同事务。合成PG备份/实际restore、DDL锁故障回滚与恢复通过，未迁移主库。

只读daemon预检证明default和desktop-linux是**同一个实际Engine**。优先等待人工提供独立Linux daemon/VM、目标访问和有限夹具验收；在该独立Engine可另批先做19项而不停止主Runner，前提是旧清理器无法控制它。共享Engine路径仍须先实际禁复起/停止旧清理器，不能仅增加标签或namespace。

最终1035个不同Python用例分批通过（843单元/HTTP＋192集成的最终结果，初始整批191通过/1夹具失败及修复后7专项证据保留），新增51；17＋2真实Sandbox继续BLOCKED、0执行。主库仍0008、主Runner未启停、真实模型请求0。四项逐行门禁、最小动作和人工责任见[P5_LIVE_MAINT_S3B3_REPORT](P5_LIVE_MAINT_S3B3_REPORT.md)，本轮不具备直接申请主Runner维护执行的全部条件。

## S3-B2 准备更新（2026-10-18，未部署）

14:45 +08重新只读确认旧主Runner完整CID、旧镜像及StartedAt不变，仍running/restart=unless-stopped；主库0008，0009/0010七表不存在。334条历史元数据与B1一致，14＋1保留；主API仍ConnectError，凭据存在性UNVERIFIED。保留4个已停止测试数据容器及2个网络，未操作资源。

新增[S3B2_MAINTENANCE_RUNBOOK](S3B2_MAINTENANCE_RUNBOOK.md)，把0008外部入口隔离、可信禁复起/退场、主库新备份与0009/0010、FROZEN默认阻断交付、兼容签认、独立19项与主业务解除分成独立人工授权。没有安全的旧新蓝绿并行方案；失败不自动restore旧宽泛清理器。有限控制器/可信采集/proof交付/主保护交接及实际Runner夹具尚未交付，历史阻塞未解决，**实际部署和17＋2仍BLOCKED**。本轮24项纯离线复测通过，984项为解析确认的B1历史结果，未重跑。详见[P5_LIVE_MAINT_S3B2_REPORT](P5_LIVE_MAINT_S3B2_REPORT.md)。

## S3-B1 更新（项目内准备，未部署）

新增持久化Sandbox Maintenance Freeze，覆盖API创建/批准恢复、Agent/P4交接、Worker发布/认领/恢复、LangGraph HTTP派发、Runner意图及Docker create/start/注入。DRAINING阻止新准入，FROZEN封存短派发窗口；不把它当旧Runner已退场证明。独立operator/approver proof和绑定epoch/目标代次的单次解除授权无公共HTTP或环境旁路；未知历史继续阻止解除。详见[SANDBOX_MAINTENANCE_FREEZE](SANDBOX_MAINTENANCE_FREEZE.md)。

独立新增0010_sandbox_maintenance，不修改0008/0009历史迁移；未来实际交付必须审阅并明确批准0009和0010。本轮只在独立数据栈的测试schema/恢复副本演练；主库仍0008、旧Runner仍运行，未应用或启用任何主运行策略。合并回归发现PermitService原先只接受0008，已增加审查过8/9/10的白名单及0008约束/防重放触发器/唯一索引结构核验，保留原签发权限、预算和次数门禁。

334条历史记录已逐条只读核验；14条needs_reconciliation和1条无CID意图分别记录原状态、历史CID、旧runner_owner、事件序号/时间、当前Docker观察及缺失证据。246个精确CID当前不存在不构成历史结果已知证明；没有新归属回填、状态改写或自动重试。详见[SANDBOX_HISTORY_RECONCILIATION](SANDBOX_HISTORY_RECONCILIATION.md)。

新增retirement.py仅离线评估两次观测的身份、自动复起、控制进程和排空条件；即使Stub清单满足，也永不返回实际退场/部署授权。可信退场采集器、旧控制通道隔离、proof交付、主API/Worker保护接管以及真实Runner隔离夹具仍待后续授权；旧pause/restore仍不可用于协议升级恢复。

**实际部署及17+2真实Sandbox测试继续BLOCKED**。主环境未接管，旧Runner没有加载新门禁，不能证明全部已部署派发路径被冻结。故障时保持维护冻结及未知账本，不自动恢复旧全局清理器。最新测试、剩余阻塞及维护步骤见[P5_LIVE_MAINT_S3B1_REPORT](P5_LIVE_MAINT_S3B1_REPORT.md)。下文S3-B0/S3-A为历史审查。

## S3-B0 最新审查（2026-10-18）

当前结论：**REVIEW_COMPLETE / DEPLOYMENT_BLOCKED**。仅完成只读检查、离线推演与文档；主Runner未升级、主库未迁移，17项真实Sandbox集成及2项浏览器测试均未执行。完整事实、0009审查、逐步维护表和恢复矩阵见[P5_LIVE_MAINT_S3B_PLAN](P5_LIVE_MAINT_S3B_PLAN.md)。以下“阶段A/B/C”是S3-A历史建议，不是已授权部署命令；具体前置以S3-B0计划为准。

### 实际版本与资源

- 主Runner仍为完整CID f2da347b403e96ba640d806eb8924ca91e389237de7e445858bfc8bb69c445d7、镜像 sha256:3e81842718ce5adf0d55a5fa82cd0f0505adf98faebdd1334c2c78e62b07ba5a，running，StartedAt=2026-10-18T02:59:04.010046215Z，restart=unless-stopped。只有rw Docker socket，无源码bind；实际旧源码哈希与S2/S3-A证据一致。
- 旧版启动时立即对账，其后每5秒按全局P3策略标签发现；本库没有有效运行记录也可能删除。新协议仍保留原标签/名称，增加namespace并不能阻止旧版发现，因此**新旧运行清理器不可按已验证安全方式共存**。不允许蓝绿并行，也不能仅换标签躲避。
- 专属主库实时READ ONLY查询确认 **0008_execution_permits**；0009三表不存在。334条旧Sandbox执行，无普通活动执行，但14条needs_reconciliation仍为未知结果。它们的cleanup_status=removed、CPU预留0，246个历史精确CID在当前daemon全部明确不存在。当前标签/名称候选0不代表历史结果已知。
- 另有旧policy v1的执行8270a5b0-37d0-4410-b412-50507495c660已有启动意图但无CID，标记failed/not_created/DOCKER_UNAVAILABLE；当前证据不足以证明当时未创建容器，保留待审。历史没有daemon/新实例账本，不能自动补归属或重新派发。
- 旧测试Runner b48610ba603aa7e1b81c59300ade1736b8502b865213e6e38976e7d3469a0046 已退出、restart=no，仍配置socket；禁止被旧测试restore逻辑重新启动。本次socket挂载者发现仅有它和主Runner，但不据此声称不存在宿主/远端客户端。
- 主API连接失败，本项目Python API/Worker候选0，主Compose API/Worker为exited；当前两端Coder Key存在状态均 **UNVERIFIED**。主生命周期version1记录保留，不调用v2接管，不复用历史True/True。模型四槽Disabled；真实模型操作/Permit/费用及预留账本0。API/Worker运行时开关、重试和配置一致性无法实时核验。

### 兼容矩阵

| 组合 | 结论 |
| --- | --- |
| 旧主Runner运行＋新版测试Runner，共享Engine | **禁止**；旧全局发现可误清理新资源 |
| 只加新版实例标签/名称/数据库/Redis/端口 | 不解决旧清理器，仍BLOCKED |
| 旧Runner已停止，但可能被restart策略、Compose或旧restore复起 | 未证明隔离，仍BLOCKED |
| 旧清理器全部退出且无法自动恢复＋新版默认阻断启动 | 后续维护阶段可验证；本轮未执行，不能宣称生产隔离PASS |
| 两个新版Runner、不同可信注册/数据库/namespace，共享Engine | S3-A真实PG＋Docker Stub离线通过；真实Engine/进程并发及崩溃尚待授权验收 |
| 新协议容器/账本存在后自动回滚旧镜像 | **禁止**；旧版可能将新版资源当孤儿删除 |
| 新注册无proof/期望代次/兼容证据 | 默认blocked，不发现或变更容器；存活HTTP200不等于就绪 |
| 独立daemon | 可作为未来独立测试路径，但当前没有验证的新daemon；不自动安装、启动或回退共享Engine |

### 必须先补齐的控制能力

1. 持久化、默认拒绝的Sandbox维护准入，覆盖API新建/审批恢复、P4/Agent、Outbox/Worker恢复、Runner dispatch；真实模型关闭不等于Sandbox冻结。旧进程不能遵守新门禁时，需明确获准的生产者/消费者隔离和API/Worker保护接管，不能以其当前离线替代。
2. 有限、可审计、绑定daemon/数据库/完整CID/镜像/实例generation/维护epoch及有效期的部署工具。provision_identity仅内部原语，尚无已验收的注册、proof交付、兼容签署、代次轮换及退休流程；不使用临时SQL或任意命令入口。
3. 旧清理器退出的实际进程证据、在途Docker调用收敛、项目级复起入口冻结。不能只等租约、看Redis、看日志安静或查一个端口。目标变化或无法验证即失效，保持blocked。
4. 14个未知结果及1个无CID意图逐项核实/隔离处置，保留原审批、状态、费用和审计。当前404只证明当前daemon上资源缺席，不可转换历史成功、制造新归属或自动重试。
5. 主库新备份与实际恢复副本的0008→0009一致性及恢复演练。0009不改旧业务，空历史才允许downgrade；注册/审计任一有行即拒绝降级。
6. 保留S1防主资源保护的Runner专项测试入口。当前conftest、网络guard、固定0008夹具及Playwright明确阻止19项真实验收；不得通过取消保护放行。

### 维护窗口及安全恢复原则

按S3-B计划B01–B14顺序执行，所有写入/中断动作仍需另行授权。先冻结全部Sandbox生产者/消费者和派发，处理执行与历史，验证新备份；再精确停止并禁复起所有旧清理器，证明无在途操作；随后才可迁移主库0009、交付新身份、默认blocked部署、人工签署兼容证据、受控认领。当前start仅尝试claim一次，签署后需要明确的受控启动/重启，不能假定自动变为ready。

真实Docker专项及17+2测试使用独立PG/Redis/API/Worker/Runner/端口/工作目录和精确资源账本；测试finally不恢复主Runner，不批量删除未知容器。共享Engine模式下主Runner先完成旧版退出/新版切换且主业务入口继续冻结。

迁移或部署失败时保持准入冻结、旧清理器禁用、未知审计/预留保留。空表降级和备份恢复均需单独证明并批准；有新归属历史优先修复前进。不得调用旧permit-test-runner-isolation.py restore、自动Compose旧镜像或删除历史来回退。数据库/Redis无计划重启；Runner停止/替换明确中断Sandbox，必要的API/Worker隔离/恢复属于另外明确列出的影响范围。

**当前不满足直接申请执行部署的全部条件，保持BLOCKED。** 本轮只改三份文档，不启停Runner、不迁移主库、不接管主服务、不调用模型、不进入P6。

## S3-A 历史阶段记录

当前结论：**BLOCKED — 不允许在现有共享Engine派发新版测试容器**。S3-A没有启停或升级任何真实Runner，也没有安装daemon。

## 已核对的旧实例

2026-10-18只读核对：主Runner容器ID为`f2da347b403e96ba640d806eb8924ca91e389237de7e445858bfc8bb69c445d7`，镜像`sha256:3e81842718ce5adf0d55a5fa82cd0f0505adf98faebdd1334c2c78e62b07ba5a`，只有Docker socket挂载，没有项目源码bind mount。旧镜像driver按全局`agentforge.sandbox.policy=p3-python-v2`发现，engine可能清理其数据库中无有效记录的容器。

新版增加归属标签并不限制旧Runner的查询。原P3标签/名称仍存在，旧Runner可能误清理新版资源；仅修改新版过滤器不够。S3-A单元用例显式复现旧过滤器仍命中新标签的风险；不是用真实旧Runner启动测试容器证明。

## 阶段A：本轮已授权范围

实现协议、默认关闭的可信身份/兼容放行、0009迁移和离线测试。只有内存Docker API；专属PG/Redis用于事务与回归，未启动第二个Runner。主库不迁移、不重写旧执行、不修改已有容器标签、不启用真实模型/Permit。原17项Sandbox集成和2项浏览器继续BLOCKED。

## 阶段B：另行授权的验证与维护准备

优先由用户提供独立测试daemon及明确资源归属；验证固定endpoint、daemon ID和镜像，不回退共享Desktop。S3-A不安装或创建daemon，也不以特权DinD替代。

若必须共享Engine，需要明确批准的维护计划：盘点所有旧Runner及执行、确认无未完成派发，备份专属数据库并做恢复演练；受控暂停旧派发、停止全部旧清理器，验证无自动恢复/旧restart策略重新启动风险，保留未知资源，不强删。**这些动作本轮均未授权或执行。**

准备注册身份/代次/proof的安全交付、daemon和兼容证据记录；先复核迁移、旧审批/旧执行状态、生命周期脚本及健康检查。现有S1应用夹具仍固定0008并排除Runner；须另行调整专属验证入口，不能取消保护后直接跑旧测试。

## 阶段C：另行批准的升级与验收

只在阶段B证据充分并获批准后，应用0009到专属主库，部署固定新镜像、可信注册与精确daemon绑定，再签署兼容放行记录。不得自动为旧执行生成归属或重放代码。

先验证两个新版Runner的真实跨实例隔离和崩溃窗口，再运行17项集成、2项浏览器及P3/P4/Permit回归。完成精确资源清理、审计和主环境门禁复核，才讨论正式派发；真实模型收费依然需要单独授权。

## 失败与安全恢复

- 未配置身份/代次/proof、放行记录缺失、daemon不符、未知资源或审计故障：保持blocked，不创建或删除容器。
- 0009仅新增3表；空历史测试库可回退。有身份/归属/审计历史时downgrade明确拒绝，不能为回退删除记录。主库恢复须用经验证备份，保留升级后历史并另行批准。
- 一旦存在新版容器，不得直接启动旧镜像或回滚到全局清理器。先停止新派发，在明确维护授权下对账所有代次及精确ID；无法确认清零时继续阻塞，不能只降级源码。
- proof或代次异常不自动重置；未知create没有可信ID时不按名称找“同名”容器删除。保留预算与精确已知信息，申请受控资源恢复。

本轮离线结果可供申请后续维护方案审查，**不等于已满足直接升级/主服务接管条件**。主Runner仍旧版，真实Docker隔离/Runner进程崩溃/共存均未验收。
