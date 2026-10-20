# Sandbox 历史记录只读对账（S3-B1）

S3-B3实现提示（2026-10-18，主库未写入）：history.py以持久化launch/UNKNOWN/ownership事实派生QUARANTINED_NO_REPLAY，不改原状态、不释放预留；Worker发布/认领/恢复/执行/迟到finish与Runner/批准/归属边界共用规则。新增无CID启动意图的thaw拒绝，保留原14＋1。合成15条在真实专属PG/Redis重复消息和恢复中原元数据/事件/预留一致；正常新请求仍能原子提交归属与launch。真实历史缺证据仍待人工逐条核对，没有解除入口；主二进制未加载新逻辑。详见[P5_LIVE_MAINT_S3B3_REPORT](P5_LIVE_MAINT_S3B3_REPORT.md)，下面B1/B2清单原文保留。

S3-B2复核（2026-10-18 14:45 +08）：334条执行元数据与B1最终快照逐条相同，14条needs_reconciliation＋1条缺CID启动意图保留；246个历史完整CID在当前同一daemon均明确不存在，没有其他inspect错误。主库仍0008，未回填新版归属、改结果、删审计或自动重发。当前thaw查询会被14条needs_reconciliation阻止；无CID failed/not_created项仍需人工审阅，不能以容器缺席推定create未发生。后续只读证据在work/maint-s3b2/20261018/history-observation.json，处置和授权条件见[S3B2_MAINTENANCE_RUNBOOK](S3B2_MAINTENANCE_RUNBOOK.md)。下面原15条详细记录完整保留。

日期：2026-10-18，Asia/Shanghai。**HISTORY_UNRESOLVED / DEPLOYMENT_BLOCKED**。本轮无数据库写入、历史状态转换、授权回填、重派发或资源清理。

## 核验来源与范围

主库固定容器身份核验后，在READ ONLY / REPEATABLE READ事务中读取334条执行的白名单元数据，查询超时8秒并ROLLBACK；采样UTC时间为2026-10-18T05:59:24.777173+00:00。实际迁移版本为0008_execution_permits。原始元数据证据保存在被Git排除的work/maint-s3b1/20261018/history-observation.json和history-control-events.json，不含代码/输出正文、Key、Issuer或请求头。

全部334条task_event_seq与事件计数相等，历史CID共246个、互不重复且格式正确，精确inspect在当前daemon全部明确返回不存在，0个无法分类错误。此核验不是外部签名审计或完整防篡改证明。旧行没有版本化Ownership记录；P3 policy_version不能充当ownership_protocol_version。

| 数据库存储状态 | 条数 |
| --- | --- |
| cancelled | 133 |
| failed | 23 |
| needs_reconciliation | 14 |
| output_limit | 12 |
| rejected | 20 |
| succeeded | 118 |
| timed_out | 14 |

当前daemon ID：a2353ec2-7b5f-4343-a16b-8a04bc95ec51。旧策略标签发现候选0。当前缺席只说明当前daemon无该精确CID；不能证明过去没有运行、过去daemon相同、代码是否注入或历史结果已结算。原cleanup_status=removed是已有存储字段，本轮没有据此把UNKNOWN改为成功/失败/已清理。

## 15条重点记录

以下“最后控制事件”指来源已核实的项目数据库中最后一条P3服务端控制记录，并非经过独立签名认证的历史Runner实机证明。runner_owner仅是旧字符串，不能当作新版注册/代次/进程/daemon身份证明。

### 1. 8270a5b0-37d0-4410-b412-50507495c660

