# S3-B0 主 Runner 兼容部署审查与 S3-B 操作计划

S3-B2准备提示：最新[S3B2_MAINTENANCE_RUNBOOK](S3B2_MAINTENANCE_RUNBOOK.md)将后续动作细化为R00–R15，列明每步独立授权、0008引导隔离、禁复起/物理退出、0009＋0010、新版默认FROZEN与失败恢复。下文B0/B1内容保留为历史审查，不构成执行授权；可信工具、保留UNKNOWN处置、主库新备份及真实Runner夹具缺失，实际部署和19项仍BLOCKED。本轮无主服务控制、主库写入、容器/网络删除或真实模型请求。

S3-B1修订提示：下文保留B0时点事实与B01–B14原计划。B1新增项目内冻结门禁及独立0010迁移，未来B08部署范围须明确包含0009＋0010，并先完成[SANDBOX_MAINTENANCE_FREEZE](SANDBOX_MAINTENANCE_FREEZE.md)中的可信交付和退场阻塞；0009单独升级不足以交付新门禁。B1没有执行主迁移/启停，14＋1历史待审和17＋2真实Sandbox继续BLOCKED。最新结果见[P5_LIVE_MAINT_S3B1_REPORT](P5_LIVE_MAINT_S3B1_REPORT.md)，不能把离线代码覆盖当作旧主Runner已被冻结。

日期：2026-10-18，Asia/Shanghai。项目：D:\AIProjects\AgentForge-AI。

结论：**REVIEW_COMPLETE / DEPLOYMENT_BLOCKED**。本轮完成源码和现状只读审查、离线推演及文档更新，不具备直接执行 S3-B 部署的条件。0009 主库迁移、Runner 启停、主 API/Worker 接管、19 项真实 Sandbox 测试均未执行；本轮外部模型请求为 0。S3-A 的 926 个不同 Python 用例、39 项归属专项是历史离线证据，本轮没有重跑或将其当作真实 Docker 验收。

## 1. 实时证据与可信范围

首轮主库只读采样为 13:26:41 +08，OS身份采样为 13:28:21 +08；其余运行时采样及收尾复核见本文末尾。Git HEAD 为 982e83ef32b7d274e820d59ee63d6fb76bd8979e，开始时索引为空、62 个已跟踪修改、94 个未跟踪文件。全部 P5-LIVE-SAFETY/S1/S2/S3-A 改动保留。

只读方法：Docker 有限字段 inspect、ps 发现线索、三份固定源码 docker cp 到内存；主库固定 SELECT 在 REPEATABLE READ / READ ONLY 事务中执行，设置局部查询超时并 ROLLBACK；Redis 仅 XLEN、XINFO GROUPS、XPENDING；固定回环 GET 和 Windows Python 进程身份查询。没有读取 Docker Config.Env、进程环境快照、模型 Key、Issuer Token、Runner proof、业务代码正文或模型回答。未运行会认领维护上下文、写锁或恢复服务的旧检查脚本。

### 主环境身份

| 对象 | 本轮实际结果 |
| --- | --- |
| Docker daemon ID | a2353ec2-7b5f-4343-a16b-8a04bc95ec51；只作为本次采样绑定，不保证未来不变 |
| 主 Runner 完整容器 ID | f2da347b403e96ba640d806eb8924ca91e389237de7e445858bfc8bb69c445d7 |
| 名称 / Compose 来源 | /agentforge-p3-runner；project=agentforge-p1、service=runner、working_dir=D:\AIProjects\AgentForge-AI；名称/标签仅为线索 |
| 实际镜像 ID | sha256:3e81842718ce5adf0d55a5fa82cd0f0505adf98faebdd1334c2c78e62b07ba5a；镜像引用 agentforge-p1-runner 不是不可变版本证据 |
| 状态 | running；StartedAt=2026-10-18T02:59:04.010046215Z；RestartCount=0；/health/live 返回 live |
| 启动 | python -m uvicorn app.sandbox.main:create_app --factory --host 0.0.0.0 --port 8000 --no-access-log；127.0.0.1:18120 → 8000 |
| 权限 / 挂载 / 重启 | Compose与实际inspect一致：user=0:0、read_only、cap_drop=ALL、no-new-privileges、384MiB/1 CPU/128 PIDs；实际只有 rw Docker socket 挂载，无源码 bind；restart=unless-stopped。配置限制不消除 Docker socket 的控制权 |
| 实际数据库连接 | pg_stat_activity 观察到 Runner IP 172.27.0.3 以 agentforge 用户连接 agentforge 数据库；未输出连接串 |
| 主 PostgreSQL | 7ea24834b4835bbb151257910a42d1891d7209c117eebc4e384fb7ce3e6c2d5d；固定 postgres:17-alpine 镜像；专属卷 agentforge-p1-postgres-data；127.0.0.1:15432；healthy |
| 主 Redis | 3acee09cc7d0dd806c8b855cb8b280b1a4ead9aa1a3a2e91a6162abad587e5f1；固定 redis:7.4-alpine 镜像；127.0.0.1:16379；healthy |
| 主库版本 | **0008_execution_permits**；0009 的身份、归属、审计三表均不存在；public schema owner=agentforge |
| 其他旧 Runner | agentforge-permit-tests-runner，ID=b48610ba603aa7e1b81c59300ade1736b8502b865213e6e38976e7d3469a0046，镜像 sha256:98e9f5eb948f6a6c9f923a6756530cf08c68a4e3879d9fb57b68913d15f5e9bd，exited、restart=no，仍配置 Docker socket；不可自动恢复 |
| socket 挂载者发现 | 本次全部容器有限字段查询仅发现上述两个 socket 挂载者，其中一个 running；这不证明不存在宿主/远端 daemon 客户端或将来新启动的旧清理器 |
| 主 API / Worker | 18100 GET 返回 ConnectError；本项目 Python API/Worker/管理器候选 0；旧 Compose backend/worker 容器为 exited；未自动恢复 |
| Coder Key 存在性 | **API=UNVERIFIED，Worker=UNVERIFIED**，没有可核验的运行进程/实时状态，不能复用历史 True/True，也不能改称当前 False/False |
| 生命周期保护 | 主 manifest 为 version=1、generation=4，保留旧 protected/running 记录；其中 PID 是历史记录，不是活跃身份证明。v2 入口拒绝旧记录，不能据此接管；manifest/audit/lock 未写入 |

