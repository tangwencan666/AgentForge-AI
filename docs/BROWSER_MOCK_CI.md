# 自动浏览器 Mock 工作流验证

本工作流在 GitHub 托管的临时 Ubuntu 环境运行 Chromium，连接真实的生产前端构建、API、Worker、PostgreSQL 和 Redis。模型路径保持显式 Mock。它是自动浏览器验证，不代表真人验收、VMware 部署、真实模型或 Sandbox 验收，不解除现有运行/部署阻塞。

## 独立入口与配置

`.github/workflows/browser-mock.yml` 使用已提交的 Python/npm 锁文件，执行依赖一致性、隔离拒绝测试、前端类型检查及生产构建，安装同一锁定 Playwright 版本的 Chromium，最后执行：

```text
python scripts/ci_mock_workflow.py --browser
```

该命令只允许通过正常托管任务调用。本地和自托管环境在事件循环或任何服务连接创建前拒绝。它不使用原有 Windows 浏览器入口、`loadEnv`、旧 Compose 或主环境配置。

环境沿用 [API/Worker Mock CI](MOCK_WORKFLOW_CI.md) 的容器 ID、run/attempt 标签、专属网络、tmpfs、随机回环端口、空数据校验、测试角色和标记数据库。原有核心 CI 和 API/Worker 工作流保持独立；默认不带参数的 API/Worker 验证流程不变。浏览器模式先完整执行原 API/Worker 场景，再增加前端和浏览器步骤。

API、Worker、迁移子进程继续使用原有 Python 审计保护和服务验证。控制进程仅为本次真实前端增加一个随机回环端点；API/Worker 的网络权限不增加。真实调用/Permit 关闭、真实预算为零、Mock 额度为有效正数，Sandbox 不配置。

`vite.browser-ci.config.ts` 只服务真实构建文件，将 `/api`、`/health` 和 `/openapi.json` 代理到经校验的本次回环 API。它不读取 dotenv、不接收认证令牌、不使用默认旧端口。`playwright.browser-ci.config.ts` 只选择 `tests/browser-ci/workflow.spec.ts`，不加载旧测试，使用安装的 Chromium、单 Worker、零重试；没有业务接口的 route/fulfill/mock 或响应伪造。

浏览器控制器的唯一凭据来自本任务生成的测试令牌，经权限 0600 的临时 JSON 传递，位于本次 `RUNNER_TEMP` 私有目录，退出后删除，不上传。前端只在页面内存中保存授权。测试通过真实页面完成创建、批准、重新授权和取消；额外的只读 HTTP 查询核对真实持久化记录，不代替页面操作。

## 四个场景

一个连续 Playwright 测试包含四个具名步骤，以提供同一段短录屏；不将其报为四个独立测试用例。

| 场景 | 断言与证据 |
| --- | --- |
| 页面创建并等待审批 | 页面 Mock 下拉值；POST 返回 202；页面 waiting_approval；账本只有 completed Planner |
| 页面批准并成功 | 点击批准；页面 succeeded 和 `[MOCK]` 结果；页面显示四角色账本及真实 SSE 事件；真实调用记录均为 Mock、无工具执行和真实费用 |
| 刷新并重新授权 | 刷新后无授权、无受保护详情、无浏览器存储；重新授权并选择同一任务，结果、调用 ID 和时间戳不变；任务 ID 集合不变，期间无新增写请求 |
| 页面取消待审批任务 | 创建另一 Mock 任务，等待审批后点击取消；页面 cancelled；持续 2 秒查询，只有 Planner，后续角色没有执行 |

浏览器结束后再次查询实际测试数据库，要求非 Mock 操作、Sandbox 执行和 Permit 记录均为零。

## 隐私与产物

认证输入本身为 password。每次导航/刷新还注入仅影响该字段外观的黑色遮挡，填入前验证透明文字颜色；截图额外 mask 该认证字段。该遮挡不改变认证逻辑。关闭 trace/HAR 和自动 DOM 截图，保留视频和四张显式截图。临时测试令牌注册为 GitHub 日志掩码，文本产物在上传前再次替换测试凭据。

`browser-mock-evidence` artifact 保留 7 天，包含：

- `result.json`：隔离身份、原 API 场景结果、浏览器汇总和最终安全计数。
- `browser-results.json`：四个步骤的实际状态、任务 ID、持久化和零重复操作断言。
- `screenshots/01-waiting-approval.png` 至 `04-cancelled-no-later-roles.png`。
- `mock-workflow.webm`：一个连续流程的自动浏览器短录屏。
- `browser.xml`、`playwright.log` 及真实前端/API/Worker/迁移日志。

测试失败保持非零退出并上传已有日志及媒体，不自动重试或跳过断言。可通过向 `main` 更新此 PR 或在 Actions 中重新运行复现。所有服务和浏览器进程均在本次托管 VM，任务结束回收；不访问、同步或比对用户原工作区的任何文件或配置。
