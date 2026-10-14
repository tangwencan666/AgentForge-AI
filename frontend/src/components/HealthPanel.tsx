import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchReadiness, type ReadyResponse } from '../api/health';

export default function HealthPanel() {
  const [result, setResult] = useState<ReadyResponse | null>(null);
  const [pending, setPending] = useState(true);
  const [failed, setFailed] = useState(false);
  const [checkedAt, setCheckedAt] = useState<string>('');
  const controller = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setPending(true);
    setFailed(false);
    setResult(null);
    const timeout = window.setTimeout(() => current.abort(), 8000);
    try {
      const response = await fetchReadiness(current.signal);
      if (controller.current === current) {
        setResult(response);
        setCheckedAt(new Date().toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai' }));
      }
    } catch {
      if (controller.current === current) setFailed(true);
    } finally {
      window.clearTimeout(timeout);
      if (controller.current === current) setPending(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => { void refresh(); }, 15000);
    return () => { window.clearInterval(interval); controller.current?.abort(); controller.current = null; };
  }, [refresh]);
  const ready = result?.data.status === 'ready';
  const label = pending ? '检查中' : failed ? '无法连接' : ready ? '服务就绪' : '服务未就绪';
  const dependencyLabel = (value?: string) => value === 'up' ? '真实连通' : value === 'down' ? '连接失败' : value === 'migration_required' ? '需要迁移' : '未确认';
  return <section className="panel" aria-labelledby="health-title">
    <div className="panel-heading"><div><span className="eyebrow">LIVE SERVICE CHECK</span><h2 id="health-title">开发环境状态</h2></div>
      <button onClick={() => { void refresh(); }} disabled={pending}>刷新状态 ↻</button></div>
    <div className="health-grid">
      <div className="health-item"><span>Backend API</span><strong data-testid="service-status" className={ready ? 'status-good' : 'status-neutral'}>{label}</strong><small>GET /health/ready</small></div>
      <div className="health-item"><span>PostgreSQL</span><strong data-testid="postgres-status">{dependencyLabel(result?.data.dependencies.postgresql)}</strong><small>连接与迁移检查</small></div>
      <div className="health-item"><span>Redis</span><strong data-testid="redis-status">{dependencyLabel(result?.data.dependencies.redis)}</strong><small>真实 PING 检查</small></div>
    </div>
    <div className="panel-foot">{result ? <>检查时间 {checkedAt} · Asia/Shanghai <span className="request-id">请求 ID {result.request_id}</span></> : '状态来自真实后端接口；当前没有已确认的服务数据。'}</div>
  </section>;
}
