# S3-B2 未提交成果审计与分阶段Git交付计划

## 2026-10-19 归档进度与运行限制（保留原始计划）

G1 `f9fdd3e`（42）、G2 `c69ef53`（5）、G3 `41d2257`（50）、G4 `e9ced78`（57）已本地提交，G4 是 **Archive-only**；本轮 G5 仍为下文权威清单中的 32 个文档，未暂存/提交。以下原基线、文件清单、1035 项分批结果和维护计划均保留各自历史时点，不是当前所有 CI 通过或生产可部署的声明。最新状态以 [PROJECT_STATUS](PROJECT_STATUS.md) 顶部为准，**RUNTIME_ACCEPTANCE：RUNTIME_BLOCKED**。

2026-10-18 后续 G4 审查为 852 单元/HTTP 通过，首项 `fake_coder_protected_start` 失败（`CONTROL_CHANNEL_UNVERIFIED`，静态 `lifecycle_v2.py:167`），其余 15 个生命周期场景未执行；原始 IPC 故障尚未完成可信诊断。B1/B2/B3 的真实运行前提未解决，B4 仅离线修复；后续 49 项 Mock 专项不能替代该场景验收。17＋2 真实 Sandbox 仍 BLOCKED，旧 Runner 交接风险未解除，真实 DeepSeek 验收未完成。0009/0010 仅代码提交和隔离验证，最近主库证据仍为历史 0008；本轮未核验任何主运行状态或签发 Permit。

第 8 节 G1–G4 命令现仅作历史交付记录，不应重复提交；G5 应使用文档修正后新生成的固定 `e9ced78` 归档 Manifest 与只读检查器，不能沿用旧 BLOCKED 摘要。只修文档事实，不以测试排除、提高预算或降低安全门禁换取归档通过。详细失败证据的本地 ignored 路径见 PROJECT_STATUS；work 日志不纳入 32 文件。

最新封存审计：2026-10-18 S3-B3结束后，当前186项为66个tracked修改＋120个untracked，索引空，HEAD仍982e83ef32b7d274e820d59ee63d6fb76bd8979e。第6节是完整当前清单，第7–10节为本轮审计、精确Windows CMD暂存/提交命令、Docker路线决策及八项真实门禁。只更新本文件，不新增架构/基础设施模块；以下B2/B3段落保留各自历史时点，不把离线通过标为生产部署。

日期：2026-10-18。固定项目：`D:\AIProjects\AgentForge-AI`。

本轮不暂存、提交、推送或重置。HEAD=982e83ef32b7d274e820d59ee63d6fb76bd8979e，起始索引空，66项已跟踪修改、106个未跟踪文件。Git相对HEAD的差异横跨P5-LIVE、Permit、封版修复、S1/S2/S3-A/B0/B1，不能把整个diff标成单独S3-B2代码。

## 1. 成果保护与审核范围

291个Git候选源码/配置示例/测试/文档在本轮开始时逐文件计算SHA-256，并保存排除凭据的源码副本与tracked-start.patch。证据位于Git排除的work/maint-s3b2/20261018；未复制主dotenv、实际Key、Issuer、数据库备份或凭据文件。副本用于比对现有成果，没有自动恢复或覆盖工作区。

仓库索引和全部未跟踪文件均需检查，不能只看tracked diff。`work/`和`.env`被忽略不等于安全检查可以跳过：备份路径及实际凭据始终禁止暂存；若将来强制添加任意忽略文件，必须重新审核。本计划没有使用git add -A、git reset、git clean或权限绕过。

本轮只新增三份文档，更新兼容/历史/原计划/项目状态文字；功能代码、迁移、测试源码、安全配置和主生命周期元数据应与起始哈希完全一致。最终核对见本轮报告。

## 2. 推荐的审阅与提交顺序

| 批次 | 内容 | 必须一起审阅的安全关系 | 建议提交主题 |
| --- | --- | --- | --- |
| G1 功能与安全实现 | DeepSeek适配、四槽/费用、Single-Use Permit、Runner归属及冻结所有功能源码、API/Worker、前端真实状态和公开配置示例 | 真实adapter前的Permit、派发意图/预算、UNKNOWN保留；P3/P4审批与资源限制；未有控制状态时默认拒绝 | feat: harden P5 live permits and sandbox admission |
| G2 数据库迁移 | 0007→0008→0009→0010和受控迁移env支持 | 0008防重放约束/trigger，0009归属三表，0010维护四表，非空历史拒绝降级；不得改写已应用旧迁移 | feat: add versioned sandbox ownership and maintenance schema |
| G3 Windows生命周期及运行/测试入口 | Lifecycle v2、可信IPC、一次维护授权、全部受保护维护/启动入口、S1隔离入口、浏览器目标配置 | PID/创建时间/解释器/SID/代次/独占锁；旧入口finally和restore风险；拒绝主实例与旧清单自动接管 | feat: guard Windows lifecycle and isolate maintenance entrypoints |
| G4 测试与夹具 | Python单元/HTTP/PG/Redis/Stub、Windows隔离夹具、浏览器与离线Provider | 区分真实DB竞争、OS竞争、Stub与未跑真实Engine；不能移除RUN_SANDBOX拦截以求通过 | test: cover permits lifecycle ownership and maintenance freeze |
| G5 文档与证据索引 | 各阶段报告/设计/状态、Runbook和本计划 | 保留历史失败/未验证项目，不声称真实19项或收费调用验收；不提交work备份/密钥/运行日志 | docs: record staged safety delivery and blocked runner rollout |

这些是**审阅/提交批次，不是五个独立可部署版本**。G1引用G2结构，维护入口依赖G3，验证依赖G4，完整交付应固定G1–G5的同一最终源码摘要。若要求每个提交都可独立部署，应先在另获批准的隔离审阅工作区重构补丁并逐提交验收；本轮没有做，也不建议从多阶段共有文件中盲选hunk。

当前版本优先保证安全改动整体交付：不能单独提交/部署“打开真实调用、放开清理、移除测试保护”的局部hunk。backend/app/core/config.py、workers/engine.py、repositories/connections.py、services/sandbox.py、sandbox/engine.py等跨阶段文件应保留完整最终版本，审阅时关联全部阶段报告。不要为制造漂亮提交历史而覆盖旧未提交成果或改旧迁移。

## 3. 用户在Windows CMD的操作模板（本轮不执行）

先保存本次审核证据及源码摘要；当前.git只读不需要Codex提权。后续用户自行操作时，先使用下列只读命令复查，再按第4节逐批明确文件列表选择性暂存，禁止用目录通配或add -A代替清单：

```cmd
cd /d D:\AIProjects\AgentForge-AI
git rev-parse HEAD
git status --short
git diff --check
git diff --cached --name-status
```

每批人工核对实际文件内容、未跟踪文件与凭据格式后，使用`git add --`后跟该批审核过的明确路径；不要把这句描述当作含占位符的命令执行。`git diff --cached --check`及`git diff --cached`确认没有漏加门禁、意外删除或敏感数据，再使用第2节对应主题提交。提交会写.git，必须由用户在本地CMD执行；本轮没有生成/执行暂存脚本。

G2只把迁移纳入Git，**不授权应用主库迁移**。G3只提交保护实现，不授权接管主API/Worker或运行旧Runner pause/restore。G4提交测试，不授权真实Docker/模型测试。完成提交后重新确认最终树与本轮源码哈希一致、工作区和索引状态符合预期，并固定最终交付提交；不自动push或打发布标签。

## 4. 完整起始改动清单

下面逐项列出本轮起始172个改动文件（M=已跟踪修改，U=未跟踪）。同批源码与对应迁移/测试必须连同最终树审查；文件归批不代表源码最初产生于该单一阶段。新增S3-B2三份文档归G5，表后单列。

