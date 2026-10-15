import { useEffect, useState } from 'react';
import { capabilitiesApi, type Audit, type Call, type Catalog, type Grant, type ToolName } from '../api/capabilities';
import { LocalAuthForm, useLocalAuth } from '../components/LocalAuth';
import CapabilityApproval from '../components/CapabilityApproval';
import ToolComposer from '../components/ToolComposer';
import '../capabilities.css';

export default function McpTools() {
  const { token } = useLocalAuth();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [calls, setCalls] = useState<Call[]>([]);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [selected, setSelected] = useState('');
  const [resource, setResource] = useState('project-notes');
  const [tool, setTool] = useState<ToolName>('notes.read');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const current = calls.find(row => row.call_id === selected);

  async function refresh(signal?: AbortSignal) {
    const [nextCatalog, nextGrants, nextCalls, nextAudit] = await Promise.all([
      capabilitiesApi.catalog(token, signal), capabilitiesApi.grants(token, signal), capabilitiesApi.calls(token, signal), capabilitiesApi.audit(token, signal),
    ]);
    if (!signal?.aborted) { setCatalog(nextCatalog); setGrants(nextGrants); setCalls(nextCalls); setAudit(nextAudit); }
  }
  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    void refresh(controller.signal).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'REQUEST_FAILED'); });
    return () => controller.abort();
  }, [token]);
  async function perform(action: () => Promise<unknown>) {
    setBusy(true); setError('');
    try { await action(); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : 'REQUEST_FAILED'); }
    finally { setBusy(false); }
  }
  return <><div className="notice">P4 · 真实受控 MCP 工具。所有调用经服务端白名单、租户资源权限、严格 Schema、额度、审计与必要的独立审批。</div>
    <LocalAuthForm />{error && <p role="alert" className="error-text">{error}</p>}
    {token && <><section className="panel"><div className="panel-heading"><h2>服务端工具目录</h2><button disabled={busy} onClick={() => { void perform(async () => {}); }}>刷新 MCP 状态</button></div>
      {catalog && <><p data-testid="mcp-policy">{catalog.policy_version} · {catalog.transport} · {catalog.configured ? '已配置' : '未配置'} · 每日 {catalog.daily_call_limit} 次 · 超时 {catalog.timeout_seconds} 秒</p>
        {catalog.tools.map(item => <details key={item.name}><summary>{item.name} @ {item.version} · {item.high_risk ? '高风险 / 独立审批' : '读取'}</summary><pre>{JSON.stringify({ input: item.inputSchema, output: item.outputSchema }, null, 2)}</pre></details>)}</>}
    </section><div className="p4-columns"><section className="panel"><h2>资源授权</h2><p>本地管理员为精确工具和资源配置权限。撤权后，已准备和已批准但未执行的调用也会被拒绝。</p>
      <form className="p4-form" onSubmit={e => { e.preventDefault(); void perform(() => capabilitiesApi.grant(token, { tool, resource, allowed: true })); }}>
        <label>授权工具<select aria-label="授权工具" value={tool} onChange={e => setTool(e.target.value as ToolName)}><option>notes.read</option><option>notes.write</option></select></label>
        <label>授权资源<input aria-label="授权资源" value={resource} pattern="[a-z][a-z0-9-]{0,47}" maxLength={48} required onChange={e => setResource(e.target.value)} /></label><button disabled={busy}>保存资源授权</button>
      </form><ul className="p4-list">{grants.map(g => <li key={g.tool + g.resource}>{g.tool} · {g.resource} · {g.allowed ? '允许' : '已撤销'} · v{g.generation}
        {g.allowed && <button disabled={busy} onClick={() => { void perform(() => capabilitiesApi.grant(token, { ...g, allowed: false })); }}>撤销 {g.tool} / {g.resource}</button>}</li>)}</ul>
    </section><section className="panel"><h2>调用工具</h2><ToolComposer token={token} created={async call => { setSelected(call.call_id); await refresh(); }} /></section></div>
    <section className="panel"><h2>持久化调用记录</h2><p className="muted">选择记录查看参数、审批及真实结果。超时或连接中断后仅核对数据库回执，不自动重放。</p>
      <div className="p4-columns"><div className="p4-list">{calls.map(call => <button key={call.call_id} onClick={() => setSelected(call.call_id)}>{call.tool} · {call.resource} · {call.status}<small>{call.call_id}</small></button>)}</div>
        {current && <div><strong data-testid="mcp-call-status">{current.status}</strong><pre data-testid="mcp-call-detail">{JSON.stringify(current, null, 2)}</pre>
          <div className="p4-actions"><button disabled={busy || !['ready', 'awaiting_approval'].includes(current.status)} onClick={() => { void perform(() => capabilitiesApi.execute(token, current.call_id)); }}>执行所选工具</button>
            {['dispatched', 'needs_reconciliation'].includes(current.status) && <button disabled={busy} onClick={() => { void perform(() => capabilitiesApi.reconcile(token, current.call_id)); }}>核对受控服务回执</button>}</div>
          {current.approval_id && current.status === 'awaiting_approval' && <CapabilityApproval key={current.approval_id} id={current.approval_id} changed={refresh} />}
        </div>}</div>
    </section><section className="panel"><h2>P4 审计</h2><div className="p4-audit">{audit.map(item => <div key={item.id}><strong>{item.event}</strong><code>{item.target_id}</code><span>{JSON.stringify(item.details)}</span></div>)}</div></section></>}
  </>;
}