- execution_id：8270a5b0-37d0-4410-b412-50507495c660；task_id：d96b6a7f-ba75-423c-9204-cee26b70eae9。
- 原存储状态：failed；cleanup_status：not_created；failure_reason：DOCKER_UNAVAILABLE；退出码：UNKNOWN。
- 历史container_id：缺失；P3策略：p3-python-v1；ownership_protocol_version：LEGACY_UNREGISTERED（无新版归属账本）。
- Runner身份：runner_owner=runner-7ec9d9729e434a379d449d2de0d042ff；实例注册/generation/proof/历史daemon及实际进程关联均UNVERIFIED。
- 最后控制事件：seq=8，sandbox_completed，2026-10-14T15:50:34.046014+00:00（UTC）；最后任务事件：seq=9，status，2026-10-14T15:50:35.117873+00:00。
- 可观察事件：启动意图1条，sandbox_started记录0条；事件未持久化不等于外部动作未发生。
- 当前Docker结果：没有不可变CID；当前旧标签候选为0，不能据此确认历史没有create。
- 预留：reserved_cpu_seconds=0.0（只读）；不改变用量、审计或原审批。
- 尚缺证据：缺CID、CREATE_COMMITTED边界和故障发生阶段；DOCKER_UNAVAILABLE/not_created及completed事件不足以排除create响应丢失。
- 建议处置：保持原failed/not_created数据库字段，审查分类仍UNKNOWN；人工查历史daemon及create/response日志，仅允许受限元数据核对。不得改标已清理、按名称删容器或发起补偿执行。

### 2. 8caf3d05-38ac-484b-8878-f718e45050ca

- execution_id：8caf3d05-38ac-484b-8878-f718e45050ca；task_id：ded78860-86ae-4f78-8f9a-ee02f881b5c9。
- 原存储状态：needs_reconciliation；cleanup_status：removed；failure_reason：RUNNER_RESTART_AFTER_LAUNCH_INTENT；退出码：UNKNOWN。
- 历史container_id：b36f97dc83830ac9c93c8db0c20aae3e12ba8961ee2122ac17ff4debce52fc65；P3策略：p3-python-v1；ownership_protocol_version：LEGACY_UNREGISTERED（无新版归属账本）。
- Runner身份：runner_owner=runner-3405508e570c48f5a571614a3240c4e5；实例注册/generation/proof/历史daemon及实际进程关联均UNVERIFIED。
- 最后控制事件：seq=10，sandbox_reconciliation_required，2026-10-14T15:53:06.642727+00:00（UTC）；最后任务事件：seq=10，sandbox_reconciliation_required，2026-10-14T15:53:06.642727+00:00。
- 可观察事件：启动意图1条，sandbox_started记录0条；事件未持久化不等于外部动作未发生。
- 当前Docker结果：精确CID明确不存在，仅针对当前daemon。
- 预留：reserved_cpu_seconds=0.0（只读）；不改变用量、审计或原审批。
- 尚缺证据：缺历史daemon关联、旧Runner创建身份/租约与Worker fence时序、代码注入和外部退出/移除的可信证据。
- 建议处置：维持needs_reconciliation/UNKNOWN；人工核验对应旧Runner、Docker历史事件和受限控制日志后，另行申请有审计的保留/隔离处置；不补新归属、不直接重跑。

### 3. 7c5ca293-b89a-4597-92bb-60c3d640594b

- execution_id：7c5ca293-b89a-4597-92bb-60c3d640594b；task_id：ffa45a81-4a91-434a-b664-65f19899a4ad。
- 原存储状态：needs_reconciliation；cleanup_status：removed；failure_reason：RUNNER_RESTART_AFTER_LAUNCH_INTENT；退出码：UNKNOWN。
- 历史container_id：2f289ca71feca281fb680ea4005060afc0da20d42c08619a3ed98510fe8c006c；P3策略：p3-python-v2；ownership_protocol_version：LEGACY_UNREGISTERED（无新版归属账本）。
- Runner身份：runner_owner=runner-2acf80ac802f435bb92172f6c91f10de；实例注册/generation/proof/历史daemon及实际进程关联均UNVERIFIED。
- 最后控制事件：seq=46，sandbox_reconciliation_required，2026-10-14T16:17:31.514572+00:00（UTC）；最后任务事件：seq=47，status，2026-10-14T16:17:33.232616+00:00。
- 可观察事件：启动意图1条，sandbox_started记录1条；事件未持久化不等于外部动作未发生。
- 当前Docker结果：精确CID明确不存在，仅针对当前daemon。
- 预留：reserved_cpu_seconds=0.0（只读）；不改变用量、审计或原审批。
- 尚缺证据：缺历史daemon关联、旧Runner创建身份/租约与Worker fence时序、代码注入和外部退出/移除的可信证据。
- 建议处置：维持needs_reconciliation/UNKNOWN；人工核验对应旧Runner、Docker历史事件和受限控制日志后，另行申请有审计的保留/隔离处置；不补新归属、不直接重跑。

### 4. 8286cdfa-77d7-4520-97f3-5afe732ceefd

