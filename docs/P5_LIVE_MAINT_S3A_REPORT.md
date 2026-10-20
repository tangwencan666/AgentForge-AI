# P5-LIVE-MAINT-S3A 实现与离线验收

日期：2026-10-18（Asia/Shanghai）。项目：`D:\AIProjects\AgentForge-AI`。

结论：**S3A_LOCAL_OFFLINE_PASS / SHARED_ENGINE_DEPLOYMENT_BLOCKED**。项目内实现及离线验收完成；真实Docker部署/共存仍BLOCKED。没有部署主Runner、迁移主库或启用真实模型。

## 基线与修改范围

HEAD为`982e83ef32b7d274e820d59ee63d6fb76bd8979e`，开始时59个已跟踪修改、86个未跟踪文件，索引空。266个允许的源码/文档保存到`work/maint-s3a/20261018/source-baseline/`，未复制真实dotenv/模型Key/Issuer。P5-LIVE-SAFETY、S1、S2既有改动保留。

| 路径 | 实现 |
| --- | --- |
| backend/app/domain/sandbox_ownership.py | 私有Runner身份、逐执行归属、有限资源审计3表 |
| backend/app/sandbox/ownership.py | 协议1、可信proof、期望代次、兼容放行、行锁认领、动作边界及SDK线程桥接 |
| backend/app/sandbox/driver.py | 实例过滤、每次IO授权、精确ID清理、未知create不按名称补偿 |
| backend/app/sandbox/engine.py | 默认拒绝未注册/未放行，事务内归属意图，按本实例恢复，缺记录不删除 |
| backend/app/core/config.py、services/context.py | 私有注册locator/代次/SecretStr proof；proof脱敏 |
| backend/app/repositories/connections.py | 兼容0008及0009的结构健康校验 |
| backend/migrations/env.py、versions/0009_sandbox_ownership.py | 新元数据与仅增表迁移；拒绝抹除已有归属历史的降级 |
| tests/unit/test_sandbox_ownership.py、test_sandbox_runner_policy.py | 新协议/公共入口拒绝与原P3故障测试适配，明确区分policy-only替身 |
| tests/integration/test_sandbox_ownership_db.py、test_dependencies.py | 专属PG并发/恢复/伪造测试，兼容新增迁移检查 |
| 本报告、SANDBOX_OWNERSHIP_PROTOCOL.md、SANDBOX_RUNNER_COMPATIBILITY.md、PROJECT_STATUS.md | 协议、兼容部署、结果与剩余风险 |

完整归属和边界说明见[SANDBOX_OWNERSHIP_PROTOCOL](SANDBOX_OWNERSHIP_PROTOCOL.md)。未改变`policy.py`中的P3执行限制或P4/Permit授权业务规则；0009不认领、改写或删除旧业务数据。

## 测试证据与限制

证据位于`work/maint-s3a/20261018/`。最终数量以本报告收尾记录及XML为准；重跑不重复计数。

- 首轮P3单元58通过、1失败：一个已有输出限制用例漏接明确policy-only权限替身；补齐夹具后完整离线回归覆盖通过。没有放宽生产默认拒绝。
- 首轮24项真实PG＋Docker Stub通过；随后补充Worker fence、P3审批/预算重验和故障用例，扩为36项。旧中间迁移仅在第一测试栈使用，最终版本在全新栈重做空库升降级。
- 单元/HTTP首轮完整775项通过，排除16项单独原生生命周期用例；包含原生IPC，Docker/供应商均为替身。
- 第一次合并集成135通过、12失败：新增归属夹具留下模拟运行任务，占用后续Workflow的全局Worker容量。改为每例独立租户，并在fixture结束时仅将自己的模拟任务收束、清除模拟Worker租约；不改生产Worker、不删归属/UNKNOWN/预算审计、不将其用作真实恢复策略。全新数据栈重跑通过，原失败XML保留。

| 最终层次 | 实际结果与证据 |
| --- | --- |
| 单元/HTTP离线全批（排除16项单独生命周期） | **775通过**，`unit-final-v3.xml/log`；包含原生Win32 IPC和P3资源/审批策略、P4、Permit/预算；不含真实Docker |
| 全部非Sandbox集成 | **149通过，17项真实Sandbox排除**，`integration-final-v2.xml/log`，206.23秒；真实PG/Redis、受控MCP进程及Permit实际OS崩溃恢复，模型为明确虚拟Transport；包含38项当时的归属用例 |
| 最终归属专项 | **39通过**，`ownership-last.xml/log`，15.92秒；在第五个全新测试栈运行，含最后补充的“旧未派发执行不自动采用” |
| 归属单元补测 | **12通过**，`ownership-unit-last.xml/log`，其中11已包含在775中，新增1项显式DB Stub的业务执行读取缺失拒绝；不是实际PG删除约束验收 |
| 去重统计 | **926个不同Python用例最终通过**：775＋149＋1＋1；分批验证，不能累加重复回归。`test-summary.json`记录去重，无最终失败/跳过；17项排除单列 |
| 真实Sandbox/浏览器 | **0执行**；原17项集成＋2项浏览器继续BLOCKED，不算进925 |