旧 Runner 实际源码（固定容器内只读获取）的 SHA-256：

- driver.py：c1cb01f1782423ef99200e1d1c1ca96117d76ec23c48947ad7cbb70b7816474c
- engine.py：5015499eecb205c0171513275d5044c165b1c0cbda8c7b1c1ff9c180375caef9
- policy.py：93315d3f6b0496f8ccd9f696e4197efa0bf06c428cce4be267fa5d79cf10d85c

实际 driver.owned 按全局 agentforge.sandbox.policy=p3-python-v2 查询。engine.start 立即 reconcile，此后每 5 秒执行；候选只要满足旧名称/策略/execution 标签，且其自用数据库没有有效运行租约，就可能 remove，包括完全没有执行行的情况。实际镜像没有加载工作区 S3-A 改动。

### 历史执行、队列与未知结果

| 检查 | 结果与含义 |
| --- | --- |
| Sandbox 历史总数 | 334；全部为旧协议、无新版逐执行归属账本；P3 policy v1 有 4 条，v2 有 330 条 |
| 业务状态 | succeeded=118、cancelled=133、failed=23、rejected=20、timed_out=14、output_limit=12、needs_reconciliation=14；普通非终态 0，不等于未知结果 0 |
| 启动意图 / CID | 247 条已有 launch_claimed_at；246 条有各不相同且格式正确的完整 CID |
| 当前资源 | 策略标签、协议标签及旧执行名称发现候选 0；246 个历史 CID 精确 inspect 均明确返回 No such container，无其他错误 |
| 未知结果 | 14 条 needs_reconciliation 的 cleanup_status 均为 removed、CPU 预留均为 0，14 个 CID 在当前 daemon 均不存在；只证明当前资源缺席，不证明历史代码结果成功/失败或历史 daemon 身份 |
| 无 CID 的旧意图 | execution=8270a5b0-37d0-4410-b412-50507495c660，task=d96b6a7f-ba75-423c-9204-cee26b70eae9；policy v1，failed / not_created / DOCKER_UNAVAILABLE，2026-10-14T15:50:33.785623Z；预留 0。没有不可变 CID/daemon 账本，单靠错误码和当前标签扫描不能证明当时绝无 create；保留待审 |
| Sandbox CPU 账本 | 历史 used=2338.000、reserved=0.000；不删除、不重置历史用量 |
| Outbox | 所有未发布 0、Sandbox 未发布 0 |
| Redis | agentforge:p2:tasks 长度 1425；group=agentforge-p2-workers，consumers=704、pending=0、lag=0。消费者为历史元数据，不代表 704 个活进程；不删消息/消费组 |
| 真实模型 | model_operations 中非 Mock 行 0；Permit 总数/活动/UNKNOWN/dispatch_attempts 均 0；trusted_model_workers=0；真实费用/预留/测试次数账本均 0 |
| 模型槽位 | 四槽均 Disabled；Coder=openai_compatible/deepseek-flash，version=2；其他槽 provider/model 未配置 |
| 运行时收费门禁 | API/Worker 不可用，当前进程的开关、日/测试预算、出口、重试与配置一致性 **UNVERIFIED**。数据库零账本/停用槽位及历史 manifest 不能替代实时进程门禁证明。本轮没有打开任何门禁 |

14 条 needs_reconciliation 的 execution_id 保留如下，当前均无对应 CID 容器；没有在本轮修改状态、补发或生成归属：

