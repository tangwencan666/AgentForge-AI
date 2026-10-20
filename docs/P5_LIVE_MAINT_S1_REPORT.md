# P5-LIVE-MAINT-S1 实施与隔离验收报告

状态：**S1_LOCAL_PASS / MAIN_TAKEOVER_BLOCKED**。项目内实现及本轮允许的隔离验收完成；没有接管主服务，不进入 P6。

项目 D:\AIProjects\AgentForge-AI；Git 基线 982e83ef32b7d274e820d59ee63d6fb76bd8979e。本轮保留全部既有未提交 P5-LIVE-SAFETY、生命周期及 SEAL 修改，不重置、暂存或提交。

基线与源码证据：work/maint-s1/d5b9df15-19f1-4a92-b374-22a37e9a0beb/baseline.json。记录224个源码/文档哈希；source-baseline 保存 scripts/tests/docs 的文本副本，backend/frontend 主要保留哈希。没有复制主 dotenv 或模型凭据。该快照不是完整工作树备份。

实时基线（2026-10-16 14:21:43 +08）：API PID9872，FILETIME134365952448839137；Worker PID17228，FILETIME134365952504254344。只读接口报告 Coder 存在 True/True、配置一致、四槽 Disabled、真实/签发开关 False、日/测试预算0、重试0、Worker deny、出口阻断。只检查名称，不验证真实 Key 内容或供应商认证。

2026-10-18 恢复会话时，主 API 的127.0.0.1:18100已无法连接、旧PID不存在，Docker Linux Engine管道也不存在。用户随后明确反馈已启动 Docker，既有 PostgreSQL/Redis/Runner 随引擎恢复。本轮没有执行这些主容器的 start/stop/restart，也没有启动或恢复主 API/Worker。不能把10月16日的 True/True 当作当前结果。

## 实际改动

相对S1开始时的工作树，39个文件发生增量变化。完整路径与源码哈希见 work/maint-s1/s1-source-changes.json；不能把相对Git HEAD的所有P5-LIVE变更都归于S1。

| 文件 | 修改目的 |
| --- | --- |
| scripts/lifecycle_windows.py、lifecycle_channel.py、lifecycle_v2.py、lifecycle_runtime.py | 原生Token/SID、可信IPC、实例代次、保护状态、一次性维护审批、应用READY |
| scripts/lifecycle_manager.py、managed_service.py、lifecycle.py | Native统一路由、同句柄身份复核、固定bootstrap、隔离Python入口导入 |
| scripts/check-coder-local.py、lifecycle_regression.py、process-ownership.ps1 | 固定可信观察入口、隔离证明、Runner拒绝、遗留谓词不授予停止权限 |
| scripts/s1_isolation.py、s1_test_environment.py、s1_application_test.py | 专属PG/Redis/网络、资源租约、精确清理、独立真实应用和浏览器监督器 |
| backend/app/main.py、backend/app/workers/main.py | 依赖/Worker初始化成功后才通知生命周期READY；没有更改P3/P4/Permit业务规则 |
| frontend/playwright.config.ts、frontend/tests/run-e2e.mjs | 独立目标与输出、实际资源证明、OS环境白名单、排除Runner测试 |
| frontend/tests/capabilities.spec.ts、deepseek-offline.spec.ts、models-chat.spec.ts、smoke.spec.ts、workflow.spec.ts | 截图改为本次输出路径；明确Stub测试使用本次隔离origin |
| tests/conftest.py、tests/fixtures/preflight_guards.py | 集成fixture前校验并持资源租约；拒绝主端口、Runner和外部模型网络 |
| tests/fixtures/lifecycle_acceptance.py、lifecycle_permit_child.py、permit_process_worker.py、s1_lifecycle_native.py；tests/integration/test_execution_permits.py | 原生进程竞争/崩溃、受控子进程、实际Job归属和真实PG恢复测试 |
| tests/unit/test_lifecycle_ipc_s1.py、test_lifecycle_v2_native.py、test_lifecycle_v2_scope.py、test_lifecycle_permit_child.py、test_s1_entry_isolation.py、test_s1_isolation.py | IPC、一次性审批、同句柄终止、资源/入口拒绝及无凭据日志回归 |
| docs/LIFECYCLE_MANAGER_DESIGN.md、LIFECYCLE_SECURITY_TESTS.md、MAINTENANCE_ENTRIES.md、本报告 | 设计、入口、证据、失败和未验证边界 |

