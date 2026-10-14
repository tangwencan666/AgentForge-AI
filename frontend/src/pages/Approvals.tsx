import { useEffect, useState } from 'react';
import { LocalAuthForm, useLocalAuth } from '../components/LocalAuth';
import { taskRequest, type Approval } from '../api/tasks';
import { NavLink } from 'react-router-dom';

export default function Approvals() {
  const { token } = useLocalAuth();
  const [items, setItems] = useState<Approval[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!token) { setItems([]); return; }
    const refresh = () => { void taskRequest<Approval[]>('/approvals', token).then(setItems).catch(() => setError('无法读取审批记录')); };
    refresh(); const timer = window.setInterval(refresh, 2000); return () => window.clearInterval(timer);
  }, [token]);
  async function decide(item: Approval, decision: string) {
    try {
      await taskRequest(`/approvals/${item.approval_id}/decision`, token, { method:'POST', body:JSON.stringify({ decision, operation_hash:item.operation_hash }) });
      setItems(await taskRequest<Approval[]>('/approvals', token)); setError('');
    } catch (err) { setError(err instanceof Error ? err.message : '审批失败'); }
  }
  return <><LocalAuthForm/><div className="notice">本页仅展示 Mock 任务的计划确认。真实沙箱代码执行审批位于 <NavLink className="text-link" to="/sandbox">Sandbox Center</NavLink>，需要独立沙箱审批者凭据；MCP 和 Skills 执行尚未开放。Reviewer 意见不能授予权限。</div>{error && <p role="alert">{error}</p>}
    {token && <section className="panel"><h2>持久化审批记录</h2>{!items.length && <p>尚未读取到审批。</p>}{items.map(item => <div className="approval-row" key={item.approval_id}><span className="badge">MOCK</span><strong>{item.status}</strong><small>{item.task_id}</small>{item.status === 'pending' && <div><button onClick={() => { void decide(item,'approved'); }}>批准计划</button><button onClick={() => { void decide(item,'rejected'); }}>拒绝计划</button></div>}</div>)}</section>}</>;
}
