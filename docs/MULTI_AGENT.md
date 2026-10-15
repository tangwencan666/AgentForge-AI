# P5 有界 Multi-Agent 协作

2026-10-15，Asia/Shanghai。真实模型传输已实现；本机缺少真实模型凭据/收费测试额度，供应商验收 BLOCKED。以下本地集成证据的模型明确使用 Provider Stub，PostgreSQL/Redis/LangGraph/MCP/Docker 是真实组件。

## 固定图与可信状态

用户任务 → Planner → 结构化 DAG 验证 → 可选计划人工确认 → Coder / Researcher → 工具审批/结果 → Reviewer → 成功或有界修订。

Planner 只输出 coder/researcher 两个固定工作角色的 instruction 和依赖。AgentPlan/Pydantic 禁止额外字段、自环、循环、替换角色或自授工具权限；不能把模型 JSON 直接转换成任意代码图。无依赖并行，有依赖串行；priority 仅影响同批就绪节点顺序。Reviewer 的 needs_revision 或非空 conflicts 均触发修订，业务迭代≤8、模型尝试≤32，另有 LangGraph recursion_limit=100，不能依赖无限递归。

AgentAnswer 中的 tools 只能是 notes.read、notes.write、sandbox.execute，每个角色每轮最多3项。Reviewer 只能输出意见、冲突和修订标记，没有执行/授权能力。Researcher 只使用已提供证据或受管笔记读取，不虚构实时网页检索；未增加外网浏览或 RAG 系统。

任务、操作、事件、预算和 outbox 存 PostgreSQL；Redis Streams 负责异步唤醒。Worker 租约/fence、PostgresTaskSaver 和稳定 operation_id 保护恢复。配置与价格固定快照，节点角色固定路由，禁止输出选择新端点/凭据/模型。真实失败不切换 Mock，部分必需节点失败不宣称整体成功，已保存草稿可在调用轨迹查看。

## 工具与 P3/P4 边界

AgentToolGateway 继承 P4 Gateway 的入口，将 task_id + role + round + proposal index 转为稳定幂等键。提案、请求哈希和实际调用/执行 ID 先持久化；恢复复用同一逻辑操作。

MCP 调用仍验证精确工具/资源授权、Schema、Skill 声明交集、配额和独立高风险批准；P4 Server 在副作用事务中重复检查父任务、当前 Worker fence/租约和授权。任务取消、暂停或失效后不能用旧提案完成新写入。notes.write 无独立有效批准就不执行；需要人工审批时父任务以 waiting_tools 中断，批准后从同一记录恢复。

sandbox.execute 先要求 Gateway 的 sandbox.execute / python 显式资源许可，再验证 SandboxCreate 参数，通过 P3 建立独立执行任务及代码哈希审批。父任务无权替代 P3 审批者；child 的 deadline 不超过父任务。Runner 在派发、代码注入边界和监测中检查父任务及当前许可，继续执行固定镜像、非 root、无网络、只读根、资源/输出限额和完整容器清理。MCP/模型/Skills 不接触 Docker Socket、宿主 Shell 或任意数据库写接口。

父任务等待真实子执行完成后，实际 exit_code/stdout_summary/stderr_summary/cleanup_status 作为证据传给 Reviewer。失败、未知或拒绝不会伪装为测试通过。已发生的副作用保存回执；模型失败、重连或进程恢复均不会盲目重放工具。

## 暂停、取消与恢复

暂停为协作式：当前模型请求在自身超时内完成并保存实际结果，在下一节点边界进入 paused；暂停不延长绝对 deadline。恢复只唤醒服务端保存的图，已完成模型操作不重计费。暂停时不开放工具副作用；已在运行的子沙箱发现父任务不活跃后停止，不能把其取消当成可安全重跑。

取消持久化 cancel_requested，模型读取监测每200ms检查状态/lease/deadline并关闭流，子沙箱取消/监测负责整容器终止。外部供应商不保证取消后立即停止计费，因此未知成本保留预留。租约过期 Worker 不能提交新结果或开展副作用。

完成节点重用账本和 PostgreSQL 检查点；真实模型 reserved/pending 状态的崩溃窗口保守转 needs_reconciliation。确定的暂时错误可在额度内有限重试，但不能声称供应商请求 exactly once。OS 重启探针在 Planner 结果/人工中断已持久化时真正终止并重启专用测试 Worker，验证 Planner 只执行一次；它使用显式 Provider Stub，不是收费 API 重启测试。

## Chat、前端和主要源码

Chat 使用独立单角色图，保留相同真实/Mock、额度、Worker、SSE 与恢复边界，不开放工具。conversation_id 由服务端生成并按租户授权，最近6条已完成会话作为有界上下文；历史存项目数据库。前端凭据只存内存，刷新/退出丢弃。任务和 Chat 都显示真实模式与未知/估算成本，草稿不伪装最终结果。

源码阅读顺序：schemas/agents.py → services/tasks.py → providers/router.py → orchestration/real_runtime.py → orchestration/graph.py / chat_graph.py → services/agent_tools.py → workers/engine.py → api/v1/inference.py / tasks.py → 前端 ModelCenter.tsx / Tasks.tsx / Chat.tsx。

测试入口：test_model_adapter.py（明确 MockTransport），test_real_agents.py（实际持久化、明确 Provider Stub），test_inference_api.py，frontend/tests/models-chat.spec.ts，scripts/p5-worker-recovery-probe.py（实际 OS 进程，明确 Stub）。test-p5.ps1 合并 P3/P4 回归；独立真实 API 检查见 MODEL_INTEGRATION。完成本阶段后暂停，不进入 P6。