`frontend/tests/offline-server.mjs`是既有文件，本轮未修改。run-e2e.mjs在初始文本快照中缺失，单独标为MODIFIED_UNSNAPSHOTTED；以完整Git diff复核。work/maint-s1/s1-delta-review.patch仅供审阅，包含有文本快照的增量和新增源码，不是完整可自动应用/暂存的补丁。

## 身份、互斥与入口

Native实例采用版本2清单：instance_id、启动generation、PID、原始FILETIME、实际解释器、TokenUser SID、TokenLogonSid、SessionId，以及角色/模式/公开配置绑定。独占OS字节锁、原子记录、live命名管道共同校验；PID文件、环境布尔值和UUID都不能单独授权。终止前在持锁期间重新证明身份，最终在同一进程句柄核对后终止。

状态包括STARTING、READY_PROTECTED、STOPPING、STOPPED_PROTECTED、RECOVERY_REQUIRED；进程消失不解除保护。明确维护停止需绑定操作者、目标代次、清单修订、动作及60秒有效期的一次性确认，核验结束后再次检查期限，并在停止前持久化CONSUMED。失败审计只记录白名单原因码，不保存异常正文或凭据。

start-local、start-coder-local、stop-local、stop-worker、restart-worker及stop-coder入口均经固定协调器；同配置专用启动幂等。旧版本1清单在打开锁前拒绝，不迁移或接管。test-p2…test-p5保留主维护保护，另须隔离证明；P3及旧共享恢复探针保持拒绝。完整分类见MAINTENANCE_ENTRIES.md。

## 本轮测试结果

没有用历史450/600/421项结果冒充本轮执行。以下批次含复测，不直接累加批次数字。

| 执行层次 | 结果与证据 |
| --- | --- |
| 完整离线单元/HTTP（排除单独执行的生命周期文件） | 762通过，work/maint-s1/unit-final-v2-20261018/result.xml，67.59秒；包含40项原生Win32 IPC测试和89项资源Stub测试 |
| 审批时效与失败审计补测 | 4通过，其中2项已包含上行、2项新增；scope-final-20261018/result.xml；明确使用时钟/身份Stub |
| 生命周期原用例＋原生新用例 | 16个不同用例最终通过；native-final-20261018/result.xml中14通过、race失败；修复后native-repair-20261018/result.xml中race/identity两项通过。原12项含FakeBackend/短命进程；新增4项走原生Backend与真实Windows进程，应用为标准库Stub；真实API/Worker另列 |
| 专属PostgreSQL/Redis集成 | 111通过，17项Sandbox用例排除；a6061d71-bc1b-4cbb-a457-d2dfbdec5f59/integration.xml，195.07秒。真实事务并发、Redis、MCP及两次实际OS Worker崩溃；模型均为虚拟Transport |
| 独立真实API/Worker/前端 | PASS，5ba7f86c-fcb7-4eb2-b9f4-3c955fd039d7/application-report.json。空测试库升级0008；四角色Mock任务成功、4个Mock调用、真实费用0；身份未变；协调器停止与清理确认True |
| 浏览器 | 14通过、0失败/重试/跳过；1项完整假后端、1项健康接口故障注入、其余12项实际本地UI/API路径；同目录browser.json。2项Sandbox浏览器未执行 |
| TypeScript/构建 | tsc通过；Vite构建通过，输出frontend-final-20261018/dist，未覆盖既有dist或读取服务器dotenv |

合计891个不同Python用例最终有通过证据（764单元/HTTP＋16生命周期＋111集成）；分批验证，不声称一次命令运行891项。集成有1条既有Alembic path_separator弃用警告。

关键证明：双真实PowerShell竞争只有一组API/Worker；另一个收到LOCK_BUSY；独立可信控制进程停止成功。错误FILETIME及错误SID在真实进程句柄上拒绝，目标Worker继续存活；没有声称强迫Windows复用了指定PID。伪造活进程清单/保护标志/代次和环境标志被拒绝；维护过期及重放被拒绝；Worker实际崩溃不自动重建；模型Permit派发未知状态保留预留、不重发。测试Worker连接的是独立Redis容器及端口，没有向主Redis写测试哨兵。

## 失败与修正记录

