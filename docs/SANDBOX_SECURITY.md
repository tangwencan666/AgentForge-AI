# P3 Docker Sandbox 安全边界与验证

沙箱提供受限的真实 Python 执行环境。Docker 容器不是绝对安全边界；本项目 P3 仅面向已授权的本地开发与测试，不发布生产部署。模型仍为显式 Mock，不能直接访问 Docker API、可信 Runner 或其凭据。

P3 实施与实际隔离验证跨 2026 年 10 月 14–15 日（Asia/Shanghai）。下文依据源码和已确认的真实 Docker 执行证据记录边界；最终全套数量与提交以 `P3_REPORT.md` 为准。配置字段、测试替身和单次探针仍不能证明绝对安全。

## 1. 信任边界

浏览器 → FastAPI → PostgreSQL/outbox → Redis Worker/LangGraph → 受保护 Runner → 固定镜像容器。

API 负责认证、Schema、租户、代码校验、资源预算、幂等请求和独立审批。Worker 只派发执行 ID、任务 ID、owner 和 fence。Runner 从数据库重新读取可信记录，在启动与代码注入边界核验租约、审批哈希、策略和资源。模型、Reviewer's 审核意见和客户端参数均不授予执行权限。

只有 Runner 管理容器生命周期。执行容器不挂载 Docker Socket，也不挂载任何宿主机文件或目录。Compose 中可信 Runner 为连接 Docker daemon 而挂载 Socket；这属于控制面，必须与不可信执行容器明确区分。该 Socket 能控制 Docker 环境，不能因为 Runner 自身只读或 drop capabilities 就视其为低权限服务。

Runner 被攻陷、数据库/控制凭据被窃取或 Docker daemon 被攻陷，可能影响同一 Docker 环境中其他容器、卷和宿主机。P3 没有实现 Docker daemon 操作授权代理或生产专用执行节点。实际测试只创建、检查并清理 AgentForge 自己的容器，不操作其他项目。

## 2. 固定执行策略

策略代码位于 `backend/app/sandbox/policy.py`，当前版本 `p3-python-v2`。调用者仅能在服务端范围内选择更低的 CPU、内存、PIDs 和超时，不能覆盖隔离配置。

| 控制 | P3 实现 | 拒绝或校验 |
| --- | --- | --- |
| 镜像 | 单一批准的 `sha256:<64 hex>` 镜像 ID；基础镜像 Dockerfile 固定 digest | 不接受 tag、任意镜像或运行时自动拉取；镜像不可用时拒绝 |
| 网络 | `network_mode=none` | 创建后检查、运行时只见 `lo`；真实 connect 探针返回 Linux errno 101 |
| 用户 | `10001:10001` 非 root | 创建配置与容器内 UID/GID 共同检查 |
| 根文件系统 | `read_only=true` | 容器内读取 mount 状态，对批准镜像内 0666 canary 的真实写入返回 EROFS |
| 临时目录 | `/workspace` 64 MiB、`/tmp` 16 MiB tmpfs，`nosuid,nodev,noexec` | 不提供宿主机 bind、volume 或 devices；每次新容器拥有新目录 |
| 资源 | CPU 0.25/0.5/1 核，内存 64–512 MiB，PIDs 8–64 | cgroup v2 核对限额；真实 CPU 节流、受限内存分配和有限进程测试通过，见证据表 |
| Swap | memory + swap 总量等于内存限额 | 要求容器 cgroup `memory.swap.max=0` |
| 权限 | `privileged=false`、`cap_drop=ALL`、无 cap_add、`no-new-privileges` | 在容器内检查 NoNewPrivs、capability effective/permitted/inheritable/ambient 均为空 |
| Seccomp | 默认 `SCMP_ACT_ERRNO` 的服务端白名单 | 禁止 mount、ptrace、bpf、keyctl、setns、unshare 等；要求运行时 Seccomp 模式 2 |
| 命名空间 | 无 host network/PID/IPC 配置 | 执行前 inspect 校验禁止的配置 |
| 文件描述符 / core | nofile 128、core 0 | 固定服务端 ulimits |
| 输出 | 累计 stdout + stderr 1 MiB；每路摘要最多 4096 字符 | 超限终止，先脱敏再裁剪持久化 |
| 并发 | 默认全局 4、租户 2，均有硬上限 | PostgreSQL 全局锁与持久化活动执行计数，不能只靠单进程内存 |

