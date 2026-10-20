# Sandbox Maintenance Freeze（S3-B1）

S3-B3修订：thaw在既有UNKNOWN检查之外，增加launch_claimed但无CID、且无可信ownership的历史意图拒绝。Worker发布/恢复/认领/执行/heartbeat/finish、批准和Runner/issue边界共用history.py的数据库事实派生隔离，旧意图不重放、不改写结果/审计/预留。正常新请求在一个事务中先issue归属后设置launch，提交后才接触外部IO；实际专属PG/Redis正反向验证见[P5_LIVE_MAINT_S3B3_REPORT](P5_LIVE_MAINT_S3B3_REPORT.md)。未增加普通客户端或环境变量解除方法，没有主库写入；主0008及旧Runner尚未加载本轮变更，以下B1机制/结果为历史说明。

状态：项目内实现、仅隔离验证；**未部署到主API/Worker/Runner，主库仍0008**。这份文档不授权实际冻结主服务、签发控制权限或部署。真实模型请求保持0，17+2真实Sandbox验收继续BLOCKED。

## 状态与持久化

新增独立迁移0010_sandbox_maintenance，依赖0009_sandbox_ownership，不修改0008/0009既有迁移。新表为sandbox_maintenance、sandbox_maintenance_authorities、sandbox_thaw_grants、sandbox_maintenance_audit。缺表、缺唯一状态行、未知状态或数据库不可读均拒绝新准入；配置布尔值、PID、Redis键、前端按钮不构成授权。迁移不写OPEN行，必须由后续可信部署原语显式初始化为FROZEN。

状态行在专属数据库内全Sandbox/租户生效，绑定deployment_id、daemon_id、单调epoch和更新时间：

| 状态 | 行为 |
| --- | --- |
| 无状态/UNVERIFIED | 新建、恢复批准、发布/认领、派发与代码注入默认拒绝；不根据缓存开放 |
| OPEN | 各边界仍须通过P3/P4业务权限、审批、预算、Worker fence和Runner归属检查 |
| DRAINING | 冻结请求已持久化，新准入立即拒绝；等待已获准的短派发窗口退出 |
| FROZEN | 封存时已取得派发窗口排他屏障；新派发仍拒绝；**不表示运行容器、未知结果或旧Runner已安全退出** |

每次合法freeze增加epoch并进入DRAINING，令旧解除授权失效；seal_freeze取得排他屏障才确认FROZEN。返回runner_quiescence_proven始终False，避免以一个数据库状态假称旧清理器已退出。已在运行的容器由原监控/超时规则继续处理；合法取消仍可请求，精确归属清理仍须原权限验证。UNKNOWN保留，不重发、不将其视为未执行。

## 原子性与外部IO边界

核心：backend/app/services/sandbox_maintenance.py。

- 新准入在业务事务中对状态行持有FOR SHARE；freeze用FOR UPDATE。先成功的准入属于冻结前意图，冻结提交后新事务不能继续通过；无法读到可信OPEN时拒绝。
- HTTP派发及Docker create/start/sendall使用数据库共享advisory事务锁。dispatch_window先取得共享锁，再读OPEN；只覆盖有时限的HTTP请求、SDK操作或一次代码传输，**不覆盖完整执行/输出流，不持业务行锁等待整个容器执行**。
- freeze先提交DRAINING，再用pg_try_advisory_xact_lock尝试排他屏障。若旧窗口尚未退出则返回DRAINING，不谎称已排空；后续可信seal操作可再次核验。新窗口即使取得共享锁，也会因DRAINING拒绝。
- 这同时覆盖“授权事务已提交、外部IO尚未开始”的本进程正常窗口。数据库断连、SDK超时、create响应未知等仍可能留下外部不确定结果；不能将advisory锁释放或FROZEN当作Docker物理动作已撤销。必须结合Ownership UNKNOWN、精确ID和实际进程退出证明，部署继续Fail Closed。
- 原P3启动意图和Ownership CREATE_COMMITTED在外部create之前持久化；本轮不重置这些状态。Docker仍无应用级原子条件删除/fencing事务，不作exactly-once外部承诺。

## 服务端覆盖矩阵