| 批次 | 状态 | 文件 |
| --- | --- | --- |
| G1 | M | .env.example |
| G1 | M | backend/app/api/v1/inference.py |
| G1 | U | backend/app/api/v1/permits.py |
| G1 | M | backend/app/api/v1/sandbox.py |
| G1 | M | backend/app/core/config.py |
| G1 | M | backend/app/domain/entities.py |
| G1 | U | backend/app/domain/permits.py |
| G1 | U | backend/app/domain/sandbox_maintenance.py |
| G1 | U | backend/app/domain/sandbox_ownership.py |
| G1 | M | backend/app/domain/tasks.py |
| G1 | M | backend/app/main.py |
| G1 | M | backend/app/providers/base.py |
| G1 | U | backend/app/providers/deepseek.py |
| G1 | M | backend/app/providers/openai_compatible.py |
| G1 | M | backend/app/providers/router.py |
| G1 | M | backend/app/repositories/connections.py |
| G1 | M | backend/app/sandbox/driver.py |
| G1 | M | backend/app/sandbox/engine.py |
| G1 | M | backend/app/sandbox/main.py |
| G1 | U | backend/app/sandbox/ownership.py |
| G1 | U | backend/app/sandbox/retirement.py |
| G1 | M | backend/app/schemas/models.py |
| G1 | M | backend/app/services/context.py |
| G1 | U | backend/app/services/execution_permits.py |
| G1 | U | backend/app/services/model_runtime_status.py |
| G1 | M | backend/app/services/models.py |
| G1 | M | backend/app/services/orchestration/real_runtime.py |
| G1 | M | backend/app/services/orchestration/sandbox_graph.py |
| G1 | U | backend/app/services/permit_authority.py |
| G1 | M | backend/app/services/sandbox.py |
| G1 | U | backend/app/services/sandbox_maintenance.py |
| G1 | M | backend/app/services/tasks.py |
| G1 | M | backend/app/workers/engine.py |
| G1 | M | backend/app/workers/main.py |
| G1 | M | compose.yaml |
| G1 | U | config/deepseek-coder-local.json |
| G1 | U | config/deepseek-preparation.json |
| G1 | M | frontend/src/pages/ModelCenter.tsx |
| G1 | M | frontend/vite.config.ts |
| G2 | M | backend/migrations/env.py |
| G2 | U | backend/migrations/versions/0007_deepseek.py |
| G2 | U | backend/migrations/versions/0008_execution_permits.py |
| G2 | U | backend/migrations/versions/0009_sandbox_ownership.py |
| G2 | U | backend/migrations/versions/0010_sandbox_maintenance.py |
| G3 | M | frontend/playwright.config.ts |
| G3 | U | frontend/playwright.offline.config.ts |
| G3 | M | scripts/bootstrap-p4.py |
| G3 | M | scripts/bootstrap-sandbox.py |
| G3 | M | scripts/bootstrap_local.py |
| G3 | U | scripts/check-coder-local.py |
| G3 | M | scripts/check_secrets.py |
| G3 | U | scripts/configure-deepseek-coder.py |
| G3 | U | scripts/deploy-permit-database.py |
| G3 | M | scripts/freeze-lock.py |
| G3 | U | scripts/lifecycle-entry.ps1 |
| G3 | U | scripts/lifecycle.py |
| G3 | U | scripts/lifecycle_channel.py |
| G3 | U | scripts/lifecycle_manager.py |
| G3 | U | scripts/lifecycle_regression.py |
| G3 | U | scripts/lifecycle_runtime.py |
| G3 | U | scripts/lifecycle_v2.py |
| G3 | U | scripts/lifecycle_windows.py |
| G3 | U | scripts/maintenance_policy.py |
| G3 | U | scripts/managed_service.py |
| G3 | M | scripts/migrate.py |
| G3 | M | scripts/p2-compose-probe.py |
| G3 | M | scripts/p2-recovery-probe.py |
| G3 | M | scripts/p3-worker-recovery-probe.py |
| G3 | U | scripts/p5-live-database-check.py |
| G3 | U | scripts/p5-live-preflight.py |
| G3 | U | scripts/p5-live-state-check.py |
| G3 | M | scripts/p5-worker-recovery-probe.py |
| G3 | U | scripts/permit-test-runner-isolation.py |
| G3 | U | scripts/prepare-permit-tests.py |
| G3 | M | scripts/process-ownership.ps1 |
| G3 | M | scripts/restart-worker.ps1 |
| G3 | U | scripts/s1_application_test.py |
| G3 | U | scripts/s1_isolation.py |
| G3 | U | scripts/s1_test_environment.py |
| G3 | U | scripts/start-coder-local.ps1 |
| G3 | M | scripts/start-local.ps1 |
| G3 | U | scripts/stop-coder-local.ps1 |
| G3 | M | scripts/stop-local.ps1 |
| G3 | M | scripts/stop-worker.ps1 |
| G3 | U | scripts/test-offline.py |
| G3 | M | scripts/test-p2.ps1 |
| G3 | M | scripts/test-p3.ps1 |
| G3 | M | scripts/test-p4.ps1 |
| G3 | M | scripts/test-p5.ps1 |
| G3 | M | scripts/test-real-models.py |
| G3 | U | scripts/verify-permit-deployment.py |
| G3 | U | scripts/verify-permit-migration.py |
| G3 | U | scripts/verify-permit-restoration.py |
| G4 | M | frontend/tests/capabilities.spec.ts |
| G4 | U | frontend/tests/deepseek-offline.spec.ts |
| G4 | M | frontend/tests/models-chat.spec.ts |
| G4 | U | frontend/tests/offline-server.mjs |
| G4 | M | frontend/tests/run-e2e.mjs |
| G4 | M | frontend/tests/sandbox.spec.ts |
| G4 | M | frontend/tests/smoke.spec.ts |
| G4 | M | frontend/tests/workflow.spec.ts |
| G4 | M | tests/conftest.py |
| G4 | U | tests/fixtures/coder-startup-probe.ps1 |
| G4 | U | tests/fixtures/lifecycle_acceptance.py |
| G4 | U | tests/fixtures/lifecycle_dummy.py |
| G4 | U | tests/fixtures/lifecycle_permit_child.py |
| G4 | U | tests/fixtures/offline_guards.py |
| G4 | U | tests/fixtures/permit_process_worker.py |
| G4 | U | tests/fixtures/preflight_guards.py |
| G4 | M | tests/fixtures/provider_stub_worker.py |
| G4 | U | tests/fixtures/s1_lifecycle_native.py |
| G4 | U | tests/fixtures/sandbox_database.py |
| G4 | U | tests/fixtures/seal_s2_probe.py |
| G4 | U | tests/fixtures/transport_permit_stub.py |
| G4 | M | tests/http/test_inference_api.py |
| G4 | U | tests/http/test_permit_api.py |
| G4 | M | tests/integration/test_dependencies.py |
| G4 | U | tests/integration/test_execution_permits.py |
| G4 | U | tests/integration/test_model_runtime_status.py |
| G4 | M | tests/integration/test_real_agents.py |
| G4 | M | tests/integration/test_sandbox_failures.py |
| G4 | U | tests/integration/test_sandbox_maintenance_db.py |
| G4 | U | tests/integration/test_sandbox_migrations_b1.py |
| G4 | U | tests/integration/test_sandbox_ownership_db.py |
| G4 | U | tests/unit/test_coder_local.py |
| G4 | U | tests/unit/test_deepseek.py |
| G4 | U | tests/unit/test_lifecycle_ipc_s1.py |
| G4 | U | tests/unit/test_lifecycle_manager.py |
| G4 | U | tests/unit/test_lifecycle_permit_child.py |
| G4 | U | tests/unit/test_lifecycle_v2_native.py |
| G4 | U | tests/unit/test_lifecycle_v2_scope.py |
| G4 | M | tests/unit/test_model_adapter.py |
| G4 | U | tests/unit/test_permit_boundaries.py |
| G4 | U | tests/unit/test_preflight_policy.py |
| G4 | U | tests/unit/test_s1_entry_isolation.py |
| G4 | U | tests/unit/test_s1_isolation.py |
| G4 | U | tests/unit/test_sandbox_maintenance.py |
| G4 | U | tests/unit/test_sandbox_ownership.py |
| G4 | M | tests/unit/test_sandbox_runner_policy.py |
| G4 | U | tests/unit/test_seal_entry_arguments.py |
| G4 | U | tests/unit/test_seal_s1_fixture_query.py |
| G4 | U | tests/unit/test_seal_s1_queries.py |
| G4 | U | tests/unit/test_seal_s2_maintenance.py |
| G4 | U | tests/unit/test_seal_s3_issuer.py |
| G5 | U | docs/DEEPSEEK_CODER_LOCAL.md |
| G5 | M | docs/GETTING_STARTED.md |
| G5 | M | docs/LEARNING_PATH.md |
| G5 | U | docs/LIFECYCLE_MANAGER_DESIGN.md |
| G5 | U | docs/LIFECYCLE_SECURITY_TESTS.md |
| G5 | U | docs/LOCAL_LIFECYCLE_GUARD.md |
| G5 | U | docs/LOCAL_LIFECYCLE_TEST_REPORT.md |
| G5 | U | docs/MAINTENANCE_ENTRIES.md |
| G5 | M | docs/MODEL_INTEGRATION.md |
| G5 | U | docs/P5_LIVE_DEEPSEEK.md |
| G5 | U | docs/P5_LIVE_FIRST_CALL_REPORT.md |
| G5 | U | docs/P5_LIVE_MAINT_S1_REPORT.md |
| G5 | U | docs/P5_LIVE_MAINT_S2_REPORT.md |
| G5 | U | docs/P5_LIVE_MAINT_S3A_REPORT.md |
| G5 | U | docs/P5_LIVE_MAINT_S3B1_REPORT.md |
| G5 | U | docs/P5_LIVE_MAINT_S3B_PLAN.md |
| G5 | U | docs/P5_LIVE_PERMIT_DESIGN.md |
| G5 | U | docs/P5_LIVE_PERMIT_TEST_REPORT.md |
| G5 | U | docs/P5_LIVE_PREFLIGHT_REPORT.md |
| G5 | U | docs/P5_LIVE_SAFETY_DEPLOYMENT_REPORT.md |
| G5 | U | docs/P5_SEAL_FIX_REPORT.md |
| G5 | U | docs/P5_SEAL_MANIFEST.md |
| G5 | M | docs/PROJECT_STATUS.md |
| G5 | U | docs/SANDBOX_HISTORY_RECONCILIATION.md |
| G5 | U | docs/SANDBOX_ISOLATION_DESIGN.md |
| G5 | U | docs/SANDBOX_MAINTENANCE_FREEZE.md |
| G5 | U | docs/SANDBOX_OWNERSHIP_PROTOCOL.md |
| G5 | U | docs/SANDBOX_RUNNER_COMPATIBILITY.md |

