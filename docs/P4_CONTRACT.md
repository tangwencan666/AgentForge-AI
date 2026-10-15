# P4 MCP Tool Gateway 与 Skills Registry 契约

2026-10-15，Asia/Shanghai。仅本地开发。范围依据用户恢复 P4 的明确授权；不进入 P5。

## 实际能力与边界

MCP 使用固定可信程序 `python -I -m app.mcp.server` 的 stdio 传输。Gateway 不能接收用户指定的 executable、endpoint、环境变量或服务器地址。协议版本固定为 `2025-11-25`，执行 initialize → notifications/initialized → tools/list → tools/call。发现的工具必须与服务端内置目录完全一致，发现不会自动授权。

本轮目录只有 `notes.read@1.0.0` 和 `notes.write@1.0.0`。它们读写 PostgreSQL `managed_notes` 中的租户笔记，具有真实持久化副作用；不是模拟远程响应。资源为 1–48 位小写 slug，不接受文件路径、URL、SQL、跨租户 ID 或动态工具名。`notes.write` 为高风险工具，必须独立批准。

Skills 是 `p4-declarative-v1` 声明式能力版本：文字说明、工具清单、权限声明、固定版本与哈希的依赖。安装指对本地已登记的不可变清单及完整依赖闭包作验证并保存安装记录，不安装 Python/npm 包。没有下载、安装 hook、动态 import 或执行候选代码的入口。Agent 候选与人工候选均先保持惰性；说明文字不作为系统指令运行。可执行 Python 仍只通过 P3 审批与 Docker Runner。

本轮没有远程 HTTP MCP、OAuth、多服务器管理、任意第三方包安装、真实模型调用或 Agent 自主调用工具。P2 四角色仍为明确 Mock；用户可在 MCP Tools / Skills Center 通过真实 Gateway 调用声明的工具。生产多用户身份、远程出口与供应链治理不属于本轮交付。

## 身份与权限

本地管理员 `AGENTFORGE_ADMIN_TOKEN` 管理工具精确资源权限、提交调用、登记候选和申请安装/启用。租户 ID 来自服务端配置。前端传入租户、requester、approved 或 endpoint 等额外字段会被拒绝。独立 `AGENTFORGE_CAPABILITY_APPROVER_TOKEN` 只能用于复核和决定 P4 审批，不能管理权限或提交调用。两者以及 P3、MCP 服务凭据均须至少 32 字符且互异。

`AGENTFORGE_MCP_SERVER_TOKEN` 只在可信 Gateway 和受控 Server 间使用。每次调用有 HMAC 能力凭证，绑定受众 `agentforge-controlled-mcp/v1`、工具 scope、租户、调用 ID、参数哈希、操作哈希和短有效期。Server 在事务中再次核对调用账本、当前权限、Skill 及批准。管理员/审批者/模型凭据、代理变量和 Python 启动配置不会继承到 MCP 子进程。不得把 MCP 服务凭据交给 Agent 或浏览器。

ToolPermission 默认不存在即拒绝。权限绑定 tenant + tool + resource，变更允许状态时递增 generation。批准后撤权再重新授权，也不能复用先前调用的批准。Skill 权限是调用者资源授权、固定服务端政策、版本工具和 required_permissions 的交集，声明权限不会创建授权。

## 调用事务与审批

1. POST `/api/v1/mcp/calls` 带 UUID `Idempotency-Key`，验证严格 Pydantic Schema（同时发布 JSON Schema，所有对象禁止额外字段）、资源语义、秘密输入、权限与 Skill。
2. 保存不可变请求指纹、操作哈希及 `ready` / `awaiting_approval` 账本。哈希绑定租户、requester、工具版本、参数、资源、权限 generation、Skill 整个依赖闭包的哈希/generation 和 policy_version。
3. 高风险审批另存 `capability_approvals`，有效期 15 分钟。审批者通过 `/review` 读取实际参数或清单/依赖，再以 operation_hash 作出决定。服务端验证身份、目标、动作、政策、期限和参数；无“approved=true”快捷通道。
4. POST `/mcp/calls/{id}/execute` 再鉴权，原子扣除租户 UTC 日调用额度，提交 `dispatched` 和预调用审计，才启动 MCP 子进程。默认每日 1000 次、端到端 8 秒、单消息 64 KiB；失败/未知派发也计次。
5. Server 在同一租户事务锁内再次检查签名与期限、账本、Schema、资源权限、审批和 Skill，写笔记、写独立回执、消费一次批准并提交审计。SQL 参数化，数据库 lock_timeout=2s、statement_timeout=3s。权限撤销与副作用事务串行化：撤销先提交则副作用被拒；副作用先提交则保留真实结果。
6. Gateway 校验输出 Schema、资源绑定与数据库回执，脱敏后记录成功。非正常输出、超时或连接中断保存 `needs_reconciliation`；进程崩溃可留下 `dispatched`，均不自动重发。仅 `/reconcile` 核对已存在回执；无回执仍是未知，不能假定回滚或改为成功。创建同一个 key 只返回原调用；执行成功记录只返回原结果。

