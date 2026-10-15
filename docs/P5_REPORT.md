# P5 开发与验收报告

2026-10-15，Asia/Shanghai。根目录 `D:\AIProjects\AgentForge-AI`。P4 基线 `3c3963931eae43fce8f4201fdcac946681a95623`，开始时 HEAD 匹配、工作区干净、Git 相关异常环境变量为空。未发现需暂停的基线冲突。

P5 实现和本地验证已完成，当前暂停；真实外部 API 验收 **BLOCKED**，未配置真实模型凭据和获准测试额度，实际外部请求 **0**。没有把 Provider Stub、MockTransport 或 Mock 回答当作真实供应商验收，不能声称 P5 全部验收通过。不进入 P6。

## 变更

| 范围 | 核心源码与实际行为 |
| --- | --- |
| 四槽位 | schemas/models.py、services/models.py、domain/entities.py；priority、版本快照、配置安全、当前版本测试状态；同供应商可绑定多模型 |
| 适配层 | providers/base.py、router.py、openai_compatible.py；OpenAI 兼容流式协议、受众/端点绑定、DNS/IP固定、TLS SNI、错误分类、用量与TTFT；其余协议保留静态接口 |
| 真调用账本 | domain/real.py、ModelOperation 新字段、real_runtime.py；任务/租户/单独测试额度原子预留，真实用量/Decimal费用估算、未知保留、有限重试、完整流/结构化结果校验 |
| 协作 | graph.py、chat_graph.py、schemas/agents.py；严格两角色DAG、并行/串行、有限Reviewer反馈和冲突处理；无动态递归/角色提权 |
| 工具 | agent_tools.py、P4 tool_gateway/capabilities、P3 sandbox service/Runner；稳定提案/任务绑定，当前fence/租约、P4审批、P3代码批准及真实结果回传 |
| 任务/API | tasks.py、workers/engine.py、api/v1/inference.py；Real/Mock接纳、Chat历史/SSE、暂停恢复、取消、指标、单独真实连接测试 |
| 数据库 | 0006_real_models；2张新表、模型priority/用量/TTFT/错误及父任务关联字段，保留既有数据 |
| 前端 | ModelCenter、AI Chat、Task Center升级；受保护配置、测试、Token/费用、实际计划、进度、工具和人工审批链接、结果与真实模式 |
| 运维/测试 | test-p5.ps1、test-real-models.py、p5-worker-recovery-probe.py、明确 Stub 专用 Worker；.env.example 和 Compose 标准角色安全注入 |
| 文档 | MODEL_INTEGRATION、MULTI_AGENT、本报告、PROJECT_STATUS、LEARNING_PATH 和启动入口 |

Python 3.13.5、FastAPI 0.143.0、LangGraph 1.2.15、LangChain 1.4.5、Pydantic 2.14.1、SQLAlchemy 2.0.54、httpx 0.28.1。复用锁定环境，仅将已存在 httpx 显式列为运行依赖；无系统组件安装或 Docker Desktop 全局配置变更。

## 测试证据

| 项目 | 实际结果 |
| --- | --- |
| Python 全量/P3/P4 | 最终281/281通过，0失败/0跳过，173.65秒；work/p5-all.xml；P4基线221项，新增60项 |
| Provider/持久化专项 | 明确 Stub/MockTransport；包含适配层27项、受保护HTTP4项、真实路径持久化协作29项，均计入上述281项 |
| 真实 Agent→Sandbox | 已在全量测试通过真实P3批准、Docker执行、清理和Reviewer证据链；模型仍是明确Stub |
| 实际 OS Worker 重启 | work/p5-worker-restart.json PASSED；PID变化，Planner1次，总Stub4次，外部API0次 |
| 浏览器 | 14/14通过，涵盖原11项和P5新增3项；最终统计表改进后再顺序复测，work/p5-e2e.json；截图work/p5-models.png、p5-chat.png已检查 |
| 真实供应商 API | work/p5-real-api.json BLOCKED，actual_calls=0，原因 SERVER_REAL_CALLS_AND_APPROVED_TEST_QUOTA_REQUIRED |
| 迁移/依赖/前端 | 0006 upgrade/check通过；pip check和Compose配置检查通过；TypeScript/Vite构建通过，60 modules |
| 秘密/Git | 工作区、暂存区、构建产物、日志和测试记录中的本地已知秘密及常见编码扫描通过；git diff --check通过；已跟踪diff与25个新增文件分别复核，不暂存、不提交 |
| 最终环境 | work/p5-environment.json：PG/Redis ready，P5 API与前端可用，MCP configured，Runner可用，活动执行/遗留执行容器0，故障Runner已移除；真实调用关闭、4槽位均无真实凭据 |