本轮新增G5文档：docs/S3B2_MAINTENANCE_RUNBOOK.md、docs/S3B2_GIT_DELIVERY_PLAN.md、docs/P5_LIVE_MAINT_S3B2_REPORT.md。其他本轮文档增量仍在原文件上追加，不覆盖历史报告。


## 5. 提交前停止条件

发现实际Key/Issuer/proof、数据库备份、临时凭据、完整环境或敏感请求头候选立即停止暂存，单独报告路径，不输出内容；没有授权不擅自删除或重写已有凭据。敏感扫描采用`check_secrets.py --no-local-secrets`，不读取dotenv或做真实Key比对，其PASS只能证明已检查的格式范围，不能排除任意格式秘密。

主库版本/Runner镜像与Git源码不一致是本次已知部署状态，不应为“同步”而运行迁移、Compose up或恢复脚本。当前19项真实Sandbox验收仍BLOCKED，后续Git提交不改变部署批准状态。全部安全缺口与维护授权见[S3B2_MAINTENANCE_RUNBOOK](S3B2_MAINTENANCE_RUNBOOK.md)。

## 6. S3-B3 精确交付附录（覆盖当前全部待提交条目）

以下清单基于S3-B3结束时实际git status --porcelain -uall，逐文件分批；第4节172项及B2三份文档的原清单保留。本轮新增退场/历史规则和测试不能只暂存某个放行hunk；0007–0010迁移文件不变，主环境不应用。提交主题沿用第2节，G1主题应补充historical quarantine/offline retirement，G3补充read-only daemon preflight。所有提交仍由用户在Windows CMD明确选择文件后执行；本轮没有git add/commit/push。

