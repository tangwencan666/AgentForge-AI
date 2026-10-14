import { useCallback, useEffect, useRef, useState } from 'react';
import { LocalAuthForm, useLocalAuth } from '../components/LocalAuth';
import { sandboxApi, type SandboxExecution, type SandboxPolicy, type SandboxExecutionInput, type SandboxSource } from '../api/sandbox';
import { taskStream, type TaskEvent } from '../api/tasks';
import '../sandbox.css';

const terminal = new Set(['succeeded', 'failed', 'cancelled', 'timed_out', 'rejected', 'limit_exceeded', 'output_limit', 'needs_reconciliation']);
const statuses: Record<string, string> = {
  waiting_approval: '等待独立审批', awaiting_approval: '等待独立审批', queued: '排队中', starting: '启动与隔离检查中', running: '执行中', succeeded: '执行成功',
  failed: '执行失败', cancelled: '已取消', timed_out: '已超时', rejected: '已拒绝',
  needs_reconciliation: '需要人工核对', limit_exceeded: '额度限制', output_limit: '输出超限并终止', pending: '待处理',
};
const messages: Record<string, string> = {
  UNAUTHORIZED: '凭据未通过校验。', FORBIDDEN: '当前凭据没有此操作的权限。',
  SANDBOX_APPROVER_REQUIRED: '需要独立沙箱审批者凭据。',
  APPROVAL_CHECKPOINT_PENDING: '审批检查点正在保存，请稍后重试。',
  DOCKER_UNAVAILABLE: 'Docker 当前不可用，服务端已拒绝执行。',
};
function errorText(error: unknown) {
  const code = error instanceof Error ? error.message : 'REQUEST_FAILED';
  return messages[code] || `请求未完成：${code}`;
}
function time(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '时间未确认' : new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'short', timeStyle: 'medium' }).format(date);
}
function summary(value: string | null) {
  if (!value) return '（无输出）';
  const bytes = new TextEncoder().encode(value);
  return new TextDecoder().decode(bytes.slice(0, 4096)) + (bytes.length > 4096 ? '\n[界面摘要已截断]' : '');
}
// Event logs show bounded metadata, never code, prompts or arbitrary event payloads.
function eventMetadata(event: TaskEvent) {
  const allowed = ['execution_id', 'status', 'cleanup_status', 'duration_ms', 'exit_code', 'policy_version', 'operation_hash', 'code_hash'];
  return allowed.filter(key => key in event.payload).map(key => `${key}: ${String(event.payload[key]).slice(0, 160)}`).join(' · ');
}

