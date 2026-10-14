# AgentForge AI P2 工作流契约

2026 年 10 月 14 日，用户要求继续，进入已规划的 P2。仅实现异步编排及其服务端控制基础，不实施 P3 至 P6。

## 范围和运行模式

实现真实 LangGraph 工作流、PostgreSQL 状态及检查点、Redis Streams 调度、事务 outbox、Worker 租约/fencing、幂等调用账本、上下文裁剪、人工计划审批、超时取消、Token/预算原子预留与可重连 SSE。前端提供任务创建、轨迹、审批和显式 Mock 结果。

尚未选择真实供应商和价格，P2 默认且仅开放用户明确选择的 Mock 工作流，所有任务、调用、结果及事件保留 is_mock=true。Mock 模型输出模拟但编排、数据库、Redis、审批和 SSE 真实运行；模拟费用与真实支出分开。禁止将其宣传为真实模型调用或真实费用。已有真实槽位配置不被改写；请求 real 模式明确拒绝。

不存在沙箱或 MCP 执行入口。sandbox.execute 等未实现能力安全拒绝；不生成本地执行回退。高风险工具的权限和审批公共控制规则先以契约及无外部副作用测试验证，真实工具留到 P3/P4。

## 任务契约

任务固定四角色快照（显式 Mock 模式使用独立 Mock 快照，不覆盖 Model Center 配置）。服务端生成 task_id、thread_id 和 tenant_id，用户提交任务目标、依赖策略、是否需要计划审批及收紧后的限额。服务端预算和权限上限不能由模型修改。

创建接口采用租户范围 Idempotency-Key，相同载荷返回同任务，不同载荷返回 409。状态为 queued/running/waiting_approval/retry_wait/cancel_requested/succeeded/failed/cancelled/timed_out/limit_exceeded/needs_reconciliation。PostgreSQL 是真相源，Redis 只通知与投递。

工作流为 Planner → 计划校验 → 可选持久化审批 → 无依赖 Coder/Researcher 并发或依赖串行 → Reviewer → 有额度时反馈修订。节点和调用使用稳定业务操作 ID，恢复不重复计量已完成调用。任务总 deadline 包含排队和审批。

## 事务和恢复

任务创建、审批恢复和 outbox 在同一事务提交。Redis 发布允许重复，Worker 使用数据库租约、递增 fencing token 和过期恢复控制运行；重复消息不重复执行已完成任务。检查点写入检查租约所有权，并保存可恢复图状态和 pending writes。业务结果与检查点的跨事务边界依靠稳定操作账本和对账处理，不声称外部 exactly once。

Worker 独立进程负责 outbox 发布、消费、租约续期和过期扫描，API 不以 BackgroundTasks 模拟持久化调度。Redis 或数据库不可用时不开展新的调用；已运行任务等待恢复或按 deadline 结束。Worker 取消、失联与重启有自动化测试。

## 审批权限

计划审批绑定租户、任务、plan_hash、policy_version、期限和决定。恢复不接受客户端任意图状态/跳转；从服务端记录读取决定，执行前重新鉴权并核对哈希。默认本地开发仍为 P1 的单管理员，计划确认可由发起者完成；高风险工具仍要求独立审批人及权限交集，本轮无真实高风险工具。不得用计划批准代替工具授权。

## 预算与上下文

调用前持有数据库任务行锁，校验迭代、调用、Token 与 Decimal 预算并预留。模拟价格明确使用 mock-usd-v1，真实费用保持零且不能伪装为已结算供应商账单。未知真实供应商费用不可当成零价接通。取消后不发起新调用。

租户每日额度以 UTC 日窗口计算，默认 1000000 个模拟 Token 单位与 10 个模拟 USD。共享 PostgreSQL 行锁控制跨任务预留，reservation_day 保证跨午夜结算回到原窗口。模拟 Token 定义为 UTF-8 JSON 字节数，不代表供应商的真实 tokenizer。

上下文默认只传任务目标的脱敏裁剪版本、角色规则和稳定证据引用；图检查点不持有 Key、完整用户文件或秘密值。用户目标持久化前脱敏，检查常见 Key/Authorization/已知本地秘密；遥测不保存原文。裁剪显式标记丢弃内容，保留来源。P2 不实施向量数据库或真实 RAG 检索。

## 接口和前端

新增鉴权任务创建/列表/详情/取消、审批查询/决定及任务事件 SSE。SSE 使用授权 fetch，Token 不进 URL，Last-Event-ID 回放 PostgreSQL 事件；断线不取消任务，重连不重新执行。前端管理 Token 仅保存在内存，不写 localStorage。任务和审批页明确提示本地开发授权及 Mock 状态。

## 验收和阶段结束

验证四角色路由、并发与依赖、审批恢复、重启检查点、重复投递、fencing、超时取消、预算竞争、Token 统计、Secret 不回显、SSE 回放和浏览器任务流程。所有数据库/Redis集成必须为本项目真实服务。P2 完成报告、Git diff/秘密检查和提交后暂停，P3 另行确认。

LangGraph 持久化与中断行为参考 [persistence](https://docs.langchain.com/oss/python/langgraph/persistence) 和 [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)。恢复中断会重跑节点，因此审批前不执行副作用。