| 批次 | 状态 | 分类 | 精确文件路径 |
| --- | --- | --- | --- |
| G1 | M | 正式源码/公开配置/维护工具 | .env.example |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/api/v1/inference.py |
| G1 | U | 正式源码/公开配置/维护工具 | backend/app/api/v1/permits.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/api/v1/sandbox.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/core/config.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/domain/entities.py |
| G1 | U | 正式源码/公开配置/维护工具 | backend/app/domain/permits.py |
| G1 | U | 正式源码/公开配置/维护工具 | backend/app/domain/sandbox_maintenance.py |
| G1 | U | 正式源码/公开配置/维护工具 | backend/app/domain/sandbox_ownership.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/domain/tasks.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/main.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/providers/base.py |
| G1 | U | 正式源码/公开配置/维护工具 | backend/app/providers/deepseek.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/providers/openai_compatible.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/providers/router.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/repositories/connections.py |
| G1 | U | 正式源码/公开配置/维护工具 | backend/app/sandbox/daemon_isolation.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/sandbox/driver.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/sandbox/engine.py |
| G1 | U | 正式源码/公开配置/维护工具 | backend/app/sandbox/history.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/sandbox/main.py |
| G1 | U | 正式源码/公开配置/维护工具 | backend/app/sandbox/ownership.py |
| G1 | U | 正式源码/公开配置/维护工具 | backend/app/sandbox/retirement.py |
| G1 | U | 正式源码/公开配置/维护工具 | backend/app/sandbox/retirement_control.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/schemas/models.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/services/context.py |
| G1 | U | 正式源码/公开配置/维护工具 | backend/app/services/execution_permits.py |
| G1 | U | 正式源码/公开配置/维护工具 | backend/app/services/model_runtime_status.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/services/models.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/services/orchestration/real_runtime.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/services/orchestration/sandbox_graph.py |
| G1 | U | 正式源码/公开配置/维护工具 | backend/app/services/permit_authority.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/services/sandbox.py |
| G1 | U | 正式源码/公开配置/维护工具 | backend/app/services/sandbox_maintenance.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/services/tasks.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/workers/engine.py |
| G1 | M | 正式源码/公开配置/维护工具 | backend/app/workers/main.py |
| G1 | M | 正式源码/公开配置/维护工具 | compose.yaml |
| G1 | U | 正式源码/公开配置/维护工具 | config/deepseek-coder-local.json |
| G1 | U | 正式源码/公开配置/维护工具 | config/deepseek-preparation.json |
| G1 | M | 正式源码/公开配置/维护工具 | frontend/src/pages/ModelCenter.tsx |
| G1 | M | 正式源码/公开配置/维护工具 | frontend/vite.config.ts |
| G2 | M | 迁移/迁移支持 | backend/migrations/env.py |
| G2 | U | 迁移/迁移支持 | backend/migrations/versions/0007_deepseek.py |
| G2 | U | 迁移/迁移支持 | backend/migrations/versions/0008_execution_permits.py |
| G2 | U | 迁移/迁移支持 | backend/migrations/versions/0009_sandbox_ownership.py |
| G2 | U | 迁移/迁移支持 | backend/migrations/versions/0010_sandbox_maintenance.py |
| G3 | M | 正式源码/公开配置/维护工具 | frontend/playwright.config.ts |
| G3 | U | 测试/夹具 | frontend/playwright.offline.config.ts |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/bootstrap-p4.py |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/bootstrap-sandbox.py |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/bootstrap_local.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/check-coder-local.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/check-sandbox-daemons.py |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/check_secrets.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/configure-deepseek-coder.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/deploy-permit-database.py |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/freeze-lock.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/lifecycle-entry.ps1 |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/lifecycle.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/lifecycle_channel.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/lifecycle_manager.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/lifecycle_regression.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/lifecycle_runtime.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/lifecycle_v2.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/lifecycle_windows.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/maintenance_policy.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/managed_service.py |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/migrate.py |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/p2-compose-probe.py |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/p2-recovery-probe.py |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/p3-worker-recovery-probe.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/p5-live-database-check.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/p5-live-preflight.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/p5-live-state-check.py |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/p5-worker-recovery-probe.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/permit-test-runner-isolation.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/prepare-permit-tests.py |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/process-ownership.ps1 |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/restart-worker.ps1 |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/s1_application_test.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/s1_isolation.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/s1_test_environment.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/start-coder-local.ps1 |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/start-local.ps1 |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/stop-coder-local.ps1 |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/stop-local.ps1 |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/stop-worker.ps1 |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/test-offline.py |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/test-p2.ps1 |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/test-p3.ps1 |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/test-p4.ps1 |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/test-p5.ps1 |
| G3 | M | 正式源码/公开配置/维护工具 | scripts/test-real-models.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/verify-permit-deployment.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/verify-permit-migration.py |
| G3 | U | 正式源码/公开配置/维护工具 | scripts/verify-permit-restoration.py |
| G4 | M | 测试/夹具 | frontend/tests/capabilities.spec.ts |
| G4 | U | 测试/夹具 | frontend/tests/deepseek-offline.spec.ts |
| G4 | M | 测试/夹具 | frontend/tests/models-chat.spec.ts |
| G4 | U | 测试/夹具 | frontend/tests/offline-server.mjs |
| G4 | M | 测试/夹具 | frontend/tests/run-e2e.mjs |
| G4 | M | 测试/夹具 | frontend/tests/sandbox.spec.ts |
| G4 | M | 测试/夹具 | frontend/tests/smoke.spec.ts |
| G4 | M | 测试/夹具 | frontend/tests/workflow.spec.ts |
| G4 | M | 测试/夹具 | tests/conftest.py |
| G4 | U | 测试/夹具 | tests/fixtures/coder-startup-probe.ps1 |
| G4 | U | 测试/夹具 | tests/fixtures/lifecycle_acceptance.py |
| G4 | U | 测试/夹具 | tests/fixtures/lifecycle_dummy.py |
| G4 | U | 测试/夹具 | tests/fixtures/lifecycle_permit_child.py |
| G4 | U | 测试/夹具 | tests/fixtures/offline_guards.py |
| G4 | U | 测试/夹具 | tests/fixtures/permit_process_worker.py |
| G4 | U | 测试/夹具 | tests/fixtures/preflight_guards.py |
| G4 | M | 测试/夹具 | tests/fixtures/provider_stub_worker.py |
| G4 | U | 测试/夹具 | tests/fixtures/retirement_boundary.py |
| G4 | U | 测试/夹具 | tests/fixtures/retirement_control_worker.py |
| G4 | U | 测试/夹具 | tests/fixtures/s1_lifecycle_native.py |
| G4 | U | 测试/夹具 | tests/fixtures/sandbox_database.py |
| G4 | U | 测试/夹具 | tests/fixtures/seal_s2_probe.py |
| G4 | U | 测试/夹具 | tests/fixtures/transport_permit_stub.py |
| G4 | M | 测试/夹具 | tests/http/test_inference_api.py |
| G4 | U | 测试/夹具 | tests/http/test_permit_api.py |
| G4 | M | 测试/夹具 | tests/integration/test_dependencies.py |
| G4 | U | 测试/夹具 | tests/integration/test_execution_permits.py |
| G4 | U | 测试/夹具 | tests/integration/test_model_runtime_status.py |
| G4 | M | 测试/夹具 | tests/integration/test_real_agents.py |
| G4 | M | 测试/夹具 | tests/integration/test_sandbox_failures.py |
| G4 | U | 测试/夹具 | tests/integration/test_sandbox_history_db_b3.py |
| G4 | U | 测试/夹具 | tests/integration/test_sandbox_maintenance_db.py |
| G4 | U | 测试/夹具 | tests/integration/test_sandbox_migration_recovery_b3.py |
| G4 | U | 测试/夹具 | tests/integration/test_sandbox_migrations_b1.py |
| G4 | U | 测试/夹具 | tests/integration/test_sandbox_ownership_db.py |
| G4 | U | 测试/夹具 | tests/unit/test_coder_local.py |
| G4 | U | 测试/夹具 | tests/unit/test_deepseek.py |
| G4 | U | 测试/夹具 | tests/unit/test_lifecycle_ipc_s1.py |
| G4 | U | 测试/夹具 | tests/unit/test_lifecycle_manager.py |
| G4 | U | 测试/夹具 | tests/unit/test_lifecycle_permit_child.py |
| G4 | U | 测试/夹具 | tests/unit/test_lifecycle_v2_native.py |
| G4 | U | 测试/夹具 | tests/unit/test_lifecycle_v2_scope.py |
| G4 | M | 测试/夹具 | tests/unit/test_model_adapter.py |
| G4 | U | 测试/夹具 | tests/unit/test_permit_boundaries.py |
| G4 | U | 测试/夹具 | tests/unit/test_preflight_policy.py |
| G4 | U | 测试/夹具 | tests/unit/test_retirement_control_b3.py |
| G4 | U | 测试/夹具 | tests/unit/test_s1_entry_isolation.py |
| G4 | U | 测试/夹具 | tests/unit/test_s1_isolation.py |
| G4 | U | 测试/夹具 | tests/unit/test_sandbox_history_b3.py |
| G4 | U | 测试/夹具 | tests/unit/test_sandbox_maintenance.py |
| G4 | U | 测试/夹具 | tests/unit/test_sandbox_ownership.py |
| G4 | M | 测试/夹具 | tests/unit/test_sandbox_runner_policy.py |
| G4 | U | 测试/夹具 | tests/unit/test_seal_entry_arguments.py |
| G4 | U | 测试/夹具 | tests/unit/test_seal_s1_fixture_query.py |
| G4 | U | 测试/夹具 | tests/unit/test_seal_s1_queries.py |
| G4 | U | 测试/夹具 | tests/unit/test_seal_s2_maintenance.py |
| G4 | U | 测试/夹具 | tests/unit/test_seal_s3_issuer.py |
| G5 | U | 文档 | docs/DEEPSEEK_CODER_LOCAL.md |
| G5 | M | 文档 | docs/GETTING_STARTED.md |
| G5 | M | 文档 | docs/LEARNING_PATH.md |
| G5 | U | 文档 | docs/LIFECYCLE_MANAGER_DESIGN.md |
| G5 | U | 文档 | docs/LIFECYCLE_SECURITY_TESTS.md |
| G5 | U | 文档 | docs/LOCAL_LIFECYCLE_GUARD.md |
| G5 | U | 文档 | docs/LOCAL_LIFECYCLE_TEST_REPORT.md |
| G5 | U | 文档 | docs/MAINTENANCE_ENTRIES.md |
| G5 | M | 文档 | docs/MODEL_INTEGRATION.md |
| G5 | U | 文档 | docs/P5_LIVE_DEEPSEEK.md |
| G5 | U | 文档 | docs/P5_LIVE_FIRST_CALL_REPORT.md |
| G5 | U | 文档 | docs/P5_LIVE_MAINT_S1_REPORT.md |
| G5 | U | 文档 | docs/P5_LIVE_MAINT_S2_REPORT.md |
| G5 | U | 文档 | docs/P5_LIVE_MAINT_S3A_REPORT.md |
| G5 | U | 文档 | docs/P5_LIVE_MAINT_S3B1_REPORT.md |
| G5 | U | 文档 | docs/P5_LIVE_MAINT_S3B2_REPORT.md |
| G5 | U | 文档 | docs/P5_LIVE_MAINT_S3B3_REPORT.md |
| G5 | U | 文档 | docs/P5_LIVE_MAINT_S3B_PLAN.md |
| G5 | U | 文档 | docs/P5_LIVE_PERMIT_DESIGN.md |
| G5 | U | 文档 | docs/P5_LIVE_PERMIT_TEST_REPORT.md |
| G5 | U | 文档 | docs/P5_LIVE_PREFLIGHT_REPORT.md |
| G5 | U | 文档 | docs/P5_LIVE_SAFETY_DEPLOYMENT_REPORT.md |
| G5 | U | 文档 | docs/P5_SEAL_FIX_REPORT.md |
| G5 | U | 文档 | docs/P5_SEAL_MANIFEST.md |
| G5 | M | 文档 | docs/PROJECT_STATUS.md |
| G5 | U | 文档 | docs/S3B2_GIT_DELIVERY_PLAN.md |
| G5 | U | 文档 | docs/S3B2_MAINTENANCE_RUNBOOK.md |
| G5 | U | 文档 | docs/SANDBOX_HISTORY_RECONCILIATION.md |
| G5 | U | 文档 | docs/SANDBOX_ISOLATION_DESIGN.md |
| G5 | U | 文档 | docs/SANDBOX_MAINTENANCE_FREEZE.md |
| G5 | U | 文档 | docs/SANDBOX_OWNERSHIP_PROTOCOL.md |
| G5 | U | 文档 | docs/SANDBOX_RUNNER_COMPATIBILITY.md |

