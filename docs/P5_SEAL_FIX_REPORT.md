# P5 三项封版缺口修复与隔离验收

2026-10-16，Asia/Shanghai。项目 `D:\AIProjects\AgentForge-AI`；原始 HEAD `982e83ef32b7d274e820d59ee63d6fb76bd8979e`，main 分支。用户授权实际修改源码、测试和文档，不授权主服务起停、业务修改、真实模型调用、提交或 P6。

本轮结论及最终执行数字见文末“收尾实测”。原450项是此前验收，不计入本次成绩。此前只读审计发现的三个问题已经进入实际修复，历史报告保留以说明证据时间。

## SEAL-S1：查询结果和身份不确定

修改 `scripts/lifecycle_manager.py`：

- `NativeBackend._query` 是统一 PowerShell 查询边界：ErrorAction Stop、显式 try/catch、检查 Error 集合、固定版本/查询类型/success/rows 成功 envelope；非零退出、任意 stderr、空输出、坏 JSON、类型不符、权限错误、超时均拒绝，诊断不携带原始输出。
- `_rows` 在项目过滤前检查 Python/Node 候选的元数据完整性；无法确认归属也拒绝，不能将受限进程过滤为空。项目行要求完整 PID、父 PID、执行路径、命令行和 CIM 创建时间；重复 PID 拒绝。
- `_identity` 将 CIM 的微秒精度与两次原始 Windows FILETIME/执行路径核对；两次原始创建身份必须完全一致。`inspect` 只有查询明确成功且 OS 也确认退出才返回不存在；CIM 未见但 OS 仍活着返回身份未验证错误。
- `_listeners` 在完整 TCP 表成功获取之后筛选端口；无监听是成功空集，端口查询错误是失败。`healthy` 的端口归属失败不能变为健康。
- `maintenance_session` 在取锁前只读拒绝任何 Protected 记录，并在 OS 锁内重新做完整检查。保留 UUID、原始创建时间、启动 claim、PID 转发关系和同一终止句柄校验。

`tests/fixtures/lifecycle_permit_child.py:PermitProcessChild._rows` 同样复用严格查询边界，验证固定 launcher 范围、完整字段及重复 PID，不再把空 stdout 解释成没有子进程。该真实数据库崩溃 fixture 本轮没有运行；只对查询部分注入故障。

所有 PowerShell 查询子进程只接收固定 OS 变量白名单，不继承模型凭据或 Issuer。服务本体的合法 Coder Key 原生继承保留，并在可信 Windows 测试替身中实际验证。

未知状态拒绝与可用性有取舍：同机 Python/Node 元数据不可读时会阻断维护/启动，而不是猜测它属于别的项目。无法消除拥有同用户权限的外部工具或恶意操作者修改状态/抢端口的所有竞态；实际停止仍在同一进程句柄重新核验创建身份。

## SEAL-S2：维护入口与通用 helper

新增 `scripts/maintenance_policy.py`：

1. 固定操作白名单、固定项目根目录和退役操作集合；未知操作直接拒绝。
2. `cli_gate` 在业务导入之前获取共同维护保护并持续至 CLI 退出/atexit；`maintenance_action` 同时覆盖导入调用和同步/异步函数，锁跨 await、异常和 finally。
3. `_logical_owner` 区分同线程不同 asyncio Task。同步 CLI 可进入首个异步操作，操作期间绑定该 Task；其他 Task 拒绝，结束恢复同步所有者。
4. `_approve` 为状态 hold、迁移 upgrade、Runner pause/restore、镜像替换提供独立真实交互 challenge；60秒、当前状态范围、确认后重新检查，不使用 Issuer，不允许静默参数。
5. `require_maintenance_context` 和 `authorize_maintenance_command` 封住导出通用 command helper：不能自行取得维护权限；已有只读权限也不能扩大成 Docker stop、任意 SQL、其他容器或 Shell。

完整41份 scripts 文件及入口分类见 [MAINTENANCE_ENTRIES](MAINTENANCE_ENTRIES.md)。本轮补齐配置、状态、Runner、迁移、备份/恢复、bootstrap、观察和锁文件维护入口；P2/P3/P5 旧通用恢复探针继续默认拒绝。0007/0008一次性旧备份/迁移/重演及旧 Compose probe 默认退役，保留源码与证据，没有新绕过开关。

`p5-live-state-check.main --stop` 仅能修改当前租户的非 Mock、非 Sandbox 任务，且需独立批准及无受保护/运行中主实例。既有 P2–P5 测试不在 finally 重启主服务。主实例的普通维护启动、测试清理、导入函数、command helper 均在副作用前拒绝。

保留维护功能的正向测试使用显式 subprocess 替身：合法固定 inspect/SELECT，以及人工批准后的固定 Runner stop/start 参数可通过；测试从未真实操作 Runner。

## SEAL-S3：Issuer 不进入维护配置或子进程

