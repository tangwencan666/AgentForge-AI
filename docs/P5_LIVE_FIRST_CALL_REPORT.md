# P5-LIVE 首次真实 DeepSeek 调用验收报告

2026-10-15 22:53 +08:00 后续状态：P5-LIVE-SAFETY已获单独部署授权，主库0008应用完成，原20张业务表不变；最新完整Python434、浏览器15+1通过。设计见 [P5_LIVE_PERMIT_DESIGN.md](P5_LIVE_PERMIT_DESIGN.md)，部署证据见 [P5_LIVE_SAFETY_DEPLOYMENT_REPORT.md](P5_LIVE_SAFETY_DEPLOYMENT_REPORT.md)。以下首次收费验收的历史结论仍为 **BLOCKED、实际外部请求0次**。本次修复和部署没有恢复或延续以前的一次收费授权，也没有发起真实供应商请求；未来必须重新明确授权。最新API/Worker的Coder凭据存在均False，等待用户原PowerShell安全重载；四槽、费用、签发与出口门禁均保持关闭。不能沿用下文历史True作为当前凭据证据。

**结论：BLOCKED，未发起真实模型调用，外部请求尝试数为0。** 已收到本次最多1次、US$0.005的明确授权，但现有服务端不具备授权要求的测试专用隔离。按照“全局开关可能让其他任务获得权限时停止”的条件，没有开放收费窗口或运行真实测试脚本。

检查日期：2026-10-15，Asia/Shanghai。只读证据时间：**21:23:17 +08:00 / 13:23:17 UTC**。目录 `D:\AIProjects\AgentForge-AI`，HEAD `982e83ef32b7d274e820d59ee63d6fb76bd8979e`。工作区保留此前已批准的P5-LIVE未提交变更，暂存区为空。

最终核验时间21:26:41 +08:00：上述4张审计表计数与初始快照完全一致，四槽位仍停用，非终态任务0，API/Worker一致且凭据名称均True。两种秘密扫描均通过（211个工作文件及构建/日志/记录；不读取真实模型Key作值比对），Git差异和26个未跟踪文件分别检查通过，P3/P4核心策略文件无差异。

## 本次授权与实际执行

授权仅Coder / openai_compatible / deepseek-flash / https://api.deepseek.com / thinking disabled；提示为“请只回答 connected”；最多1次外部尝试、64输出Token、8192输入预留、30秒模型超时、60秒任务期限；本次和日预算各US$0.005，重试0。

本轮只执行了源码和Git读取、本机服务GET、只读数据库事务、项目Redis状态读取、请求参数本地构造和费用重算、只读容器检查。**未调用adapter.complete、模型HTTP端点、POST测试/Chat/Agent入口或test-real-models.py。** 未创建测试任务、费用预留、模型操作或授权消耗记录；未调用MCP工具、Skills或沙箱执行。健康检查曾读取MCP工具目录和Runner状态，均不属于模型派生工具执行。

| 必需验收结果 | 本轮事实 |
| --- | --- |
| 是否实际发起供应商调用 | 否 |
| 实际外部请求尝试数 | **0**；依据本轮执行路径未派发，非将任务预留次数冒充HTTP发送次数 |
| Provider / Model | 目标openai_compatible / deepseek-flash，未进行供应商认证 |
| Coder配置版本 | 2，未变更 |
| 模型HTTP成功与状态码 | N/A，未发送；本机健康HTTP200不代表供应商HTTP成功 |
| SSE正常结束 | N/A，未建立模型流 |
| 真实模型回答 | N/A，无回答；未伪造connected结果 |
| 输入 / 输出Token | N/A，未调用；没有伪造精确用量 |
| 推理 / 缓存Token字段 | N/A，未调用 |
| 模型延迟 / TTFT | N/A，未调用 |
| 本次实际预算预留 | 未创建 |
| 本次应用侧新增费用 | 0；没有派发，不代表查询过供应商账单 |
| 未知结算 | 未发现，本租户真实费用账本没有记录；没有清零或删除任何预留 |
| 本次PostgreSQL调用审计 | 无新增ModelOperation或任务；真实ModelOperation总数仍0 |
| Worker与请求一致 | 1个有效项目Worker心跳，API/Worker配置一致；没有测试请求或在途真实任务 |

## 执行前检查结果

| 检查 | 结果 |
| --- | --- |
| Git基线、差异 | HEAD符合授权；现有P5-LIVE变更已读，diff --check通过；本轮不修改生产源码或暂存提交 |
| 数据库迁移 | 0007_deepseek；21张公开表；PG/Redis readiness为up |
| API / Worker | API live/ready与前端readiness代理正常；Worker状态新鲜、配置摘要和槽位版本一致 |
| Coder Key名称存在 | API=True，Worker=True；只看存在布尔值，未读取、打印或回传Key值，未认证 |
| Coder配置 | provider=openai_compatible，model=deepseek-flash，base_url=https://api.deepseek.com，完整env引用，thinking=disabled，max_tokens=64，timeout=30，enabled=false |
| 精确全局名单 | 仅api.deepseek.com，无通配符 |
| Coder受众 | 仅AGENTFORGE_MODEL_CODER_KEY → api.deepseek.com |
| 其余三个角色 | 全部Disabled |
| 活动或待恢复任务 | 非终态任务0，包括queued、waiting、paused和待恢复状态；未发布且关联非终态任务的outbox为0 |
| 重试 | 当前real_max_retries=0；专用model_test固定1次尝试；httpx AsyncHTTPTransport默认retries=0；无SDK封装或模型故障切换 |
| 思考关闭的请求参数 | 只作本地request_body构造：stream=true，max_tokens=64，thinking.type=disabled；不发reasoning_effort、max_completion_tokens或tools |
| 当前预算 | 日预算0、测试预算0，test_max_calls=1，日Token上限8256；本轮没有增加 |
| 专用测试任务与Worker隔离 | **不满足，执行阻塞** |