| execution_id | 原因 |
| --- | --- |
| 8caf3d05-38ac-484b-8878-f718e45050ca | RUNNER_RESTART_AFTER_LAUNCH_INTENT，policy v1 |
| 7c5ca293-b89a-4597-92bb-60c3d640594b | RUNNER_RESTART_AFTER_LAUNCH_INTENT，policy v2 |
| 8286cdfa-77d7-4520-97f3-5afe732ceefd | RUNNER_LEASE_LOST |
| f460db95-3b53-4376-906a-e99b27c20ffc | RUNNER_LEASE_LOST |
| be7c46f3-03ee-45eb-a7d3-bd00226b1b0a | RUNNER_LEASE_LOST |
| d4f0ef95-ec1a-4463-b954-690e0f735591 | RUNNER_LEASE_LOST |
| 86b5f8ee-1dfa-4aa7-90b2-c277ffb5d6a5 | RUNNER_LEASE_LOST |
| 2625b900-d98f-4e2f-abde-0cc283420935 | RUNNER_LEASE_LOST |
| c4ee8b03-2831-4726-a1f0-debd94173236 | RUNNER_LEASE_LOST |
| 61f912b4-f95a-4bbc-aac0-b150fb37ef5b | RUNNER_LEASE_LOST |
| 09ddcf00-be26-48bf-9839-1f44d67c19aa | RUNNER_LEASE_LOST |
| 2dc6b18b-d3a4-4ee2-b8b2-a6d29f432152 | RUNNER_LEASE_LOST |
| 197a3f0b-e6ce-46c2-951d-6d6d5ead335c | RUNNER_LEASE_LOST |
| 558f3b44-733c-4938-9014-c9b226fa0e03 | RUNNER_LEASE_LOST |

这些结果仍未知。需要逐条只读核对原事件、审计、审批、历史基础设施证据并签署保留/隔离处置清单；无法核实的继续 BLOCKED。不得把当前 404 改写为成功、清空历史预留、当作未调用重新执行，或用普通维护批准替代原业务审批。

## 2. S3-A 实现审查与部署缺口

| 核心路径 | 已有实现及边界 |
| --- | --- |
| backend/app/domain/sandbox_ownership.py | 注册、逐执行账本、审计三表；没有对旧 Sandbox 记录自动认领 |
| backend/app/sandbox/ownership.py | provision_identity 可信内部原语生成 UUID/namespace/独立 proof；默认无兼容放行；注册行锁、30 秒租约、固定 generation/process_owner；每个有限动作校验真实持久化记录、精确 CID、P3 参数、Worker fence 和审批 |
| backend/app/sandbox/driver.py | 五项实例标签发现线索；daemon ID 校验；create 前持久化消费意图，bind 后精确 ID；stop/remove 前再验证；未知 create 不按名称补偿删除 |
| backend/app/sandbox/engine.py | 身份/兼容失败时 start 默认 blocked、无发现；恢复 join 本实例账本；外来/缺失记录拒绝操作；保留 P3 容量及未确认清理的全局阻断 |
| config.py、services/context.py | 私有 ID/generation/SecretStr proof 及脱敏；不是用模型 Key 或 Issuer 作为 Runner 身份 |
| repositories/connections.py、migrations/env.py | 新工作区代码识别 0008/0009；该结果不能证明旧镜像/API 已兼容 0009；Runner /health/live 也不是注册/对账就绪证明 |
| ownership 单元及 DB 专项 | 真实 PG 行锁/竞争与 Docker Stub；真实 SDK/Engine 的 create、注入、kill/remove、进程崩溃窗口未验收 |

当前不能直接部署的缺口：

1. **新旧不可安全并存**：新容器仍有旧策略/名称，旧 Runner 不理解新注册、generation 或兼容记录。升级只允许在已证明旧清理器停止且无法自动恢复后进行；不能蓝绿并行或自动回滚旧镜像。
2. **缺少完整部署控制面**：只有内部 provision_identity 原语，没有已验收的有限部署工具完成身份交付、兼容证据写入、代次/proof 轮换、退休与恢复。compose.yaml 未接入新身份配置。不能用临时 SQL、环境布尔值或通用 Force 代替。
3. **缺少统一持久化 Sandbox 维护准入门禁**：SandboxService.create/decide、P4 sandbox.execute、Agent 提案、Worker publish/claim/sweep/recovery、Runner dispatch 都可能参与派发。真实模型开关关闭不阻止 Sandbox。API 当前离线也不是重启后仍成立的冻结证明。需要可信维护 epoch、目标绑定和服务端检查，或在明确授权维护窗口中验证所有生产者/消费者与控制面均已隔离；不可仅停前端。
4. **主服务保护尚未接管**：version=1 历史 manifest 不可直接供 v2 接管。若维护方案需隔离/恢复 API/Worker，必须另有明确接管授权及迁移保护流程；现有普通启动入口不是绕过办法。
5. **历史处置证据不完整**：14 个未知执行结果及 1 个无 CID 旧意图保留阻塞项。无自动回填新版账本、改标签、转为新代次或重新派发路径。
6. **真实测试入口仍封锁**：S1 应用夹具固定 0008；conftest 拒绝 AGENTFORGE_RUN_SANDBOX，网络 guard 不授权 Runner，Playwright 排除 sandbox.spec.ts。需要后续专项实现并验收资源证明，不能删除保护后直接运行。
7. **默认配置不代表冻结配置**：Settings/Compose 中 real_max_retries 默认 2，model egress 默认并非全局阻断。新部署必须逐项显式验证 false/0/deny/blocked；不能裸用 Compose 默认值，不能导入真实 Key/Issuer 到 Runner 或测试子进程。
8. **租约不是 Docker 的原子 fencing**：事务提交到外部 Docker 动作间仍有暂停/崩溃窗口。升级与新代次切换必须证明旧进程实际退出、无在途动作，不能只等 30 秒租约或查一个 Redis key。权限范围外的 daemon 管理员仍属于可信边界。

