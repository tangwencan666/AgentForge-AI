# P4 实施与验收报告

2026-10-15，Asia/Shanghai。项目 `D:\AIProjects\AgentForge-AI`。基线 HEAD：`032e8aa2cc52bf7ecc992370c30bf9fe5def1c3d`，开始时工作区干净。

P4 编码与本地验收已完成，现暂停。范围为用户明确批准的 MCP Tool Gateway + Skills Registry；本轮不进入 P5、不提交 Git。

## 交付内容

| 变更 | 行为与依据 |
| --- | --- |
| `backend/app/mcp/` | 固定可信 stdio Client/Server，真实初始化、目录比对、签名能力与调用；无动态 endpoint/命令 |
| `schemas/tools.py`、`services/capabilities.py` | 严格输入/输出 Schema、资源语义、固定目录、权限交集、租户事务锁、哈希绑定与依赖闭包 |
| `services/tool_gateway.py` | 精确资源授权、不可重放账本、UTC 日额度、预调用审计、独立高风险审批、回执、输出脱敏与对账 |
| `services/skills.py` | 候选、不可变版本和来源、登记、安装/启用分别批准、禁用/撤销、升级重新批准及依赖生命周期检查 |
| `domain/tools.py`、0005 迁移 | 7 张新表：tool_permissions、tool_calls、tool_daily_usage、capability_approvals、capability_audit、skill_versions、managed_notes |
| `api/v1/capabilities.py` | 受保护的工具/Skills/审批/审计 API；租户由服务端决定；审批者与管理员权限不互换 |
| `/mcp`、`/skills` 及共享组件 | 真实目录/Schema、授权撤销、调用、独立复核、安装启用停用、版本、结果及审计；内存凭据 |
| 配置/脚本 | 新角色凭据互异校验、项目 .env bootstrap、test-p4 全量回归、含未跟踪文件和测试报告的秘密扫描 |
| 现有入口 | system/live 显示 P4 与 Mock 模型；ready 验证 0005 和核心表；迁移连接超时和模板 import 支持 |
| 文档 | 更新 README、PROJECT_STATUS、GETTING_STARTED、LEARNING_PATH，新增 P4_CONTRACT/P4_TEST_RECORD/本报告；P0–P3 历史报告保留 |

目录提供 `notes.read` 和高风险 `notes.write`，真实读写 PostgreSQL 租户受管笔记。Skills 为 `p4-declarative-v1`，启用版本能通过 Gateway 调用声明工具。安装指本地不可变清单和依赖闭包验证及持久记录，不安装或执行第三方包。候选文字不会运行。

## 验收结果

| 检查 | 结果 |
| --- | --- |
| 最终 Python 全量（含 P3 安全回归） | 221/221 通过，0 失败/错误/跳过，124.24 秒；149 单元/HTTP + 72 真实集成（含 MCP 36、P3 沙箱 16） |
| 完整浏览器联调 | 11/11 通过，0 失败/跳过，41.37 秒；其中 P4 3 项、原 P2/P3 核心 8 项 |
| Alembic upgrade/check | 0005_capabilities 已应用；No new upgrade operations detected |
| TypeScript / Vite | 通过，57 modules，真实同源 API 联通 |
| Python 环境 | pip check 无冲突；无新增依赖 |
| 敏感信息 | 已通过：当前已跟踪/未跟踪源码、暂存区、bundle、日志及 JUnit/E2E 报告的已知本地秘密/常见编码扫描 |
| Git | git status / diff --check / diff 已检查；25 个新增文件单独检查，Python 语法与新文件 whitespace 检查通过；无 add/commit |

场景、命令与证据见 P4_TEST_RECORD。JUnit、Playwright JSON 和截图在被忽略的 work。集成测试使用独立临时租户，finally 只清理自己的行；浏览器保留无敏感演示记录，撤销其精确资源授权，Skill 保持停用。

已验证：无权限、无批准、过期、哈希/参数/政策变化、职责未分离、撤权及撤权再授权均不能写入；Server 在副作用事务重复检查；并发/重复执行只写一次；额度在派发前检查；坏输出不成为成功；对账也重新验证回执 Schema 与资源绑定；写入已提交但丢失响应或结果审计失败后只核对原子回执，不重放；候选/安装未启用/禁用/撤销均不授予能力；依赖 hash/generation 变化要求重新批准。

## 修复与环境处理

原 MCP/Skills 是占位能力，本轮实现本地受控链路。DTO 明确仅发送 Skill 身份和权限变更必要字段，避免展示用 generation/manifest 进入严格 API。禁用 Candidate 不提升成 registered；拒绝 Skill 审批不要求依赖仍有效，允许安全拒绝失效请求。Server 设置有界数据库锁/语句超时，取得事务锁后重复校验能力期限。最终复核补齐对账回执资源绑定并新增篡改回执测试；秘密扫描同时保留暂存区检查，避免暂存内容与工作副本不同导致遗漏。

Docker 最初未启动，用户启动后本项目 PostgreSQL、Redis、Runner 恢复健康。沙箱内 Docker 管道、本机数据库及测试子进程受限，按权限工具申请具体项目操作后运行。一项补充测试自动审核超时，按工具允许重试后通过。沙箱内 Edge 启动即退出，11 项未进入页面；申请具体无头浏览器验收后全部实际通过。未修改 Docker Desktop 全局设置、Git 配置或 `.git` 权限，未为提交申请完全系统访问。

可信 Runner 按现有锁定依赖重建并仅按本项目服务更新。无 Socket 的专用故障 Runner 只用于 P3 故障回归，finally 按服务名清理；不停止共享 daemon、不执行全局 prune。执行容器继续禁止网络、宿主挂载、Socket 和提权。最终确认数据库/Redis、前后端与 Runner 可用，活跃执行、所有策略执行容器、故障 Runner 和项目 MCP 子进程均为 0。早期浏览器遗留的 3 项精确测试资源授权也已撤销，未删除业务记录。

## 限制与阶段停止

本轮仅固定可信 stdio MCP，不含远程 HTTP/OAuth、任意服务器注册、第三方包下载/安装、Skill 动态 Python 或 Agent 自主工具编排。工具仅操作受管数据库笔记，不写宿主路径/请求外网。模型回答和费用仍为明确 Mock；P3 Docker 是真实执行。

身份仍为本地单管理员加独立角色 Token，不是生产多用户 IAM。可信 MCP 程序持有项目应用库连接；清单、业务参数和回执在受保护业务表保存，生产加密/保留和凭据治理未发布。无回执的未知派发保留未决，不能证明外部效果回滚。P3 共享内核/VM、可信 Runner daemon 权限和未专门强杀 Runner 的残余风险继续存在。

P4 完成后暂停，不进入 P5。HEAD 不变，修改留在工作区。建议用户在 Windows CMD 审阅后手动提交：

```cmd
cd /d D:\AIProjects\AgentForge-AI
git status --short
git diff --check
git diff
git ls-files --others --exclude-standard
git add -- .env.example README.md compose.yaml backend frontend docs scripts tests
git commit -m "feat: implement P4 MCP tool gateway and skills registry"
```

上述 add/commit 仅为建议，本轮没有运行。不要加入 .env、work、依赖或测试生成目录。