- execution_id：8286cdfa-77d7-4520-97f3-5afe732ceefd；task_id：a03041a9-467f-488c-9ce0-25453a3eedf2。
- 原存储状态：needs_reconciliation；cleanup_status：removed；failure_reason：RUNNER_LEASE_LOST；退出码：137。
- 历史container_id：02f050771057e04dbe16b6b959c743538a898ba5368908c2696aee2faaf1f26e；P3策略：p3-python-v2；ownership_protocol_version：LEGACY_UNREGISTERED（无新版归属账本）。
- Runner身份：runner_owner=runner-d15bd7edfe554d06b40de55c7212953b；实例注册/generation/proof/历史daemon及实际进程关联均UNVERIFIED。
- 最后控制事件：seq=9，sandbox_completed，2026-10-14T16:27:09.990363+00:00（UTC）；最后任务事件：seq=10，status，2026-10-14T16:27:10.129697+00:00。
- 可观察事件：启动意图1条，sandbox_started记录1条；事件未持久化不等于外部动作未发生。
- 当前Docker结果：精确CID明确不存在，仅针对当前daemon。
- 预留：reserved_cpu_seconds=0.0（只读）；不改变用量、审计或原审批。
- 尚缺证据：缺历史daemon关联、旧Runner创建身份/租约与Worker fence时序、代码注入和外部退出/移除的可信证据。
- 建议处置：维持needs_reconciliation/UNKNOWN；人工核验对应旧Runner、Docker历史事件和受限控制日志后，另行申请有审计的保留/隔离处置；不补新归属、不直接重跑。

### 5. f460db95-3b53-4376-906a-e99b27c20ffc

- execution_id：f460db95-3b53-4376-906a-e99b27c20ffc；task_id：a9b718f9-a752-464a-8312-b82f12aab954。
- 原存储状态：needs_reconciliation；cleanup_status：removed；failure_reason：RUNNER_LEASE_LOST；退出码：137。
- 历史container_id：c0e7a7e3ba616e85b4bae162cecd724b0067ec90fb8c55c0d6bf3e91f1621f2a；P3策略：p3-python-v2；ownership_protocol_version：LEGACY_UNREGISTERED（无新版归属账本）。
- Runner身份：runner_owner=runner-d15bd7edfe554d06b40de55c7212953b；实例注册/generation/proof/历史daemon及实际进程关联均UNVERIFIED。
- 最后控制事件：seq=9，sandbox_completed，2026-10-14T16:31:28.799445+00:00（UTC）；最后任务事件：seq=10，status，2026-10-14T16:31:28.997453+00:00。
- 可观察事件：启动意图1条，sandbox_started记录1条；事件未持久化不等于外部动作未发生。
- 当前Docker结果：精确CID明确不存在，仅针对当前daemon。
- 预留：reserved_cpu_seconds=0.0（只读）；不改变用量、审计或原审批。
- 尚缺证据：缺历史daemon关联、旧Runner创建身份/租约与Worker fence时序、代码注入和外部退出/移除的可信证据。
- 建议处置：维持needs_reconciliation/UNKNOWN；人工核验对应旧Runner、Docker历史事件和受限控制日志后，另行申请有审计的保留/隔离处置；不补新归属、不直接重跑。

### 6. be7c46f3-03ee-45eb-a7d3-bd00226b1b0a

- execution_id：be7c46f3-03ee-45eb-a7d3-bd00226b1b0a；task_id：ae8d7876-2242-445a-ad4f-0c983afb49bd。
- 原存储状态：needs_reconciliation；cleanup_status：removed；failure_reason：RUNNER_LEASE_LOST；退出码：137。
- 历史container_id：acb50cc116c517b3e2721b63b6cbb02f487a77871294319f51dab27f9b5ede0b；P3策略：p3-python-v2；ownership_protocol_version：LEGACY_UNREGISTERED（无新版归属账本）。
- Runner身份：runner_owner=runner-4ee9a03d3ad549568ac7855d8f1702fe；实例注册/generation/proof/历史daemon及实际进程关联均UNVERIFIED。
- 最后控制事件：seq=9，sandbox_completed，2026-10-14T16:37:16.590457+00:00（UTC）；最后任务事件：seq=10，status，2026-10-14T16:37:16.708472+00:00。
- 可观察事件：启动意图1条，sandbox_started记录1条；事件未持久化不等于外部动作未发生。
- 当前Docker结果：精确CID明确不存在，仅针对当前daemon。
- 预留：reserved_cpu_seconds=0.0（只读）；不改变用量、审计或原审批。
- 尚缺证据：缺历史daemon关联、旧Runner创建身份/租约与Worker fence时序、代码注入和外部退出/移除的可信证据。
- 建议处置：维持needs_reconciliation/UNKNOWN；人工核验对应旧Runner、Docker历史事件和受限控制日志后，另行申请有审计的保留/隔离处置；不补新归属、不直接重跑。

