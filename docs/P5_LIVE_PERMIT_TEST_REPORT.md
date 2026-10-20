# P5-LIVE-SAFETY 离线验收报告

后续部署更新（2026-10-15 22:53 +08:00）：已获单独授权并完成主库0008部署、新备份恢复与升降级演练；20张原业务表不变。本次全量Python **434通过**、浏览器 **15+1通过**，所有费用门禁关闭、真实外部请求0。主服务健康，当前API/Worker Coder凭据均False，凭据重载仍BLOCKED。详见[P5_LIVE_SAFETY_DEPLOYMENT_REPORT](P5_LIVE_SAFETY_DEPLOYMENT_REPORT.md)。下面421项及主库0007为上一轮离线修复的历史证据。

日期：2026-10-15，Asia/Shanghai。项目 `D:\AIProjects\AgentForge-AI`，HEAD `982e83ef32b7d274e820d59ee63d6fb76bd8979e`。本轮仅开发、迁移准备和离线验证，**真实外部模型请求0次**，不延用以前的一次收费授权，不进入P6，不自动暂存或提交。

**结论：本轮P5-LIVE-SAFETY离线修复验收PASS；真实供应商调用验收继续BLOCKED。** 最终恢复核验：2026-10-15 **22:32:35 +08:00 / 14:32:35 UTC**。主库保持0007；0008只在隔离副本验证。未取得新收费授权，不能开始真实调用。

## 实现与范围

新增服务端 Single-Use Execution Permit：固定Coder/DeepSeek请求、独立签发身份、可信Worker进程证明、PostgreSQL原子认领、HTTP前持久化派发意图、关联预算和哈希审计链。普通Chat、其它Agent、旧连接测试与后台真实模型入口全部拒绝；真正HTTP适配器还要求sealed派发能力。其它三个真实模型保持停用。

核心文件和完整状态机见 [P5_LIVE_PERMIT_DESIGN.md](P5_LIVE_PERMIT_DESIGN.md)。本轮新增/修改的关键路径：

- `backend/app/domain/permits.py`、`backend/migrations/versions/0008_execution_permits.py`。
- `backend/app/services/permit_authority.py`、`execution_permits.py`、`backend/app/api/v1/permits.py`。
- `services/tasks.py`、`services/orchestration/real_runtime.py`、`workers/engine.py`、`workers/main.py`、`providers/openai_compatible.py`。
- `.env.example`、`compose.yaml`、`scripts/start-local.ps1`：默认关闭、Worker不持有签发能力。
- `scripts/test-real-models.py`：只观察服务端已签发Permit，无ID为BLOCKED，不再创建普通Chat。
- `scripts/prepare-permit-tests.py`、`verify-permit-migration.py`、`permit-test-runner-isolation.py`、`verify-permit-restoration.py`：专属副本、备份、恢复与主服务复原。
- `tests/integration/test_execution_permits.py`、`tests/fixtures/permit_process_worker.py`、`tests/http/test_permit_api.py`、`tests/unit/test_permit_boundaries.py`、`frontend/tests/models-chat.spec.ts`。

既有DeepSeek兼容性准备及0007相关未提交文件保留；不把所有工作区差异都称为本轮新增。P3 Sandbox策略、独立审批、无网络/无宿主挂载/无Docker socket的执行容器，以及P4 Gateway/Skills权限生产代码没有降低限制。

## 已完成的验证

