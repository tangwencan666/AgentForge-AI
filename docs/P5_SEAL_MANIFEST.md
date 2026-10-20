# P5封版候选提交清单

2026-10-16，Asia/Shanghai。项目 D:\AIProjects\AgentForge-AI。

本文件为逐路径候选清单，不是暂存/提交授权。SEAL-S1/S2/S3已按后续明确授权实际修复，隔离验证与当前结论见[P5_SEAL_FIX_REPORT](P5_SEAL_FIX_REPORT.md)。历史只读审计的BLOCKED记录和指纹保留，不能视为修复后代码指纹。必须重新申请封版审计；本轮不暂存、提交、创建Tag或Push。

## 历史只读审计基线

原始HEAD：982e83ef32b7d274e820d59ee63d6fb76bd8979e；分支main；索引为空。起始49个跟踪修改、57个未跟踪条目；config/展开两个文件，因此实际107个候选文件。本轮只改文档，新增本清单后总108文件（49跟踪修改、59未跟踪文件；status显示58未跟踪条目）。既有工作未重置、覆盖删除或暂存。

起始107候选的排序[path,原始文件SHA256]紧凑JSON聚合指纹：7ee76e3e9aca47479c732f19901544556cd8a823a0e18f87e18def96fe28750a。此为本轮审计快照，不是历史测试时的指纹；文档随后更新，不应再用它验证最终整树。

94个非文档候选源码的同算法聚合指纹：93e8716f4f1aea2cc56b13c66db17498f8322eda5b1e2ed03c52f5b959dad89a。本轮未修改这些源码。历史XML未绑定完整源码树，不能声称原HEAD已包含并验证这些未提交文件。

全部107个起始文件内容与P5/P5-LIVE/Permit/生命周期保护相关，未发现明确无关用户文件；关联不等于自动授权纳入。跨P3/P4路径为P5安全集成及测试调整，须在最终暂存差异中逐项复核。不删除暂不纳入的工作。

## 历史审查阻塞文件（后续修复另见报告）

- scripts/lifecycle_manager.py：SEAL-S1：查询故障默认拒绝尚未闭合。
- scripts/p5-live-state-check.py：SEAL-S2：--stop缺少共享维护保护及租户约束。
- scripts/configure-deepseek-coder.py：SEAL-S2：直接改槽位/维护配置，缺共享维护保护。
- scripts/permit-test-runner-isolation.py：SEAL-S2：pause/restore可直接操作主Runner。
- scripts/p5-live-preflight.py：SEAL-S3：prepare可能复制Issuer权限。

上列为修复前发现，后续授权已覆盖这些源码。修复报告逐项记录函数、测试、命令helper与配置链补强；不能仅排除安全相关文件就将其他依赖代码视为安全封版。

## 明确排除

- .env、.env.*（公开占位模板.env.example除外）、真实Key/Token及任何秘密导出。
- work/全部运行状态、锁、启动日志、数据库备份、XML/OS证据、Redis配置和审计临时材料；保留本机，不删除。
- .venv/、node_modules/、dist/、__pycache__/、.pytest_cache/、test-results/、playwright-report/、*.log及运行时数据库/卷。
- 其他项目、系统文件、未列出的用户改动，以及未来新出现的文件；出现后重新审查。

现有.gitignore已覆盖实际运行敏感路径；没有把实际日志、备份、依赖、二进制产物或个人Users路径放入本候选集。忽略规则不是所有任意位置秘密的保证。

## 逐文件候选

M=本轮开始已有的跟踪修改；U=本轮开始已有的未跟踪文件；N=本轮新增文档。均未暂存。路径相对于固定项目根目录。

### 根部署和非秘密配置（4）

- [ ] M `.env.example`
- [ ] M `compose.yaml`
- [ ] U `config/deepseek-coder-local.json`
- [ ] U `config/deepseek-preparation.json`

### 后端和迁移源码（25）

