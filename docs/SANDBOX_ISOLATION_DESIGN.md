# Sandbox 跨实例隔离设计（S2 待授权实施）

状态：**DESIGN / BLOCKED，未实施、未部署、未验收**。实际证据见[P5_LIVE_MAINT_S2_REPORT](P5_LIVE_MAINT_S2_REPORT.md)。

## 当前边界

S1已隔离API/Worker生命周期、端口、日志/目录、PostgreSQL、Redis及浏览器目标；数据栈清理需资源租约、精确ID及镜像/挂载/网络证明。这不包含Runner。当前Sandbox名称/策略标签全局共享，本库无记录可能触发删除；名称、普通标签或Redis状态不能授予清理权限。

主Runner持有共享Docker socket，旧镜像会持续运行原对账规则。只给测试Runner增加过滤不能防止旧主Runner发现测试容器。直接改策略版本躲避旧过滤器涉及执行及审批协议，不作为临时绕过方案。

## 路径与兼容前置

优先使用用户提供且已证明归属的独立测试Docker daemon：验证daemon身份、socket/endpoint、资源基线和固定镜像，拒绝回退到Desktop共享daemon。当前没有建立或验证此环境；不自动安装组件、启用特权DinD或修改Desktop全局配置。

若继续共用daemon，需要单独授权协议升级及兼容部署计划。先在独立daemon或无Docker替身中验证新协议，再安排明确的主Runner维护窗口；旧主Runner仍能发现测试执行时不能运行共存验收。主部署、停止/重启权限均不包含在本设计内。

## 计划中的可信归属

1. 服务端生成不可由任务/模型/普通客户端选择的实例身份和generation，绑定可信Runner、固定daemon、数据库身份、镜像和策略版本。
2. 执行记录持久化实例/generation、execution、启动意图及后续不可变container ID。标签和命名空间只用于发现，与可信记录交叉验证，不能单独授权。
3. 创建前提交意图，结果明确后持久化精确ID。创建结果未知保留UNKNOWN/待对账，拒绝重派发和不明确清理，不能按前缀强删。
4. 派发、对账、取消、超时、finally及恢复共用归属检查。无本实例记录、generation变化、策略不符、身份冲突或daemon不明确时，保留审计并阻塞，不能当孤儿自动删除。
5. 删除前重新核对可信记录、独占操作认领、固定daemon、不可变ID和实际配置；不按名称重试或标签批量删除。并发协调不能只靠Redis键/instance_id。
6. 保留审批哈希、可信Worker/fence、预算、launch-intent、未知结果不重发、运行时attestation、无网络、非root、只读根、seccomp/capability和资源限制。Reviewer或维护审批不能替代P3/P4业务审批。

完整Docker socket持有者仍可绕过应用代码操作daemon；该设计不是对恶意daemon管理员的隔离，跨信任域应使用独立daemon和受限控制面。

## 后续需改文件（本轮未修改）

| 路径 | 目的 |
| --- | --- |
| backend/app/sandbox/policy.py、driver.py、engine.py | 创建、检查、精确清理与未知恢复统一实例边界 |
| backend/app/domain/sandbox.py、schemas/sandbox.py、core/config.py、migrations/versions/下一迁移 | 归属持久化、严格配置和审批兼容；迁移须先备份/恢复演练 |
| scripts/s1_isolation.py、s1_test_environment.py、s1_application_test.py | 真实Runner资源证明、租约、独立工作目录、有归属的失败清理 |
| tests/conftest.py、fixtures/preflight_guards.py | 只凭已证明的Runner能力放行；误指主端口/库/Redis时在写入前拒绝 |
| frontend/playwright.config.ts、tests/run-e2e.mjs、tests/sandbox.spec.ts | 独立浏览器目标、测试审批凭据和输出；证明前继续排除Sandbox |
| tests/integration/test_sandbox*.py、test_real_agents.py及新增用例 | 补齐17项及跨实例竞争、未知归属、实际Runner崩溃 |
| compose.yaml与维护入口 | 仅在后续批准的部署阶段升级；不复用旧pause/restore流程 |

## 验收顺序

1. 静态/Stub：无记录不删除，伪造标签无权清理，意图/ID/代次/daemon不一致拒绝，未知状态不重复执行。
2. 独立daemon实际集成：两个数据库/Runner并发运行，A不能把B容器判为可删除或删除，反向亦然；保留真实ID、配置及审计。
3. 实际Runner进程崩溃：创建前、创建响应未知、ID持久化后、注入后及清理前后恢复，不重复注入、不清理其他实例。
4. API/Worker/PG/Redis/Stream/日志/浏览器独立；误指主资源时在写入/消费/终止前拒绝，失败finally仅操作重新证明归属的本次资源。
5. 原17项集成和2项浏览器全部实际运行，再验证P3/P4/Permit/预算/出口；模型均为Stub，真实供应商请求0。
6. 前后核对主服务身份、生命周期元数据和容器ID/StartedAt；确认测试资源清零，不明归属保留并报告BLOCKED。

生命周期原生多进程竞争、PID创建时间/SID/同句柄验证、IPC、审批过期/重放、异常中断仍须用独立实例及假凭据复测。Stub不能替代。升级须明确旧审批/执行记录的处理，不静默迁移授权或回退全局清理。
