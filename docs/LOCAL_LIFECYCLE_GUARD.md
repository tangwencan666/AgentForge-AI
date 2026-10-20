# P5-LIVE 本地进程启动保护

> 2026-10-19 文档修正：最新归档与运行结论见 [PROJECT_STATUS](PROJECT_STATUS.md)。G4 `e9ced78` 为 Archive-only，原 IPC 故障未完成可信诊断，**RUNTIME_BLOCKED**。本轮未核验主服务/Protected状态、凭据、数据库/Docker或Permit/预算，当前值均为 UNKNOWN / 未验证。下述源码行为与有日期的历史测试不能代替当前实例证明，所有运维仍需独立批准。

> 2026-10-16历史记录：后续授权已修复SEAL-S1/S2/S3，当时Protected服务保持原实例运行、故障注入仅在假凭据环境；不把该观察沿用到现在。原证据见[P5_SEAL_FIX_REPORT](P5_SEAL_FIX_REPORT.md)和[MAINTENANCE_ENTRIES](MAINTENANCE_ENTRIES.md)。源码更新不代表运行中进程自动加载修复。

源码设计用于防止 AgentForge 自身启动、停止、恢复和测试脚本误操作；当前 G4 动态验收仍失败，不能声明现有实例已完成此保证。它不阻止拥有足够 Windows 权限的用户直接结束进程、修改项目文件或手工操作 Docker，不构成操作系统强安全边界。

## 身份与共享互斥

所有受支持的本地生命周期入口调用固定项目的 scripts/lifecycle.py，由 scripts/lifecycle_manager.py 管理。work/lifecycle/operation.lock 是稳定、不替换的 OS 独占锁；生命周期内部身份/状态检查、审批消费、启动/停止和清理保持持锁。专用 Coder 入口的数据库启动前后校验在此锁外，启动动作进入管理器后仍重新检查进程范围。竞争、异常状态或无法确认身份时拒绝，没有 force/skip-guard 参数。

manifest.json 保存实例 UUID、角色、模式、设置文件路径及元数据、非秘密关闭策略、PID、Windows 原始创建 FILETIME、实际可执行路径和启动意图。API/Worker 由固定 managed_service.py 引导，实例 ID 进入命令行；Windows venv launcher PID 与实际 Python 子进程分开识别。不能单凭旧 work/dev-pids.json 接管服务。发现旧的未登记服务时拒绝，不自动杀进程或导入旧 PID。

停止前验证整个作用范围，实际终止在同一 OpenProcess 句柄上核对创建时间、TerminateProcess 并等待退出，防止验证后 PID 被复用。先写启动意图/停止审计，再操作进程；清理不确定不能作为成功或自动重试。

## 模式与保护

普通 start-local.ps1 仅用于没有模型凭据的 Mock 环境。发现任何模型凭据名称或 Issuer 名称即拒绝，避免把持 Key 的子进程误标为非保护实例。原生环境继承不读取、打印、复制或保存 Key 值。

start-coder-local.ps1 要求当前 PowerShell 已具有 AGENTFORGE_MODEL_CODER_KEY，且没有 AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN 及其他模型角色凭据；只检查名称。专用入口创建受保护 API/Worker。重复调用只允许复用身份和配置一致的健康受保护实例，不把“有 Key”视为强制替换授权。

保护状态不含秘密。已保护实例即使退出或经人工停止，也保留保护记录；停止审批不授权无 Key 的维护环境自动替换。不同实例、配置不一致、残留启动意图等异常均应保留证据并拒绝，不手工删除 manifest/锁来解锁。

## 不变的模型门禁

专用入口仍执行 check-coder-local.py 的启动前后校验：0008_execution_permits、无活动任务/Permit、真实模型操作账本为零、四模型槽位 Disabled。校验不负责自动升级数据库，也不自动关闭已启用槽位。Python 优化模式被明确拒绝，不能跳过 assert 校验。

引导进程再次固定 real_calls_enabled=false、日/测试预算0、single_use_permits_enabled=false、real_worker_mode=deny、AGENTFORGE_EXTERNAL_MODELS_BLOCKED=1、重试0、凭据仅环境引用及关闭外部遥测。模型出口是应用层拒绝，不宣称 Windows 全局网络封锁。凭据名称存在不能证明 Key 有效。