- 初始IPC最小权限缺少FILE_READ_ATTRIBUTES；修正后40项原生测试通过。没有修改系统ACL。
- 隔离Python `-I`入口找不到sibling模块；改为固定可信脚本目录导入。
- race夹具等待退出却未读取大于Windows管道缓冲的清单输出；改为独立输出文件。随后发现父启动器退出造成子进程归属漏记；以匿名测试Job的内核成员关系和同句柄身份补证，不按PID猜测。失败证据保留。
- Docker创建态无Health字段、--tmpfs仅在HostConfig呈现、网络自动补IPv4/IPv6选项；精确支持这些实际表示，额外挂载/网络仍拒绝。internal网络实测无主机端口，改为专属bridge、ICC/masquerade关闭、回环发布，并新增运行态端口校验；不声称容器具备绝对外网隔离。
- a6061d71应用尝试在前端react-router/dom别名处失败；未启动业务验收，保留失败记录，Job和归属校验确保进程退出。依据安装包exports修正隔离副本配置。
- aaa57a43在写应用日志前启动失败；保留START_UNCERTAIN，随后相同端口的只读查询成功。原错误已被归一化，不能断言一定是超时。新增启动失败白名单原因审计及独立只读预检；不放宽查询或自动重试旧实例。5ba7f86c全新实例完整通过。

## 主环境、清理与凭据

2026-10-18 11:39:12 +08只读OS核验：测试范围Python/Node/Edge进程0；原主PID9872/17228不存在。主work/lifecycle的manifest.json、audit.jsonl、operation.lock三项哈希、大小及写入时间均与S1基线一致。

最终主API仍ConnectError：**Main API Coder Credential Present = UNVERIFIED；Main Worker Coder Credential Present = UNVERIFIED**。不能确认当前主环境True/True、实时配置或预算。独立Mock实例的False/False是预期测试状态，不能代替主环境检查。没有读取、迁移或修改真实Key/Issuer Token。

本轮7个专属数据栈均CLEANED，Docker复核S1标签容器/网络0；失败清单/审计保留，未把RECOVERY_REQUIRED伪造为成功。最后三个数据栈清理记录见cleanup-final-20261018.json；OS记录见final-os-state-20261018.json。主容器ID保持不变，当前StartedAt均为用户启动引擎后的2026-10-18 02:59:03–04 UTC、RestartCount0。本轮没有控制主Runner或清理其他实例执行容器。

所有外部真实模型请求0，真实费用0。没有真实Key/Issuer读取、供应商健康探测或主环境Permit签发、收费开关/槽位启用。Provider Stub测试中的真实路径开关、虚拟额度及假凭据槽位仅存在于隔离测试对象和独立测试库，不能解释为主环境授权。

## Git与敏感信息

HEAD保持982e83ef32b7d274e820d59ee63d6fb76bd8979e，暂存区空。当前59个已跟踪修改、84个未跟踪文件包含原有P5-LIVE工作，不能全部作为S1独立提交。没有基线源码丢失。git diff --check通过；CRLF规范化提示不属于diff错误。

269个Git工作文件、暂存内容、bundle及既有报告的凭据格式扫描通过；没有读取dotenv或真实Key做逐值比较。新增测试配置均在被忽略的work内；Git候选中未发现dotenv、备份、.key/.pem。S1证据和新构建产物另做格式扫描。没有自动add/commit/push。

建议提交名：`feat: isolate Windows lifecycle maintenance and S1 tests`。先审查现有P5-LIVE基线，按39文件清单分块选择S1改动；共享文件不要直接git add -A。部分旧文本快照缺失，不能自动应用审阅补丁来分离提交。

## 剩余风险与下一阶段

1. 旧主实例未部署v2、当前主API无法核验，**不具备立即接管条件**。须另外授权主环境恢复/对账与受控交接，在持Key的用户PowerShell操作，不能复用旧收费授权。
2. Runner跨实例容器归属尚未升级；17项真实Sandbox集成和2项浏览器保持BLOCKED，不把Stub算作真实P3执行验收。
3. 当前机制保护合作式入口，不抵御同Windows用户篡改可信代码/所有审计或直接系统操作；实际跨Windows账户登录部署未验证。任意手工uvicorn、Compose app profile、系统kill仍不属于受支持入口。
4. CIM/IPC异常会保留保护并拒绝；必须保留人工恢复流程，不能为可用性增加Force或自动清空状态。回滚源码应逐块移除S1新增内容、保留P5-LIVE未提交改动；不能reset/覆盖工作树，运行中实例和v2记录也不能靠回滚脚本接管。
5. 下一阶段先审阅39文件、完成独立提交安排；再明确授权旧主实例的身份对账和v2交接、现场True/True与关闭策略验收；Runner隔离另外实施。之后若要真实DeepSeek测试，仍须新的单次明确授权。

S1到此暂停。设计见LIFECYCLE_MANAGER_DESIGN.md，验收含义见LIFECYCLE_SECURITY_TESTS.md，全部入口见MAINTENANCE_ENTRIES.md。
