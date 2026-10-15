# P4 测试记录

2026-10-15，Asia/Shanghai。实际 PostgreSQL/Redis、固定可信 MCP stdio 子进程、项目 Docker Runner 和无头 Edge。测试替身/故障注入只证明对应失败分支；正常 MCP/数据库/Docker/浏览器均用真实组件。

## 运行记录

| 命令/证据 | 结果 |
| --- | --- |
| migrate.py upgrade/check | 0005_capabilities，ORM 无差异 |
| 首轮 P4 专项 work/p4-capabilities.xml | 55 通过，0 失败/跳过 |
| 补充 P4 真实集成 work/p4-mcp-integration-final.xml | 35 通过，0 失败/跳过 |
| 最终 scripts/test-p4.ps1 → work/p4-all.xml | 221 通过，0 失败/错误/跳过，124.24 秒：unit 114、HTTP 35、integration 72 |
| npm run test:e2e → work/p4-e2e.json | 最终 11 通过，0 失败/跳过，41.37 秒 |
| npm run build | TypeScript / Vite 通过，57 modules |
| python -m pip check | 无依赖冲突，无新增依赖 |
| scripts/check_secrets.py | 工作文件（含 untracked）、暂存区、bundle、logs、JUnit/E2E 扫描通过 |
| 只读 Git/新增文件检查 | status / diff --check / diff 通过；25 个新增文件单独做差异/whitespace 检查，Python AST 解析通过 |

完整脚本暂停本项目 Worker，使用测试 Worker 驱动工作流，并启动无 Socket 的专用故障 Runner；finally 清理故障服务、恢复本地服务。MCP 集成逐项创建独立租户并只清理其行，不清空共享数据库或 Redis。

## 场景映射

| 场景 | 主要测试 | 断言 |
| --- | --- | --- |
| D01 未授权/Schema/路径/跨租户 | test_mcp_policy、test_capabilities_api、gateway_schema_rejection、tenant_identity_and_secrets | 默认拒绝，路径/URL/类型/额外字段拒绝，租户不由客户端指定；拒绝无写入 |
| A05 高风险审批 | no_permission_no_approval、approved_write_cannot_bypass_binding_or_revocation | 缺批准、过期、改参、撤权、重授权、同一人批准、政策变更、拒绝均无副作用 |
| Server 最终边界 | server_repeats_checks、revocation_between_gateway_dispatch_and_server_execution | 资源授权不替代批准，绕派发状态/伪造能力不可写，派发后撤权也阻止写入 |
| D02 受众/端点/超时/额度 | capability 单元测试、actual_transport_timeout、quota_denial | 签名绑定受众/工具/参数，动态端点拒绝；真实超时未决且不重放，额度先于派发；远程 HTTP/OAuth 未实施 |
| 幂等/回执 | real_mcp_write_read_and_idempotency、concurrent_dispatch、uncertain_result | 真实子进程读写、替换 Gateway 后原结果、并发仅一次、丢响应仅核对回执 |
| D09 审计/输出 | pre_dispatch_audit_failure、result_audit_failure、invalid_tool_output | 预审计故障零副作用；结果审计失败保留回执；坏输出不伪装成功或泄密 |
| D03 惰性候选 | manifest_cannot_supply_install_hooks、candidate_is_inert_install_and_enable | 不接受 hook/包/动态端点；候选不可用，安装后未启用也不可用 |
| D04 生命周期 | skill_permissions_disable_and_new_version、dependency_closure、approval_rejection_and_expiry、manifest_integrity | 权限交集、停用撤销、新版本不继承批准；依赖哈希/generation/状态变化阻断，拒绝/过期不安装 |
| P3 安全回归 | 原 test_sandbox.py 16 项及原 policy/failure HTTP/单元 | 真实执行、非 root、无外网、只读根、宿主标记不可读、CPU/内存/PIDs、超时取消、输出限制、重复拒绝、无跨任务状态、Docker 故障/恢复和清理 |
| 前后端联调 | capabilities.spec.ts 3 项 + 原 sandbox/smoke/workflow 8 项 | 审批读写撤权、Skill 全生命周期、角色拒绝、内存授权/刷新清理及原 P2/P3 可用 |

## 证据范围

截图 work/p4-mcp.png、work/p4-skills.png 已目视核对，无布局重叠。最终环境核对见 work/p4-environment.json：真实依赖/代理/Runner 就绪，无活跃执行和遗留执行/故障容器；项目 MCP 子进程数量为 0。凭据不写 trace，源码/产物/报告扫描已知本地秘密。工具输入和候选输入拒绝已知秘密/敏感赋值模式，输出另做 Schema、资源绑定与脱敏。

最初沙箱内 Edge 启动失败未执行页面；申请具体验收后 11 项通过。一项自动审核超时通过允许的一次重试恢复。未满足前置条件没有算通过或 skip。

未验证远程 MCP/OAuth、生产 IAM、任意安装器供应链、真实模型/计费或完整 P5 观测。P3 共享内核/可信控制面及未专门强杀 Runner 的残余风险保持原表述。完成本阶段后暂停。