凭据加载不再是本轮阻塞原因：用户启动后的两个运行进程均已报告True。无需让Codex获取同一Key，也不能把Key复制到Codex环境。现有入口的安全隔离问题同样适用于在用户PowerShell运行旧测试脚本，不能通过改换执行终端规避。

## 当前价格规则重算

从当前服务配置和Coder行重新读取非秘密价格/参数，经PricePolicy验证：

- 登记键：`openai_compatible/deepseek-flash`；版本 `ds-20261015-peak-v1`；currency=USD。
- 输入US$0.30/百万Token、输出US$1.20/百万Token，均为已登记的保守峰时未命中估算。
- 输入预留上界8192，Coder输出64；登记输出能力上界4096没有覆盖槽位64的限制。
- Decimal向上取8位：`(8192 × 0.30 + 64 × 1.20) / 1000000 = US$0.00253440`。
- 该预留小于授权US$0.005，合计Token预留为8256。**这是本地重算通过，不是已创建预留或已获供应商扣款证明。** 当前实际零预算继续阻止派发。

## 必须停止的服务端缺口

1. **独立测试额度不是独占授权。** `RealRuntime._real_attempt`只在`task.options.model_test`为真时检查并递增test_calls。普通`/api/v1/chat`经`TaskService.create`创建的Coder真实任务不受这个测试计数限制。启用Coder、全局真实开关和费用后，普通Chat也能竞争同一个租户日额度。
2. **限制容量不能约束授权归属。** 8256日Token与原子预算预留能约束容量，但没有将唯一派发机会绑定到本次指定任务、提示、配置版本和专用Worker。即使当前队列为空，另一个普通任务仍可能在开放窗口中抢占首次派发。不能依赖前端不点按钮或“当前只观察到一个Worker”。
3. **现有Worker是通用队列消费者。** `Worker.claim`有租约、fence和并发控制，但没有本次授权task_id/worker_owner的专用消费约束。已有全局ENV开关/预算及槽位配置接口，不是限时、限路径、单次消耗的授权接口。

这些缺口直接触发用户的停止条件。没有为了完成测试而提高预算、开放全局开关、停止其他安全策略或新增绕过入口。

## 执行入口与审计的其他待修项

在修复独占授权后仍需复核，不能直接运行现有脚本：

- `scripts/test-real-models.py`及模型测试HTTP入口当前硬编码英文“Reply with the word connected.”，与本次精确授权提示不同。脚本任务期限为60秒，但HTTP测试入口沿用TaskCreate的默认期限，不能将两种入口视为同一份60秒约束。
- 当前脚本actual_calls来自任务model_attempts，代表账本尝试/预留，不是精确的HTTP发送观测；异常外层还可能写回0。需要持久化真实派发阶段，不能在未知结果时报告0或重新运行。
- DeepSeek适配器会校验缓存和reasoning计数字段，但ModelReply和ModelOperation尚未保留这些细分计数。成功HTTP状态和SSE结束证据也未完整持久化。后续验收需保存获准的数值与结束标识，不能保存Authorization、敏感头或思考正文。

## 安全状态与账本保留

收费窗口从未开放，因此不需要写回恢复配置；已重新读取确认目标安全状态仍成立：Coder和其他三槽位Disabled；REAL_CALLS_ENABLED=False；日/测试预算0；出口阻断开启；自动重试0；活动真实任务和非终态任务0；Runner活动执行0；无遗留沙箱执行容器。

只读审计快照：model_operations共901条，其中真实记录0；tool_calls共24条；agent_tool_operations为0；sandbox_executions共312条。最新工具/沙箱记录仍为历史时间（UTC11:20:45、11:21:06），不是本轮生成。没有删除历史记录，没有清理未知费用。真实日用量表本租户无记录。

P3/P4生产安全策略未改。没有新建MCP工具调用、Skills或沙箱执行；未重启持有用户临时Key的API/Worker，未尝试读取其他进程环境。没有系统安装、Docker全局变更或其他项目修改。

证据文件仅包含非秘密状态：`work/p5-live-preflight/first-call-preflight.json`、`coder-state.json`、`health.json`及本轮最终审计快照。备份、dotenv和Key不进入报告或Git。交付前只运行必要的只读健康、队列、价格、审计、容器、Git和秘密检查，没有把历史回归数量当成本轮测试结果。

## 下一步建议与暂停

先实现并离线验证服务端原子一次性授权：绑定指定Coder配置版本、端点、模型、完整请求约束/提示摘要、任务、Worker、期限和费用；在创建与真实派发边界都核验；普通Chat和其他任务无权使用；重启或未知结果不重新发放派发机会。补齐准确HTTP派发与安全用量元数据审计，校正专用入口提示/期限，并覆盖并发抢占、第二次调用、失败/超时/断流、恢复和门禁回收测试。

之后再按用户后续指示复核并执行唯一实测。本轮授权**未被外部请求消耗**，但不会自动延后执行，也不提供绕过现有门禁缺口的本地收费命令。报告提交后暂停，不进入P6。
