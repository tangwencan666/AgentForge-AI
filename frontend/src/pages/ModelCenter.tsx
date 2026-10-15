import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { LocalAuthForm, useLocalAuth } from '../components/LocalAuth';
import { taskRequest } from '../api/tasks';
import '../capabilities.css';
import '../models.css';

type Slot = { role: string; provider: string | null; base_url: string | null; model: string | null; credential_reference: string | null;
  temperature: number; max_tokens: number; timeout: number; enabled: boolean; priority: number; version: number; credential_configured: boolean; call_status: string };
const roles = ['planner', 'coder', 'researcher', 'reviewer'];
type Policy = { real_calls_enabled: boolean; daily_budget_usd: string; test_budget_usd: string; test_max_calls: number; paid_test_status: string };
type Metric = { role: string; provider: string; model: string; is_mock: boolean; requests: number; success_rate: number;
  timeout_rate: number; error_rate: number; input_tokens_reported: number; output_tokens_reported: number;
  total_tokens_reported: number; usage_unknown: number; estimated_cost_usd: string; pending_upper_bound_usd: string;
  latencies_ms: number[]; first_token_ms: number[] };
function average(values: number[]) { return values.length ? `${Math.round(values.reduce((a, b) => a + b, 0) / values.length)} ms` : '未知'; }
function SlotForm({ initial, saved }: { initial: Slot; saved: () => Promise<void> }) {
  const { token } = useLocalAuth();
  const [slot, setSlot] = useState({ ...initial, provider: initial.provider || 'mock' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [testId, setTestId] = useState('');
  async function save() {
    setBusy(true); setError('');
    const { provider, base_url, model, credential_reference, temperature, max_tokens, timeout, enabled, priority } = slot;
    try {
      await taskRequest(`/model-slots/${slot.role}`, token, { method: 'PUT', body: JSON.stringify({ provider,
        base_url: provider === 'mock' ? null : base_url || null, model, credential_reference: provider === 'mock' ? null : credential_reference || null,
        temperature, max_tokens, timeout, enabled, priority, expected_version: initial.version }) }); await saved();
    } catch (e) { setError(e instanceof Error ? e.message : 'SAVE_FAILED'); } finally { setBusy(false); }
  }
  return <section className="panel"><h2>{slot.role[0].toUpperCase() + slot.role.slice(1)}</h2>
    <p>{initial.call_status} · {initial.credential_configured ? '凭据引用已配置' : '未配置真实凭据'} · version {initial.version}</p>
    <form className="p4-form" onSubmit={e => { e.preventDefault(); void save(); }}>
      <label>provider<select aria-label={`${slot.role} provider`} value={slot.provider || 'mock'} onChange={e => setSlot({ ...slot, provider: e.target.value })}><option>mock</option><option>openai_compatible</option><option disabled>anthropic</option><option disabled>google</option><option disabled>azure_openai</option></select></label>
      <label>base_url<input aria-label={`${slot.role} base_url`} value={slot.base_url || ''} onChange={e => setSlot({ ...slot, base_url: e.target.value })} placeholder="https://approved-host/v1" /></label>
      <label>model<input aria-label={`${slot.role} model`} required value={slot.model || ''} onChange={e => setSlot({ ...slot, model: e.target.value })} /></label>
      <label>credential_reference<input aria-label={`${slot.role} credential_reference`} value={slot.credential_reference || ''} onChange={e => setSlot({ ...slot, credential_reference: e.target.value })} placeholder={`env:AGENTFORGE_MODEL_${slot.role.toUpperCase()}_KEY`} /></label>
      <p className="muted">这里只接受服务端环境变量引用。实际 Key 请在本机受保护环境中设置，无需粘贴到页面或聊天。</p>
      {(['temperature', 'max_tokens', 'timeout', 'priority'] as const).map(field => <label key={field}>{field}<input aria-label={`${slot.role} ${field}`} type="number" step={field === 'temperature' ? '.1' : '1'} value={slot[field]} onChange={e => setSlot({ ...slot, [field]: Number(e.target.value) })} /></label>)}
      <label className="checkbox"><input type="checkbox" checked={slot.enabled} onChange={e => setSlot({ ...slot, enabled: e.target.checked })} />enabled</label>
      <button disabled={busy}>保存 {slot.role}</button>
    </form><button disabled={busy} onClick={() => {
      setBusy(true); setError(''); void taskRequest<{ task_id: string }>(`/model-slots/${slot.role}/test`, token, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() } })
        .then(task => setTestId(task.task_id)).catch(e => setError(e instanceof Error ? e.message : 'TEST_FAILED')).finally(() => setBusy(false));
    }}>测试 {slot.role} 真实连接</button>
    {testId && <p>测试任务：{testId} <NavLink to="/tasks">查看执行结果</NavLink></p>}{error && <p role="alert" className="error-text">{error}</p>}
  </section>;
}
export default function ModelCenter() {
  const { token } = useLocalAuth();
  const [slots, setSlots] = useState<Slot[]>([]);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [metrics, setMetrics] = useState<{ models: Metric[] } | null>(null);
  const [error, setError] = useState('');
  async function refresh(signal?: AbortSignal) {
    const [next, p, m] = await Promise.all([taskRequest<Slot[]>('/model-slots', token, { signal }), taskRequest<Policy>('/models/policy', token, { signal }), taskRequest<{ models: Metric[] }>('/models/metrics', token, { signal })]);
    if (!signal?.aborted) { setSlots(next); setPolicy(p); setMetrics(m); }
  }
  useEffect(() => { if (!token) return; const controller = new AbortController(); void refresh(controller.signal).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'LOAD_FAILED'); }); return () => controller.abort(); }, [token]);
  return <><LocalAuthForm /><div className="notice">P5 · 四个角色独立路由。同一供应商可绑定多个模型。真实调用仅在服务端启用、凭据/价格及预算齐全时开放；失败不会回退为 Mock。</div>
    {error && <p role="alert">{error}</p>}
    {!token && <div className="model-grid">{roles.map(role => <section className="panel" key={role}><h2>{role[0].toUpperCase() + role.slice(1)}</h2><p>未读取</p></section>)}</div>}
    {token && <><section className="panel"><h2>真实 API 状态与测试额度</h2><div data-testid="model-policy">{policy ? <>
      <p>真实调用：<strong>{policy.real_calls_enabled ? '服务端已开放' : '服务端未开放'}</strong> · 收费连接测试：<strong>{policy.paid_test_status}</strong></p>
      <p>每日费用上限 ${policy.daily_budget_usd} · 当日测试额度 ${policy.test_budget_usd} · 当日测试最多 {policy.test_max_calls} 次调用</p>
      <p className="muted">状态、凭据、端点、价格及剩余额度均通过服务端检查后才能调用。未配置时可明确选择 Mock。</p>
    </> : <p>读取中…</p>}</div><button onClick={() => { void refresh().catch(() => setError('REFRESH_FAILED')); }}>刷新模型状态</button></section>
      <div className="model-grid">{slots.map(slot => <SlotForm key={slot.role + slot.version} initial={slot} saved={refresh} />)}</div>
      <section className="panel"><h2>模型 Token、延迟与费用估算</h2><p>汇总最近 2000 次尝试，Mock 与真实调用分别统计。缺失用量计为未知；费用为估算，预留金额仍待核对。</p>
        <div className="model-metrics" data-testid="model-metrics">{metrics?.models.length ? <table><caption>按角色和模型汇总调用记录</caption><thead><tr>
          <th>角色 / 模型</th><th>模式 / 请求</th><th>成功 / 超时 / 错误</th><th>输入 / 输出 / 总 Token</th><th>未知用量</th><th>估算 / 预留 USD</th><th>平均延迟 / 首 Token</th>
        </tr></thead><tbody>{metrics.models.map(row => <tr key={`${row.role}/${row.provider}/${row.model}/${row.is_mock}`}>
          <th scope="row">{row.role}<small>{row.provider} / {row.model}</small></th><td>{row.is_mock ? 'MOCK' : 'REAL'}<small>{row.requests} 次</small></td>
          <td>{(row.success_rate * 100).toFixed(1)}% / {(row.timeout_rate * 100).toFixed(1)}% / {(row.error_rate * 100).toFixed(1)}%</td>
          <td>{row.input_tokens_reported} / {row.output_tokens_reported} / {row.total_tokens_reported}</td><td>{row.usage_unknown} 次</td>
          <td>${row.estimated_cost_usd}<small>预留 ${row.pending_upper_bound_usd}</small></td><td>{average(row.latencies_ms)}<small>{average(row.first_token_ms)}</small></td>
        </tr>)}</tbody></table> : <p>{metrics ? '尚无模型调用记录。' : '读取中…'}</p>}</div>
      </section></>}
  </>;
}
