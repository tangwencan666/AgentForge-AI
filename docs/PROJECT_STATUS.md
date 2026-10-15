# AgentForge AI 项目状态

2026-10-15，Asia/Shanghai。路径 `D:\AIProjects\AgentForge-AI`。P4 基线 `3c3963931eae43fce8f4201fdcac946681a95623`，初始工作区干净。

P5 实现与本地验证已完成，现暂停。**真实外部 API 验收 BLOCKED：缺少真实模型凭据与获准收费测试额度，外部调用0次，P5尚未全部验收通过。** 不将 Stub/MockTransport 当真实供应商验收，不进入 P6。

| 领域 | 实际状态 |
| --- | --- |
| 四模型 | 固定角色独立配置/版本/priority；可同供应商多模型；已实现 OpenAI 兼容适配，其余协议明确未开放 |
| 安全 | 环境/凭据引用、端点/受众双白名单、DNS/IP固定/TLS、无重定向代理、输出/日志/SSE脱敏；Key不入数据库或前端 |
| 协作 | 持久化LangGraph、真实/明确Mock、有界结构化DAG、并行/依赖、Reviewer反馈与冲突、取消/暂停/deadline、租约恢复 |
| 预算 | 任务与UTC日Token/调用/Decimal费用上界，独立测试额度；用量缺失/未知结果保留预留，估算不作账单 |
| MCP/Sandbox | Agent稳定提案经P4 Gateway；独立高风险批准；P3独立代码复核和固定受限Docker；父任务/fence/许可再次验证 |
| 数据库 | 0006_real_models已应用，2新表与用量/父任务关联字段；ORM检查通过，P1–P4数据保留 |
| 前端 | Model Center、Tasks与AI Chat连接真实API；Mock/Real明确，历史/安全状态/SSE/计划/预算/审批可查看 |
| 验证 | Python281/281（0跳过），浏览器14/14，实际OS Worker更换PID且Planner不重放（明确Provider Stub）；迁移/依赖/构建/秘密扫描/已跟踪与25个新增文件差异检查通过 |
| 未验收 | 真实供应商认证/模型参数/DNS-TLS/usage/费用；生产IAM、加密保留、额外协议/RAG/外网检索及P6 |

服务默认前端 `http://127.0.0.1:15173`，后端 `http://127.0.0.1:18100/docs`，Runner `127.0.0.1:18120`只供可信控制面。重启方法见GETTING_STARTED第12节；地址不保证主机重启后自动可用。

P3/P4核心安全边界保留，预热关闭，无宿主不可信代码执行回退。单本地管理员身份、业务字段明文、Docker共享内核和可信Runner daemon权限等原有风险仍存在。本轮不安装系统组件、不修改Docker Desktop全局设置或其他项目。

Git只读操作，不改.git权限、不暂存提交；HEAD仍为P4基线。最终报告给出CMD手动提交建议。真实验收缺口关闭且获得新授权前，不进入P6。

详情：[P5_REPORT](P5_REPORT.md)、[MODEL_INTEGRATION](MODEL_INTEGRATION.md)、[MULTI_AGENT](MULTI_AGENT.md)。P0–P4报告保留历史事实。
