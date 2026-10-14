# AgentForge AI P1 执行范围

2026 年 10 月 14 日，用户已批准仅进入 P1，并以本轮明确要求收紧 P0 的 P1 范围。

允许：FastAPI/Pydantic v2 项目基础，配置与秘密引用校验，健康接口、日志、PostgreSQL/Redis 连接、SQLAlchemy/Alembic，React 十个基础页面，真实健康接口联调，独立开发 Compose，测试与学习文档。

本轮不实施：真实或模拟模型回答、Provider 调用、计费调度、LangGraph 执行、SSE、Agent 工作流、Docker Sandbox/预热执行、MCP 调用、Skill 执行及审批流程。只预留接口和页面，状态明确为未实现。

项目内依赖安装已获用户确认，安装于 .venv、frontend/node_modules，缓存和临时文件限制于 work 下；不更改系统 Python/Node 或其他项目。初次 Docker Engine 不可连接，用户随后启动现有 Docker Desktop；本轮只创建、验证和管理 AgentForge 专属服务、网络及卷。
