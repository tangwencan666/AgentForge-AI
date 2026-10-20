# Sandbox Ownership Protocol v1

S3-A项目内实现；未部署到主Runner。真实Docker执行/共存验收仍BLOCKED。

## 信任与字段

代码：`backend/app/sandbox/ownership.py`；持久化：`domain/sandbox_ownership.py`；增量迁移：`0009_sandbox_ownership`。迁移只新增三张表，不补写、认领或删除旧执行记录。

| 字段 | 来源与用途 |
| --- | --- |
| ownership_protocol_version | 服务端固定1，与P3 policy_version独立 |
| project_id | 可信部署端生成的项目UUID；不是请求租户参数 |
| runner_instance_id | 服务端注册UUID，必须附独立私有proof验证 |
| runner_generation | 注册记录正整数；进程配置固定期望值，旧代次/旧启动配置拒绝 |
| sandbox_namespace | 服务端生成UUID；用于精确发现，不单独授权 |
| task_id / execution_id | 现有P3服务端生成，持久化外键；重新核对执行与任务关联 |
| container_id | Docker返回后验证完整64位ID，再持久化；创建前为空，不伪造容器ID标签 |
| policy_version / image_id | 原P3策略和固定镜像；执行审批继续绑定它们 |
| created_at | 服务端归属意图时间；不是声称Docker实际启动时间 |
| worker_owner / worker_fence | 派发时可信任务租约快照；创建、启动与注入时重验 |

标签前缀为`ai.agentforge.sandbox.`，包含除container_id外的协议字段。原P3策略/execution标签和容器名称保留以兼容原安全检查；**这也意味着旧Runner仍能宽泛发现新容器**，不是安全共存方案。

注册表`sandbox_runner_identities`绑定项目、实例、代次、namespace、daemon ID和proof哈希。proof由可信部署原语`provision_identity()`生成，以SecretStr返回、数据库仅存哈希；没有公共API/CLI签发入口。不使用模型Key或Permit Issuer Token。普通SandboxCreate和RunnerDispatch不能提交归属字段。

新注册默认无兼容部署放行记录。必须有可信部署审查落库的`compatibility_evidence_id/compatibility_cleared_at`，并提供注册ID、期望代次及独立proof，才能认领。普通环境布尔值不能开启；这条记录本身不是Docker物理隔离证明，审查者必须先完成兼容方案。

## 状态、互斥及恢复

注册认领使用PostgreSQL行锁，校验proof、代次、退休状态及兼容放行。同注册只有一个有效process_owner；租约30秒、对账每5秒刷新。重启需原注册、同代次、proof，并等待旧租约释放/到期；旧进程在每个边界重新验证owner后被拒绝。随机process_owner、标签和ID本身不是身份凭据。

逐执行状态：`INTENT → CREATE_COMMITTED → CREATED → CLEANUP_INTENT → REMOVED`。外部结果不确定时保留`UNKNOWN`或尚未完成的已提交意图，不重置、不自动重派发。

1. 现有P3事务中提交启动意图和归属账本。执行必须在该注册及兼容放行之后创建；旧未派发记录不自动采用，需新请求/新审批。SDK create之前另一次事务原子消费INTENT并审计CREATE_COMMITTED。
2. 创建响应明确后，验证P3全部容器配置和归属标签，持久化精确container ID，然后才允许原P3启动/attestation/代码注入握手。
3. create/start/inject将实际代码哈希、限制、超时及镜像组成P3操作摘要，与服务端批准记录比对；再核对可信注册、daemon、实际ID、归属、Worker fence、任务期限/状态和资源预算。父任务原检查仍在Engine握手边界执行。
4. stop/remove/恢复只作用于持久化精确ID，并在操作前重验实际attrs及P3限制；取消/审批撤销阻止运行，但不妨碍合法当前Runner清理自己的精确资源。
5. 删除后的精确ID查询404才记录REMOVED。异常审计保留精确资源ID，不扩大扫描。create响应未知、ID未落库时，禁止按名称补偿删除；记录UNKNOWN并阻塞，等待后续受控人工对账。

事务在Docker IO之前提交，不持锁等待容器完整执行或Docker响应。`ThreadAuthority`只将SDK线程的有限动作提交回可信数据库协调器；超时/审计失败拒绝操作，不提供任意命令入口。

## 发现不是删除授权

`DockerDriver.owned()`按协议、项目、实例、代次、namespace五项标签发现；每个候选再核对数据库归属和不可变ID。其他实例/代次不在发现范围；伪造标签、缺失账本、执行关联冲突、daemon变化或实际ID不符时，不kill/remove，标记阻塞并保存有限审计。

旧记录没有归属账本，不能自动采用。新代次不能操作旧代次容器；代次轮换须后续受控流程处理旧资源、轮换私有proof并更新期望代次，不能只改整数、自动接管或回滚到全局清理。

## 边界与剩余风险

P3的无网络、非root、只读根、seccomp、cap_drop、固定镜像、资源/输出限制和独立审批保持；`policy.py`未修改。P4与模型Permit不提供额外Docker权限。

可信数据库写入方、部署端及Docker daemon管理员属于信任边界。Docker没有应用级条件删除/fencing事务：已提交授权与外部API之间仍有崩溃/暂停窗口；不可变ID保证晚到操作不会因名称/PID式复用转向新容器，但不能声称外部exactly-once或抵御恶意daemon管理员。未知结果保守保留。审计表不是对数据库管理员不可篡改的外部日志。

本轮只验证真实专属PostgreSQL事务与内存Docker API；没有证明真实Engine/Runner进程级恢复、删除行为或新旧共存。主环境保持旧版，后续步骤见[SANDBOX_RUNNER_COMPATIBILITY](SANDBOX_RUNNER_COMPATIBILITY.md)。
