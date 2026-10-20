# P5-LIVE-MAINT-S2 隔离预检与暂停报告

日期：2026-10-18（Asia/Shanghai）。结论：**BLOCKED — RUNNER_CROSS_INSTANCE_CLEANUP_UNSAFE**。

用户要求在必须改变主 Runner 协议、标签或清理逻辑时先暂停。本轮在启动测试 Runner 前确认此阻塞，未修改或升级主 Runner，未解除任何测试保护。S2 实现及完整验收尚未完成。

## 基线与实际工作

- 项目：`D:\AIProjects\AgentForge-AI`；HEAD：`982e83ef32b7d274e820d59ee63d6fb76bd8979e`；暂存区空。
- 开始时59个已跟踪修改、84个未跟踪文件，全部保留。264个允许的源码/文档文件已另存文本和哈希，未复制真实 dotenv、Key 或 Issuer Token。
- 只读检查 S1 报告、生命周期协调器、测试资源证明、维护入口和浏览器目标保护。
- 通过 Docker `inspect`、标签清单及三个固定源码文件的只读 `docker cp`，核实实际主 Runner 镜像。没有在容器内执行命令。
- 使用实际 `SandboxRunner.reconcile()` 与内存 Driver/Session 替身复现跨数据库清理判断；所有网络连接受离线审计限制。
- 仓库改动仅为本报告、`SANDBOX_ISOLATION_DESIGN.md`、`PROJECT_STATUS.md` 和 `LEARNING_PATH.md`。没有修改生产或测试入口代码。

证据目录：`work/maint-s2/readonly-precheck-20261018/`。`baseline.json`/`source-baseline/`保存基线；`main-observation.json`保存脱敏观察；`main-runner-source-review.json`保存镜像源码哈希及相关函数；`stub-repro.py/json`保存离线复现。该目录被 Git 忽略，不建议提交。

## 已确认的安全问题

实际主 Runner ID：`f2da347b403e96ba640d806eb8924ca91e389237de7e445858bfc8bb69c445d7`；镜像：`sha256:3e81842718ce5adf0d55a5fa82cd0f0505adf98faebdd1334c2c78e62b07ba5a`。其 `driver.py`、`engine.py`、`policy.py` 与工作树对应文件字节一致。

1. `DockerDriver.owned()`只筛选全局标签 `agentforge.sandbox.policy=p3-python-v2`。
2. `create_options()`只写策略及 execution 标签，名称为全局 `agentforge-p3-exec-<execution UUID>`，没有部署实例归属。
3. `SandboxRunner.start()`立即对账，后台每5秒再次对账。`reconcile()`对名称/标签匹配的容器查询本实例数据库；没有记录或没有有效租约时，调用 `driver.remove()`。
4. `remove()`只验证上述策略、execution 和名称，然后可能 kill/remove；`_absence()`和创建结果未知的补偿查找也采用全局名称。
5. 独立数据库会让另一实例的合法执行记录变成“本库不存在”。新旧 Runner 共用 Docker daemon 时，存在双向误清理风险。普通标签、随机 UUID、独立 Redis 或当前容器为空，均不能证明未来删除权限。

这是源码缺陷及 Stub 清理决策复现；没有证据表明本轮真的发生误清理。没有创建真实容器来冒险证明问题。

## 本轮验证分层

| 类别 | 实际结果 |
| --- | --- |
| 主 Runner 镜像核对 | 只读确认，3个源码文件与工作树一致；不是跨实例执行通过 |
| 内存 Stub 诊断 | 2个情形符合现有行为：本库无记录时记录1次模拟删除决策；本库有效租约时0次。**复现缺陷，不是安全验收 PASS** |
| 17项真实 Sandbox 集成 | **0项执行，17项 BLOCKED**：`test_sandbox.py`13项、`test_sandbox_failures.py`3项、`test_real_agents.py`中实际 P3 执行1项 |
| 2项 Sandbox 浏览器 | **0项执行，2项 BLOCKED**，未取消 Playwright 排除规则 |
| 生命周期 S2 回归 | **静态复核，未重新执行**：OS锁、同句柄身份检查、代次绑定、IPC、审批过期/消费和 finally 隔离仍在；S1的891/14仅为历史证据 |
| P3/P4、Permit、预算/出口 | 源码与S2基线一致，未改规则；本轮没有重新执行运行时回归，不能宣称全部通过 |
| 外部真实模型请求 | 本轮 **0次**；未运行供应商探测或真实模型入口 |