| 检查 | 结果与证据 |
| --- | --- |
| 单元与HTTP完整回归 | **293通过**，0失败/跳过，`work/p5-live-offline.xml`；禁所有网络及真实凭据继承 |
| Permit专项 | 最终**25通过**，包含在全量421中；此前23项独立运行通过 |
| 浏览器全部真实后端回归 | **15通过**，44.1秒，`work/p5-e2e.json`；含P3审批/执行、MCP/Skills与Permit拒绝 |
| 独立离线浏览器 | **1通过**；假后端，仅验证DeepSeek配置UI |
| TypeScript/Vite | 类型检查和构建通过 |
| PostgreSQL/Redis | 使用真实容器和项目app角色，无SQLite/fakeredis |
| 全量Python/P3/P4 | **421通过、0失败、0跳过**，239.80秒，`work/p5-all.xml`；1条Alembic配置弃用提示，无失败 |
| 迁移 | 原库备份、隔离恢复、0008升级/回退/再升级/metadata检查通过，20张原业务表一致 |
| 泄露扫描 | 已知服务秘密及常见编码扫描、无dotenv凭据格式扫描均通过；未读取真实模型Key作值比较 |
| 主服务恢复 | 主API18100/前端15173/Worker及主Runner恢复；配置一致，健康就绪；隔离3容器已停止，卷和证据保留 |
| Git检查 | HEAD未变、暂存区为空；diff --check通过，42个新增文件分别检查语法/空白/差异 |

测试中的Provider Stub、HTTP MockTransport和假Key均明确标识，不能作为真实DeepSeek认证、usage、收费或公网协议验收。旧多模型图测试显式使用授权与Provider双重测试替身，物理HTTP门禁仍未开放；新增Permit集成用例保留真实签发、身份、认领和派发门禁，仅替换物理Transport/DNS。

环境：Python3.13.5、FastAPI0.143.0、LangGraph1.2.15、HTTPX0.28.1、SQLAlchemy2.0.54、asyncpg0.32.0、Redis客户端7.4.1、pytest9.1.1。本轮未升级这些依赖。

## 并发与崩溃证据

数据库并发测试启动两个独立async session，由第三连接锁住Permit；`pg_stat_activity`实际观察两个不同PostgreSQL backend同时等待行锁，放锁后仅1个认领成功、另1个PERMIT_CONSUMED。仅1条ModelOperation，预留8256 Token / USD0.00253440，日测试次数1。另有两个不同Worker竞争：只有已绑定且持有随机内存证明的Worker获准；并发签发只能生成一个活动Permit。

最终全量运行的竞争backend PID为6372、6373，证据 `work/p5-live-permit-concurrency.json`。实际OS派发前PID24176→24036：ABORTED、dispatch上界0；派发后PID24352→6184：UNKNOWN、dispatch上界1、活跃预留USD0.00253440保留。历史Permit.reserved_cost在ABORTED后也保留，活跃日/任务预留才释放。

实际OS测试启动原生Python Worker子进程，分别阻塞在CLAIMED/DISPATCH前，以及DISPATCH_COMMITTED后的虚拟HTTP入口。核验归属后强制结束进程，等待真实20秒Worker租约过期，再由不同PID的新Worker恢复。前者ABORTED、活跃预留释放但认领/次数已消费；后者UNKNOWN、预留保留；两者均不重发。证据位于 `work/permit-process-tests/*/evidence.json`，均为虚拟请求，真实外部请求0。

UNKNOWN保留断言在真实数据库中检查完成。Fixture最终只清理本用例随机租户的明确虚拟测试数据，未删除主库任何真实费用或审计；证据文件保留。账本行数、派发意图上界和任务预算消费次数都不能冒充实际供应商HTTP请求数。

既有P5实际OS Worker恢复探针也通过：PID7444→7960，Planner仅1次、总计4次明确Provider Stub，任务succeeded，外部模型0；`work/p5-worker-restart.json`。它验证旧图checkpoint，不代表四模型真实API已验收。

其它用例覆盖：普通Coder Chat和其它角色拒绝、客户端字段伪造、公开admin不能签发、直接适配器/旧后台入口拒绝、重复Redis消息、过期/撤销/配置版本变化、请求指纹变化、并发预算不足、重复消费/状态重置拒绝、HTTP前后事务失败及提交确认丢失、超时/流中断/429/缺失usage/回答不符，以及等待HTTP期间可用NOWAIT获得Permit行锁。审计链重算验证通过。

## 迁移与备份

主库本轮**未应用0008，保持0007**。只在本项目隔离副本应用和验证0008。原库本轮没有新增真实调用或费用记录。

备份：`work/p5-live-preflight/permit-test/before-0008-20261015135302.dump`，1,048,659字节，SHA256：