旧脚本 scripts/permit-test-runner-isolation.py 的 pause/restore 保存名称和 was_running，restore 会启动旧主 Runner；maintenance_policy.py 仍有受控 runner.pause/runner.restore 命令白名单。它们不是 S3-B 的协议升级/恢复工具，必须保持禁用；本轮未运行或修改。scripts/test-p2.ps1 至 test-p5.ps1、旧 recovery probes、bootstrap-sandbox、Compose app/sandbox/sandbox-test profiles 及外部手动启动都要纳入窗口变更冻结清单，防止重新创建旧清理器。

## 3. 0009 主库迁移审查

文件：backend/migrations/versions/0009_sandbox_ownership.py；revision=0009_sandbox_ownership，down_revision=0008_execution_permits。

| 对象 | 结构与约束 |
| --- | --- |
| sandbox_runner_identities | runner_instance_id 主键；project_id 索引；namespace 唯一；generation > 0；daemon_id、proof_hash、可空兼容证据/时间、owner/lease、retired、created_at |
| sandbox_ownership | execution_id 主键且 FK → sandbox_executions；task_id FK → agent_tasks；runner ID FK → 注册表；CID 可空、唯一；协议固定 1 / generation > 0；六种状态 CHECK；固定策略/镜像、Worker owner/fence、时间 |
| sandbox_ownership_audit | UUID 主键、注册 FK、代次、可空 execution UUID、有限 action、resource JSONB、时间；execution 无 FK，允许保存缺业务记录的拒绝审计 |

upgrade 只有三表及一个 project 索引的新增 DDL，没有 UPDATE/DELETE/TRUNCATE、重命名旧表、字段类型改写、旧审批转换或容器操作。无额外 PostgreSQL extension 需求。UUID、generation、task/execution 跨行关联、proof 与配置等语义部分依靠服务端校验，不应把单字段 FK/CHECK 描述成完整复合归属约束。

P3 原表、P4 Gateway/Skills/审批、0008 Permit/费用账本没有迁移写入；历史行无新版账本是预期兼容状态。新所有权行的外键不带 CASCADE，新增历史后可能拒绝删除关联任务/执行/注册，这会影响未来保留与删除流程，需显式验收；不能为清理而临时级联删除。

**历史记录不能安全自动关联**：旧行没有项目/daemon/实例/代次/proof 等证据；名称、标签和已有审批不能制造新身份。issue() 还拒绝注册或兼容放行之前创建的执行。旧请求要继续执行必须走新的业务请求/审批，不迁移旧授权。

PG 事务性 DDL 可在正常失败时回滚，但加外键/DDL 需要锁；主库未来执行需短 lock_timeout、statement_timeout、固定目标及独占迁移者。超时、断连或版本不确定时停止派发并检查实际事务/版本/表结构，不能重跑 head 或删表强行通过。

**可逆边界**：downgrade 先检查三表任一有行即抛 SANDBOX_OWNERSHIP_HISTORY_PRESENT；空历史才允许降回 0008。创建注册本身即跨过“可无损直接 downgrade”的边界。保留审计的设计有意阻止非空降级，不是任意状态下可逆。不要删除身份/UNKNOWN/审计后降级。

主库迁移准备仍未完成：S3-A 仅在专属测试库做过空历史升降级与非空降级拒绝，不是本轮从主库生成的新备份/恢复验收。本轮只读，不创建备份、不迁移、不恢复。

后续获准维护窗口必须完成：

1. 验证完整 PG CID/镜像/Compose 来源、专属卷、数据库名/owner、0008、P3/P4/Permit 表及全部写入者；不把端口/名称单独当身份。
2. 持有项目维护授权并冻结写入后，将专属数据库 custom-format dump 写到仓库排除、访问受限的项目备份目录；不输出或复制 Key/Issuer/Runner proof，备份不进 Git。若部署后备份包含 proof 哈希等敏感业务字段，同样按受保护数据管理。
3. 记录文件长度/校验和，pg_restore --list 核验目录，然后实际恢复到重新证明归属的专属空库，验证 schema、约束、索引、行数和排序后的业务行指纹（只保留摘要，不输出原文/密码）；仅检查文件可读不足以通过。
4. 在恢复副本 0008 → 0009；比较所有原业务表结构/行指纹，检查新表为空、外键和 CHECK/唯一约束有效、API/P4/0008 Permit 只读兼容；在副本做空历史 downgrade/upgrade、独立假数据非空 downgrade 拒绝，保留恢复演练结果。
5. 只有上述证据有效、部署制品固定、历史处置完成才申请主库 0009。失败停在冻结状态，不删除原数据。不能用旧 0006/0007 检查脚本的硬编码版本代替 0009 专项复核。