### 7. d4f0ef95-ec1a-4463-b954-690e0f735591

- execution_id：d4f0ef95-ec1a-4463-b954-690e0f735591；task_id：c0ee16b3-2ab2-4ebd-ba79-bfa30ee336d8。
- 原存储状态：needs_reconciliation；cleanup_status：removed；failure_reason：RUNNER_LEASE_LOST；退出码：137。
- 历史container_id：71fea342ce4e0fdeeafdf72c952b2e7d2af9e69947a24ee0910868398667d1ac；P3策略：p3-python-v2；ownership_protocol_version：LEGACY_UNREGISTERED（无新版归属账本）。
- Runner身份：runner_owner=runner-1f6121ce6f1b46e89bef3a73837d9b93；实例注册/generation/proof/历史daemon及实际进程关联均UNVERIFIED。
- 最后控制事件：seq=9，sandbox_completed，2026-10-15T04:40:50.982829+00:00（UTC）；最后任务事件：seq=10，status，2026-10-15T04:40:51.139726+00:00。
- 可观察事件：启动意图1条，sandbox_started记录1条；事件未持久化不等于外部动作未发生。
- 当前Docker结果：精确CID明确不存在，仅针对当前daemon。
- 预留：reserved_cpu_seconds=0.0（只读）；不改变用量、审计或原审批。
- 尚缺证据：缺历史daemon关联、旧Runner创建身份/租约与Worker fence时序、代码注入和外部退出/移除的可信证据。
- 建议处置：维持needs_reconciliation/UNKNOWN；人工核验对应旧Runner、Docker历史事件和受限控制日志后，另行申请有审计的保留/隔离处置；不补新归属、不直接重跑。

### 8. 86b5f8ee-1dfa-4aa7-90b2-c277ffb5d6a5

- execution_id：86b5f8ee-1dfa-4aa7-90b2-c277ffb5d6a5；task_id：b3e14b9d-fd41-4765-a95e-7755b8b7b163。
- 原存储状态：needs_reconciliation；cleanup_status：removed；failure_reason：RUNNER_LEASE_LOST；退出码：137。
- 历史container_id：9258095f8470a491bb86e0503489522fd6699f74f301d44fad967e4ef33db63c；P3策略：p3-python-v2；ownership_protocol_version：LEGACY_UNREGISTERED（无新版归属账本）。
- Runner身份：runner_owner=runner-1f6121ce6f1b46e89bef3a73837d9b93；实例注册/generation/proof/历史daemon及实际进程关联均UNVERIFIED。
- 最后控制事件：seq=9，sandbox_completed，2026-10-15T04:47:21.807182+00:00（UTC）；最后任务事件：seq=10，status，2026-10-15T04:47:21.954788+00:00。
- 可观察事件：启动意图1条，sandbox_started记录1条；事件未持久化不等于外部动作未发生。
- 当前Docker结果：精确CID明确不存在，仅针对当前daemon。
- 预留：reserved_cpu_seconds=0.0（只读）；不改变用量、审计或原审批。
- 尚缺证据：缺历史daemon关联、旧Runner创建身份/租约与Worker fence时序、代码注入和外部退出/移除的可信证据。
- 建议处置：维持needs_reconciliation/UNKNOWN；人工核验对应旧Runner、Docker历史事件和受限控制日志后，另行申请有审计的保留/隔离处置；不补新归属、不直接重跑。

### 9. c4ee8b03-2831-4726-a1f0-debd94173236

