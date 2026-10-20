# P5-LIVE-MAINT-S1 生命周期设计

本阶段仅开发和隔离验收，不部署或接管现有主 API/Worker，不使用真实模型凭据，不签发模型 Permit，不进入 P6。已有 P5-LIVE-SAFETY 和 SEAL 修复作为增量基线保留。

## 运行边界

`scripts/lifecycle_manager.py` 保留已审查的严格 PowerShell 查询、OS 独占锁、原子记录和同句柄终止算法；其公开 `LifecycleManager` 将所有 NativeBackend 调用路由至 `scripts/lifecycle_v2.py`。显式 FakeBackend 仅供代码内测试依赖注入，不存在对应 CLI、环境变量或 Force 开关。

版本 1 清单和没有新 IPC 的旧进程拒绝自动升级、停止和接管。旧服务继续运行不代表加载了新代码。主服务接管必须另外授权。

## 身份与状态

每个新实例包含 instance_id、不可变启动 generation、角色、mode、保护级别、公开配置摘要、PID、原始 Windows FILETIME、实际解释器路径、TokenUser SID、TokenLogonSid 和 TokenSessionId。清单的 generation 是持久记录修订号，实例 generation 是具体启动代次，二者用途不同。

进程身份通过内核句柄与受严格错误协议保护的 CIM 查询核对。命令行不进入审计；不读取环境块、Key、Issuer Token 或凭据摘要。Windows venv 转发父进程和实际 Python 子进程分别核对。

状态对应关系：starting/STARTING → running/READY_PROTECTED 或 READY_MOCK → stopping/STOPPING → stopped/STOPPED_PROTECTED 或 STOPPED。不能确认的启动或停止进入 unknown/RECOVERY_REQUIRED；保护不会随 PID 消失而解除。API 必须实际依赖就绪，Worker 必须初始化成功，才能发送应用 READY。

稳定的 operation.lock 使用 OS 独占字节范围锁。检查、审批消费、派发意图、操作、记录及清理处于同一锁范围。文件存在不等于锁已持有。终止前核验 live IPC，最终在同一 OpenProcess 句柄核验创建时间、解释器和 Token 身份，再终止并等待退出。

## 可信本地观察通道

`lifecycle_windows.py` 封装 Win32 Token/进程身份；`lifecycle_channel.py` 使用本地命名管道、显式最小 DACL、PIPE_REJECT_REMOTE_CLIENTS 和 FILE_FLAG_FIRST_PIPE_INSTANCE。双向对端 PID 由 Windows 提供，再核对 FILETIME、SID、登录身份和实际解释器。

协议为有限大小 JSON，绑定实例、generation、角色、mode、保护状态、公开配置摘要、单次 nonce/challenge 与有效期。管道路径从项目路径和实例代次推导。伪造清单、旧握手、过期/重放消息、无效对端或通道异常均拒绝。ready JSON 只是定位信息，不能授予停止权限。

通道只提供状态观察，不接受 Shell、任意命令、停止或模型执行。原创建者的精确 OS 身份或固定项目生命周期 CLI 可请求观察。维护执行仍须管理器持锁和单独授权。

I/O 使用 overlapped event、有限等待和 CancelIoEx。取消并不等于 I/O 已完成；未确认完成时不复用缓冲或端点。不能用 Redis、PID 文件、环境布尔值替代此协议。

## 维护授权和审计

普通维护不能覆盖保护实例。专用 Coder 启动仅在 live IPC、身份和公开配置一致时幂等复用。Key 名称存在不能授予覆盖权限，也不证明供应商认证有效。

显式停止采用真实交互确认，授权固定绑定动作、操作者的 OS 身份、目标实例代次、清单修订号和短有效期。持锁复核后，将一次性记录持久化为 CONSUMED，再执行停止。没有通过 ID 加载授权的接口；修改 JSON 不创建进程内权限，不允许重放。该记录与模型 Execution Permit 完全独立，不使用 Issuer Token。

审计只保存操作 ID、时间、非敏感 OS 身份、实例/代次、状态和结果；不保存 Key、认证头、环境快照或凭据哈希。审计写入失败阻断后续操作。

## 隔离测试资源

`s1_test_environment.py` 只创建本轮新 PostgreSQL/Redis 容器和专属 bridge 网络，使用固定已缓存镜像 ID、独立 loopback 端口、tmpfs 数据和新生成的测试服务凭据。不复制主 .env，不拉镜像、不运行 Runner、不挂 Docker Socket。

实测发现本机 Docker Desktop 的 internal 网络会留下空的运行态端口映射，Windows API/Worker 无法连接。最终网络精确绑定 bridge、ICC=false、IP masquerade=false、host_binding_ipv4=127.0.0.1、IPv4=true、IPv6=false；验证 HostConfig 声明与 NetworkSettings 实际端口一致。它不是容器级“所有外网绝对阻断”的证明。模型出口由 API/Worker 关闭策略、无真实凭据、子进程独立端点审计钩子及 Provider Stub 共同限制；PG/Redis 不运行模型客户端，且与主网络不相连。没有修改 Docker Desktop 全局设置。[Docker bridge](https://docs.docker.com/engine/network/drivers/bridge/)、[端口发布](https://docs.docker.com/engine/network/port-publishing/)、[Docker Desktop 网络限制](https://docs.docker.com/desktop/features/networking/networking-how-tos/)。

`s1_isolation.py` 在访问前验证清单路径、UUID、实际容器/网络 ID、镜像、精确标签、端口、挂载、网络成员、健康状态、数据库/Redis URL 和关闭策略。清单/环境变量只定位，不是授权。主环境和旧测试端口明确拒绝。

测试生命周期持资源租约；只读快照不授予写权限。Docker mutation 必须在匹配的进程内操作范围、OS 锁和精确 argv 白名单下执行并预写审计。不确定创建结果保留 RECOVERY_REQUIRED，不按名称兜底删除。测试最终只清理本轮可证明归属的资源。

## 剩余边界

本机制保护合作式项目入口，不抵御同 Windows 用户主动修改代码/审计或直接调用系统终止权限。没有安装系统服务、修改系统 ACL 或扩大全局权限。普通服务退出不会触发无 Key 自动重建。

测试监督器的匿名 KILL_ON_JOB_CLOSE Job 仅涵盖其自身及子孙，进程归属由同句柄 IsProcessInJob 和内核身份核对；不依赖已退出父进程的 PID。此机制用于测试失败清理，不部署到当前主服务。跨 Windows 账户实际登录测试未执行；已验证当前登录身份、DACL及负向身份分支，不能宣称跨账户部署通过。

Runner 跨实例标签和清理归属尚未升级；S1 不部署该修改，不停止主 Runner，不运行要求 Runner 共存的真实沙箱回归。P3/P4、模型 Permit、预算及出口策略保持独立有效。

官方参考：[GetTokenInformation](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-gettokeninformation)、[Token 信息类别](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ne-winnt-token_information_class)、[Named Pipe 安全](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights)、[CancelIoEx](https://learn.microsoft.com/en-us/windows/win32/api/ioapiset/nf-ioapiset-cancelioex)。