## 4. S3-B 真实维护操作清单（全部为计划，尚未授权执行）

以下顺序是强依赖，不能跳步。每次人工确认须绑定固定 daemon、完整目标 CID/镜像、数据库、维护 epoch、有效期及单次操作；目标改变即失效。不使用通用 Force/SkipGuard，不借模型 Permit 或真实 Issuer 签发维护权限。尚未实现的工具须先获得项目内开发/隔离测试授权，不提供临时直连绕过替代。

| 步骤 | 前置条件 | 执行动作 | 影响范围 | 验证方法 | 失败停止条件与恢复策略 | 人工确认 |
| --- | --- | --- | --- | --- | --- | --- |
| B01 制品与窗口 | 本审查缺口已通过后续独立开发解决；待部署源码/镜像清单审阅完成 | 固定源文件摘要、不可变镜像、0009、依赖与维护窗口；登记写入者/旧启动入口负责人 | 仅项目部署材料，暂不启停服务 | 复核差异、敏感扫描、有限部署工具和审计；确认不导入真实 Key/Issuer、不开放模型 | 任何制品/身份不明则不开始；保持原状 | 是，批准确切范围；不包含收费或 P6 |
| B02 基线快照 | B01，daemon/主容器/卷/库已重新证明 | 只读盘点所有旧清理器、业务记录、CID、UNKNOWN、队列、API/Worker、生命周期记录 | 不写运行环境 | 完整 ID/镜像/StartedAt、源码摘要、socket 持有者、PG/Redis只读状态相互对应 | 新未知容器/双旧 Runner/记录不明即停；不清理获取通过 | 是，接受本次目标清单 |
| B03 冻结 Sandbox 入口 | 有可信持久化维护门禁；旧 API/Worker 的兼容及保护接管已另获批准 | 冻结新建、批准恢复、MCP/Agent提案、Outbox发布/Worker认领/恢复和 Runner 派发；读状态保留；必要时受控隔离生产者/消费者 | 可能中断 API/Worker 全部任务；若需其启停必须单独列入授权，禁止意外替换持 Key 实例 | 并发否定探针不能产生任务/Outbox/派发；所有实例确认维护 epoch；重启也默认拒绝 | 任一路径/离线实例不能证明冻结则停，不停止旧 Runner、不派发测试；门禁故障默认关闭 | 是，特别确认 API/Worker 的中断/保护流程 |
| B04 排空与历史处置 | B03 生效；真实模型、Permit、槽位、预算保持关闭 | 只读等待正常执行退出；取消中的资源通过原有限授权流程结束；逐项复核 14+1 清单；未知保留 | 可能等待或受控取消现有 Sandbox；不删除历史、不自动重发 | 两次稳定快照证明无 active/starting/canceling/在途 dispatch；每个旧 CID/未知意图有证据与处置结论 | 结果未知/身份不明无法核实则 BLOCKED，入口保持冻结；不能以超时强删或重置状态解锁 | 是，逐项处置；不自动把未知转成功 |
| B05 可恢复备份 | 目标库确认为 0008；全部写入者冻结 | 执行第3节新备份、独立恢复、业务指纹和0009副本升降级/拒绝降级演练 | 项目专属备份及独立恢复数据库；主库仅备份读取 | 校验和＋实际restore＋全原表一致性＋故障记录；备份路径不入Git | 备份不完整或恢复不一致则停止，不迁移；保留原主库/历史 | 是，批准备份/恢复目标；不批准恢复覆盖主库 |
| B06 停止全部旧清理器 | B03–B05 通过，固定完整主 CID/镜像/daemon，单次维护权限有效 | 通过审核过的有限工具撤掉本项目旧 Runner 自动启动路径/项目级重启策略，精确停止旧主 Runner；保持旧测试 Runner 禁用，禁止自动restore | **中断主 Runner**；不 stop PG/Redis、不停止其他项目 | 停止返回后检查完整CID State非running且Pid=0、退出时间、restart=no；源码/DB客户端/控制端口对应；审计操作 | 停止不确认、仍有旧清理进程/连接或无法防复起则不部署；冻结不解除，不扩大kill范围 | 是，Runner维护中断的独立确认 |
| B07 证明无旧清理活动 | B06 已确认，维护锁持续；无容器在创建/清理途中 | 等待旧SDK/线程退出及在途请求收敛；跨超过5秒对账周期和原30秒控制请求界限重复观察（至少两轮，建议60秒）；核查所有可复起入口 | 只读观测；主 Runner 继续停用 | CID无运行进程/restarts不增、无旧PG客户端、无旧18120监听、无本项目Docker创建/kill/destroy事件及目标变动；停止/请求审计互证 | 单纯日志安静/端口断开/租约过期不算证明；任何旧复起/在途不明则停止，保持冻结和旧版禁用 | 是，人工签署无旧清理器证据；不能只写compatibility字段 |
| B08 主库0009 | B05–B07通过，最终快照仍0008，唯一迁移者 | 仅升级至明确0009，有限锁/语句超时；不运行任意head | 专属主库DDL；API/Worker仍处于已批准维护状态 | 实际版本、新3表/约束/索引、原业务结构/行指纹、P4/0008保留一致 | 事务状态/版本/数据不明则停并只读核验；保持旧Runner停用；不可drop或删除数据强行重试 | 是，主库迁移单独确认 |
| B09 可信身份交付 | B08成功；已审阅的注册/安全交付工具存在；B07证据仍有效 | 服务端生成项目/实例/generation/namespace及独立proof，绑定精确daemon/DB/镜像；先无兼容放行；proof仅交给本Runner可信运行边界，不输出/进Git/进入APIWorker | 新注册与审计；非模型凭据；不导入Key/Issuer | 注册默认blocked，秘密存储/交付最小权限，API不能任意签发或更改；记录创建使直接downgrade保护生效 | 交付/身份不明则停，保留注册和审计；不重置代次/伪造状态 | 是，批准身份与可信运行边界 |
| B10 部署默认阻断新Runner | B09，旧清理器仍停、固定新镜像、精确启动配置 | 先在维护隔离态启动唯一新主Runner；无兼容证据、不派发、不创建测试容器；显式关闭模型/Permit/预算/重试/出口 | **主Runner替换**；API/Worker不自动恢复；可能尚无业务服务 | 认证元数据证明镜像/daemon/DB/实例/generation；/health/live仅存活；internal/status unavailable/blocked且无认领/发现/容器动作；PG/Redis正常 | 新Runner不默认blocked、身份回读不一致或旧Runner复起立即中止，不回滚旧清理器；保留新审计 | 是，批准唯一目标的新制品 |
| B11 兼容签署与注册认领 | B07持续证明＋B10，准入仍冻结，资源/历史全部明确 | 有限管理工具签署绑定daemon/目标代次/制品/窗口的兼容证据，再受控启动/重启相同新Runner完成claim；不得靠等待自动放行 | 新注册与当前Runner；仍无正式任务 | 当前实现start只尝试claim一次，不能假定补写后自动就绪；确认单owner/lease，旧owner拒绝，精确scope、审计可核验 | 竞争/旧代次/身份缺失/审计失败即停；不得重复放行或借新ID掩盖未知资源 | 是，签署与必要的同实例受控重启均列明 |
| B12 独立真实验收 | B11，19项专用隔离入口与全新PG/Redis/APIWorker/Runner资源证明已验收；主业务入口继续冻结 | 先运行新版跨实例/崩溃/失败清理专项，再17集成+2浏览器；模型始终Stub，主库不用于测试写入 | 仅获准的测试实例/容器；共享Engine也必须已无任何旧清理器 | 每个测试映射精确ID/归属审计、数据库/Redis/Stream/端口/生命周期记录；外部模型网络0 | 身份不明/主资源漂移/其他实例被触碰立即停；不批量删除；只有确认归属的测试资源可受控结束 | 是，真实Docker测试单独授权 |
| B13 收尾与停留 | B12通过或已安全失败；本实例资源已精确核对 | 清理已证明的测试资源，保留审计；重新核对主库/Runner/模型闭锁；交付报告 | 只管理本次精确资源；不删主数据/卷或未知资源 | 测试容器0、测试进程0或准确列出残留；19项实际结果、UNKNOWN/费用账本完整；主服务身份符合授权 | 无法确认清理则blocked并保留精确ID，不扩大范围；旧Runner继续禁用 | 是，确认收尾；失败不默认恢复 |
| B14 恢复正式业务（可不包含在S3-B） | 所有安全验收与历史处置通过；主APIWorker保护/凭据存在性、配置一致性已另行实时验收 | 获得单独确认后仅解除Sandbox维护准入；若需启动API/Worker，在用户持Key环境通过已批准接管流程，不接触Key值 | **可能影响API/Worker及正式Sandbox业务**；收费模型仍关闭，四槽Disabled、费用0、Permit签发关闭、deny、出口blocked、重试0 | 可信身份/代次、当前True/True或明确不要求模型凭据的停用状态、业务审批及资源策略、无双Runner | 不满足则维持维护停留；不为了恢复而裸跑start-local/旧restore；不借用已结束收费授权 | 是，不能由部署成功隐含批准 |

