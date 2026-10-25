# 托管 Mock 镜像与专用 Compose 验证

`.github/workflows/vm-mock-images.yml` 在同仓库 PR 的 GitHub-hosted Ubuntu 24.04 amd64 任务运行。它不部署到 VMware，也不连接自托管 Runner。原有 Core CI、Isolated Mock 和 Browser Mock 工作流保持独立。本工作流结论不能替代 CentOS 7 启动兼容性或真人手动验收。

## 构建与真实身份

API 和 Worker 明确复用 `Dockerfile.backend` 构建的同一个镜像，分别以 `api` / `worker` 模式启动；Frontend 使用独立多阶段镜像。后端安装已提交 `backend/requirements.lock`，前端执行 `npm ci` 和锁定项目的生产构建。准备测试使用 `deploy/vm-mock/ci-requirements.lock`，没有把测试工具加到应用运行依赖。PostgreSQL 和 Redis 仅拉取已固定 digest 的官方 amd64 镜像，不重新构建。

工作流只授予 contents:read。官方 checkout/setup-python/upload-artifact 和 Docker setup-buildx Action 固定完整提交 SHA；没有 registry 登录、生产 secrets、真实模型凭据、Permit 或 Sandbox。构建提交是实际检出的 PR HEAD，而非隐含合并提交。构建脚本在任何 Docker 命令前要求 GitHub-hosted Linux、准确的仓库与工作目录，并拒绝 VM/Windows 两个已知 Engine ID。

Buildx 同次构建导出 OCI tar 和 Docker tar。脚本读取 OCI index 的 manifest，校验 manifest/config blob 的 SHA256，再要求 Docker load 的 image ID 等于该 config digest。`images.resolved.json` 包含 logical_names、repository_tag、image_id、repo_digests、oci_manifest_digest、config_digest、architecture、os、size_bytes、base_image、build_revision 和 run_url。

没有推送 registry，`repo_digests` 可能为空；OCI manifest digest 不冒充可拉取的 RepoDigest。tag 只用于可读命名，Compose 实际使用完整 `sha256:<config>` image ID。两者是不同类型的不可变身份，不能互换。模板 `deploy/vm-mock/images.lock.json` 继续为 NOT_BUILT；真实构建记录在对应 Actions artifact 中，避免在源码中写入自引用的构建 SHA。

## 离线归档

构建后、生成任何测试凭据之前，按显式四镜像白名单执行 docker save，再 gzip。白名单为 Backend、Frontend，以及未修改内容的官方 PostgreSQL/Redis 镜像。保存后读取 Docker archive manifest 和 config，验证恰好四个预期 tag 和四个预期 config digest。不会 docker commit 运行容器，不归档卷、运行数据、环境文件或测试日志。

`vm-mock-offline-images` artifact 保留 3 天，压缩层级 0（内部已经 gzip），包含 `agentforge-vm-mock-amd64.tar.gz` 和 `SHA256SUMS`。归档 SHA256 与大小同时写入 resolved 清单。只有实际 Compose 验证成功才上传此镜像 artifact。使用前应再次验证 artifact 来源的 run、构建提交及 archive SHA256。

docker save/load 不保证保留 registry RepoDigest，因此四个服务的离线配置使用清单中的实际 image ID；官方来源 registry digest 单独保留。API/Worker 共用 Backend 身份，没有重复构建第三个应用镜像。

## 真实临时服务链

`scripts/ci_vm_compose.py` 使用专用 VM Compose 文件本身，全部服务保持只读根文件系统和原安全约束，不发布任何端口，两个网络均为 internal。仅通过本次前端容器实际私网 IP 访问 Nginx，再代理到真实 API，包含真实 SSE；没有 StubConnections 或接口伪造。

创建前要求演示前缀的容器/网络/卷均不存在。每次运行新建实例 UUID 和四个独立随机凭据，存放于 RUNNER_TEMP 私有目录内的 0600 `.inputs` 文件；Compose 显式 --env-file、禁用默认 dotenv，并清除继承应用/Compose/Docker 配置。凭据注册日志掩码，服务日志再次替换凭据后才写入可上传目录，临时文件退出删除。

数据阶段只启动新 PostgreSQL/Redis，检查 healthy、空 public 和专属数据库实例标记。迁移只调用原专用入口，保留非超级用户、身份标记、空库、同事务锁及第二次空库校验。随后以本轮构建的同一 Backend image ID 启动真实 API/Worker，以 Frontend image ID 启动真实前端；官方数据镜像也以实际 image ID 运行。

实际断言：

- Compose config；PG/Redis healthy；新库迁移达到 `0010_sandbox_maintenance`。
- Frontend 可访问、API ready、Worker available，API/Worker 配置摘要一致。
- 真实模型关闭、真实日/测试预算为零、Permit 关闭、Worker real mode=deny、无模型凭据；Mock 预算 10、token 额度 1000000。
- 创建显式 Mock 任务返回 202；Planner 完成后等待审批，连续观察 2 秒只有 Planner，真实 checkpoint 已持久化。
- 批准后四角色完成、顺序正确、任务 succeeded，真实费用为零、没有工具执行。
- SSE 在待审批时可流式读取；成功后事件有序、完成事件存在、Last-Event-ID 恢复后缀完全一致。
- 另一待审批任务取消后，持续 2 秒没有后续角色执行。
- 最终真实 PostgreSQL 中非 Mock/provider 操作、Sandbox execution、Permit 记录均为 0；真实/测试费用及预留费用合计为 0。

退出时采集经过替换的服务日志，按本次实例标签核对资源后，仅清理此托管任务新建的专用栈和数据卷。任何失败保留非零退出，上传已经产生的证据，不关闭安全校验或跳过断言。

## 产物与复现

`vm-mock-evidence` 保留 7 天，包括 `host.json`、BuildKit metadata、`images.resolved.json`、`compose-result.json`、经过替换的初始化/API/Worker/Frontend 日志。没有完整 docker inspect/env/config 转储。

向此 PR 正常推送即可在全新托管任务中复现。单独运行入口为 `python scripts/ci_vm_images.py` 和 `python scripts/ci_vm_compose.py`，它们在本机或自托管环境会先拒绝，不提供关闭边界的选项。只读 `deploy/vm-mock/inspect_target.py --images --manifest <resolved-file>` 是后续 VM 检查入口，仍拒绝错误 Engine、历史容器状态变化或同名资源。

VM 镜像导入、版本探测容器、建卷、迁移及部署均不由此 Actions 执行。CentOS 7 的内核、cgroup、overlay2、seccomp 与实际应用镜像组合仍须单独评估；托管 Ubuntu 成功不能标记其为已通过。
