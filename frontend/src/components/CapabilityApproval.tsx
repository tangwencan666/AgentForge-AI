import { useEffect, useRef, useState } from 'react';
import { capabilitiesApi, type Review } from '../api/capabilities';

export default function CapabilityApproval({ id, changed }: { id: string; changed: () => Promise<void> }) {
  const [token, setToken] = useState('');
  const [review, setReview] = useState<Review | null>(null);
  const [verified, setVerified] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  useEffect(() => { generation.current++; setReview(null); setVerified(false); setToken(''); setError(''); }, [id]);

  async function read() {
    const current = generation.current;
    setBusy(true); setError('');
    try { const value = await capabilitiesApi.review(token, id); if (generation.current === current) { setReview(value); setVerified(false); } }
    catch (e) { if (generation.current === current) setError(e instanceof Error ? e.message : 'REQUEST_FAILED'); }
    finally { if (generation.current === current) setBusy(false); }
  }
  async function decide(decision: string) {
    if (!review) return;
    const current = generation.current;
    setBusy(true); setError('');
    try {
      await capabilitiesApi.decide(token, review, decision);
      if (generation.current === current) { setToken(''); setReview(null); setVerified(false); await changed(); }
    } catch (e) { if (generation.current === current) setError(e instanceof Error ? e.message : 'REQUEST_FAILED'); }
    finally { if (generation.current === current) setBusy(false); }
  }
  return <div className="p4-approval">
    <h3>独立 P4 审批</h3><p>读取并核对实际工具参数或完整 Skill 及依赖闭包，再作出决定。审批有效期为 15 分钟。</p>
    <label>独立 P4 审批者 Token<input aria-label="独立 P4 审批者 Token" type="password" autoComplete="off" disabled={busy} value={token}
      onChange={e => { generation.current++; setToken(e.target.value); setReview(null); setVerified(false); }} /></label>
    <p className="muted">使用 .env 中 AGENTFORGE_CAPABILITY_APPROVER_TOKEN。凭据仅保存在页面内存，读取成功不代表已经批准。</p>
    <button disabled={busy || token.length < 32} onClick={() => { void read(); }}>读取 P4 审批内容</button>
    {review && <><pre data-testid="p4-review">{JSON.stringify(review, null, 2)}</pre>
      <label className="checkbox"><input type="checkbox" checked={verified} onChange={e => setVerified(e.target.checked)} />我已核对参数、版本、依赖、权限及操作哈希</label>
      <div className="p4-actions"><button disabled={busy || !verified || review.status !== 'pending'} onClick={() => { void decide('approved'); }}>批准 P4 操作</button>
        <button disabled={busy || review.status !== 'pending'} onClick={() => { void decide('rejected'); }}>拒绝 P4 操作</button></div></>}
    {error && <p role="alert" className="error-text">{error}</p>}
  </div>;
}