窗口内 PG/Redis无计划重启。B03/B14 可能中断 API/Worker，B06/B10/B11 明确中断或替换主 Runner；不能把这些影响隐藏在测试 finally。前端不需为 Runner 升级重启，是否维护展示由后续产品范围决定。

证明旧 Runner 不再清理的核心是**退出的实际进程＋禁止本项目复起路径＋在途动作已收敛＋维护互斥持续有效**，不是“日志没变化”。若无法证明，B07 后全部步骤 BLOCKED；不通过停整个 Docker Engine、修改全局策略或停止其他项目来获得证明。

## 5. 失败恢复矩阵

| 失败点 | 安全停留与恢复 |
| --- | --- |
| 旧Runner停止之前 | 不开新Runner/新容器、不迁移；维持已批准的冻结。若需解除冻结须确认没有半完成任务并另获批准 |
| 旧Runner停后、迁移前 | Runner维护中断保持，保留旧容器/镜像仅供审计；不得在finally自动start旧版。即使还无新容器，也须重新审查共享Engine资源后获得独立恢复授权 |
| 迁移失败/状态不明 | 确认DB事务和实际版本；PG事务回滚成功也不自动恢复旧清理器。出现部分表/版本漂移或原业务差异时阻塞，保留备份，另行批准恢复 |
| 0009成功且三表全空 | 只有验证空历史、无新版容器、没有写入差异后，才可另行批准受控downgrade；不是默认回滚。旧Runner恢复还需单独安全证明 |
| 注册/审计已存在 | 禁止普通downgrade；优先修复前进。需要数据恢复时先冻结全部写入并导出保留升级后账本/业务差异，在独立目标恢复验证，再另行批准切换，不能静默覆盖主库或删除UNKNOWN |
| 新Runner/新容器已存在 | 不允许自动回旧镜像；停新派发，对所有generation按精确ID对账。可证明本实例资源才清理；未知create或身份冲突保留审计/预留，Runner维护态保持 |
| 身份proof/代次/daemon异常 | 不重置注册、不重新发放身份掩盖旧资源；冻结并查明来源。proof恢复使用原可信交付流程，不经过聊天、日志、普通环境标志或模型Issuer |
| 测试或finally失败 | 测试侧仅认领本次资源；主服务恢复不是测试清理动作。无法重新证明归属时保留资源及准确残留清单并BLOCKED |