- execution_id：c4ee8b03-2831-4726-a1f0-debd94173236；task_id：aeb75937-be90-4f66-94ab-cecbc7da6e62。
- 原存储状态：needs_reconciliation；cleanup_status：removed；failure_reason：RUNNER_LEASE_LOST；退出码：137。
- 历史container_id：dee92ccb1cdf22acdf9e3a1c84c279e0d781ad1983d360fea470d0ca11071824；P3策略：p3-python-v2；ownership_protocol_version：LEGACY_UNREGISTERED（无新版归属账本）。
- Runner身份：runner_owner=runner-1f6121ce6f1b46e89bef3a73837d9b93；实例注册/generation/proof/历史daemon及实际进程关联均UNVERIFIED。
- 最后控制事件：seq=9，sandbox_completed，2026-10-15T04:51:59.846728+00:00（UTC）；最后任务事件：seq=10，status，2026-10-15T04:52:00.008463+00:00。
- 可观察事件：启动意图1条，sandbox_started记录1条；事件未持久化不等于外部动作未发生。
- 当前Docker结果：精确CID明确不存在，仅针对当前daemon。
- 预留：reserved_cpu_seconds=0.0（只读）；不改变用量、审计或原审批。
- 尚缺证据：缺历史daemon关联、旧Runner创建身份/租约与Worker fence时序、代码注入和外部退出/移除的可信证据。
- 建议处置：维持needs_reconciliation/UNKNOWN；人工核验对应旧Runner、Docker历史事件和受限控制日志后，另行申请有审计的保留/隔离处置；不补新归属、不直接重跑。

### 10. 61f912b4-f95a-4bbc-aac0-b150fb37ef5b

- execution_id：61f912b4-f95a-4bbc-aac0-b150fb37ef5b；task_id：4e233075-4f72-44bf-9a1a-7b19faea13f9。
- 原存储状态：needs_reconciliation；cleanup_status：removed；failure_reason：RUNNER_LEASE_LOST；退出码：137。
- 历史container_id：c3eabf77a19f50456573a3e85d1eae63cada0b8cd69e1c658b2bf9c2e7c4c39f；P3策略：p3-python-v2；ownership_protocol_version：LEGACY_UNREGISTERED（无新版归属账本）。
- Runner身份：runner_owner=runner-f52b088d85e841d49c9f96f33e33d2d4；实例注册/generation/proof/历史daemon及实际进程关联均UNVERIFIED。
- 最后控制事件：seq=9，sandbox_completed，2026-10-15T05:19:21.366148+00:00（UTC）；最后任务事件：seq=10，status，2026-10-15T05:19:21.569608+00:00。
- 可观察事件：启动意图1条，sandbox_started记录1条；事件未持久化不等于外部动作未发生。
- 当前Docker结果：精确CID明确不存在，仅针对当前daemon。
- 预留：reserved_cpu_seconds=0.0（只读）；不改变用量、审计或原审批。
- 尚缺证据：缺历史daemon关联、旧Runner创建身份/租约与Worker fence时序、代码注入和外部退出/移除的可信证据。
- 建议处置：维持needs_reconciliation/UNKNOWN；人工核验对应旧Runner、Docker历史事件和受限控制日志后，另行申请有审计的保留/隔离处置；不补新归属、不直接重跑。

### 11. 2625b900-d98f-4e2f-abde-0cc283420935

- execution_id：2625b900-d98f-4e2f-abde-0cc283420935；task_id：cb594c26-3311-48a5-8c58-597e1933653d。
- 原存储状态：needs_reconciliation；cleanup_status：removed；failure_reason：RUNNER_LEASE_LOST；退出码：137。
- 历史container_id：8d1c034816d14b4235542d1c4c97c1c7fd076edd5200bb122042c9ba36bad376；P3策略：p3-python-v2；ownership_protocol_version：LEGACY_UNREGISTERED（无新版归属账本）。
- Runner身份：runner_owner=runner-f52b088d85e841d49c9f96f33e33d2d4；实例注册/generation/proof/历史daemon及实际进程关联均UNVERIFIED。
- 最后控制事件：seq=9，sandbox_completed，2026-10-15T05:24:37.249328+00:00（UTC）；最后任务事件：seq=10，status，2026-10-15T05:24:37.394979+00:00。
- 可观察事件：启动意图1条，sandbox_started记录1条；事件未持久化不等于外部动作未发生。
- 当前Docker结果：精确CID明确不存在，仅针对当前daemon。
- 预留：reserved_cpu_seconds=0.0（只读）；不改变用量、审计或原审批。
- 尚缺证据：缺历史daemon关联、旧Runner创建身份/租约与Worker fence时序、代码注入和外部退出/移除的可信证据。
- 建议处置：维持needs_reconciliation/UNKNOWN；人工核验对应旧Runner、Docker历史事件和受限控制日志后，另行申请有审计的保留/隔离处置；不补新归属、不直接重跑。