`none` 网络仍有容器自身的 loopback，不应把“完全没有任何 socket 能力”作为承诺；验收要求是无授权外网或宿主机网络访问。Docker 官方说明该模式只创建 loopback 接口。[Docker none network](https://docs.docker.com/engine/network/drivers/none/)

Seccomp 限制系统调用，依赖 Docker 与内核支持。P3 使用针对批准 Python 镜像的自定义较小白名单，兼容性不等同于通用 Docker 默认配置；任何 syscall 放宽都需审查和策略版本更新。[Docker seccomp](https://docs.docker.com/engine/security/seccomp/)

v2 只为 CPython 打开脚本时的 close-on-exec 设置补充 `ioctl` 参数 1 等于 `FIOCLEX=0x5451`，保留 `TCGETS=0x5401`。不放行 FIONCLEX、FIONBIO 或任意 ioctl；命名空间创建与 AF_VSOCK 仍被拒绝。该变更对应 CPython 的文件描述符不可继承处理，经源码审阅后升级策略，不以禁用 seccomp 解决启动失败。[CPython v3.13.5 fileutils.c](https://github.com/python/cpython/blob/v3.13.5/Python/fileutils.c#L1395-L1433)

CPU/内存限制依赖内核控制，设置内存与 memory-swap 相同用于禁止容器使用 swap。采样数值不证明硬限制，必须验证实际运行行为。[Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints/)

## 3. 双重启动检查与代码传输

1. Runner 校验固定镜像、服务端持久化参数、独立审批、预算和 Worker 租约，先提交启动意图。
2. 创建未运行容器，检查 Docker inspect 与固定策略一致，将容器 ID 持久化。
3. 再次授权后启动批准镜像内的可信 launcher。此时未发送不可信代码。
4. launcher 报告 UID/GID、只读根、seccomp、NoNewPrivs、capabilities、接口与 cgroup v2 限额。Runner 核验后再次从数据库检查权限和租约。
5. 只有全部通过，代码才通过 attach stdin 注入一次。launcher 写入容器 tmpfs `/workspace/main.py`，用 `python -I -S` 启动独立子进程。

launcher 不带 Docker 客户端，不在 Windows 宿主机执行。其子进程环境变量是服务端固定的安全集合，未注入数据库、Redis、管理员、审批者、Runner 或模型凭据。父 launcher 关闭可转储属性，减少同 UID 子进程读取或修改父进程内存的机会；这不构成新的独立内核隔离边界。

运行时报告来自代码注入前的批准 launcher，可发现错误配置，但报告本身不能证明无内核漏洞或无逃逸能力。因此验收还要运行受限、非破坏性的实际代码探针。

## 4. 超时、取消、清理与幂等

可信 Runner 在容器外监控时间与取消状态。容器内 launcher 另有超时 alarm，并对执行子进程组发出终止信号。外部 Driver 到期 kill 容器并移除；任务总 deadline 同时包括排队与审批时间。

不可信代码可能创建子进程、改变自己的进程组或试图影响 launcher。最终清理由 Docker 容器级 kill/remove 处理，不以子进程正常退出或工作目录清空作为隔离证明。输出流、取消信号、状态检查与超时均受服务端控制。

每次执行使用独立容器和 tmpfs。完成或失败后强制移除容器，并向 daemon 再次查询确认不存在。`cleanup_status=removed` 表示已确认删除；没有创建容器则为 `not_created`。如果 daemon 断连或无法确认删除，标记 `unconfirmed`，全局阻止新的沙箱执行，不伪造“已清理”。

Runner 启动及周期 reconcile 只识别同时满足以下条件的本项目容器：固定命名 `agentforge-p3-exec-<execution UUID hex>`、策略标签以及对应执行 ID 标签。不能确定归属的容器不删除。活跃有效 Runner 租约的容器不被另一 Runner 清理。

清理以当前策略标签为范围。策略/镜像轮换前，先核对旧版本执行容器已为零，再更新登记；不能假定新版本自动清理所有旧标签，也不能批量删除未知归属的容器。

启动意图已写入数据库的执行不会重新启动。Worker 重启、重复 Redis 消息和重复 Runner dispatch 读取原记录或原结果。启动后结果未知时保留 `needs_reconciliation`，原代码不会重跑。若该记录仍未确认清理则阻断新执行；若已确认 `removed`，保守结算原预留后可接收新任务，但原结果仍需人工核对，不能改成成功。此设计不保证外部副作用 exactly once。

`assert_runner_lease()` 在启动、注入、监控边界拒绝已经过期的 Runner 租约；晚到的完成者也不能续活过期权限或发布成功。实际 Worker OS 进程重启已验证；这不同于强杀 Runner OS 进程。受控数据库 Runner 租约过期案例已在最终套件中通过，实际运行容器被清理且原启动意图没有重放；本轮未专门强杀 Runner 后重启来证明全部崩溃窗口。

Docker unavailable、镜像缺失、运行时报告不匹配、状态/权限校验失败或清理未确认，均 Fail Closed。没有宿主机 Python、shell 或其他不受限执行回退。若 Docker daemon 无响应，系统不能凭空保证立即 kill；未确认状态必须保留并阻断后续工作。

## 5. 预热与跨任务状态

P3 默认关闭预热，设置校验拒绝启用；没有声称实现可验证的预热池。当前全部执行使用一次性容器。

未来预热只能保留未运行过不可信代码的容器，需要固定策略、池大小、租约、有效期与隔离验证；容器一旦分配执行，无论成功、失败、超时或取消都必须销毁，不能回池。不能证明清理和隔离时继续使用一次性容器。

跨任务验收需要前一容器创建文件并退出，后一容器确认文件不存在；同时确认前容器已删除，而不是仅删除工作目录。这项测试只用本项目无敏感内容的标记文件。

## 6. 数据、输出与秘密

执行审计保存任务/执行 ID、代码哈希、策略、审批、限制、时刻、退出码、脱敏摘要、采样资源、失败原因和清理状态。Docker 执行容器采用 `log_config=none`，应用日志不默认记录完整 stdout/stderr、代码、请求正文或任意异常 traceback；SSE 保存安全元数据。

为了持久化审批和恢复，64 KiB 以内源代码保存在独立 `sandbox_executions.code` 业务字段，普通列表与执行结果不返回。独立审批者 `/source` 可读取，响应 no-store；前端只在页面内存展示。当前源代码在 PostgreSQL 中为明文业务输入，P3 没有应用层加密或到期删除机制，数据库管理员与可信服务仍可访问。不要提交敏感文件或秘密代码。

已知本地凭证、常见密钥模式和部分编码变体会在创建时拒绝，输出再脱敏后裁剪。脱敏不能保证识别所有未知、拆分、加密或任意编码的秘密；不能把它当作允许提交真实 API Key 的依据。即使未向容器传递服务端凭据，用户自行写入代码的内容仍可能被输出。

输出洪泛调试暴露了 URL 凭据脱敏正则的耗时问题，现已收紧匹配，并将有界输出脱敏移到线程、在持有业务 SQL 行锁之前完成。`tests/unit/test_sandbox_output.py` 覆盖 1 MiB 输入与凭据过滤，防止正则阻塞取消和检查点；最终运行结果计入 P3_REPORT，不把安全配置检查当作该测试通过。

`resource_usage` 是采样而非完整峰值或精确计费，短任务可能没有 CPU/内存/PIDs 采样。未知资源使用不能被解释为零消耗或免费重试。P2 模拟模型费用与沙箱资源额度分开，没有真实模型账单。

## 7. Windows Docker Desktop 的能力与残余风险

本阶段在 Windows Docker Desktop 的 Linux 容器环境验证。cgroup、seccomp、UID、Linux 文件系统和 namespace 行为发生在 Docker Desktop 的 Linux VM 中，不能据此推导 Windows 宿主机的全部安全属性。

| 风险 / 不能充分验证的能力 | P3 边界 |
| --- | --- |
| 共享 Linux 内核、Docker/runtime 或 Python 漏洞导致逃逸 | 本轮没有破坏性漏洞利用，不能证明不存在逃逸；固定镜像仍需要补丁与供应链审核 |
| Docker Desktop VM 与 Windows 宿主集成、共享目录或 hypervisor 边界 | 只能验证没有授权挂载和常规路径不可读；不能证明 VM/宿主内核逃逸不可能 |
| AppArmor / SELinux 与 Linux 生产环境的 LSM 策略 | 本轮未建立生产专用配置或充分验证，不能以 seccomp 结果替代 LSM 验收 |
| 生产 Linux 身份、rootless/user namespace、宿主 UID 映射 | 本轮只有容器内非 root；没有证明生产宿主与多租户身份隔离 |
| 有 Docker Socket 的可信 Runner | 被攻陷可超出项目控制；生产需要独立执行节点和受限控制面设计 |
| 资源 DoS 与高频执行 | 每容器和并发受限，但 VM/daemon、磁盘元数据与整体宿主承载能力仍有残余风险 |
| 同 UID launcher 与执行子进程 | 只读镜像及独立外部超时降低影响；不能声称进程间绝对隔离 |
| 控制面与数据库损坏、凭据外泄 | 本轮固定本地角色；未提供生产认证、密钥管理、存储加密和留存治理 |

不得为演示关掉安全策略、切换 `privileged`、host 网络、`seccomp=unconfined` 或挂载敏感目录。任何系统权限、Docker Desktop 全局配置或新组件变更必须先获得用户确认。P4 仍需单独授权。

## 8. 实际隔离证据与验收方法

已确认的证据来自本项目 PostgreSQL、Redis、独立 Runner 和 Docker Desktop Linux 容器。`work/p3-docker-isolation.xml` 记录隔离试跑 13 项，其中 12 通过、1 个网络探针失败；修正后 `work/p3-extended-docker-final.xml` 的网络、容量与隔离故障 Runner 三项均通过。最终 `work/p3-all-final.xml` 为 153 项通过，包括 16 项真实沙箱服务集成；浏览器 8 项通过，两套均无失败或跳过。不能把首次失败隐去或把多次调试重复加为额外成功数量。

| 要求 | 实际结果与边界 | 对应证据 / 测试 |
| --- | --- | --- |
| 正常 Python | 真实输出、退出码 0、图检查点存在、删除确认；通过 | `test_python_real_docker_execution_and_checkpoint` |
| 无网络 | 真实 `connect(('1.1.1.1',80))` 立即返回 Linux ENETUNREACH 101；没有成功连接；不声称穷尽全部网络路径 | `test_runtime_network_identity_root_and_credentials`，extended final XML |
| 宿主机文件不可读 | 本项目无敏感标记在 Windows 路径和两个 Docker Desktop host 路径候选均不存在；通过，不读取真实敏感目录 | `test_host_marker_is_not_readable` |
| 非 root / 权限 / 无 Socket | UID 10001、Seccomp 2、NoNewPrivs 1、CapEff 全零、Docker Socket 不存在；通过 | `test_runtime_network_identity_root_and_credentials` |
| 只读根文件系统 | 对镜像内权限 0666 的 canary 写入返回 EROFS，排除只因普通文件权限拒绝的误判；通过 | 同一 runtime 探针 |
| CPU | 0.25 核额度下忙循环约 2 秒，CPU 时间 / 墙钟时间小于 0.55；实际节流通过，不声称精确性能保证 | `test_cpu_quota_actually_throttles` |
| 内存 | 64 MiB 限额下有界尝试分配 128 MiB，非零退出且未完成分配；通过，不制造宿主机 OOM | `test_memory_limit_bounded_allocation` |
| PIDs | 上限 8，最多尝试 12 个短时子进程，触发限制且创建数量不超过 6；通过，不做 fork bomb | `test_pids_limit_bounded_spawn` |
| 超时 / 取消 | 1 秒任务超时，以及运行中取消，均终止并 `removed`；通过 | `test_timeout_kills_entire_container`、`test_cancel_kills_and_confirms_cleanup` |
| 输出截断 | 有界输出 2 MiB 被 `output_limit` 终止，每路摘要 ≤4096 字符，容器删除；通过 | `test_output_limit_truncates_and_removes` |
| 并发 | 实际同时观察 4 个执行容器；同租户第 3 个及全局第 5 个请求均 429，未写新启动意图；通过 | `test_real_runner_tenant_and_global_capacity_with_live_containers` |
| 审批拒绝 | 拒绝后没有容器 ID 与容器；实际通过 | `test_rejection_never_launches` |
| 无权限 / 镜像 / 参数审批绑定 | HTTP 与策略拒绝测试覆盖，不以替身称真实执行通过；最终套件结果另列 | `test_unauthorized_execution_never_reaches_storage`、`test_admin_cannot_approve_high_risk_code`、`test_only_immutable_approved_image_ids_are_accepted`、`test_approval_hash_binds_all_execution_parameters` |
| Docker 不可用 | 专用 18121 控制面无 Socket、DOCKER_HOST 指向不存在地址，真实服务返回 503，无启动意图、无容器、无宿主机回退；通过，没有停止共享 daemon | `test_real_isolated_unavailable_runner_refuses_without_launch_or_host_fallback` |
| Worker 恢复 / 重复消息 | replacement Worker 测试保留同容器、输出 once 一次；真实 OS Worker 重启探针也确认唯一启动意图、同容器和删除；通过 | `test_duplicate_messages_and_worker_restart_reuse_execution`、`scripts/p3-worker-recovery-probe.py` |
| Runner 恢复 | 受控租约过期、Worker 租约仍有效时拒绝续活、保留原启动意图并清理实际容器；通过。未专门强杀 Runner OS 后恢复，不能宣称完整进程崩溃验收 | `test_real_expired_runner_lease_cannot_revive_with_live_worker_lease` |
| 无状态泄露 | 前一任务写 workspace 标记，后一新容器看到 False，两个容器 ID 不同且都删除；通过 | `test_no_state_leak_between_disposable_tasks` |
| 凭据不泄露 | 容器中 TOKEN/PASSWORD/AGENTFORGE/DATABASE/REDIS 环境键为空；已知秘密代码被拒绝，实际通过；最终 Git/日志扫描由 P3_REPORT 汇总 | runtime 探针、`test_idempotent_create_and_secret_rejection` |
| 无遗留执行容器 | 上述真实测试在结束时逐个向 daemon 确认本执行标签无容器；阶段结束全局本项目核对由 P3_REPORT 记录 | `assert_no_container()` / `RealHarness.no_containers()` |

首次网络探针调用 `socket.settimeout()` 被 FIONBIO 策略拒绝，该失败验证了禁止的 ioctl 生效，但没有证明网络不可达。修正为直接 connect，靠任务总超时作外部界限，保持 FIONBIO 拒绝；随后发现断言误用 Windows errno 10051，改用实际 Linux errno 101。只读测试改为批准镜像中的可写权限 canary，以 EROFS 区分只读挂载与 EACCES。

初期 CPython 启动缺少 FIOCLEX 的失败同样如实保留；只在审阅对应源码后增加最小参数规则并升版，未放宽任意 ioctl、网络、挂载或权限。修复后使用新的执行 UUID 和重新审批验证，原已提交启动意图的诊断任务不重放。这些修正和执行故障不是最终成功数量之外的额外“通过项”。

## 9. 维护者阅读顺序

所有路径相对于项目根 `D:\AIProjects\AgentForge-AI`：

1. `backend/app/schemas/sandbox.py` 与 `backend/app/core/config.py`：请求上限、固定镜像、不同角色凭据、拒绝预热。
2. `backend/app/services/sandbox.py` 的 `create()` / `decide()` / `cancel()`：服务端审批、预算与持久化控制。
3. `backend/app/sandbox/policy.py` 的 `validate_execution()` / `create_options()` / `verify_container()` / `verify_attestation()`：不可覆盖的 Docker 策略。
4. `sandbox-image/Dockerfile`、`launcher.py` 的 `attest()` / `main()`：批准镜像内的可信启动、单次输入和子进程超时。
5. `backend/app/sandbox/driver.py` 的 `run()` / `remove()`：真实 Docker attach、输出上限、终止与删除确认。
6. `backend/app/sandbox/engine.py` 的 `dispatch()` / `_authorize_boundary()` / `_monitor()` / `_finish()` / `reconcile()`：数据库启动意图、租约、失联恢复与泄漏阻断。
7. `backend/app/services/orchestration/sandbox_graph.py`、`backend/app/workers/engine.py`：持久化图与 Worker 集成。
8. `tests/http/test_sandbox_api.py`、真实集成测试与 `frontend/tests/sandbox.spec.ts`：按测试类型阅读，区分安全替身和实际 Docker 证据。

P3 完成后的下一阶段条件：先关闭任何未确认执行与清理问题，补充独立 Linux 执行环境和生产身份边界的设计审查，再在新的授权范围内实施 P4。不能自动进入 P4，也不能因本轮测试通过声称沙箱绝对安全。