所有模型Transport明确为Mock/Stub，不能算真实供应商验收；测试中的假预算/签发权限仅存在隔离对象和测试库，不改变主环境授权。有既有Alembic path_separator弃用警告，未为消除警告修改其他配置。

专属PG测试包括真实行锁竞争、两个Runner对象并发对账、同身份仅一方认领、恢复后旧owner拒绝、旧启动配置代次拒绝、伪造标签/缺失账本/精确ID不符、兼容默认拒绝、错误daemon、P3注入前审批/fence/预算拒绝、取消后精确清理、UNKNOWN不重派发及历史不可降级删除。这里的Runner为pytest进程内对象，Docker API全在内存；没有真实Runner进程或真实执行容器。

## 主环境与未验收部分

12:54 +08收尾只读确认：主Runner仍旧镜像，ID、StartedAt、RestartCount0未变；主PG/Redis的ID、启动时间及RestartCount同样未变。没有主服务启停、镜像替换、已有标签修改、旧记录迁移、全局Docker配置修改或新daemon安装。主API当前ConnectError，API/Worker Coder凭据均UNVERIFIED；当前主环境预算、槽位、任务数量也不能通过实时接口核实，未用历史True/True替代。本轮没有写主库，未声称实时查询到主库版本。

本轮5个PG/Redis测试栈均已按资源租约/镜像/挂载/标签及精确ID证明清理，未建测试Runner或执行容器。最终S1标签容器/网络0，P3策略标签执行容器0。归属审计导出不含proof或proof哈希、模型Key、Issuer或源代码；两个最终数据栈保留205/206条脱敏操作审计。清理结果见`cleanup-first-two.json`、`cleanup-regression-first.json`、`cleanup-final.json`。

13:01 +08只读OS收尾：本轮固定测试脚本范围的Python进程0；主生命周期manifest/audit/lock的哈希、大小和写入时间全部与S3-A基线相同。P3策略文件、P4 Gateway、模型Permit、生产Worker、DeepSeek冻结配置、生命周期启动脚本及S1测试保护的源码哈希不变。

外部真实模型请求0；真实Sandbox执行0。原17项Sandbox集成＋2项浏览器未执行、仍BLOCKED。真实Engine并发清理、实际Runner崩溃恢复、Windows/Linux部署身份交付及兼容维护窗口未验证。S1原生生命周期批次本轮不重跑，不能引用其成绩冒充S3A。

新旧协议仍不能证明安全共存；新注册默认没有兼容放行，未配置独立proof/期望代次时不发现或派发Docker资源。保留原策略标签，不通过改标签隐藏风险。共享daemon管理员、可信DB写入方和部署操作者属于信任边界；没有对恶意管理员的隔离保证。

同数据库的P3全局容量/配额及未确认清理阻断保留，并未改成按namespace独立配额。未知create没有可信ID时仍需受控人工对账；本轮不声称自动恢复所有外部崩溃窗口。

## 后续与提交

可以提交离线证据申请下一阶段维护方案审查，**不能直接升级/接管主Runner**。须另行批准独立daemon验证或停止旧清理器的维护方案、备份恢复、可信注册交付及17＋2真实验收；详见[SANDBOX_RUNNER_COMPATIBILITY](SANDBOX_RUNNER_COMPATIBILITY.md)。本轮不进入P6，旧收费授权不延续。

建议提交标题：`feat: add fenced Sandbox ownership protocol and offline isolation tests`。共享文件含原P5/S1改动，需按本轮增量分块审阅暂存；不得`git add -A`。建议先组织提交P5-LIVE-SAFETY/S1/S2基线，再提交本轮增量；0009依赖尚未提交的0008，不能把本轮补丁视作直接针对HEAD的自足提交。

新文件可逐项`git add --`，已有共享文件用`git add -p --`仅选择本轮修改，然后`git diff --cached --check`、`git diff --cached`复核，再由用户在Windows CMD执行`git commit -m "feat: add fenced Sandbox ownership protocol and offline isolation tests"`。本轮未执行任何暂存/commit/push。最终文件清单、独立增量补丁和扫描/元数据核对见`source-changes.json`、`s3a-review.patch`、`final-checks.json`。

Git收尾HEAD不变、索引空，62个已跟踪修改、94个未跟踪文件（含所有既有阶段工作）；本轮增量17个文件，无基线文件丢失。`git diff --check`通过，279个Git候选文件/索引/既有构建报告及787个本轮证据文件的凭据格式扫描无发现。没有读取真实Key逐值比较，格式扫描不作绝对无秘密保证。
