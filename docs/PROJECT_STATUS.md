# AgentForge AI 项目状态

2026-10-15，Asia/Shanghai。项目 `D:\AIProjects\AgentForge-AI`。

P0–P3 历史验收保留。用户已明确恢复并批准 P4：MCP Tool Gateway + Skills Registry；P4 编码与本地验收已完成，现暂停。P5 未开始。

| 领域 | 当前实际状态 |
| --- | --- |
| 基础应用 | FastAPI、React、安全错误/日志、四模型槽位、真实 PostgreSQL/Redis |
| 模型与协作 | 模型回答和费用仍为明确 Mock；LangGraph、Outbox/Streams、检查点、租约/fencing、审批和 SSE 为真实实现 |
| P3 Docker | 独立可信 Runner、固定镜像、非 root/无网络/只读根/资源限制、一次性容器及独立审批继续生效；预热关闭，无宿主机执行回退 |
| P4 MCP | 固定可信 stdio Client/Server；真实租户笔记读写；精确工具/资源权限、严格 Schema、配额、独立高风险审批、调用账本、原子回执及对账 |
| P4 Skills | 惰性候选、不可变版本/来源、依赖闭包、安装/启用分别批准、停用/撤销、权限交集及依赖 generation 检查；启用版本可调用 Gateway |
| 数据库 | 0005_capabilities 已应用，保留 P1–P3 数据，Alembic check 无差异 |
| 前端 | `/mcp` 和 `/skills` 真实联通；已通过独立审批、读写撤权、候选安装启用停用浏览器验证；凭据只存页面内存 |
| 验证 | 最终 Python 221/221（单元/HTTP 149、真实集成 72，含 MCP 36 与 P3 沙箱 16），浏览器 11/11；0 失败/跳过；构建、迁移、秘密和 Git 差异检查通过 |
| 后续范围 | 真实 Provider、远程 HTTP MCP/OAuth、任意包安装、生产 IAM/加密保留治理及 P5 均未实施 |

本地前端 `http://127.0.0.1:15173`，MCP `/mcp`，Skills `/skills`，沙箱 `/sandbox`；后端文档 `http://127.0.0.1:18100/docs`。地址为本轮验证环境，不保证主机重启后自动运行；启动见 GETTING_STARTED 第 11 节。

bootstrap-p4 已在被忽略的项目 .env 补充独立随机 MCP 与 P4 审批凭据，无输出秘密、无新增依赖。MCP Server 是按最小环境启动的固定可信程序，不接受用户 endpoint、命令、hook 或 Python。声明式 Skill 安装验证本地清单和依赖，不联网下载。

本地服务及可信 Runner 已恢复，PostgreSQL/Redis 就绪，无遗留执行容器/故障 Runner/MCP 子进程。测试资源授权已撤销，演示记录保留。

遵守 `.git` 只读约束，仅读取 Git，不 add/commit、不改权限。HEAD 保持 `032e8aa2cc52bf7ecc992370c30bf9fe5def1c3d`；用户可在最终报告后手动提交。

契约与证据见 [P4_CONTRACT](P4_CONTRACT.md)、[P4_REPORT](P4_REPORT.md)、[P4_TEST_RECORD](P4_TEST_RECORD.md)。P3 Docker 共享内核、可信 Runner 持 daemon 权限等残余风险继续成立；本轮通过不等于生产安全认证。完成 P4 后暂停，不进入 P5。