尚无实际供应商 Token/费用数据。测试中的 Token/费用为 Stub 所报数字与明确测试价目，用于核对事务/聚合；不得作为真实账单、模型质量或性能。真实输入/输出用量缺失时保存unknown/pending；费用为人工登记价格的估算，未决派发保留上界。

## 已验证、限制与风险

已验证：四槽位固定路由、同供应商多模型、结构化规划和依赖、并发分支预算、有限修订、部分模型失败不冒充成功、401/429/5xx/超时处理、格式拒绝、缺用量保留、Chat SSE/租户历史、取消/deadline/暂停、完成节点恢复与未知派发不重放、Key不进入结果/SSE、MCP/沙箱授权和审批。

最终复核修复了策略变量与凭据识别混淆：MODEL_PRICES / MODEL_CREDENTIAL_HOSTS 的 `{}` 默认值不会被脱敏器当作密钥替换，也不能被引用为模型凭据。新增3项回归验证环境变量、本地dotenv、实际凭据脱敏及策略引用拒绝。

模型 Key、真实测试额度均未配置；实际 DNS/TLS/供应商认证、具体模型参数、真实流式 usage 和费用/账单偏差未验收。OpenAI兼容接口实现不代表所有供应商兼容。Researcher只使用提供证据和受管笔记，不伪装联网检索。未新增真实 RAG、原生web工具、其他协议适配器或生产IAM。

本地身份仍为单管理员与独立角色 Token；业务清单、目标、模型结果和回执在数据库明文业务字段存储，生产加密/保留治理未发布。供应商计费上界依赖登记的能力/价格/Token约定，不能保证任意兼容服务的最终账单。暂停为当前模型完成后生效；部分行缓冲的SSE可能延迟。未知模型账单需外部核对，保留预算不自动释放。P3共享内核、Runner daemon权限和强杀Runner未覆盖的原有风险保持。

没有解除 P3/P4 限制；Agent不获得宿主Shell、Docker Socket或任意数据库写权限。Reviewer通过意见不能授权工具；存在conflicts会强制有限修订。测试只操作本项目服务/临时租户/精确受控子进程，不修改其他项目、不执行全局清理。

## P6 准备条件与交付

先由用户在本机配置真实凭据，批准具体供应商/模型、端点、价格及有限测试额度；单独完成四角色真实供应商验收与成本核对。补充生产身份、数据加密/保留、供应商计量约定/出口治理及P3控制面风险评审。P6需新的明确授权，当前不得自动进入。

Git HEAD保持P4基线，修改留工作区，.git保护不被更改。只读复核产物为work/p5-tracked.diff、p5-untracked.diff、p5-untracked-review.json；新增文件单独检查路径、UTF-8、Python语法、空白和差异。可由用户在Windows CMD手动执行：

```cmd
cd /d D:\AIProjects\AgentForge-AI
git status --short
git diff --check
git diff
git ls-files --others --exclude-standard
git add -- .env.example README.md compose.yaml backend frontend docs scripts tests
git commit -m "feat: integrate bounded P5 model workflows and chat"
```

本轮未执行 add/commit；不加入.env、work、依赖、日志或测试生成目录。实现与本地验证完成后已暂停，真实API验收仍保持BLOCKED，不进入P6。
