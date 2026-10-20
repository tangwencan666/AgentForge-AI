# P5-LIVE-MAINT-S1 安全测试

这是 S1 独立验收记录，不将历史 450/600 项结果计入新机制。最终本轮数量、证据和未验证项目见 P5_LIVE_MAINT_S1_REPORT.md。

| 层次 | 证据含义 | 不能证明的内容 |
| --- | --- | --- |
| 纯单元/Stub | 错误路径、权限范围、资源身份拒绝、固定入口、数据格式 | 真实容器、生产服务隔离 |
| 原生 Windows IPC | Token/SID、管道 DACL、内核对端、期限和重放、断连 | 供应商认证或完整业务工作流 |
| 原生生命周期＋标准库应用 Stub | 真实 Python/PowerShell 竞争、进程归属、幂等、伪造状态拒绝、崩溃保护 | 真实 FastAPI/Redis Worker 已验收 |
| 独立 PostgreSQL/Redis 集成 | 实际事务、队列、Permit 和持久恢复 | 真实模型调用或主库部署 |
| 独立真实 API/Worker | 新版 bootstrap、真实业务就绪和 Mock 任务调度 | 真 Key 有效性或付费调用授权 |
| 浏览器 | 独立目标的实际 UI/API 行为；Stub 浏览器另列 | 被排除的真实 Runner 场景 |

关键验收：无 Key 覆盖拒绝；重复专用启动幂等；两个真实 Windows 启动器不产生双 Worker；PID/FILETIME 不符拒绝终止；伪造 mode/保护标志/代次不能取得维护权限；过期与重放授权拒绝；崩溃不解除保护；finally 不恢复主服务；精确 Redis/数据库隔离；日志无假凭据标记；未知归属不清理；所有真实模型请求为零。

PID 复用测试必须区分错误创建时间模拟与真实 Windows 句柄验证，不能宣称强制 OS 重用了某个指定 PID。Python 单元/HTTP 的无网络钩子不会自动传给新解释器；子进程必须独立安装保护或只运行明确标准库 Stub。

首次 IPC 试验发现最小访问掩码缺少 FILE_READ_ATTRIBUTES，修正后最小 DACL 生效；沙箱内对 Windows 管道客户端的限制另行记录。原生验证只对隔离测试进程使用必要执行权限，没有修改系统 ACL。所有初次失败证据保留。

真实 P3 Docker 执行及依赖主 Runner 的浏览器用例在 S1 保持未执行/BLOCKED。不运行旧 Runner pause/restore，不用 Stub 替代真实沙箱验收。

## 2026-10-18 最终验收对应

最终891个不同Python用例有通过证据，分批执行及去重方式见S1报告；14项浏览器通过，其中完整后端Stub与健康接口故障注入各1项，其余12项走实际本地UI/API。17项Sandbox集成和2项Sandbox浏览器明确未执行。所有外部供应商请求0，实际费用0。

| 目标 | 实际证据与限制 |
| --- | --- |
| 无Key覆盖拒绝、专用重复幂等、finally不重启 | protected原生场景使用假Key、实际Python进程和live IPC；PID/代次保持；普通维护拒绝。没有向当前主服务注入故障 |
| 并发启动无双Worker | race：两个真实PowerShell在屏障后竞争，1成功/1 LOCK_BUSY；另一固定可信CLI完成停止 |
| PID复用保护 | identity：实际Worker的错误FILETIME和SID均在同句柄终止前拒绝，进程继续存活；不宣称强制OS复用PID |
| 伪造清单/环境/代次 | protected活实例双向IPC拒绝伪造绑定；环境标志不能授权；不宣称抵御同用户同时篡改可信源码和全部审计 |
| 维护授权过期/重放 | protected以隔离时钟偏移61秒触发过期；旧challenge拒绝。scope单元测试覆盖核验结束后过期及墙钟回退；不是实际等待60秒的声明 |
| 崩溃不解除保护 | 原生Worker被精确终止后无自动重建；保护记录保留；过期/未知状态不自动清零 |
| 实际Worker恢复 | Permit集成两次真实OS崩溃并等待真实数据库租约过期；重启后不重发，DISPATCH后保留UNKNOWN和预算预留；HTTP使用虚拟Transport |
| 测试数据库和队列隔离 | 验证真实容器/网络ID、标签、实际回环端口、tmpfs及URL；独立API/Worker完成4个Mock调用；父租约覆盖全部业务及清理 |
| 未确认归属不清理 | 资源Stub拒绝伪造ID/标签/挂载/网络；原生IsProcessInJob拒绝Job外进程；归属不明保持拒绝，不按PID/名称兜底 |
| 日志和权限 | 假凭据标记不进入生命周期证据；凭据格式扫描通过且未读真实Key比对。P3/P4/Permit/预算单元与真实数据库回归通过；真实Runner仍BLOCKED |

测试进程/容器已清理；失败记录没有改成成功。当前主API不可连接、主凭据状态UNVERIFIED，旧主元数据哈希/大小/写入时间保持一致。隔离验收不授予生产接管或真实调用权限。跨Windows账户登录测试、Runner共存及主环境v2部署仍未验证。
