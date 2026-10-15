import { useCallback, useEffect, useRef, useState } from 'react';
import { LocalAuthForm, useLocalAuth } from '../components/LocalAuth';
import { taskRequest, taskStream, type TaskRecord, type TaskEvent, type Approval } from '../api/tasks';

export default function Tasks() {
  const { token } = useLocalAuth();
  const [mode, setMode] = useState('mock');
  const [budget, setBudget] = useState('1');
  const [maxTokens, setMaxTokens] = useState(100000);
  const [maxCalls, setMaxCalls] = useState(32);
  const [timeoutSeconds, setTimeoutSeconds] = useState(900);
  const [goal, setGoal] = useState('');
  const [approval, setApproval] = useState(true);
  const [dependency, setDependency] = useState('independent');
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [selected, setSelected] = useState('');
  const [detail, setDetail] = useState<TaskRecord | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const requestKey = useRef({ payload: '', key: '' });
  const refresh = useCallback(async () => {
    if (!token) return;
    try {
      setTasks(await taskRequest<TaskRecord[]>('/tasks', token));
      setApprovals(await taskRequest<Approval[]>('/approvals', token));
      if (selected) setDetail(await taskRequest<TaskRecord>(`/tasks/${selected}`, token));
    } catch (err) { setError(err instanceof Error ? err.message : 'REQUEST_FAILED'); }
  }, [token, selected]);
  useEffect(() => {
    if (!token) { setTasks([]); setDetail(null); setEvents([]); return; }
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 2000);
    return () => window.clearInterval(timer);
  }, [refresh, token]);
  useEffect(() => {
    setEvents([]); setDetail(null);
    if (!token || !selected) return;
    const controller = new AbortController();
    void taskStream(selected, token, controller.signal, event => setEvents(previous => [...previous.filter(item => item.id !== event.id), event].slice(-200)), () => { void refresh(); });
    return () => controller.abort();
  }, [selected, token, refresh]);
  async function create() {
    setBusy(true); setError('');
    const payload = JSON.stringify({ goal, execution_mode: mode, max_budget_usd: budget, max_tokens: maxTokens, max_calls: maxCalls, timeout_seconds: timeoutSeconds, require_approval: approval, worker_dependency: dependency });
    if (requestKey.current.payload !== payload) requestKey.current = { payload, key: crypto.randomUUID() };
    try {
      const task = await taskRequest<TaskRecord>('/tasks', token, { method: 'POST', headers: { 'Idempotency-Key': requestKey.current.key }, body: payload });
      setSelected(task.task_id); requestKey.current = { payload: '', key: '' }; await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : 'REQUEST_FAILED'); }
    finally { setBusy(false); }
  }
  async function decide(item: Approval, decision: string) {
    try {
      for (let attempt = 0; ; attempt++) {
        try {
          await taskRequest(`/approvals/${item.approval_id}/decision`, token, { method: 'POST', body: JSON.stringify({ decision, operation_hash: item.operation_hash }) });
          break;
        } catch (err) {
          if (!(err instanceof Error) || err.message !== 'APPROVAL_CHECKPOINT_PENDING' || attempt >= 4) throw err;
          await new Promise(resolve => window.setTimeout(resolve, 200));
        }
      }
      await refresh(); setError('');
    } catch (err) { setError(err instanceof Error ? err.message : 'REQUEST_FAILED'); }
  }
  const actualPlan = events.filter(e => e.kind === 'plan').slice(-1)[0]?.payload.plan as { nodes: { id: string; depends_on: string[] }[] } | undefined;
  const pending = approvals.find(item => item.task_id === selected && item.status === 'pending');
  return <><LocalAuthForm/><div className="notice"><strong>{mode.toUpperCase()} 模式</strong>：Mock 为明确模拟；Real 使用服务端四槽位及预算。工具提案须经 Gateway 和独立审批，Reviewer 不能授予权限。</div>
    {error && <div className="error-box" role="alert">请求未完成：{error}</div>}
    {token && <section className="panel"><h2>创建协作任务</h2><form className="task-form" onSubmit={event => { event.preventDefault(); void create(); }}>
      <label>执行模式<select aria-label="执行模式" value={mode} onChange={e => setMode(e.target.value)}><option value="mock">Mock</option><option value="real">Real</option></select></label>
      <label>最大费用估算 USD<input aria-label="最大费用估算 USD" type="number" min="0.00000001" max="1" step="0.00000001" value={budget} onChange={e => setBudget(e.target.value)} /></label>
      <label>最大调用次数<input aria-label="最大调用次数" type="number" min={1} max={32} value={maxCalls} onChange={e => setMaxCalls(Number(e.target.value))} /></label>
      <label>最大 Token<input aria-label="最大 Token" type="number" min={1} max={100000} value={maxTokens} onChange={e => setMaxTokens(Number(e.target.value))} /></label>
      <label>最大执行秒数<input aria-label="最大执行秒数" type="number" min={1} max={900} value={timeoutSeconds} onChange={e => setTimeoutSeconds(Number(e.target.value))} /></label>
      <label>任务目标<textarea aria-label="任务目标" value={goal} onChange={event => setGoal(event.target.value)} minLength={1} maxLength={12000} required placeholder="输入需要规划的任务；不要粘贴密钥或敏感文件"/></label>
      <div className="task-controls"><label>Worker 依赖<select aria-label="Worker 依赖" value={dependency} onChange={event => setDependency(event.target.value)}><option value="independent">无依赖并发</option><option value="research_first">先 Researcher 后 Coder</option><option value="code_first">先 Coder 后 Researcher</option></select></label>
        <label className="checkbox"><input type="checkbox" checked={approval} onChange={event => setApproval(event.target.checked)}/>计划需要人工确认</label><button type="submit" disabled={busy}>{busy ? '提交中…' : mode === 'mock' ? '创建 Mock 任务' : '创建真实任务'}</button></div>
    </form></section>}
    {token && <div className="task-columns"><section className="panel"><h2>持久化任务</h2>{tasks.length === 0 && <p>尚未读取到任务。</p>}{tasks.map(task => <button className={`task-list-item ${selected === task.task_id ? 'selected' : ''}`} key={task.task_id} onClick={() => setSelected(task.task_id)}><span className="badge">{task.is_mock ? 'MOCK' : 'REAL'}</span><strong>{task.goal.slice(0, 80)}</strong><small>{task.status}</small></button>)}</section>
    <section className="panel"><h2>执行轨迹</h2>{!detail && <p>选择任务查看服务端状态。</p>}{detail && <><div className="task-summary"><span className="badge">{detail.is_mock ? 'MOCK' : 'REAL'}</span><strong data-testid="task-status">{detail.status}</strong><span>轮次 {detail.iterations}</span></div>
      <p>{detail.is_mock ? '模拟 Token' : '已报告 Token'} {detail.usage.input_output_tokens} · Mock ${detail.usage.mock_cost_usd} · 真实费用估算 ${detail.usage.real_cost_usd} · 未决预留 ${detail.usage.reserved_real_cost_usd || '0'} · {detail.usage.cost_status}</p>
      {pending && <div className="notice">计划等待确认。此批准只针对计划，不授予工具权限。<div className="approval-actions"><button onClick={() => { void decide(pending, 'approved'); }}>批准计划</button><button onClick={() => { void decide(pending, 'rejected'); }}>拒绝计划</button></div></div>}
      {!['succeeded','failed','cancelled','timed_out','limit_exceeded','needs_reconciliation'].includes(detail.status) && <button onClick={() => { void taskRequest(`/tasks/${selected}/cancel`, token, { method:'POST' }).then(refresh).catch(() => setError('CANCEL_FAILED')); }}>取消任务</button>}
      {!['succeeded','failed','cancelled','timed_out','limit_exceeded','needs_reconciliation'].includes(detail.status) && <div className="approval-actions"><button onClick={() => { void taskRequest(`/tasks/${selected}/${detail.status === 'paused' ? 'resume' : 'pause'}`, token, { method: 'POST' }).then(refresh).catch(() => setError('PAUSE_FAILED')); }}>{detail.status === 'paused' ? '恢复任务' : '暂停任务'}</button></div>}
      <h3>任务依赖图</h3><div data-testid="task-dag">{actualPlan ? `用户任务 → Planner → ${actualPlan.nodes.find(n => n.id === 'coder')?.depends_on.length ? 'Researcher → Coder' : actualPlan.nodes.find(n => n.id === 'researcher')?.depends_on.length ? 'Coder → Researcher' : 'Coder ∥ Researcher'} → 工具审批/执行 → Reviewer → 结果` : '尚无结构化规划，等待 Planner'}</div>
      <pre>{JSON.stringify(events.filter(e => e.kind === 'plan').slice(-1)[0]?.payload || {}, null, 2)}</pre>
      <h3>工具调用记录</h3><pre data-testid="agent-tools">{JSON.stringify(detail.tools || [], null, 2)}</pre>
      <p><a href="/mcp">MCP 独立审批</a> · <a href="/sandbox">沙箱独立代码复核与审批</a></p>
      <h3>模型调用</h3><pre>{JSON.stringify(detail.calls || [], null, 2)}</pre>
      {detail.result && <p data-testid="task-result">{detail.result.summary}</p>}{detail.error_code && <p className="error-text">{detail.error_code}</p>}
      <div className="event-list">{events.map(item => <div key={item.id}><span>#{item.id}</span><strong>{item.kind}</strong><code>{JSON.stringify(item.payload)}</code></div>)}</div>
    </>}</section></div>}</>;
}
