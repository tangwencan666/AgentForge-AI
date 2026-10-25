**VMware 专用 Mock 部署准备**

这是一套独立准备文件，不是已部署环境。基线为 main 提交 662eb38d72f2bed243594deae54008042adf7e45；当前主工作流、CI 隔离入口及旧 Compose 均未修改。新增托管构建和 Compose 验证的范围见 [VM 镜像验证](../../docs/VM_IMAGE_CI.md)。VM 兼容性、SSH 转发与真人浏览器操作尚未验证。禁止直接用旧 Compose 代替此入口。

**文件与范围**

| 文件 | 用途 |
| --- | --- |
| compose.yaml | 六个显式命名服务，其中 migrate 为单独的一次性阶段；五个持续服务 |
| Dockerfile.backend / Dockerfile.frontend | 现代独立 Linux 构建输入，使用提交的锁文件和固定基础镜像 |
| images.lock.json | 基础镜像固定引用、依赖 SHA256、尚未构建的应用镜像空位 |
| runtime.py / vm_mock_policy.py | 无 dotenv 的独立配置入口、显式 Mock 策略及数据身份验证 |
| postgres-init.sh / redis-start.sh | 仅供新建的专属数据容器使用 |
| inspect_target.py | CentOS Python 2.7 可解析的只读目标与镜像检查，不包含部署操作 |
| validate_files.py | 本地 Compose 静态解析，使用无效实例 UUID 和假凭据，不访问 Engine |
| ../../tests/vm_mock/test_preparation.py | 离线配置、目标拒绝与内存数据服务桩测试 |

**保持隔离**

所有资源名以 agentforge-vm-mock- 开头；实例 UUID 写入每项资源标签。新建前必须检查不存在同名容器、网络或卷；不能借助 external 复用现有资源。API/Worker 仅连接新 PostgreSQL 和 Redis，数据库名仍为 agentforge、Redis 路径仍为 /0，以满足现有 URL 校验。禁止连接宿主机 MySQL、旧 mysql8/redis 或旧卷。

数据和 Web 网络均 internal=true；所有服务都没有 ports。前端通过 backend 别名访问真实 API，保留真实 SSE 代理。Windows 未来通过 SSH，将 Windows 回环入口转发至新前端容器的实际 IP:8080。容器 IP 必须在创建后核对专用网络、实例标签并实际读取，不能复用历史地址。SSH 转发尚未实测；本次没有执行以下示意命令：

~~~text
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:15174:<verified-frontend-container-ip>:8080 itheima@192.168.88.130
~~~

不启动 Sandbox、不挂载 Docker socket、不执行生成代码，也不提供 privileged 或 seccomp=unconfined。应用非 root、根文件系统只读、丢弃 capabilities；PostgreSQL/Redis 保留官方镜像初始化新卷所需的默认权限，之后由官方入口降权。不得为了旧内核兼容而放宽这些约束。Redis 的配置文件在其专用 tmpfs 创建并归 redis 所有，密码不放在 server argv。日志每容器 5 MiB x 3，不输出完整配置或环境。

**配置与身份**

未来的输入文件必须是新建、权限 0600 的显式文件，不能位于 Windows 原工作区或来自其 .env。每次 Compose 调用都显式指定 --env-file，并设置 COMPOSE_DISABLE_ENV_FILE=1。不得打印展开后的真实配置；静态验证工具只使用假值。输入名称如下，当前未生成真实值：

| 名称 | 要求 |
| --- | --- |
| VM_MOCK_INSTANCE_ID | 新生成的规范 UUID |
| VM_MOCK_APP_PASSWORD | 新生成 64 位十六进制 |
| VM_MOCK_REDIS_PASSWORD | 新生成 64 位十六进制，独立于其他凭据 |
| VM_MOCK_ADMIN_TOKEN | 新生成 64 位十六进制，独立于其他凭据 |
| VM_MOCK_POSTGRES_PASSWORD | 新生成的独立 PostgreSQL 引导凭据 |
| VM_MOCK_BACKEND_IMAGE / VM_MOCK_FRONTEND_IMAGE | resolved 清单中的不可变 image ID（sha256:config），也支持已验证的 repo@sha256 |
| VM_MOCK_POSTGRES_IMAGE / VM_MOCK_REDIS_IMAGE | 离线导入后使用 resolved 清单中官方镜像的 image ID；省略时使用 Compose 已固定的官方 registry digest |

入口在导入应用 Settings 之前拒绝继承的配置文件定位、数据库 URL、模型密钥和其他服务凭据；允许的策略环境必须与关闭值严格一致。然后仅用上述新输入构造固定服务别名的连接地址，使用 Settings(_env_file=None)，保留全部现有 Settings 校验。真实调用/Permit 关闭、真实 Worker 为 deny、真实日预算及测试预算为 0；Mock token 限额 1000000、模拟预算 10（均为有效正数）。真实模型密钥、Sandbox 令牌和镜像 ID 均不配置，不能以空字符串代替 None。