预调用审计失败会回滚派发并阻止副作用。Server 回执与副作用原子提交，结果审计失败时仍可在不重放的情况下核对回执。拒绝审计另用事务持久化；审计不保存参数原文、笔记正文或秘密。操作参数和回执是受控业务字段，普通调用 DTO 只向对应本地管理员返回；生产加密和保留政策尚未发布。

## Skill 生命周期

`candidate → registered → pending_install → installed_disabled → pending_enable → enabled`。

安装和启用分别有绑定动作与内容的独立审批；拒绝安装回到 registered，拒绝启用回到 installed_disabled，不能获得能力。禁用会取消未完成审批并递增 generation；撤销终止该版本。再次启用必须新审批。版本内容和来源不可覆盖，升级另建版本并重新审批，不自动迁移旧版本的授权。

依赖必须精确指定 skill_id、version、content_hash。安装要求依赖已安装；启用/使用要求全部依赖已启用，并验证传递闭包，无环、深度≤8、节点≤32。启用记录绑定依赖 lifecycle generation：依赖停用后再启用，父版本也必须停用并申请新的启用批准。依赖变化发生于审批期间时，原批准请求无法生效。

Skill 停用/撤销会阻止新调用和已准备但尚未实际执行的调用；Server 已提交的结果保留为事实。单次笔记操作没有持续执行的用户代码或后续步骤。未增加宿主机代码执行和任何 P3 禁令豁免。

## API 与前端

| API | 管理员 | 独立 P4 审批者 |
| --- | --- | --- |
| GET `/mcp/tools`, GET/PUT `/mcp/permissions` | 目录/精确授权 | 拒绝 |
| GET/POST `/mcp/calls`, GET `/{id}`, POST `/{id}/execute`, POST `/{id}/reconcile` | 准备/查看/执行/核对 | 拒绝 |
| GET `/skills`, POST `/skills/candidates`, POST `/skills/{skill_id}/{version}/actions` | 候选/版本/生命周期申请 | 拒绝 |
| GET `/capabilities/approvals`, GET `/capabilities/audit` | 状态与审计 | 拒绝 |
| GET `/capabilities/approvals/{id}/review`, POST `/{id}/decision` | 拒绝 | 复核/批准/拒绝 |

路径均带 `/api/v1` 前缀。操作载荷禁止额外字段；失败采用统一安全错误 envelope 和 request_id。`/api/v1/system` 如实报告 P4 与 Mock 模型状态。`/health/ready` 验证 0005_capabilities 及实际核心表。

`/mcp` 显示真实目录、Schema、授权、调用状态、独立审批、回执核对和审计。`/skills` 提交候选、展示不可变版本和依赖、申请安装启用、批准/拒绝、停用撤销及通过版本调用工具。Token 只在页面内存保存，刷新、退出授权或离开审批组件会丢弃；无 localStorage/sessionStorage，无默认遥测或 Token URL。UI 校验只帮助使用，授权以服务端为准。

## 协议参考

本轮选择的 stdio 帧格式、初始化和工具目录字段依据 MCP 官方规范：

- [Transports — stdio](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [Lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
- [Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)

固定本地 stdio 与私有能力凭证不宣称实现远程 MCP OAuth。后续远程传输必须另行设计受众、scope、端点/出口、重定向、DNS 与协议认证，不能简单开放 URL 输入。