## 6. 17+2 真实 Sandbox 验收准备（未执行）

固定测试选择来自静态源码，不运行 pytest collection、fixture、浏览器或任何会访问主服务的测试入口。现有17项包括 test_sandbox.py 的13项、test_sandbox_failures.py 的3项，以及 test_real_agents.py 的1项；另有 sandbox.spec.ts 的2项。

| 来源与用例 | 后续真实验收重点 | B0结果 |
| --- | --- | --- |
| test_python_real_docker_execution_and_checkpoint | 实际受限容器执行、PG checkpoint、精确归属/移除 | BLOCKED，未执行 |
| test_runtime_network_identity_root_and_credentials | 无网络、非root、只读root、无Key/proof/Issuer注入 | BLOCKED，未执行 |
| test_host_marker_is_not_readable | 测试专属marker不可见，不触碰宿主业务文件 | BLOCKED，未执行 |
| test_cpu_quota_actually_throttles | 实际CPU限制 | BLOCKED，未执行 |
| test_memory_limit_bounded_allocation | 实际内存/交换限制 | BLOCKED，未执行 |
| test_pids_limit_bounded_spawn | 实际进程数上限 | BLOCKED，未执行 |
| test_timeout_kills_entire_container | 超时终止本实例精确CID及子进程 | BLOCKED，未执行 |
| test_cancel_kills_and_confirms_cleanup | 取消、本实例授权清理、404确认 | BLOCKED，未执行 |
| test_output_limit_truncates_and_removes | 输出上限、审计/清理 | BLOCKED，未执行 |
| test_no_state_leak_between_disposable_tasks | 一次性容器不共享状态 | BLOCKED，未执行 |
| test_rejection_never_launches | 审批拒绝不创建 | BLOCKED，未执行 |
| test_duplicate_messages_and_worker_restart_reuse_execution | 测试Redis重复消息/测试Worker重启不重复注入 | BLOCKED，未执行 |
| test_idempotent_create_and_secret_rejection | 幂等及假凭据拒绝，不读取真实秘密 | BLOCKED，未执行 |
| test_real_runner_tenant_and_global_capacity_with_live_containers | 测试库租户与全局容量；不停止主Worker | BLOCKED，未执行 |
| test_real_isolated_unavailable_runner_refuses_without_launch_or_host_fallback | 测试Runner独立故障endpoint，Docker不可用安全拒绝 | BLOCKED，未执行 |
| test_real_expired_runner_lease_cannot_revive_with_live_worker_lease | 测试Runner租约/fence不可复活 | BLOCKED，未执行 |
| test_coder_proposal_uses_real_p3_approval_runner_then_actual_review_evidence | Provider Stub→P4 Gateway→P3独立审批→真实测试容器→Reviewer Stub；无真实模型请求 | BLOCKED，未执行 |
| browser: approves and executes Python | 测试UI/后端、人工审批、真实输出和精确清理；trace关闭 | BLOCKED，未执行 |
| browser: rejects code execution | 测试UI拒绝不派发容器 | BLOCKED，未执行 |

运行前必须全部成立：