export default function Sandbox() {
  const { token } = useLocalAuth();
  const [policy, setPolicy] = useState<SandboxPolicy | null>(null);
  const [executions, setExecutions] = useState<SandboxExecution[]>([]);
  const [selected, setSelected] = useState('');
  const [detail, setDetail] = useState<SandboxExecution | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [code, setCode] = useState('');
  const [timeout, setTimeoutSeconds] = useState(10);
  const [cpu, setCpu] = useState(0.5);
  const [memory, setMemory] = useState(128);
  const [pids, setPids] = useState(32);
  const [approverToken, setApproverToken] = useState('');
  const [source, setSource] = useState<SandboxSource | null>(null);
  const [verified, setVerified] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const requestKey = useRef({ payload: '', key: '' });
  const sourceGeneration = useRef(0);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    if (!token) return;
    try {
      const [currentPolicy, records, execution] = await Promise.all([
        sandboxApi.policy(token, signal), sandboxApi.list(token, signal),
        selected ? sandboxApi.detail(selected, token, signal) : Promise.resolve(null),
      ]);
      if (signal?.aborted) return;
      setPolicy(currentPolicy); setExecutions(records); setDetail(execution);
      setError('');
    } catch (err) {
      if (!signal?.aborted) { setPolicy(null); setError(errorText(err)); }
    }
  }, [token, selected]);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const timer = window.setInterval(() => { void refresh(controller.signal); }, 2000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [refresh]);
  useEffect(() => { sourceGeneration.current++; setVerified(false); setEvents([]); setSource(null); }, [selected]);
  useEffect(() => () => { sourceGeneration.current++; }, []);
  const taskId = detail?.task_id;
  useEffect(() => {
    if (!token || !taskId) return;
    const controller = new AbortController();
    void taskStream(taskId, token, controller.signal,
      event => setEvents(previous => [...previous.filter(item => item.id !== event.id), event].slice(-100)),
      () => { void refresh(controller.signal); });
    return () => controller.abort();
  }, [token, taskId, refresh]);

  async function create() {
    if (!policy || !token) return;
    setBusy(true); setError('');
    const input: SandboxExecutionInput = { language: 'python', code, timeout_seconds: timeout, resource_limits: { cpu, memory_mb: memory, pids } };
    const payload = JSON.stringify(input);
    if (requestKey.current.payload !== payload) requestKey.current = { payload, key: crypto.randomUUID() };
    try {
      const execution = await sandboxApi.create(input, requestKey.current.key, token);
      setSelected(execution.execution_id); setDetail(execution);
      setExecutions(previous => [execution, ...previous.filter(item => item.execution_id !== execution.execution_id)]);
      requestKey.current = { payload: '', key: '' };
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }
  async function decide(decision: 'approved' | 'rejected') {
    if (!detail) return;
    if (decision === 'approved' && (!source || source.code_hash !== detail.code_hash || source.operation_hash !== detail.operation_hash)) {
      setError('请先使用独立审批者凭据读取并核对当前待审批代码。'); return;
    }
    setBusy(true); setError('');
    try {
      for (let attempt = 0; ; attempt++) {
        try { await sandboxApi.decide(detail, decision, approverToken.trim()); break; }
        catch (err) {
          if (!(err instanceof Error) || err.message !== 'APPROVAL_CHECKPOINT_PENDING' || attempt >= 4) throw err;
          await new Promise(resolve => window.setTimeout(resolve, 200));
        }
      }
      sourceGeneration.current++; setApproverToken(''); setVerified(false); setSource(null); await refresh();
    } catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }
  async function readSource() {
    if (!detail) return;
    const generation = ++sourceGeneration.current;
    setBusy(true); setError(''); setVerified(false); setSource(null);
    try {
      const current = await sandboxApi.source(detail.execution_id, approverToken.trim());
      if (generation !== sourceGeneration.current) return;
      if (current.code_hash !== detail.code_hash || current.operation_hash !== detail.operation_hash) throw new Error('SOURCE_HASH_MISMATCH');
      setSource(current);
    } catch (err) { if (generation === sourceGeneration.current) setError(errorText(err)); }
    finally { setBusy(false); }
  }
  async function cancel() {
    if (!detail) return;
    setBusy(true); setError('');
    try { await sandboxApi.cancel(detail.execution_id, token); await refresh(); }
    catch (err) { setError(errorText(err)); }
    finally { setBusy(false); }
  }

  const pending = detail && (detail.approval_status === 'pending' || detail.status === 'waiting_approval');
  const runner = policy?.runner_status;
  const runnerStatus = !runner ? '未知' : runner.blocked ? '已阻断（Docker或清理状态需核对）' : runner.available ? '可用' : '不可用';
  return <><LocalAuthForm />
    <div className="notice"><strong>真实 Docker 执行</strong>：P3 使用固定 Python 镜像执行经独立人工审批的代码。不会调用真实模型。Docker 不可用时拒绝执行；容器仍有隔离残余风险，请勿提交密钥或敏感文件。</div>
    {error && <div className="error-box" role="alert">{error}</div>}
    {token && <>
      <section className="panel sandbox-policy"><div className="panel-heading"><h2>服务端执行策略</h2><span className="badge">默认拒绝 · 审批后执行</span></div>
        <div className="sandbox-policy-grid"><div><span>Runner 实际可用状态</span><strong data-testid="sandbox-runner-status">{runnerStatus}</strong></div><div><span>当前 Runner 活跃执行</span><strong data-testid="sandbox-runner-active">{runner?.active_executions ?? '未知'}</strong></div><div><span>控制面配置登记</span><strong>{!policy ? '未知' : policy.configured ? '已登记' : '未登记'}</strong></div></div>
        <p className="muted">配置登记不等于 Docker 就绪。活跃数量来自当前独立 Runner，仅对应本地单 Runner 部署，不是全局并发指标；接口读取失败显示未知。阻断可能由 Docker 不可用或未确认清理引起，须核对服务端状态。</p>
        {!policy && <p>尚未读取策略，不允许提交执行请求。</p>}
        {policy && <><div className="sandbox-policy-grid"><div><span>策略版本</span><strong data-testid="sandbox-policy">{policy.policy_version}</strong></div><div><span>全局 / 当前租户并发上限</span><strong>{policy.max_concurrency} / {policy.tenant_concurrency}</strong></div><div><span>预热容器</span><strong>{policy.prewarm_enabled ? '已启用 · 单次使用后销毁' : '关闭'}</strong></div><div><span>服务端输出上限</span><strong>{policy.limits.output_bytes.toLocaleString()} 字节</strong></div></div>
          <p className="muted">固定无网络、非 root、只读根文件系统、drop all capabilities、no-new-privileges 与 seccomp。禁止宿主机挂载和 Docker Socket。请求只能降低允许的资源额度，不能修改安全策略。</p></>}
      </section>
      <section className="panel"><h2>提交 Python 执行审批</h2><p>每次提交创建真实持久化记录。新请求需要独立审批者授权；批准绑定代码哈希、资源限制与策略版本。</p>
        <form className="task-form sandbox-form" onSubmit={event => { event.preventDefault(); void create(); }}>
          <label>Python 代码<textarea aria-label="Python 代码" value={code} onChange={event => setCode(event.target.value)} minLength={1} maxLength={12000} required spellCheck={false} placeholder="输入待审查的 Python 代码；不要粘贴凭证或私密数据" /></label>
          <div className="task-controls">
            <label>CPU 核额度<select aria-label="CPU 核额度" value={cpu} onChange={event => setCpu(Number(event.target.value))}>{policy?.limits.cpu.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
            <label>内存 MiB<select aria-label="内存 MiB" value={memory} onChange={event => setMemory(Number(event.target.value))}>{[128, 256, 512].filter(value => policy && value <= policy.limits.memory_mb).map(value => <option key={value} value={value}>{value}</option>)}</select></label>
            <label>PIDs 上限<select aria-label="PIDs 上限" value={pids} onChange={event => setPids(Number(event.target.value))}>{[32, 64].filter(value => policy && value <= policy.limits.pids).map(value => <option key={value} value={value}>{value}</option>)}</select></label>
            <label>超时秒数<input aria-label="超时秒数" type="number" value={timeout} min={1} max={policy?.limits.timeout_seconds || 1} required onChange={event => setTimeoutSeconds(Number(event.target.value))} /></label>
            <button type="submit" disabled={busy || !policy}>{busy ? '处理中…' : '提交沙箱执行审批'}</button>
          </div>
        </form>
      </section>
      <div className="sandbox-columns"><section className="panel sandbox-history"><h2>当前任务与执行历史</h2><p className="muted">状态来自后端；每 2 秒刷新。</p>{executions.length === 0 && <p>尚未读取到执行记录。</p>}
        {executions.map(item => <button key={item.execution_id} disabled={busy} className={`sandbox-list-item ${selected === item.execution_id ? 'selected' : ''}`} onClick={() => { setSelected(item.execution_id); setDetail(null); }}>
          <span className="badge">{item.is_mock ? 'MOCK' : 'DOCKER'}</span><strong>{statuses[item.status] || item.status}</strong><code>{item.execution_id}</code><small>{time(item.created_at)}</small>
        </button>)}
      </section><section className="panel sandbox-detail"><h2>执行详情与审计轨迹</h2>{!detail && <p>选择执行记录查看实际状态。</p>}
        {detail && <><div className="task-summary"><span className="badge">{detail.is_mock ? 'MOCK' : '真实 Docker'}</span><strong data-testid="sandbox-status">{detail.status}</strong><span>{statuses[detail.status]}</span></div>
          <dl className="sandbox-metadata"><dt>执行 ID</dt><dd data-testid="sandbox-execution-id">{detail.execution_id}</dd><dt>任务 ID</dt><dd>{detail.task_id}</dd><dt>策略</dt><dd>{detail.policy_version}</dd><dt>代码 SHA-256</dt><dd>{detail.code_hash}</dd><dt>审批绑定哈希</dt><dd>{detail.operation_hash}</dd><dt>资源限制</dt><dd>{detail.resource_limits.cpu} CPU · {detail.resource_limits.memory_mb} MiB · {detail.resource_limits.pids} PIDs · {detail.timeout_seconds} 秒</dd><dt>审批状态</dt><dd data-testid="sandbox-approval-status">{detail.approval_status}</dd><dt>清理状态</dt><dd data-testid="sandbox-cleanup-status">{detail.cleanup_status}</dd><dt>容器 ID</dt><dd>{detail.container_id || '尚未分配'}</dd><dt>耗时 / 退出码</dt><dd>{detail.duration_ms === null ? '尚无结果' : `${detail.duration_ms} ms`} / {detail.exit_code === null ? '尚无结果' : detail.exit_code}</dd></dl>
          {pending && <div className="sandbox-approval"><h3>高风险代码执行审批</h3><p>审批者须先读取并核对绑定的代码、资源限制与策略。此授权允许容器内运行代码；不授予宿主机、网络、MCP 或 Skills 权限。无法核实代码时，请拒绝。</p>
            <label className="sandbox-approver-label">独立沙箱审批者 Token<input aria-label="独立沙箱审批者 Token" type="password" autoComplete="off" spellCheck={false} disabled={busy} value={approverToken} onChange={event => { sourceGeneration.current++; setApproverToken(event.target.value); setSource(null); setVerified(false); }} /></label>
            <p className="muted">使用项目 .env 中 AGENTFORGE_SANDBOX_APPROVER_TOKEN，仅保存在当前页面内存；操作成功、刷新、离开页面或退出管理员授权后清除。管理员 Token 不能代替独立审批。</p>
            <button disabled={busy || approverToken.trim().length < 32} onClick={() => { void readSource(); }}>读取待审批代码</button>
            {source && <><h3>受控代码复核 · {source.language}</h3><pre className="sandbox-output sandbox-source" data-testid="sandbox-source">{source.code}</pre><p className="muted">代码仅存于当前页面内存，不加入 SSE 审计轨迹。展示内容绑定上述代码与操作哈希。</p></>}
            <label className="checkbox sandbox-confirm"><input type="checkbox" checked={verified} disabled={!source} onChange={event => setVerified(event.target.checked)} />我已核对代码哈希、执行内容、限制与风险</label>
            <div className="approval-actions"><button disabled={busy || approverToken.trim().length < 32 || !verified || !source} onClick={() => { void decide('approved'); }}>批准沙箱执行</button><button disabled={busy || approverToken.trim().length < 32} onClick={() => { void decide('rejected'); }}>拒绝沙箱执行</button></div>
          </div>}
          {!terminal.has(detail.status) && <button className="sandbox-cancel" disabled={busy} onClick={() => { void cancel(); }}>取消沙箱任务</button>}
          {detail.failure_reason && <p className="error-text">服务端失败原因：{detail.failure_reason}</p>}
          {detail.status === 'output_limit' && <p className="error-text">累计输出超过服务端上限，执行已终止。以下内容仅为截断后的摘要，请核对容器清理状态。</p>}
          <h3>stdout 摘要</h3><pre className="sandbox-output" data-testid="sandbox-stdout">{summary(detail.stdout_summary)}</pre><h3>stderr 摘要</h3><pre className="sandbox-output">{summary(detail.stderr_summary)}</pre><p className="muted">仅显示服务端脱敏后的摘要，每个输出窗口最多 4 KiB。截断输出不代表完整执行日志。</p>
          <h3>实际资源采样</h3><pre className="sandbox-output" data-testid="sandbox-resource-usage">{detail.resource_usage ? JSON.stringify(detail.resource_usage, null, 2) : '尚未取得资源采样'}</pre><p className="muted">采样可能无法捕获短时峰值；限制是否生效以实际隔离测试为准。</p>
          <div className="event-list" aria-label="沙箱 SSE 审计轨迹">{events.map(event => <div key={event.id}><span>#{event.id}</span><strong>{event.kind}</strong><code>{eventMetadata(event)}</code></div>)}</div>
        </>}
      </section></div>
    </>}
  </>;
}