`p5-live-preflight.py` 将模型凭据与独立 Issuer 权限显式分类，不再仅依赖 core 的模型引用分类器。prepare 受共享维护保护；父环境出现 Issuer 名称就拒绝，不获取其值。根 dotenv 或已有维护文件出现 Issuer/模型凭据声明时，在 dotenv 解析之前按名称拒绝；包含 export、小写、引号及无等号形式。模型 Key 行不复制到服务配置。

`run` 仅接受固定项目 Python 和固定可信脚本/参数，拒绝任意 -c、-m、Shell、Docker、路径替换及任意 cwd。子进程环境从 OS 白名单重新建立，只添加服务设置引用和关闭策略；父环境不清除、不修改。服务设置文件也必须通过凭据声明检查。

`configure-deepseek-coder.py` 在 Settings、dotenv 值解析和配置写出前重复按声明名拒绝 Issuer/模型凭据；解析结果再显式拒绝。这覆盖“维护文件已经污染”及校验后、写出前出现污染的路径。旧配置生成器因退役无法继续复制旧权限。

专用 start-coder-local.ps1 仍要求 Coder Key 名称存在、Issuer 名称不存在，只在合法专用环境原生继承 Coder Key。没有改变用户全局环境或其他进程环境。本轮只使用虚构凭据验证，未获取、打印、记录、哈希或导出真实模型 Key/Issuer Token。

## 测试隔离和证据

本轮证据根：`work/seal-fixes/repair-20261016-121118-62e6865d`。开始时 baseline.json 保存244个源码/文档指纹和7个已知不含秘密的保护元数据指纹；不扫描真实 dotenv、Key 或日志内容来做已知秘密比较。所有原有工作和证据保留。

新增测试矩阵：

| 范围 | 新增用例 | 最终独立证据 |
| --- | ---: | --- |
| S1 查询/身份故障 | 54 | repair目录 s1.xml；后续联合结果以 s1-query-fixtures.xml 为准 |
| S1 fixture 查询和查询环境 | 29 | repair目录 s1-query-fixtures.xml（合104，另含既有21） |
| S2 维护入口和权限 | 111 | 独立s2-maintenance-final-109.xml为前109项；最终offline-final.xml包含全部111项 |
| S3 Issuer 与配置链 | 65 | work/seal-fixes/s3-chain-unit.xml |
| 镜像替换参数缩写拒绝 | 2 | repair目录 arguments.xml |
| 新增合计 | 261 | 完整执行汇总不重复累计这些独立复跑 |

S2 111项为26个CLI动作、28个导出函数调用、26个固定操作、17个状态/锁/审批/异步场景、8个helper越权反例和6个正例。业务声明桩只允许纯导入；Settings、数据库、dotenv实际访问、socket和进程副作用均有禁止探针。

完整离线回归的 run_checks.py 明确创建白名单环境，禁止主 dotenv 和外部 socket，使用独立 TEMP、pytest cache、XML 路径，未覆盖历史450项证据。Native 测试复制三份生产脚本到独立项目目录，用随机端口、空服务文件、假Key和标准库 API/Worker stub；不是实际 FastAPI/Redis Worker，也不是真实供应商验证。仅终止这些测试自己创建并校验的进程。

### 失败与修正记录

- S2 首轮 policy40项38通过/2个夹具问题：Protected 优先拒绝语义、子进程stdin TTY；入口50项49通过/1失败发现 configure 导入时隐式执行。夹具修正、生产入口加 if-main，证据保留。
- 本轮首轮12项 Windows/逻辑生命周期回归11通过/1失败，native.xml保留。严格查询耗时增加，标准库测试服务达到原90秒寿命，人工停止阶段的身份变化被拒绝。仅将可信测试服务寿命调到300秒、独立场景超时调到360秒，未延长生产执行/安全超时、删除断言或放宽身份检查。
- 新增同线程跨Task保护时发现同步CLI→asyncio.run嵌套被误拒，已通过逻辑所有者交接修正并加入正反回归。
- bootstrap-sandbox 禁止 argparse 参数缩写，避免镜像替换参数缩写被解析器接受却未被固定审批分类器识别；2项独立参数回归证明在 dotenv 访问前拒绝。
- 最终独立复核发现Permit汇总验证需要的固定执行标签只读查询漏列，已为permit.verify/restoration加入精确查询及2项替身正例；未开放Docker写命令。旧restoration的0007历史前置条件保留，当前0008下不会成功冒充通过。

历史450项及其真实Docker/MCP/数据库证据保留，本轮不重跑会触发生命周期、Runner或业务数据修改的P2–P5集成测试。P3/P4相关离线权限/策略/HTTP测试包含于本轮完整回归；它们不能替代真实Docker/MCP集成。未执行收费认证、推理或计费探测。

## 当前运行实例与残余限制

12:28:35 +08只读快照已确认 API9872、Worker17228仍为11:34原始创建身份和UUID、Protected，18100属API，GET健康HTTP200/ready，PG/Redis UP、主库0008。两端Coder Key存在布尔为True、configuration_consistent=true。四槽Disabled，真实/Permit关闭、两预算0、Worker deny、出口阻断、重试0；活动任务/Permit、真实模型操作账本、Permit派发、待发布Outbox均0。保护元数据7文件内容/大小/mtime完全未变。

