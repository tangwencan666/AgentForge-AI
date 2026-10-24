# Core CI 范围

此工作流仅验证干净的 GitHub 托管环境中的依赖安装、明确范围的后端核心测试，以及前端类型检查和生产构建。核心 CI 通过不代表项目运行验收通过；`RUNTIME_BLOCKED`、`DEPLOYMENT_BLOCKED` 和既有未完成项不因此解除。

## 后端

Linux 和 Windows 托管 Runner 均使用 Python 3.12，执行：

```text
python -m pip install --requirement backend/requirements.lock
python -m pip check
python scripts/test-offline.py --core
```

直接使用已提交的锁文件，不在 CI 中重新解析或更新依赖。`pywin32` 保留 `sys_platform == "win32"` 标记，仅安装在 Windows。当前锁文件未包含所有安装包的内容哈希，不宣称具备哈希级供应链复现保证；CI 中的官方 Actions 固定到提交 SHA。

`--core` 在原离线入口增加明确的文件白名单，完整运行以下文件，不用 `-k` 排除失败断言：

| 文件 | 验证范围 |
| --- | --- |
| `tests/unit/test_config.py` | 配置、凭据引用、端点白名单、默认拒绝 |
| `tests/unit/test_logging.py` | 日志字段与秘密脱敏 |
| `tests/unit/test_workflow_policy.py` | 工作流限制、上下文与工具权限 |
| `tests/unit/test_model_adapter.py` | 模型路由、预算、MockTransport 协议与错误处理 |
| `tests/unit/test_deepseek.py` | DeepSeek 协议夹具、离线 SQL 生成、内存 SQLite、离线保护断言 |
| `tests/unit/test_mcp_policy.py` | MCP Schema、Capability 绑定与子进程环境构造；不启动 MCP 子进程 |
| `tests/http/test_api.py` | 健康、鉴权、配置、错误与 OpenAPI 契约 |
| `tests/http/test_capabilities_api.py` | MCP/Skills 权限及请求校验 |
| `tests/http/test_inference_api.py` | 模型入口鉴权、额度阻断 |
| `tests/http/test_permit_api.py` | Permit 权限与不可伪造的授权绑定 |
| `tests/http/test_sandbox_api.py` | Sandbox 请求校验、鉴权及未配置时拒绝；不启动 Sandbox |

沿用 `offline_guards` 和显式 `pytest_asyncio.plugin`，禁用第三方 pytest 插件自动加载；测试子进程只继承原入口列出的 OS 运行变量，不继承模型凭据、代理或服务配置。审计钩子阻止项目 `.env` 读取、真实 DNS 和 socket 连接。仅保留 Windows 标准库 asyncio 自用 socketpair 的既有精确例外，不放开 HTTP、模型、数据库或 Runner 网络。

HTTP 使用进程内 TestClient、StubConnections，模型协议使用 MockTransport。离线 SQL 生成和内存 SQLite 只属于测试夹具，不操作外部 PostgreSQL/Redis。JUnit 报告为 `work/core-ci.xml`，按 OS 上传 artifact 并保留 7 天；失败保持失败，不用 `continue-on-error`。

## 前端

Ubuntu 托管 Runner 使用 Node 22，在 `frontend/` 执行 `npm ci`、`npm run typecheck`、`npm run build`。依赖版本和完整性信息来自已提交的 `package-lock.json`；生产构建使用现有 Vite 配置，不加载后端 `.env`，不启动前端或后端服务器。浏览器测试不在首轮范围。

## 触发与边界

针对目标为 `main` 的 `pull_request` 和推送到 `main` 的提交运行。使用只读仓库权限、托管 Runner 和不持久化凭据的 checkout；不使用生产 secrets、环境授权、自托管 Runner、服务容器或部署步骤。不合并 PR，不启动或操作用户电脑上的 Runner、VMware、Docker、数据库或真实模型。

没有把整个 `tests/unit` 当作跨平台集合，也没有更改不带参数的原离线测试范围。其余生命周期、进程归属、维护与沙箱测试均在核心范围外；Windows 生命周期/IPC/进程所有权专项需要另行验收。已知 `fake_coder_protected_start` 的 `CONTROL_CHANNEL_UNVERIFIED` 仍未关闭，不能用本工作流的 Windows 核心测试通过代替该专项通过。真实 Sandbox、真实模型及计费验收、VMware Mock 演示继续保持原有未验证/阻塞状态。

实际结果以 PR 对应提交的 Actions 日志和 JUnit artifacts 为准。首次源码上传的历史测试数字不作为本工作流结果。