17项含网络/资源限制、超时/取消、Worker恢复、容量、Docker不可用和租约失效，不能用两项内存诊断替代。后续还需新增真正的跨 Runner、崩溃恢复和归属不明拒绝清理测试。

## 主环境现状与影响

2026-10-18 12:15 +08只读检查：主 API固定地址`127.0.0.1:18100`连接失败；12:13端口检查未发现18100/15173监听，历史API/Worker PID9872/17228不存在，18120仍监听。**API/Worker Coder Credential Present = UNVERIFIED / UNVERIFIED**。没有自动恢复；这些结果不足以确定此前退出原因，也不能排除其他未知Worker进程。

主 PostgreSQL、Redis、Runner均 running，容器ID和StartedAt与S1最后记录一致，RestartCount均0；主Runner未挂载项目源码，只有Docker socket挂载。未执行主服务 start/stop/restart/dispatch/cleanup，未写主库、Redis或生命周期状态。

主 API不可用，因此当前四槽、预算、真实/签发开关、Worker模式、任务/Permit数量**无法通过实时接口确认**。不把历史关闭状态或测试配置当作当前证明。本轮未修改这些配置；隔离配置源码仍固定真实关闭、Worker deny、预算0、出口阻断和重试0。

检查时既有策略标签执行容器0、S1标签容器/网络0。本轮没有创建测试服务、数据库、Redis、浏览器或容器，无本轮测试资源需要清理；不清理未知资源。12:18收尾核对主生命周期manifest/audit/lock的哈希、大小、写入时间全部未变。

## 后续授权与提交

隔离设计和需改文件见[SANDBOX_ISOLATION_DESIGN](SANDBOX_ISOLATION_DESIGN.md)。共享 daemon 下不能直接运行19项；需要单独批准 Runner 协议/归属/恢复逻辑源码改造及兼容部署方案，或提供经验证的独立测试 daemon。不能只更新测试一侧而假定旧主 Runner 不会清理测试容器。

**不具备申请主服务接管的条件**：19项未执行、旧Runner缺乏跨实例边界、主API/Worker实时身份/凭据/安全状态尚未核实。主服务恢复和接管仍须另行授权，真实模型收费授权不延续。

Git收尾：59个已跟踪修改、86个未跟踪文件（使用`--untracked-files=all`计数），索引空；只有两个既有文档相对本轮基线改变，另新增两个文档，没有基线源码丢失。`git diff --check`通过；271个Git候选文件、索引、既有构建与报告的凭据格式扫描通过，新证据目录格式扫描无发现。没有读取dotenv或真实Key逐值比较。

建议独立文档提交标题：`docs: record S2 runner isolation blocker and remediation plan`。用户可在 Windows CMD审阅后执行：

```bat
cd /d D:\AIProjects\AgentForge-AI
git add -- docs/P5_LIVE_MAINT_S2_REPORT.md docs/SANDBOX_ISOLATION_DESIGN.md
git add -p -- docs/PROJECT_STATUS.md docs/LEARNING_PATH.md
git diff --cached --check
git diff --cached
git commit -m "docs: record S2 runner isolation blocker and remediation plan"
```

交互暂存只选择本轮段落；其他P5/S1改动不应一并提交。以上为建议，未执行add、commit或push。最终差异、敏感格式扫描和基线对比见证据目录`final-checks.json`；格式扫描不能代替真实Key逐值比较，本轮不读取Key比较。不进入P6。