- [ ] M `backend/app/api/v1/inference.py`
- [ ] U `backend/app/api/v1/permits.py`
- [ ] M `backend/app/core/config.py`
- [ ] M `backend/app/domain/entities.py`
- [ ] U `backend/app/domain/permits.py`
- [ ] M `backend/app/domain/tasks.py`
- [ ] M `backend/app/main.py`
- [ ] M `backend/app/providers/base.py`
- [ ] U `backend/app/providers/deepseek.py`
- [ ] M `backend/app/providers/openai_compatible.py`
- [ ] M `backend/app/providers/router.py`
- [ ] M `backend/app/repositories/connections.py`
- [ ] M `backend/app/schemas/models.py`
- [ ] M `backend/app/services/context.py`
- [ ] U `backend/app/services/execution_permits.py`
- [ ] U `backend/app/services/model_runtime_status.py`
- [ ] M `backend/app/services/models.py`
- [ ] M `backend/app/services/orchestration/real_runtime.py`
- [ ] U `backend/app/services/permit_authority.py`
- [ ] M `backend/app/services/tasks.py`
- [ ] M `backend/app/workers/engine.py`
- [ ] M `backend/app/workers/main.py`
- [ ] M `backend/migrations/env.py`
- [ ] U `backend/migrations/versions/0007_deepseek.py`
- [ ] U `backend/migrations/versions/0008_execution_permits.py`

### 前端源码和测试配置（10）

- [ ] M `frontend/playwright.config.ts`
- [ ] U `frontend/playwright.offline.config.ts`
- [ ] M `frontend/src/pages/ModelCenter.tsx`
- [ ] M `frontend/tests/capabilities.spec.ts`
- [ ] U `frontend/tests/deepseek-offline.spec.ts`
- [ ] M `frontend/tests/models-chat.spec.ts`
- [ ] U `frontend/tests/offline-server.mjs`
- [ ] M `frontend/tests/sandbox.spec.ts`
- [ ] M `frontend/tests/workflow.spec.ts`
- [ ] M `frontend/vite.config.ts`

### 脚本（39）

- [ ] M `scripts/bootstrap_local.py`
- [ ] M `scripts/bootstrap-sandbox.py`
- [ ] M `scripts/bootstrap-p4.py`
- [ ] M `scripts/freeze-lock.py`
- [ ] M `scripts/migrate.py`
- [ ] M `scripts/p2-compose-probe.py`
- [ ] U `scripts/maintenance_policy.py`

- [ ] U `scripts/check-coder-local.py`
- [ ] M `scripts/check_secrets.py`
- [ ] U `scripts/configure-deepseek-coder.py` — 已修，待复审
- [ ] U `scripts/deploy-permit-database.py`
- [ ] U `scripts/lifecycle-entry.ps1`
- [ ] U `scripts/lifecycle.py`
- [ ] U `scripts/lifecycle_manager.py` — 已修，待复审
- [ ] U `scripts/lifecycle_regression.py`
- [ ] U `scripts/managed_service.py`
- [ ] M `scripts/p2-recovery-probe.py`
- [ ] M `scripts/p3-worker-recovery-probe.py`
- [ ] U `scripts/p5-live-database-check.py`
- [ ] U `scripts/p5-live-preflight.py` — 已修，待复审
- [ ] U `scripts/p5-live-state-check.py` — 已修，待复审
- [ ] M `scripts/p5-worker-recovery-probe.py`
- [ ] U `scripts/permit-test-runner-isolation.py` — 已修，待复审
- [ ] U `scripts/prepare-permit-tests.py`
- [ ] M `scripts/restart-worker.ps1`
- [ ] U `scripts/start-coder-local.ps1`
- [ ] M `scripts/start-local.ps1`
- [ ] U `scripts/stop-coder-local.ps1`
- [ ] M `scripts/stop-local.ps1`
- [ ] M `scripts/stop-worker.ps1`
- [ ] U `scripts/test-offline.py`
- [ ] M `scripts/test-p2.ps1`
- [ ] M `scripts/test-p3.ps1`
- [ ] M `scripts/test-p4.ps1`
- [ ] M `scripts/test-p5.ps1`
- [ ] M `scripts/test-real-models.py`
- [ ] U `scripts/verify-permit-deployment.py`
- [ ] U `scripts/verify-permit-migration.py`
- [ ] U `scripts/verify-permit-restoration.py`

### 测试（29）

