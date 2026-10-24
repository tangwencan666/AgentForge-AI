# 隔离 Mock 工作流验证

本入口验证真实 API、Worker、PostgreSQL 和 Redis 的显式 Mock 工作流，独立于 [核心离线 CI](CORE_CI.md)。不运行整个本机集成测试集，不使用原 Compose，也不改写现有 S1 验证、生命周期保护或任何应用安全校验。

## 环境与隔离

`.github/workflows/mock-workflow.yml` 只在 GitHub 托管的 Ubuntu 任务中运行。GitHub 为每个任务新建 PostgreSQL 16、Redis 7 服务容器及专属网络，任务结束后回收。两项数据目录使用 tmpfs，无固定容器名称、复用卷、宿主机数据挂载或固定宿主端口；只有随机端口绑定 `127.0.0.1`。不以修改 Compose 项目名作为隔离证据。

`scripts/ci_mock_workflow.py` 在任何 Docker 查询或数据库连接前验证托管 Linux、仓库、工作目录和运行标识；本机或自托管环境直接拒绝。随后只读检查 GitHub 服务上下文提供的两个完整容器 ID、当前 run/attempt 标签、健康状态、tmpfs、端口、网络身份及恰好两个网络成员。容器实际镜像 ID 和端口保存在报告中。服务镜像使用主版本标签，具体镜像以每次报告中的 ID 为准，不宣称跨时间完全相同。

只有证明属于本任务的资源才允许连接。数据库必须没有 public 用户表，Redis 必须为空。入口生成新应用数据库角色、密码、Redis 密码、管理员令牌及 tenant UUID；API/Worker 使用非超级用户角色，迁移也仅允许该角色在带本次实例标记的空数据库执行。PostgreSQL 服务初始化密码仅为本次临时任务的 bootstrap 值，不是生产凭据。没有读取或复用主环境 `.env`、模型 Key 或 Permit Issuer。

父进程与迁移/API/Worker 子进程都安装 Python 审计保护：禁止 dotenv 读取，只允许本次三个回环端点（PG、Redis、API），拒绝外部 DNS、旧端口、Docker Socket 和 Sandbox Runner。子进程禁止再启动程序。子进程先重新核验容器，再接受通过 stdin 传递的测试配置；配置和秘密不进入命令行、报告或 artifacts。API/Worker 使用正常应用实现和真实 Connections，没有 StubConnections、MockTransport、Worker.tick 手动驱动或内部审批调用。

真实模型开关与单次 Permit 均关闭，Worker 为 `deny`，日/测试真实费用预算为 0、重试为 0，保留 `AGENTFORGE_EXTERNAL_MODELS_BLOCKED=1`。Mock 每日模拟预算为有效正数 10 USD、100 万 token，每任务模拟预算 1 USD。Sandbox Token、镜像和 Runner 均不配置。

## 验证场景

| 场景 | 实际断言 |
| --- | --- |
| API/Worker 就绪 | `/health/ready` 返回 200；API 观察到独立 Worker、配置摘要一致且无 Coder Key |
| 创建 Mock 任务 | 真实 HTTP POST 返回 202，执行模式明确为 Mock |
| Planner 后待审批 | Planner 完成，任务等待审批，PostgreSQL checkpoint 持久化且 Worker 认领已释放 |
| 审批前无后续角色 | 持续 2 秒观察多个调度周期，调用账本只有已完成的 Planner |
| 批准后完成 | 使用审批列表返回的 hash 经 HTTP 批准；四角色各执行一次、顺序正确，任务 succeeded，费用为模拟值，真实费用 0 |
| SSE 和游标恢复 | 待审批时可读取真实 SSE；完成后事件 ID 有序且唯一；Last-Event-ID 恢复结果精确等于原事件后缀 |
| 取消待审批任务 | 取消后终态 cancelled，迟到批准返回 409，继续观察 2 秒仍无 Coder/Researcher/Reviewer |

收尾查询数据库，要求非 Mock 模型调用、Sandbox 执行和 Permit 记录均为 0。入口只结束自己创建的子进程；GitHub 自动回收服务容器和网络。不创建或操作用户电脑上的旧 Runner、VMware、Docker 或数据库，不启动 Sandbox，不执行生成代码。

## 复现与证据

1. 在本仓库向 `main` 创建或更新包含此工作流的 PR。它会与现有 Core CI 分开运行；也可在 Actions 页面对该运行选择重新运行。
2. 工作流使用已提交的 `backend/requirements.lock` 和 Python 3.12，执行 `pip check` 及无服务的隔离拒绝测试。
3. 在托管任务的服务上下文下执行 `python scripts/ci_mock_workflow.py`；该命令没有本地放行参数。不要通过伪造 CI 环境变量在本机运行。
4. 查看 `isolated-mock-evidence` artifact：`result.json` 为逐项结果、容器/网络身份、端口、任务 ID、SSE 游标和安全计数；`migrate.log`、`api.log`、`worker.log` 为实际子进程日志。artifact 保留 7 天。失败使用非零退出码并保留已得到的结果，不跳过断言或把失败改为成功。

这是自动化测试模拟经人工批准的 API 决策，不代表发生了真人操作。通过只证明此次托管环境的显式 Mock 路径；VMware Mock 演示、真实模型与计费、真实 Sandbox、Windows 生命周期已知故障及生产运行/部署验收仍保持原有未验证或阻塞状态。新 Mock 验证 PR 保持未合并。