`80265efd7a6d492ccb00f7ad72ac68f6568abd4471103e03cac960d5337f8151`

隔离项目 `agentforge-permit-tests`；PostgreSQL25432、Redis26379、Runner28120、测试故障Runner28121、API28100、前端25173；数据库名agentforge，独立卷和端口。执行前核验Compose项目、工作目录和端口归属。没有修改其它项目数据库、Docker Desktop全局配置或系统组件。

0008仅新增3表、索引和单调状态触发器，不改已有业务表。空历史副本降级和恢复演练通过；存在Permit或审计时，降级必须拒绝，防止删除未知费用证据，该拒绝也有真实PG测试。

## 回归中发现并处理的问题

1. 主Runner与副本Runner共享P3标签、使用不同数据库，主Runner会把副本执行视为孤儿，导致CLEANUP_UNCONFIRMED。首错诊断155通过/1失败，旧工作流单文件30通过。确认主库无活动执行并验证容器归属后，测试期间暂停本项目主Runner；最终先停测试Runner，再恢复主Runner。未修改P3安全规则。
2. 第二次全量419通过/1失败：旧脱敏单测隐式依赖dotenv模式，而维护启动器强制env-only。单测改为显式选择假dotenv回退模式；生产仍env-only。修复后293单元/HTTP通过，最终全量重新执行。
3. 浏览器首次以错误cwd启动，4张测试截图写到项目外的临时work目录。立即停止该次运行，按创建时间和精确路径核验后移回本项目，并移除本次创建的空目录；没有处理其它文件。随后从frontend目录完整重跑15通过。

## 安全恢复与后续条件

只读最终恢复检查通过，证据 `work/p5-live-permit-restoration.json`：四槽位Disabled、真实总开关False、日/测试预算0、重试0、出口阻断、Permit签发False、Worker mode=deny、签发凭据未配置、活动真实任务0、真实ModelOperation总数0、执行容器0。原21张表（含alembic_version）结构及行指纹与备份完全一致。主服务健康；在0007上查询Permit明确503 PERMIT_MIGRATION_REQUIRED，不假装已经部署。

API与Worker的Coder凭据名称存在状态当前均为 **False**，配置摘要一致。此前持有真实Key的进程已停止；为避免读取/复制临时Key，恢复时使用无模型Key的维护环境，不能假定新进程继承用户另一个PowerShell里的变量。没有修改用户原PowerShell中的Key，也没有写入Key到文件、镜像、参数或日志。再次测试前需要用户持Key的PowerShell重新安全启动服务。

暂存区为空，HEAD不变。工作区包含此前DeepSeek准备以及本轮修复，建议人工完整审阅后合并成一次P5-LIVE提交；若分拆，需由用户按hunk选择，不能只提交0008而遗漏入口门禁。可在Windows CMD中手动执行（本轮没有执行）：

```bat
cd /d D:\AIProjects\AgentForge-AI
git diff --check
git status --short
git add .env.example compose.yaml backend config docs frontend scripts tests
git diff --cached --check
git diff --cached --stat
git commit -m "feat(p5-live): enforce single-use model execution permits"
```

不要添加`.env`、`work`、备份或真实凭据。新增文件逐项审阅清单为`work/p5-live-untracked-review.json`，完整差异为`work/p5-live-tracked.diff`、`work/p5-live-untracked.diff`。

当前只能完成修复的离线验收，**真实供应商验收继续BLOCKED**。再次真实测试之前仍须用户确认主库0008部署、备份与服务版本一致，重新从用户控制PowerShell安全继承Key，配置独立签发角色，再取得新的精确一次收费授权。不能恢复旧Permit或沿用已失效授权。

剩余风险：本地可信进程/数据库owner属于信任边界；UNKNOWN无自动对账/释放路径，须独立人工审查；真实供应商DNS/TLS、Key有效性、SSE协议、用量和账单尚未验证；应用预算为估算上界，不能保证供应商账单。原有Docker共享内核、可信Runner daemon权限及单本地管理员限制保留。