临时产物/源码副本/SQLite假控制审计/测试清单/三份最终测试归档位于work/maint-s3b3及专属work/maint-s1目录，均被忽略，**不进入以下清单**。真实Key/Issuer/主dotenv从未读取或复制，不以force-add把备份纳入仓库。常见凭据格式扫描不等于真实秘密全集比对；暂存前必须再次审阅实际内容和索引。

## 7. 本轮封存审计与依赖结论

完整匹配186项当前条目，逐文件核对存在性、类型、SHA-256、文本/AST及安全敏感模式，复核实际Git diff和关键授权/恢复/派发链路；32份文档按历史时点与当前证据核对。本轮只修改本文件；未新增功能源码、运行测试、迁移、暂存或提交。这里是完整文件级交付审计，不声称对全部累积代码重新逐分支证明，也不重新计算生产验收PASS。

| 主分类 | 项数 | 说明 |
| --- | --- | --- |
| 正式源码、公开配置及维护工具 | 91 | API/Worker、适配器/Permit、Runner/冻结/历史规则、生命周期工具及公开模板；维护/验收入口按主用途归此类，不等于均可在主环境运行 |
| 迁移 | 5 | 四份0007–0010迁移＋env.py支持；不包含执行主库迁移 |
| 测试和测试夹具 | 58 | Python/浏览器用例、fixture和离线浏览器配置；Stub、实际PG/Redis、真实Engine层次分开 |
| 文档 | 32 | 阶段设计/报告、状态、Runbook、公开配置教程及本计划 |
| 临时文件、备份、实际敏感文件 | 0个待提交候选 | work、dotenv、测试数据库归档及本地控制SQLite均不在186项；只查本地产物路径/忽略状态，不打开真实密钥或本地凭据内容 |

分类和提交批次是不同维度：离线Playwright配置属于G3运行入口但主分类为测试，因此测试分类58项、G4批次57项；全部186项均有唯一主分类和唯一提交批次。本轮仅对本地产物做路径/忽略核验，看到的dotenv类路径也包含大量合成测试文件，不据文件名推断其内容或真实凭据状态。

没有发现常见模型Key、私钥、云访问ID或GitHub token格式的待提交内容；正式JSON配置使用credential_reference，Compose/公开模板通过环境引用和占位值供配置。没有读取实际DeepSeek Key、Issuer Token或主数据库密码做匹配，故不把格式扫描称为任意秘密不存在的保证。测试中明确的假身份/假凭据只能作为测试数据解释，不能当实际凭据交付。305个Git工作候选、索引、既有bundle/报告的无本地秘密扫描以及新增文件的语法/空白检查结果保存在work/delivery-seal/20261018。

只读核对当前未配置core.hooksPath，项目默认hooks目录没有活动hook；186项的Git属性仅有text/eol规则，未发现外部clean/filter或diff处理器。Git会按既有属性把部分CRLF规范化为LF；不修改Git配置。若之后hook、属性、索引或文件内容变化，下面命令对应的审阅结论需要重新确认。

实现依赖按最终源码树理解：

1. P5-LIVE DeepSeek/四角色适配和公开配置依赖0007、已有P5模型/Token/成本账本。
2. P5-LIVE-SAFETY/Single-Use Permit依赖0008和独立Issuer、可信Worker身份、原子认领/派发意图、预算/UNKNOWN保留。普通Chat/背景任务不因全局开关取得权限。
3. S1及后续封版修复提供Windows身份/代次/创建时间/OS锁/受控IPC、维护入口保护与独立PG/Redis/浏览器目标。旧主version1记录尚未交接，不能调用普通start覆盖。
4. S2暴露共享Engine下旧清理器风险，未提供独立可部署功能；其17＋2未执行状态必须保留。
5. S3-A归属协议依赖0009、可信注册/代次/daemon/CID/审批账本；标签不是删除授权，旧新清理器尚未获准共存。
6. S3-B1依赖0010，接通持久化冻结与短派发屏障；Permit仅在结构核验后兼容8/9/10。旧二进制不会自动理解新表。
7. S3-B2仅交付审查/操作卡/Git清单，没有部署或主库迁移。
8. S3-B3在上述基础上补离线退场内核、历史派生隔离/无CID意图拒绝、真实隔离PG恢复与DDL故障验证；生产退场适配和真实Engine验收仍未完成。

源码中的既有权限检查/预算/冻结/审批不能按阶段挑掉。全G1–G5共同构成被1035项历史Python用例验证的最终版本，单个中间提交不是发布点。原整批集成191通过/1夹具失败、修复后7项通过的分批事实保留，不能改写为192项整批一次全绿。本轮未重跑这些测试。

封存特别限制：旧p2/p3/p5 recovery probe明确禁用；permit-test-runner-isolation.py虽有生命周期外层保护，内部pause/restore仍按名称及was_running恢复，**不准用于新版交接或测试finally**。历史prepare/backup/rehearsal入口受退休操作规则限制，不能用于主0009/0010。将这些文件纳入Git保存历史和保护修复，不等于批准执行它们。OfflineRetirementController只有Stub端口，不能承担主Runner停止。

