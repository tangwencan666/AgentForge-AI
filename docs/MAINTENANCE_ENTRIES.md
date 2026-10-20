# P5 本地维护入口与权限清单

2026-10-16；固定项目根目录 `D:\AIProjects\AgentForge-AI`。本清单描述源码修复后的合作式脚本策略，不授权执行维护操作，也不代表当前内存中的 API/Worker 已加载修复。

## 共同边界

`maintenance_policy.py` 的固定操作集合、`cli_gate` 和 `maintenance_action` 统一调用 `LifecycleManager.maintenance_session`。Protected 记录在取锁前只读拒绝；取锁后再次校验完整状态、PID/创建时间/实例身份及未登记进程。有运行中 API/Worker、未知状态、查询失败或竞争即拒绝。审批不允许覆盖 Protected 实例。

CLI 在业务导入之前取得保护，租约持续至进程 atexit，包含异常及 finally。导入后调用公开维护函数仍需保护。异步函数持锁跨 await；不同 asyncio Task 不视为同线程锁重入。同步 CLI 到首个异步操作的嵌套会临时绑定 Task，结束恢复同步所有者。

高风险维护使用独立交互式 `MAINTAIN <本次UUID>`，60 秒后失效，确认后重验状态；没有 force、跳过检查、环境授权令牌或静默批准参数。维护授权与模型 Permit/Issuer 权限分离。Protected 人工停止仍只走原有 `STOP` 独立审批流程；本轮没有执行。

## 完整 scripts 入口分类

| 文件 | 策略与范围 |
| --- | --- |
| start-local.ps1、stop-local.ps1、stop-worker.ps1、restart-worker.ps1 | 固定 lifecycle CLI；Mock 环境校验、OS 锁、完整身份检查；拒绝 Protected |
| start-coder-local.ps1 | 要求 Coder 凭据名称存在且无 Issuer/其他模型凭据；保持关闭策略；已有匹配健康实例只复用 |
| stop-coder-local.ps1 | 独立交互式人工停止；不会授权自动重建 |
| test-p2.ps1、test-p3.ps1、test-p4.ps1、test-p5.ps1 | 固定 maintenance-run；拒绝 Protected/运行中主实例；没有 finally 自动恢复主服务 |
| lifecycle-entry.ps1、lifecycle.py | 固定项目/固定动作分派；不接收任意 root、状态目录或命令 |
| lifecycle_manager.py、managed_service.py | 统一状态与进程管理；引导需已登记启动意图、管理器创建身份及一次 claim |
| lifecycle_regression.py | 导入调用亦受 regression.run 保护；固定项目/阶段；P5 另要求隔离设置路径 |
| maintenance_policy.py | 固定维护权限、审批、CLI/导入入口及内部命令上下文；无独立通用执行功能 |
| bootstrap_local.py | bootstrap.local；仅首次创建项目配置，已有文件拒绝覆盖 |
| bootstrap-p4.py | bootstrap.p4；补齐项目角色凭据；Protected 时拒绝 |
| bootstrap-sandbox.py | bootstrap.sandbox；固定镜像登记；替换已有镜像另需 bootstrap.sandbox.rotate 人工批准 |
| migrate.py | migrate.current/check/upgrade；在保护之后加载 Alembic；upgrade 需要独立批准 |
| configure-deepseek-coder.py | configure.coder；模型仍 Disabled；写配置前按名称拒绝 Issuer/模型凭据；Protected 时拒绝 |
| p5-live-preflight.py | prepare 受 preflight.prepare 保护；run 仅固定可信命令及 OS 环境白名单，不能作为任意命令桥 |
| p5-live-state-check.py | state.inspect；--stop 为 state.hold，需独立批准且更新限当前租户；Protected 时均拒绝 |
| permit-test-runner-isolation.py | runner.pause/restore 均需独立批准；Protected 时拒绝；仅固定项目 Runner 命令 |
| deploy-permit-database.py | verify 保留 permit.verify；backup/migrate 旧迁移路径默认退役拒绝 |
| verify-permit-deployment.py、verify-permit-restoration.py | permit.verify/permit.restoration；调用/导入函数均需维护保护 |
| p5-live-database-check.py | database.owner/verify 保留；backup 旧演练路径默认退役拒绝 |
| prepare-permit-tests.py、verify-permit-migration.py、p2-compose-probe.py | 旧准备/升降级演练/Mock 探针默认退役拒绝；保留历史源码，不提供绕过开关 |
| p2-recovery-probe.py、p3-worker-recovery-probe.py、p5-worker-recovery-probe.py | 原有默认拒绝保持；不能隔离的旧恢复方式不重新开放 |
| test-real-models.py | model.observe；仅观察独立 Permit，不签发/派发/重试；Protected 时拒绝 |
| freeze-lock.py | dependency.freeze；改项目锁文件也需维护保护 |
| check-coder-local.py | 只读前置/运行状态检查，写本地非秘密证据；不启动/停止/恢复或更新业务；本轮未执行其带锁 status 路径 |
| test-offline.py | OS 环境白名单、禁止项目 dotenv 和外部 socket 的单元/HTTP；前端选项仅离线构建或明确 Stub 浏览器；不运行主服务维护流程 |
| check_secrets.py | 只读扫描；本轮仅 --no-local-secrets，不读取已知秘密值 |
| process-ownership.ps1、test-process-ownership.ps1 | 遗留纯身份谓词及其测试；不能作为终止授权，不含进程停止操作 |