PostgreSQL 首次初始化在新 PGDATA 中建立无超级权限的应用角色及 vm_demo_guard.identity。API/Worker 必须检查实例、基线提交、角色、模式版本及四个已启用的 Mock 槽位；Redis 的身份标记必须匹配。常规服务不会创建缺失的身份标记或自动迁移。

迁移只能通过显式 migration profile 执行。入口先核对专属标记、非超级用户和空 public，再允许初始化空 Redis 的身份标记。Alembic 使用同一 PostgreSQL 事务中的 advisory lock 与第二次空库检查，之后仅为演示租户启用四个 Mock 槽位。失败不删除数据库、清空卷或自动修复；已有 public 表时拒绝再次迁移。Schema 固定为基线的 0010_sandbox_maintenance。

**镜像与资源限制**

images.lock.json 是未构建模板，应用引用和构建提交为 null，状态为 NOT_BUILT，不能填假 digest 使检查通过。托管构建成功后，实际身份写入对应 Actions artifact 的 images.resolved.json；必须使用与构建提交及 run URL 匹配的产物。基础镜像沿用基线已提交的 PostgreSQL 17、Redis 7.4、Python 3.13、Node 24 和 Nginx digest。既有 Mock CI 使用的 PostgreSQL 16/Python 3.12 成功不能替代这些容器镜像的验证。

构建必须在现代独立 Linux 完成，不使用 Windows Docker Desktop 或这台 1 vCPU VM 编译。构建参数 BUILD_REVISION 必须是真实准备文件提交 SHA；完成后记录真实 image ID、config digest、OCI manifest digest、构建提交和运行链接，检查 OCI 来源标签。本 PR 的独立 Actions 入口只构建/导出镜像并在临时托管环境验证，不发布 registry 或自动部署到 VM。

Compose 设置 pull_policy=never。VM 镜像导入/拉取需后续单独授权；不存在正确本地镜像时应失败，不能自动改用 latest。只读 inspect_target.py --images 在模板未构建时立即拒绝；可显式提供 --manifest /path/to/images.resolved.json。清单解决后核对平台、image ID/config digest 或 RepoDigest，及应用 OCI 标签。本地 build/save/load 没有 RepoDigest 时不会伪造一个，也不把 tag 当作身份。这仍不代表目标内核运行兼容性。

已核对的唯一目标 Engine ID 为 f270beef-fc00-4691-8d57-a6643ad6f7cd。目标检查在 Windows 上会在 Docker 查询前拒绝；Linux 上显式使用本地 /run/docker.sock。五个旧容器必须仍为 exited/no，两个旧卷必须仍在，同名演示资源必须不存在。当前 Engine 汇总 Running 计数异常，检查依据逐容器真实状态，不使用该汇总计数替代运行状态。目标变化时停止并更新盘点，不修改旧资源。

持续服务拟议内存上限合计 1440 MiB：PG 384、Redis 96、API 384、Worker 512、前端 64；迁移阶段另用一次性 384 MiB。限额不是已测峰值。仅一个 Worker，保留上游调度器（最多两个活跃任务），演示应逐任务操作；本准备不声称已经添加强制单并发开关。任何运行限额、AOF/数据库资源开销和旧内核兼容性仍需实测。

**本轮可复现的离线验证**

在独立副本根目录执行（需要已有 Python、PyYAML、Pydantic 及 pydantic-settings；不安装或改动 VM 软件）：

~~~text
python -m unittest discover -s tests/vm_mock -v
python deploy/vm-mock/validate_files.py
~~~

第一项使用内存数据服务桩，不连接数据库、Redis、VM、模型或 Docker。Windows asyncio 本地 socketpair 需工具环境允许。第二项仅调用 Compose config，显式使用不存在的 Engine endpoint、临时假输入文件，并删除临时文件；报告写入独立副本的 work/vm-mock-prep。它不拉取镜像或创建资源。本机 Compose 版本不等同于 VM 的 v2.27.1；目标版本的实际解析尚未执行。

2026-10-24 本轮实际结果：Windows / Python 3.13.5 下上述 19 项离线测试全部通过；Compose 5.4.0 完成六服务静态解析，发布端口为 0；Git Bash 对两个初始化脚本的语法检查通过，未执行脚本。没有重跑核心 CI、API/Worker 或浏览器集成测试，也没有触发新的 Actions。内存桩不能验证真实 PostgreSQL 初始化、迁移事务、Redis 权限或镜像启动，以上仍待独立环境实测。

**下一阶段仍需明确授权**

托管构建/验证属于本 PR 范围。之后仍需单独授权 VM 的镜像导入及受限、network=none 的一次性版本/依赖探测容器；不运行应用工作流、生成代码或 Sandbox。兼容性通过后，才另外授权新目录/凭据、新数据容器和卷、专属数据库迁移、API/Worker/前端启动及 SSH 转发。

本次没有向 VM 传文件、创建凭据、导入镜像、创建容器/网络/卷、迁移或部署。Windows agentforge-p3-runner 和原项目 .env 均不接触。任何静态检查通过都不能改写为 VMware 或真人手动演示验收通过。