## 8. 精确人工暂存与提交命令（Windows CMD，本轮未执行）

当前五批合计186个不同文件：G1=42、G2=5、G3=50、G4=57、G5=32。均为明确文件路径，无目录通配、add -A或force-add。没有reset、clean、配置修改或部署命令。下面`^`是CMD续行，必须在该行末尾，不要在PowerShell执行；路径与本轮审计清单完全一致。

先在用户Windows CMD执行只读预检：

```cmd
cd /d D:\AIProjects\AgentForge-AI
git rev-parse HEAD
git status --short
git diff --cached --name-status
git diff --check
```

首次HEAD须等于上述基线，暂存区须空，当前条目须与第6节一致。每批只先执行“暂存与审阅”代码块，确认退出码、文件列表、内容及敏感检查均符合后，才手动执行该批单独的commit代码块；失败或存在其他暂存内容就停，不用重置/清理来修正。G1–G5之间先前提交会正常改变HEAD，后续不应再强求等于最初HEAD，但索引应在上一批提交完成后为空。

### G1 功能与安全实现（42项）

内容与验收证据：P5-LIVE Permit/DeepSeek、S3-A归属和S3-B1/B3冻结/历史测试；最终1035项的相关源码路径，无真实模型/Engine验收。

暂存与审阅（没有commit）：

```cmd
git diff --cached --name-status
git add -- ^
  ".env.example" ^
  "backend/app/api/v1/inference.py" ^
  "backend/app/api/v1/permits.py" ^
  "backend/app/api/v1/sandbox.py" ^
  "backend/app/core/config.py" ^
  "backend/app/domain/entities.py" ^
  "backend/app/domain/permits.py" ^
  "backend/app/domain/sandbox_maintenance.py" ^
  "backend/app/domain/sandbox_ownership.py" ^
  "backend/app/domain/tasks.py" ^
  "backend/app/main.py" ^
  "backend/app/providers/base.py" ^
  "backend/app/providers/deepseek.py" ^
  "backend/app/providers/openai_compatible.py" ^
  "backend/app/providers/router.py" ^
  "backend/app/repositories/connections.py" ^
  "backend/app/sandbox/daemon_isolation.py" ^
  "backend/app/sandbox/driver.py" ^
  "backend/app/sandbox/engine.py" ^
  "backend/app/sandbox/history.py" ^
  "backend/app/sandbox/main.py" ^
  "backend/app/sandbox/ownership.py" ^
  "backend/app/sandbox/retirement.py" ^
  "backend/app/sandbox/retirement_control.py" ^
  "backend/app/schemas/models.py" ^
  "backend/app/services/context.py" ^
  "backend/app/services/execution_permits.py" ^
  "backend/app/services/model_runtime_status.py" ^
  "backend/app/services/models.py" ^
  "backend/app/services/orchestration/real_runtime.py" ^
  "backend/app/services/orchestration/sandbox_graph.py" ^
  "backend/app/services/permit_authority.py" ^
  "backend/app/services/sandbox.py" ^
  "backend/app/services/sandbox_maintenance.py" ^
  "backend/app/services/tasks.py" ^
  "backend/app/workers/engine.py" ^
  "backend/app/workers/main.py" ^
  "compose.yaml" ^
  "config/deepseek-coder-local.json" ^
  "config/deepseek-preparation.json" ^
  "frontend/src/pages/ModelCenter.tsx" ^
  "frontend/vite.config.ts"
git diff --cached --check
git diff --cached --stat
git diff --cached --name-status
git diff --cached
```

确认本批文件/内容正确后，单独执行：

```cmd
git commit -m "feat: harden P5 live permits and sandbox history isolation"
```

### G2 迁移与迁移支持（5项）

内容与验收证据：独立PG的合成备份/实际restore、旧23表一致性、0009/0010非空降级拒绝及DDL锁失败回滚/恢复；不是主库迁移验收。

暂存与审阅（没有commit）：

```cmd
git diff --cached --name-status
git add -- ^
  "backend/migrations/env.py" ^
  "backend/migrations/versions/0007_deepseek.py" ^
  "backend/migrations/versions/0008_execution_permits.py" ^
  "backend/migrations/versions/0009_sandbox_ownership.py" ^
  "backend/migrations/versions/0010_sandbox_maintenance.py"
git diff --cached --check
git diff --cached --stat
git diff --cached --name-status
git diff --cached
```

确认本批文件/内容正确后，单独执行：

```cmd
git commit -m "feat: add versioned sandbox ownership and maintenance migrations"
```

### G3 生命周期与维护入口（50项）

内容与验收证据：S1及封版修复的隔离生命周期/入口测试和S3-B3的只读daemon预检；真实主version1接管与生产Runner控制仍BLOCKED。

暂存与审阅（没有commit）：

```cmd
git diff --cached --name-status
git add -- ^
  "frontend/playwright.config.ts" ^
  "frontend/playwright.offline.config.ts" ^
  "scripts/bootstrap-p4.py" ^
  "scripts/bootstrap-sandbox.py" ^
  "scripts/bootstrap_local.py" ^
  "scripts/check-coder-local.py" ^
  "scripts/check-sandbox-daemons.py" ^
  "scripts/check_secrets.py" ^
  "scripts/configure-deepseek-coder.py" ^
  "scripts/deploy-permit-database.py" ^
  "scripts/freeze-lock.py" ^
  "scripts/lifecycle-entry.ps1" ^
  "scripts/lifecycle.py" ^
  "scripts/lifecycle_channel.py" ^
  "scripts/lifecycle_manager.py" ^
  "scripts/lifecycle_regression.py" ^
  "scripts/lifecycle_runtime.py" ^
  "scripts/lifecycle_v2.py" ^
  "scripts/lifecycle_windows.py" ^
  "scripts/maintenance_policy.py" ^
  "scripts/managed_service.py" ^
  "scripts/migrate.py" ^
  "scripts/p2-compose-probe.py" ^
  "scripts/p2-recovery-probe.py" ^
  "scripts/p3-worker-recovery-probe.py" ^
  "scripts/p5-live-database-check.py" ^
  "scripts/p5-live-preflight.py" ^
  "scripts/p5-live-state-check.py" ^
  "scripts/p5-worker-recovery-probe.py" ^
  "scripts/permit-test-runner-isolation.py" ^
  "scripts/prepare-permit-tests.py" ^
  "scripts/process-ownership.ps1" ^
  "scripts/restart-worker.ps1" ^
  "scripts/s1_application_test.py" ^
  "scripts/s1_isolation.py" ^
  "scripts/s1_test_environment.py" ^
  "scripts/start-coder-local.ps1" ^
  "scripts/start-local.ps1" ^
  "scripts/stop-coder-local.ps1" ^
  "scripts/stop-local.ps1" ^
  "scripts/stop-worker.ps1" ^
  "scripts/test-offline.py" ^
  "scripts/test-p2.ps1" ^
  "scripts/test-p3.ps1" ^
  "scripts/test-p4.ps1" ^
  "scripts/test-p5.ps1" ^
  "scripts/test-real-models.py" ^
  "scripts/verify-permit-deployment.py" ^
  "scripts/verify-permit-migration.py" ^
  "scripts/verify-permit-restoration.py"
git diff --cached --check
git diff --cached --stat
git diff --cached --name-status
git diff --cached
```

确认本批文件/内容正确后，单独执行：

```cmd
git commit -m "feat: guard Windows lifecycle and isolate maintenance entrypoints"
```

### G4 测试与夹具（57项）

内容与验收证据：843单元/HTTP＋集成191通过/1夹具失败后7专项通过，去重1035（新增51）；保留全部分批事实；19项真实Sandbox未执行。

暂存与审阅（没有commit）：