### 12. 09ddcf00-be26-48bf-9839-1f44d67c19aa

- execution_id：09ddcf00-be26-48bf-9839-1f44d67c19aa；task_id：78942767-19df-41d0-849e-a78d06cf0588。
- 原存储状态：needs_reconciliation；cleanup_status：removed；failure_reason：RUNNER_LEASE_LOST；退出码：137。
- 历史container_id：68f225c1a3cf91f29ff68b423108a7332741bd1e5caeb31c48d52302c005b85f；P3策略：p3-python-v2；ownership_protocol_version：LEGACY_UNREGISTERED（无新版归属账本）。
- Runner身份：runner_owner=runner-f52b088d85e841d49c9f96f33e33d2d4；实例注册/generation/proof/历史daemon及实际进程关联均UNVERIFIED。
- 最后控制事件：seq=9，sandbox_completed，2026-10-15T05:30:12.176073+00:00（UTC）；最后任务事件：seq=10，status，2026-10-15T05:30:12.369846+00:00。
- 可观察事件：启动意图1条，sandbox_started记录1条；事件未持久化不等于外部动作未发生。
- 当前Docker结果：精确CID明确不存在，仅针对当前daemon。
- 预留：reserved_cpu_seconds=0.0（只读）；不改变用量、审计或原审批。
- 尚缺证据：缺历史daemon关联、旧Runner创建身份/租约与Worker fence时序、代码注入和外部退出/移除的可信证据。
- 建议处置：维持needs_reconciliation/UNKNOWN；人工核验对应旧Runner、Docker历史事件和受限控制日志后，另行申请有审计的保留/隔离处置；不补新归属、不直接重跑。

### 13. 2dc6b18b-d3a4-4ee2-b8b2-a6d29f432152

- execution_id：2dc6b18b-d3a4-4ee2-b8b2-a6d29f432152；task_id：a7ed9cf6-95eb-46ea-83a9-d50987735da3。
- 原存储状态：needs_reconciliation；cleanup_status：removed；failure_reason：RUNNER_LEASE_LOST；退出码：137。
- 历史container_id：150ddb0e9962994fc8661e06dcd112c9d416a40fd82f8a82eceb07271b09a3ad；P3策略：p3-python-v2；ownership_protocol_version：LEGACY_UNREGISTERED（无新版归属账本）。
- Runner身份：runner_owner=runner-f52b088d85e841d49c9f96f33e33d2d4；实例注册/generation/proof/历史daemon及实际进程关联均UNVERIFIED。
- 最后控制事件：seq=9，sandbox_completed，2026-10-15T05:38:07.118412+00:00（UTC）；最后任务事件：seq=10，status，2026-10-15T05:38:07.242943+00:00。
- 可观察事件：启动意图1条，sandbox_started记录1条；事件未持久化不等于外部动作未发生。
- 当前Docker结果：精确CID明确不存在，仅针对当前daemon。
- 预留：reserved_cpu_seconds=0.0（只读）；不改变用量、审计或原审批。
- 尚缺证据：缺历史daemon关联、旧Runner创建身份/租约与Worker fence时序、代码注入和外部退出/移除的可信证据。
- 建议处置：维持needs_reconciliation/UNKNOWN；人工核验对应旧Runner、Docker历史事件和受限控制日志后，另行申请有审计的保留/隔离处置；不补新归属、不直接重跑。

### 14. 197a3f0b-e6ce-46c2-951d-6d6d5ead335c