## 使用

以下为另行批准后、确认旧实例交接和资源归属时的条件示例，当前不执行。用户只能在已经持有 Key 且无 Issuer 的独立 PowerShell 中检查名称；不能因存在 Key 就认为有接管或覆盖权限：

```powershell
Set-Location D:\AIProjects\AgentForge-AI
Test-Path Env:\AGENTFORGE_MODEL_CODER_KEY
Test-Path Env:\AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN
# 必须分别为 True / False；不要输出变量值。
& .\scripts\start-coder-local.ps1
```

本次修复不自动执行该操作。数据库、Redis 及主库0008需已就绪；失败就暂停，不开放模型出口或预算作为替代。

普通维护停止、Worker 重启及 test-p2 至 test-p5 遇受保护或未管理实例必须拒绝。显式人工停止使用独立 stop-coder-local.ps1，在真实交互终端确认本次实例范围和短时一次性 STOP challenge，审计成功后才停止；它不使用 Issuer Token，不提供静默批准参数，也不授予无 Key 重建权限。

## 测试入口与隔离

维护测试由共同作用域和OS锁保护，并要求独立资源证明；存在运行中主实例或保护冲突就拒绝，不停止后恢复。test-p2 至 test-p5 没有自动启动主服务的finally。**当前 P3 在 lifecycle_regression.py 直接拒绝 S1_RUNNER_ISOLATION_BLOCKED，既不启动也不清理 runner-unavailable。** 旧按服务名清理/was_running恢复不是可信跨实例授权，不得重新开放。

P2/P4/P5的源码分别选择阶段集成及单元/HTTP，并须验证S1 manifest/settings和持有资源租约；P3真实沙箱及故障测试仍BLOCKED，不能按历史阶段列表执行。test-p4/test-p5不隐含前序完整验收。旧固定permit-test路径本身不是隔离授权，实际容器/数据库/Redis身份、端口和归属必须通过验证；入口不自动迁移基础设施或恢复主应用。旧recovery probes保持退役，permit-test-runner-isolation.py的pause/restore即使有外层维护保护也不得用于新旧Runner交接或测试finally。

仅换端口或租户不能隔离共享 Redis Streams、消费组及 Docker 执行标签。历史离线进程验收使用假 Key、专用 work 子目录和可信短命替身，包含复制三份生命周期脚本、通过 NativeBackend/引导运行标准库 API/Worker stub 的 Windows 进程链；不验证真实供应商认证。两项 Permit OS 崩溃恢复在当时的克隆 PostgreSQL/Redis 运行、模型为虚拟传输，本轮均未重跑。旧 P2/P3/P5 通用 Worker 恢复探针因缺乏可靠资源隔离已默认拒绝运行，历史报告保留；不得拿旧报告当新探针已通过。

Compose app profile、手工 uvicorn/python、Windows taskkill 等不经本地启动脚本的直接运维不是本机制授权入口；禁止与受保护主实例并行运行共享数据库/Redis 的容器 Worker。若需要统一生产/容器生命周期，须另行设计，不使用环境变量绕过本地保护。

## 限制与恢复原则

相同 Windows 用户可直接改代码或状态文件，本机制不抵御该权限级别的恶意操作者。锁不是秘密，文件存在不等于锁被持有；不要删除锁。原子 manifest 与 fsync 降低中断风险，但不保证任意断电时零状态损失。未知实例先保留并检查，不能批量按进程名清理。

中断启动的人工收敛也使用 stop-coder-local.ps1（manual-stop --models-only），没有独立 reconcile 命令。原管理器已退出、单个 UUID/角色候选身份可确认时，明确确认后才停止或清理已死意图；多候选、身份不符、未登记进程或管理器仍活跃继续拒绝。收敛后保留 protected，只有专用 Coder 入口可新建；Mock、普通重启和维护测试仍拒绝接管。

本轮不增加全局权限、服务安装、自动下载、收费授权或 P6 功能。实际测试结果和未完成项单独记录在 LOCAL_LIFECYCLE_TEST_REPORT.md。