```cmd
git diff --cached --name-status
git add -- ^
  "frontend/tests/capabilities.spec.ts" ^
  "frontend/tests/deepseek-offline.spec.ts" ^
  "frontend/tests/models-chat.spec.ts" ^
  "frontend/tests/offline-server.mjs" ^
  "frontend/tests/run-e2e.mjs" ^
  "frontend/tests/sandbox.spec.ts" ^
  "frontend/tests/smoke.spec.ts" ^
  "frontend/tests/workflow.spec.ts" ^
  "tests/conftest.py" ^
  "tests/fixtures/coder-startup-probe.ps1" ^
  "tests/fixtures/lifecycle_acceptance.py" ^
  "tests/fixtures/lifecycle_dummy.py" ^
  "tests/fixtures/lifecycle_permit_child.py" ^
  "tests/fixtures/offline_guards.py" ^
  "tests/fixtures/permit_process_worker.py" ^
  "tests/fixtures/preflight_guards.py" ^
  "tests/fixtures/provider_stub_worker.py" ^
  "tests/fixtures/retirement_boundary.py" ^
  "tests/fixtures/retirement_control_worker.py" ^
  "tests/fixtures/s1_lifecycle_native.py" ^
  "tests/fixtures/sandbox_database.py" ^
  "tests/fixtures/seal_s2_probe.py" ^
  "tests/fixtures/transport_permit_stub.py" ^
  "tests/http/test_inference_api.py" ^
  "tests/http/test_permit_api.py" ^
  "tests/integration/test_dependencies.py" ^
  "tests/integration/test_execution_permits.py" ^
  "tests/integration/test_model_runtime_status.py" ^
  "tests/integration/test_real_agents.py" ^
  "tests/integration/test_sandbox_failures.py" ^
  "tests/integration/test_sandbox_history_db_b3.py" ^
  "tests/integration/test_sandbox_maintenance_db.py" ^
  "tests/integration/test_sandbox_migration_recovery_b3.py" ^
  "tests/integration/test_sandbox_migrations_b1.py" ^
  "tests/integration/test_sandbox_ownership_db.py" ^
  "tests/unit/test_coder_local.py" ^
  "tests/unit/test_deepseek.py" ^
  "tests/unit/test_lifecycle_ipc_s1.py" ^
  "tests/unit/test_lifecycle_manager.py" ^
  "tests/unit/test_lifecycle_permit_child.py" ^
  "tests/unit/test_lifecycle_v2_native.py" ^
  "tests/unit/test_lifecycle_v2_scope.py" ^
  "tests/unit/test_model_adapter.py" ^
  "tests/unit/test_permit_boundaries.py" ^
  "tests/unit/test_preflight_policy.py" ^
  "tests/unit/test_retirement_control_b3.py" ^
  "tests/unit/test_s1_entry_isolation.py" ^
  "tests/unit/test_s1_isolation.py" ^
  "tests/unit/test_sandbox_history_b3.py" ^
  "tests/unit/test_sandbox_maintenance.py" ^
  "tests/unit/test_sandbox_ownership.py" ^
  "tests/unit/test_sandbox_runner_policy.py" ^
  "tests/unit/test_seal_entry_arguments.py" ^
  "tests/unit/test_seal_s1_fixture_query.py" ^
  "tests/unit/test_seal_s1_queries.py" ^
  "tests/unit/test_seal_s2_maintenance.py" ^
  "tests/unit/test_seal_s3_issuer.py"
git diff --cached --check
git diff --cached --stat
git diff --cached --name-status
git diff --cached
```

确认本批文件/内容正确后，单独执行：

```cmd
git commit -m "test: cover permits lifecycle ownership and maintenance recovery"
```

### G5 设计、报告与交付文档（32项）

内容与验收证据：各阶段报告、当前状态、15条历史记录及Runbook与本轮封存审计；历史时点证据与当前BLOCKED分开。

暂存与审阅（没有commit）：

```cmd
git diff --cached --name-status
git add -- ^
  "docs/DEEPSEEK_CODER_LOCAL.md" ^
  "docs/GETTING_STARTED.md" ^
  "docs/LEARNING_PATH.md" ^
  "docs/LIFECYCLE_MANAGER_DESIGN.md" ^
  "docs/LIFECYCLE_SECURITY_TESTS.md" ^
  "docs/LOCAL_LIFECYCLE_GUARD.md" ^
  "docs/LOCAL_LIFECYCLE_TEST_REPORT.md" ^
  "docs/MAINTENANCE_ENTRIES.md" ^
  "docs/MODEL_INTEGRATION.md" ^
  "docs/P5_LIVE_DEEPSEEK.md" ^
  "docs/P5_LIVE_FIRST_CALL_REPORT.md" ^
  "docs/P5_LIVE_MAINT_S1_REPORT.md" ^
  "docs/P5_LIVE_MAINT_S2_REPORT.md" ^
  "docs/P5_LIVE_MAINT_S3A_REPORT.md" ^
  "docs/P5_LIVE_MAINT_S3B1_REPORT.md" ^
  "docs/P5_LIVE_MAINT_S3B2_REPORT.md" ^
  "docs/P5_LIVE_MAINT_S3B3_REPORT.md" ^
  "docs/P5_LIVE_MAINT_S3B_PLAN.md" ^
  "docs/P5_LIVE_PERMIT_DESIGN.md" ^
  "docs/P5_LIVE_PERMIT_TEST_REPORT.md" ^
  "docs/P5_LIVE_PREFLIGHT_REPORT.md" ^
  "docs/P5_LIVE_SAFETY_DEPLOYMENT_REPORT.md" ^
  "docs/P5_SEAL_FIX_REPORT.md" ^
  "docs/P5_SEAL_MANIFEST.md" ^
  "docs/PROJECT_STATUS.md" ^
  "docs/S3B2_GIT_DELIVERY_PLAN.md" ^
  "docs/S3B2_MAINTENANCE_RUNBOOK.md" ^
  "docs/SANDBOX_HISTORY_RECONCILIATION.md" ^
  "docs/SANDBOX_ISOLATION_DESIGN.md" ^
  "docs/SANDBOX_MAINTENANCE_FREEZE.md" ^
  "docs/SANDBOX_OWNERSHIP_PROTOCOL.md" ^
  "docs/SANDBOX_RUNNER_COMPATIBILITY.md"
git diff --cached --check
git diff --cached --stat
git diff --cached --name-status
git diff --cached
```

确认本批文件/内容正确后，单独执行：

```cmd
git commit -m "docs: seal S3-B3 evidence and blocked rollout decisions"
```


五批全部提交后只读核对：

```cmd
git log -5 --oneline
git status --short
git diff --cached --name-status
git diff --check
```

若执行期间没有其他改动，所有186项均应已进入五个提交，工作区/索引应为空；记录最终HEAD作为待真实验收的S3-B3封存基线。不自动push、tag或部署。提交不改变主库0008/旧Runner镜像，也不恢复主API/Worker或放开模型。

## 9. 独立Docker环境决策

本轮只读实际结果：default端点npipe:////./pipe/docker_engine与desktop-linux端点npipe:////./pipe/dockerDesktopLinuxEngine均返回Linux daemon ID **a2353ec2-7b5f-4343-a16b-8a04bc95ec51**。当前没有经确认的独立测试daemon。下面估时是基于本项目现状的工程范围，未经实际执行计时，不含采购、下载、管理员排期或故障返工。