- execution_id：197a3f0b-e6ce-46c2-951d-6d6d5ead335c；task_id：88676d1a-9dd3-43df-8184-5fafecf21fc8。
- 原存储状态：needs_reconciliation；cleanup_status：removed；failure_reason：RUNNER_LEASE_LOST；退出码：137。
- 历史container_id：fb179fd6fe1b97eb5a36f094d6e62c0ada2db97ce6dd29471f9a36fad49fa3ee；P3策略：p3-python-v2；ownership_protocol_version：LEGACY_UNREGISTERED（无新版归属账本）。
- Runner身份：runner_owner=runner-17bea97683864b53a6ea25b2b01da6a8；实例注册/generation/proof/历史daemon及实际进程关联均UNVERIFIED。
- 最后控制事件：seq=9，sandbox_completed，2026-10-15T11:19:39.753728+00:00（UTC）；最后任务事件：seq=10，status，2026-10-15T11:19:39.930788+00:00。
- 可观察事件：启动意图1条，sandbox_started记录1条；事件未持久化不等于外部动作未发生。
- 当前Docker结果：精确CID明确不存在，仅针对当前daemon。
- 预留：reserved_cpu_seconds=0.0（只读）；不改变用量、审计或原审批。
- 尚缺证据：缺历史daemon关联、旧Runner创建身份/租约与Worker fence时序、代码注入和外部退出/移除的可信证据。
- 建议处置：维持needs_reconciliation/UNKNOWN；人工核验对应旧Runner、Docker历史事件和受限控制日志后，另行申请有审计的保留/隔离处置；不补新归属、不直接重跑。

### 15. 558f3b44-733c-4938-9014-c9b226fa0e03

- execution_id：558f3b44-733c-4938-9014-c9b226fa0e03；task_id：e7ff49ef-12b1-4286-af4b-e102d8caf796。
- 原存储状态：needs_reconciliation；cleanup_status：removed；failure_reason：RUNNER_LEASE_LOST；退出码：137。
- 历史container_id：34fc4023b30f9de4532c8657788b2d195bd52148143704dd1bef0f52c9fbeaa5；P3策略：p3-python-v2；ownership_protocol_version：LEGACY_UNREGISTERED（无新版归属账本）。
- Runner身份：runner_owner=runner-749e1a54460949d3b50f32b30b2866c7；实例注册/generation/proof/历史daemon及实际进程关联均UNVERIFIED。
- 最后控制事件：seq=9，sandbox_completed，2026-10-16T02:49:05.000762+00:00（UTC）；最后任务事件：seq=10，status，2026-10-16T02:49:05.138127+00:00。
- 可观察事件：启动意图1条，sandbox_started记录1条；事件未持久化不等于外部动作未发生。
- 当前Docker结果：精确CID明确不存在，仅针对当前daemon。
- 预留：reserved_cpu_seconds=0.0（只读）；不改变用量、审计或原审批。
- 尚缺证据：缺历史daemon关联、旧Runner创建身份/租约与Worker fence时序、代码注入和外部退出/移除的可信证据。
- 建议处置：维持needs_reconciliation/UNKNOWN；人工核验对应旧Runner、Docker历史事件和受限控制日志后，另行申请有审计的保留/隔离处置；不补新归属、不直接重跑。

## 人工核对条件与后续阻塞

1. 只用完整CID、旧Runner镜像/创建时间、daemon身份和任务事件关联；不读取Key/Issuer或代码/输出正文。控制日志若无法安全脱敏，只记录无法核验，不将完整日志拷入仓库或聊天。
2. sandbox_started事件只是持久化控制证据；缺失或存在都不能单独证明业务结果。已有审批不允许迁移成新实例授权。
3. 14条结果未知以及无CID意图仍未解决。当前无安全、自动的历史认领/状态重置机制；本轮不制造此机制。
4. 新冻结门禁在解除时拒绝needs_reconciliation/unconfirmed及新版UNKNOWN/CREATE_COMMITTED/CLEANUP_INTENT。当前主库历史会继续阻止解除；后续必须独立设计并批准保留UNKNOWN的隔离处置，不能删除行或加通用忽略参数。
5. 本轮没有发现当前可见的P3容器，但不能据当前扫描对无CID历史作出绝对清零证明。因此主Runner维护升级和17+2真实Sandbox仍BLOCKED。

主Runner仍运行旧镜像；新冻结源码尚未部署，不能把离线门禁实现当作旧Runner已停止清理。详见[SANDBOX_MAINTENANCE_FREEZE](SANDBOX_MAINTENANCE_FREEZE.md)和[P5_LIVE_MAINT_S3B1_REPORT](P5_LIVE_MAINT_S3B1_REPORT.md)。