源码更新未重启服务，当前进程仍使用原内存代码。其健康只证明未受影响；修复的运行证据来自独立目录的新源码进程。没有加载真实Key运行新进程。

尚未验证：DeepSeek认证、deepseek-flash实际可用性、真实推理/usage/计费、生产部署与P6。进程脚本保护是合作式约束，不能阻止有权限用户通过操作系统或自行执行任意代码；Docker也不被视为绝对安全边界。

## 收尾实测

**PASS — THREE SEAL ISSUES FIXED AND VERIFIED**。

最终实际执行去重 **600项，600通过，0失败，0错误，0跳过**，新增261项、既有339项。先完整596项在274.13秒通过，再补参数2项；最终审查补齐Permit只读helper查询2项后，最新非原生回归588项在60.98秒通过、12项明确deselected（非skip）。这12项是前组已经通过、源码逐字节未变且只依赖三份复制模块的Windows生命周期场景；与最终588项不重叠。最终600不是同一条命令输出，不累计重复复跑或历史450。

证据绑定于本轮 evidence-summary.json：offline-final.xml（588项）SHA256 `4b6d0fe195415428c888ced8e19d8b7d381517680e539063f5b3f3b6d277ff80`；offline.xml（含12项原生子集的596项）SHA256 `01687699aab911121ccc3d47c0cd35451b9c67b96d734da2e8b02a72d09ecb5c`。两份本轮Native可信替身目录的lifecycle_manager.py/lifecycle.py/managed_service.py均与最终源码逐字节一致；核心manager SHA256 `abf20ea4bc13784b92577ca6cf126afc888ee4f7d14dc6143fe2cae1ca889752`。XML和这些指纹是非秘密测试/源码证据，不是凭据哈希。

12:40:41 +08再次只读检查：原API9872/Worker17228身份、HTTP200、PG/Redis UP、0008、Key存在布尔、配置一致、四槽Disabled和零费用门禁保持，所有活动/真实账本/派发/Outbox计数0，7个保护元数据内容/mtime/大小未变。12:35只读进程清点本轮测试残留0；Docker只读查询执行标签容器0，主Runner仍Up、主PG/Redis healthy，克隆Runner/PG/Redis仍Exited。没有生命周期、容器或业务修复操作。

Git HEAD仍982e83ef32b7d274e820d59ee63d6fb76bd8979e/main、索引空。当前整体55跟踪修改、68未跟踪文件（config目录在short输出折叠为单项），含此前大量工作。本轮相对baseline.json修改28个已有文件、新增9个，共37；其他216个基线文件字节不变，无删除。后端、前端、迁移、配置定义、依赖和既有安全实现没有被本轮重写。

本轮完整源码/文档253文件格式扫描、Git diff --check及29个Python文件AST/空白检查通过；14份PowerShell仅语法解析通过。未读取真实Key/Issuer或dotenv秘密值做对照，格式扫描不是已知秘密值比对，也不证明任意秘密绝不可能存在。运行时.env、日志、锁、备份、XML、依赖与构建产物继续排除在候选提交之外；证据只在忽略的work目录保留。

### 本轮实际修改的37个文件

脚本20个：

- scripts/lifecycle_manager.py、maintenance_policy.py、lifecycle_regression.py。
- scripts/bootstrap_local.py、bootstrap-sandbox.py、bootstrap-p4.py、migrate.py、freeze-lock.py。
- scripts/configure-deepseek-coder.py、p5-live-preflight.py、p5-live-state-check.py。
- scripts/prepare-permit-tests.py、deploy-permit-database.py、p5-live-database-check.py、permit-test-runner-isolation.py。
- scripts/verify-permit-deployment.py、verify-permit-migration.py、verify-permit-restoration.py、p2-compose-probe.py、test-real-models.py。

测试9个：

- tests/fixtures/lifecycle_acceptance.py、lifecycle_permit_child.py、seal_s2_probe.py。
- tests/unit/test_lifecycle_manager.py、test_seal_s1_queries.py、test_seal_s1_fixture_query.py、test_seal_s2_maintenance.py、test_seal_s3_issuer.py、test_seal_entry_arguments.py。

文档8个：

- docs/P5_SEAL_FIX_REPORT.md、MAINTENANCE_ENTRIES.md、LOCAL_LIFECYCLE_TEST_REPORT.md、LOCAL_LIFECYCLE_GUARD.md。
- docs/PROJECT_STATUS.md、P5_SEAL_MANIFEST.md、GETTING_STARTED.md、LEARNING_PATH.md。

已审查的受支持入口未发现未解决的S1/S2/S3绕过路径。任意手工Python/同用户改文件/系统终止/直接Compose等在合作式边界之外，不能称为OS级不可绕过。退役路径不能未经重设计再启用。当前真实服务未加载修复是刻意保留的运行边界，不将原进程健康当成新代码验证。

可以重新申请P5封版审计。重新审计、最终逐路径暂存、Commit、Tag、Push以及加载新源码的人工维护均需后续明确授权；本轮未执行这些操作，不进入P6。