| 项目 | A：独立测试VM＋独立daemon（后续技术路线优先） | B：单独维护窗口退旧版、升级主Runner |
| --- | --- | --- |
| 所需资源 | 专属Linux VM/已有Engine、独立Docker数据目录/网络、独立PG/Redis、API/Worker/Runner身份与目录、浏览器目标。容量规划可先按4vCPU/8GiB/40GiB评估，非测量出的最低配置；不复制主Key/Issuer | 现有Windows项目与共享Engine、主PG备份和独立实际restore目标、受审核固定镜像、有限控制工具、操作员及独立复核者 |
| 具体前置 | 人工证明VM/daemon归属和管理边界，实际ID与主不同；批准SSH/TLS等最小访问，旧清理器不能访问测试daemon；SDK固定目标并保留每步daemon验证。专用真实Runner夹具/身份交付须先就绪；现有conftest和Playwright拦截不能直接删除 | 有限生产控制适配/分权交付和主version1保护交接已验收；所有旧任务入口已隔离，活动/在途已对账；14＋1保留并人工签认；新主库备份及独立restore证明；明确批准0009/0010、禁复起、主Runner中断及必要API/Worker中断 |
| 主要风险 | 新context仍指回主Engine、远端证书/端点误配、测试SDK退回默认context、挂载/共享存储串环境、测试夹具误指主DB/Redis；不同ID本身不是完整权限证明 | 旧Runner/恢复脚本自动复起、Docker已接受但未返回的请求、新旧双清理器、DDL锁/备份失败、未知历史被错误结算；目前主thaw仍会被14＋1阻止 |
| 对现有Runner/DB影响 | 测试资源完全在独立VM；主Runner不停，主DB不迁移/不写入。隔离证明未通过前不运行19项 | 必然中断主Runner，可能中断API/Worker；主DB未来明确执行0009/0010。故障保持冻结/旧版禁用，不自动restore旧镜像；不能承诺当场恢复业务 |
| 管理员权限 | 已有VM及已授权账户时通常无需本机Windows管理员；创建VM/安装Engine若涉及宿主权限需管理员另批。VM的Docker管理权限等同高权限边界，限专属测试主机；本轮不创建/安装 | 需要已批准的Docker管理权、主专属DB备份/迁移权和独立恢复目标权限；不应因此修改系统ACL或Docker全局配置，通常无需额外Windows管理员提权 |
| 时间估算 | 已有VM/Engine：环境绑定与资源准备约1–2小时；限定现有夹具适配/预检约0.5–1工程日；预检全过后19项执行与归属核对预留1–2小时。没有VM时资源供应时间另计 | 技术前置补齐与真实适配验收约0.5–2工程日；就绪后维护窗口预留2–4小时，含备份/独立restore/两轮退出确认/迁移/默认阻断验证；历史缺证据或故障时无固定完成上限 |
| 可验证完成标准 | 实际daemon/管理边界独立、主Runner无访问能力；独立数据/身份/端口证明；真实跨实例及崩溃验证、17＋2逐项有结果，费用0，所有清理仅针对已证明测试资源，主状态前后不变 | 旧版准确CID非running/Pid0/restart=no，复起来源及在途清理已关闭；无双Runner；主备份实际可恢复；0009/0010及旧数据/审计一致；新版FROZEN默认拒绝、身份/代次/CID账本正确；真实19项另获授权后通过，主业务恢复须另批 |
| 当前可执行性 | **BLOCKED**：尚无独立daemon、有限真实夹具仍需验收；创建VM不是本轮动作 | **BLOCKED**：生产控制适配、旧入口/身份交付、主备份、历史处置及维护授权均不足；不能现在申请执行stop/迁移 |

A能先验证真实Sandbox而不触及主环境，优先于B作为后续技术路线；A通过不会自动证明主库备份、主生命周期交接或主部署完成。B是后续主升级必须单独审阅的维护路径，并非可用来省略A类隔离验证的快捷方式。可继续复用现有模块做有限目标适配，不新增通用基础设施框架。

## 10. 最终真实验收门禁与唯一下一步

下面状态面向**真实运行验收**；离线PASS只作证据，不能升级为对应真实门禁PASS。八项中当前没有可以如实标为真实验收PASS的项目。

| 项目 | 状态 | 现有证据与解除阻塞的最小实际操作 |
| --- | --- | --- |
| 1 可信旧Runner退场 | **BLOCKED** | 离线内核/竞争/崩溃通过，旧主仍running/unless-stopped。先验收有限生产适配和可信身份/交付，再单独授权精确目标禁复起/停止，并验证循环退出、在途收敛和无旧控制进程；不得按名称restore |
| 2 主数据库备份/恢复 | **BLOCKED** | 只完成合成独立库恢复。批准固定主库的新一致备份与独立目标实际restore，核对原23表、14＋1、P4/Permit/账本；此步不自动批准主迁移 |
| 3 Runner实例隔离 | **BLOCKED** | PG/Redis＋Docker Stub已验证，两个本地context实际同daemon。按A提供并证明独立Engine、固定SDK目标及有限测试夹具；共享Engine则必须先完成门禁1 |
| 4 真实Sandbox 19项 | **NOT_TESTED** | 门禁3通过后，单独批准17集成＋2浏览器及精确测试资源清理；逐项实际执行，不能移除现有保护后直接跑 |
| 5 主API/Worker生命周期接管 | **BLOCKED** | 主version1/generation4记录保留、API当前ConnectError。先审阅旧保护记录到新版的有限交接路径，再批准仅目标实例的接管/必要重启，实时验证SID/创建时间/代次/IPC和健康；不运行普通无Key覆盖启动 |
| 6 DeepSeek Coder凭据恢复 | **BLOCKED** | 当前两端存在性UNVERIFIED。门禁5就绪后，经授权由持Key的用户PowerShell安全继承给指定API/Worker，再只读确认True/True及配置一致；不把Key发聊天/命令参数/文件，不给普通PowerShellIssuer权限 |
| 7 单次Permit与预算验证 | **BLOCKED** | 原子认领、预算隔离、重复消息/未知结果离线通过。待真实服务就绪，只做无费用实时策略预检：可信Worker、槽位/版本、域名/凭据受众、请求指纹、价格预留、max_attempts=1/重试0/无旁路；保持日/测试预算0及签发关闭，不签发“测试用真实Permit”来探测 |
| 8 一次真实DeepSeek API | **NOT_TESTED** | 原收费授权已结束。门禁5–7及本次请求/价格复核就绪后，重新取得明确的一次授权，才可指定Coder/deepseek-flash、thinking disabled、SSE、最多1次尝试、64输出/8192输入预留、30/60秒、应用日/测试累计<=US$0.005、零重试并恢复安全门禁。此次没有调用，也不承诺供应商绝对账单上限 |

模型最小测试依赖5–7和新收费授权；不启动MCP/Skills/Sandbox。Runner的1–4另行推进，不为单模型连通性测试增加人工的Sandbox先行依赖。

本轮只读数据保护结果：334条原执行和14＋1元数据与S3-B3快照一致，246个历史完整CID在当前daemon缺席但结果不改写；主库仍0008，0009/0010没有在主库应用。新增两测试数据容器完整CID为bf09c114222fd86831dca3efd7b2ad78efc50f8efa8c2932ef0d9a732f34999d及ed308ec4bb1484c8bc765e68ee985a57e291e9bba178441a18e899dc0fd026b6，仍running/restart=no/StartedAt不变；未删除。新历史隔离规则阻止自动重放的结论来自S3-B3源码及合成集成，**旧主二进制尚未加载新规则**。

**唯一推荐的下一步人工操作：在Windows CMD按第8节逐批审阅并提交G1–G5，将当前186项成果封存成可追溯的S3-B3 Git基线。** 这一步无需服务中断、主库写入、VM供应或费用窗口；完成之后再按A路线申请独立测试资源。当前不申请执行主Runner维护窗口，不开启Permit或模型，不进入P6。本轮在交付审计及路线决策完成后暂停。