| 路径 | 门禁位置 |
| --- | --- |
| API /sandbox/executions | SandboxService.create业务事务，在新任务、审批、Outbox与CPU预留写入前检查 |
| API独立审批恢复 | SandboxService.decide仅approved路径检查；拒绝/取消不借机开放执行 |
| P4/Agent sandbox.execute | 既有AgentToolGateway校验权限/父任务后调用相同SandboxService；冻结无法创建子执行。已有结果读取不产生新派发 |
| Worker Outbox发布 | publish读取任务类型，冻结时保留Sandbox未发布行，不向Redis发布 |
| Worker认领 | claim在更新owner/fence/attempts之前检查；Redis重复消息/伪造OPEN键不能供给权限 |
| Worker恢复调度 | sweep冻结时不恢复/重排Sandbox，保留运行、取消中、UNKNOWN与资源预留；普通工作流仍保留原模型Permit门禁 |
| 已认领后才冻结 | 实际LangGraph审批/派发再检查；尚无启动意图的精确owner/fence可延迟回queued并释放本次租约，不完成为失败、不释放预算；已有启动意图和UNKNOWN不重置 |
| LangGraph HTTP派发 | sandbox_graph.execute中有限dispatch_window包裹HTTP POST；直接到该节点仍受门禁 |
| Runner dispatch | 未启动的执行在P3校验/启动意图事务中检查；已存在意图只返回持久化状态，不重复启动 |
| Runner逐执行归属意图 | OwnershipCoordinator.issue再次检查，与原P3意图共同提交 |
| Docker create/start/代码注入 | OwnershipCoordinator动作检查＋DockerDriver/ThreadAuthority短窗口；缺真实durable authority依然拒绝 |
| 状态展示 | API policy及认证Runner internal/status返回固定maintenance状态，无法核验时available=False；只读状态不能解除冻结 |

原P3 policy.py、安全资源限制、P4 Gateway业务权限、审批、模型Permit计数和外部出口没有解除。代码覆盖针对当前工作区入口；**运行中的旧镜像不包含新门禁**，不能用这张矩阵声称主环境已冻结。

## 独立解除授权

没有公共解除/签发HTTP入口，没有Force/SkipGuard、环境开关或Redis管理键。普通admin、模型、Chat请求和Sandbox审批令牌不能获得维护身份。

可信内部provision_maintenance生成彼此独立的operator/approver身份和随机SecretStr proof，数据库只保存哈希；proof不进入日志、API、SSE或审计，MaintenancePrincipal隐藏repr。它不是模型Key或Permit Issuer Token。初始化只在空控制状态下允许，默认FROZEN，不自动运行。

解除过程要求：独立approver proof验证→服务端生成一次性grant→指定operator proof验证→事务原子消费。授权绑定deployment、冻结epoch、指定operator/approver、目标Runner注册ID/generation、daemon、兼容evidence以及不超过60秒的有效期。目标退休、代次/daemon/兼容证据改变、过期、撤销身份、旧epoch或USED重放均拒绝。消费与FROZEN→OPEN/epoch增加、审计同事务提交；两个并发执行者只能一个成功。

解除前另外拒绝历史needs_reconciliation/unconfirmed，以及新版UNKNOWN/CREATE_COMMITTED/CLEANUP_INTENT。**当前主库14个未知结果会继续阻断解除**，不能删历史或加忽略参数。

可信部署工具、安全proof交付、实际旧Runner退场证明和兼容证据签署流程仍未实现为可部署控制面。内部primitive不是供普通PowerShell/客户端调用的命令，数据库中的evidence UUID不是Docker物理隔离证明。后续必须另行审阅并授权相关交付；本轮仅在独立测试schema用假身份和Stub兼容证据验证机制。

## 审计、恢复与信任边界

审计只包含动作、deployment/epoch、可信actor/grant UUID和服务端时间。合法操作与状态变更共同提交；拒绝在回滚后的独立事务记录固定REFUSED，不使用未经认证的actor或原始异常。数据库整体不可用时不能保证写入拒绝审计，但仍拒绝准入，不向缓存/本地文件回退开放。

源码是默认拒绝的服务端边界，不防御拥有数据库/daemon管理权限的恶意管理员或任意宿主代码执行。数据库行锁、有限控制函数和认证proof防普通客户端/模型滥用；不能把审计称作对DB管理员不可篡改的外部日志。

恢复备份必须先保持全部业务生产者/消费者和旧清理器隔离。恢复出的旧OPEN/epoch/grant不可直接作为当前放行；要通过独立审阅的恢复/代次流程重新冻结并核验，不能自动恢复服务或回退旧清理镜像。本轮不执行主库恢复。

0010仅新增4表，无旧业务数据转换；控制状态/authority/grant/audit任一有行时downgrade拒绝，不通过删审计来回退。0009的非空历史降级保护保持原样。主环境未来需要明确批准0009及0010，不能只升级到0009就使用新增门禁。

验证结果、已知失败与修复、主环境实时状态及窗口清单见[P5_LIVE_MAINT_S3B1_REPORT](P5_LIVE_MAINT_S3B1_REPORT.md)；逐条历史处置见[SANDBOX_HISTORY_RECONCILIATION](SANDBOX_HISTORY_RECONCILIATION.md)。所有真实Sandbox/模型执行仍未授权。