- [ ] U `tests/fixtures/seal_s2_probe.py`
- [ ] U `tests/unit/test_seal_entry_arguments.py`
- [ ] U `tests/unit/test_seal_s1_queries.py`
- [ ] U `tests/unit/test_seal_s1_fixture_query.py`
- [ ] U `tests/unit/test_seal_s2_maintenance.py`
- [ ] U `tests/unit/test_seal_s3_issuer.py`

- [ ] U `tests/fixtures/coder-startup-probe.ps1`
- [ ] U `tests/fixtures/lifecycle_acceptance.py`
- [ ] U `tests/fixtures/lifecycle_dummy.py`
- [ ] U `tests/fixtures/lifecycle_permit_child.py`
- [ ] U `tests/fixtures/offline_guards.py`
- [ ] U `tests/fixtures/permit_process_worker.py`
- [ ] U `tests/fixtures/preflight_guards.py`
- [ ] M `tests/fixtures/provider_stub_worker.py`
- [ ] U `tests/fixtures/transport_permit_stub.py`
- [ ] M `tests/http/test_inference_api.py`
- [ ] U `tests/http/test_permit_api.py`
- [ ] M `tests/integration/test_dependencies.py`
- [ ] U `tests/integration/test_execution_permits.py`
- [ ] U `tests/integration/test_model_runtime_status.py`
- [ ] M `tests/integration/test_real_agents.py`
- [ ] M `tests/integration/test_sandbox_failures.py`
- [ ] U `tests/unit/test_coder_local.py`
- [ ] U `tests/unit/test_deepseek.py`
- [ ] U `tests/unit/test_lifecycle_manager.py`
- [ ] U `tests/unit/test_lifecycle_permit_child.py`
- [ ] M `tests/unit/test_model_adapter.py`
- [ ] U `tests/unit/test_permit_boundaries.py`
- [ ] U `tests/unit/test_preflight_policy.py`

### 文档（16）

- [ ] U `docs/MAINTENANCE_ENTRIES.md`
- [ ] U `docs/P5_SEAL_FIX_REPORT.md`

- [ ] U `docs/DEEPSEEK_CODER_LOCAL.md`
- [ ] M `docs/GETTING_STARTED.md`
- [ ] M `docs/LEARNING_PATH.md`
- [ ] U `docs/LOCAL_LIFECYCLE_GUARD.md`
- [ ] U `docs/LOCAL_LIFECYCLE_TEST_REPORT.md`
- [ ] M `docs/MODEL_INTEGRATION.md`
- [ ] U `docs/P5_LIVE_DEEPSEEK.md`
- [ ] U `docs/P5_LIVE_FIRST_CALL_REPORT.md`
- [ ] U `docs/P5_LIVE_PERMIT_DESIGN.md`
- [ ] U `docs/P5_LIVE_PERMIT_TEST_REPORT.md`
- [ ] U `docs/P5_LIVE_PREFLIGHT_REPORT.md`
- [ ] U `docs/P5_LIVE_SAFETY_DEPLOYMENT_REPORT.md`
- [ ] N `docs/P5_SEAL_MANIFEST.md`
- [ ] M `docs/PROJECT_STATUS.md`

## 未来人工批准的操作边界

1. 本轮已获授权修复SEAL-S1/S2/S3；隔离验收和精确文件变化另见修复报告，未触碰当前Protected实例。
2. 更新安全复核和证据绑定，重新确认运行门禁、差异、秘密与逐路径清单。
3. 用户明确批准后，仅按最终审定清单逐路径暂存，复核cached diff、cached check及敏感扫描；不得git add -A或自动包含新文件。
4. 再创建单个提交，建议消息：chore(p5): finalize lifecycle safety and zero-cost acceptance。
5. 仅在提交及清单复核通过且用户另行明确批准Tag后，创建p5-lifecycle-safe-baseline；当前同名本地Tag不存在。本轮未创建。
6. Push不在本次授权内，另行批准；不将P5封版视为收费模型授权或P6授权。

本次git add、commit、tag、push均未执行。修复后候选为123文件（55跟踪修改、68未跟踪文件）；此处M/U为当前Git状态，不代表本轮新增。重审全部差异后仍需用户另行明确批准提交与Tag；本轮停在修复验收交付点。