## 通用 helper 的额外约束

`prepare-permit-tests.command`（含 deploy 的别名）、`p5-live-database-check.command`、`permit-test-runner-isolation.command` 不会自行取得新权限。调用者必须已经由同一逻辑 Task 持有匹配维护 scope，之后再验证完整参数元组。

- Permit 校验只允许固定 PostgreSQL 容器标签 inspect、固定端口及执行容器标签只读查询；permit.verify/restoration 均不授予写命令。旧 restoration 汇总仍保留原0007前置条件，不能作为当前0008部署验收命令。
- 数据库校验额外仅允许固定 `SELECT current_database()`，拒绝任意 SQL、stdin 和其他容器。
- Runner 只允许固定元数据/执行标签查询；停止只在已批准 pause 中，启动只在已批准 restore 中；不得换目标、换动作或执行 Shell。

退役入口中的旧备份/DDL/配置生成实现不是可重新使用的安全接口。重新设计它们需单独授权、资源归属和隔离验收；不能删除保护后沿用旧断言。

## 隔离与限制

测试使用新建项目 work 子目录、假凭据、假业务模块/进程后端，或可信标准库短命进程与随机端口。只在这些目录中测试竞争、审批和恢复；不对真实实例注入故障。历史 work 诊断是保留证据，不是受支持的可重放运维入口。

同 Windows 用户直接修改 Python、手工 uvicorn/Worker、Docker Compose app profile、系统终止及任意导入后执行自写代码不受合作式脚本权限隔离。这不是操作系统安全边界；不能把它解释成恶意管理员无法绕过。当前任务禁止这些操作，也没有运行 Docker/数据库维护或真实模型请求。

## S1 增量（2026-10-18）

本节更新上述历史验收范围；不授权接管主服务。

| 入口 | S1 行为 |
| --- | --- |
| lifecycle.py / lifecycle-entry.ps1 | 固定根目录、固定动作；支持 `python -I` 的固定 sibling 导入；NativeBackend 统一进入 v2 |
| start-local / start-coder-local / stop-local / stop-worker / restart-worker / stop-coder-local | 沿用统一入口，新增 Windows Token 身份、代次和 live IPC 校验；版本1清单在碰锁前拒绝，不自动迁移 |
| managed_service.py | 登记的启动意图、操作者内核身份、单次 claim、固定角色与代次；应用初始化成功才 READY |
| process-ownership.ps1 | 保留只读遗留谓词；没有停止权限，不能作为协调器替代品 |
| test-p2…test-p5 / lifecycle_regression.py | 保留主维护保护，另须独立资源证明；不得在 finally 恢复主服务；P3 Runner 实测明确拒绝 |
| tests/conftest.py / preflight_guards.py | 集成环境在任何业务 fixture 前完成实际资源校验并持租约；只准独立端口，拒绝主 Redis/DB/Runner 和外部模型网络 |
| s1_test_environment.py | 只创建全新 UUID、固定缓存镜像及精确标签的 PostgreSQL/Redis/专属bridge；关闭ICC和masquerade，仅回环端口；变更操作绑定真实锁和进程内 scope，按记录 ID 清理 |
| s1_application_test.py | 在该专属资源租约内建立独立应用根、端口、venv、日志，运行真实 API/Worker 的 Mock 任务及可选浏览器；只允许初始化新的空测试库至0008 |
| frontend/tests/run-e2e.mjs / playwright.config.ts | OS 环境白名单、固定只读资源验证器、独立浏览器目标与报告；不回退主配置；排除真实 Sandbox 用例 |
| lifecycle_permit_child.py / permit_process_worker.py | 父租约和子进程独立资源证明；实际 OS 崩溃仅针对捕获并复核创建身份的测试 Worker；模型 HTTP 使用虚拟 Transport |
| recovery probes / coder-startup-probe | 原退役或只读 PolicyOnly 保护保持；没有重新启用共享环境恢复路径 |

独立应用测试使用新生成的服务测试口令，不读、迁移或保存真实模型 Key/Issuer Token。隔离 Python 子进程通过自己的 `.pth` guard 重新验证资源并安装端口限制；受控 MCP 子进程仅对精确固定模块命令绑定同一测试库，不放宽生产 MCP 权限。

Docker `--tmpfs` 的声明必须精确匹配；支持实际 Docker 将其仅呈现于 HostConfig 而不列在 Mounts 的表示方式。额外 bind/volume/network、错误资源 ID、挂载或端口均拒绝。失败创建保留 RECOVERY_REQUIRED，不能重置状态复用；只在完整归属复核后清理本轮资源。

未覆盖入口仍包括用户直接系统终止、手工 Docker/Compose、修改源码后自建启动器，以及 Runner 跨实例容器归属。历史脚本/临时 work 文件不作为受支持的运维入口。下一阶段须另行批准旧主实例处置、新版部署及 Runner 隔离。