- 测试实例使用独立 API/Worker/Runner UUID、generation、namespace、端口、PID/创建时间清单、工作目录/日志/浏览器目标；主 18100/18120/15173、主数据库、主Redis不得成为写入/消费/终止目标。
- 测试数据库为 0009，独立PostgreSQL和Redis实例/数据资源；测试/主虽可使用同名Stream常量，但必须有不同的已证明Redis服务身份，不仅换DB编号或消息字段。
- 固定Engine/daemon ID/镜像；共享Engine模式下所有旧全局清理器已停止且不可复起。不能只靠改策略标签或容器名称隐藏资源。
- 测试注册、兼容证据、proof安全交付及实际进程身份已验证；不使用真实Key或Issuer，外部模型网络阻断，所有供应商Transport明确Stub。
- 测试资源由可信DB意图、精确CID、实例代次和实际容器P3配置共同授权；候选扫描不赋予删除权。容器未创建前没有CID的UNKNOWN不得按名称批删。
- 后续专项入口保留原S1防主资源保护并扩展有限Runner能力；测试fixture不能通过finally运行旧pause/restore。只对已证明本次资源请求有限取消/清理，失败保留残留及审计。
- 先补真实的新版跨实例双Runner隔离、代次切换、实际Runner崩溃/SDK在途恢复验证，再执行19项。离线PG并发/内存Docker Stub不能替代这些前置验收。
- 未通过的项继续BLOCKED；禁止用pytest跳过、配置忽略或Stub的通过数覆盖真实测试空白。测试结束对照主身份/时间及数据证据，精确确认本次容器/进程清理。

## 7. 交付、Git 与下一步

本轮只新增本计划，更新 SANDBOX_RUNNER_COMPATIBILITY.md 和 PROJECT_STATUS.md。没有修改源码/Compose/冻结配置/凭据/数据库/容器/生命周期文件，也没有创建测试资源。本轮模型调用、Sandbox执行、迁移和服务启停均为0。

提交建议：先按既有阶段组织审阅未提交的P5/S1/S2/S3-A依赖；本轮为独立文档增量。SANDBOX_RUNNER_COMPATIBILITY.md尚未跟踪，已有S3-A内容不可丢失；PROJECT_STATUS.md包含多阶段改动，需分块选择或先提交依赖。可由用户在Windows CMD审阅后手动执行以下命令，不应直接 git add -A：

~~~cmd
git diff --check
git diff -- docs/PROJECT_STATUS.md
git diff --no-index -- NUL docs/P5_LIVE_MAINT_S3B_PLAN.md
git diff --no-index -- NUL docs/SANDBOX_RUNNER_COMPATIBILITY.md
rem 审阅并组织好前置阶段后，再逐文件/分块暂存；本轮未执行：
git add -- docs/P5_LIVE_MAINT_S3B_PLAN.md docs/SANDBOX_RUNNER_COMPATIBILITY.md
git add -p -- docs/PROJECT_STATUS.md
git diff --cached --check
git diff --cached
git commit -m "docs: review Runner compatibility deployment gates and recovery plan"
~~~

git diff --no-index 对新增文件返回1表示存在差异，不能误当格式测试失败。

**是否满足申请S3-B直接部署的条件：否，BLOCKED。** 需要先单独授权并完成有限部署控制面、持久化准入冻结、兼容/身份交付和Runner专项隔离测试入口，补齐主库新备份恢复证明与14+1历史处置，并明确API/Worker保护接管范围。当前资料可用于讨论和申请上述准备工作，不构成部署放行；后续任何Runner中断、主库0009、真实Docker测试、API/Worker接管均需确切范围的另行授权。

### 本轮收尾复核

- 13:36:44 +08 主库再次READ ONLY确认：0008、Sandbox334/needs_reconciliation14/普通活动0、未发布Outbox0、真实模型操作0、Permit0、Enabled槽位0、归属表不存在；没有主库写入。
- 13:37:10 +08 主Runner完整CID/镜像/StartedAt/RestartCount0与首轮一致，实际Linux PID=1242、资源/权限限制与Compose一致；PG/Redis完整CID、StartedAt与RestartCount0也一致，healthy。没有对主服务执行启停、镜像变更或清理。
- 13:36:48 +08 固定API只读接口仍ConnectError，本项目Python进程候选0。当前API/Worker Key存在性及运行时政策保持UNVERIFIED；未读取Key或Issuer值，未因检查失败自动启动服务。
- Git HEAD不变，索引空；62个已跟踪修改、95个未跟踪文件，比基线只增加本计划。排除本轮三份授权文档后，其余154个既有修改文件内容摘要整体一致；主manifest/audit/lock的内容、大小和mtime与基线一致。
- git diff --check及暂存区空白检查通过；两份未跟踪文档独立no-index检查无空白错误输出（返回1表示有新增差异），另逐行空白检查三文档无错误。检查中有既有CRLF→LF提示，不执行换行修复。
- scripts/check_secrets.py --no-local-secrets 对280个Git候选文件、索引、现有bundle与P5-LIVE报告的凭据格式扫描通过；无敏感命名的dump/bak/key/pem/真实.env候选，.env及work内备份路径被忽略。扫描没有读取dotenv或真实Key作逐值比对，不保证发现所有未知秘密格式。
- 本轮未创建进程型测试实例、执行容器或数据栈，无本轮待清理资源；没有执行Python/浏览器回归或真实Docker实验。17+2仍BLOCKED，外部模型请求0；未暂存、提交或push。

完成后暂停，不自动进入S3-B实施或P6，之前收费授权不延续。
