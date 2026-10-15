import { useEffect, useState } from 'react';
import { LocalAuthForm, useLocalAuth } from '../components/LocalAuth';
import { taskRequest, taskStream, type TaskRecord, type TaskEvent } from '../api/tasks';
import '../capabilities.css';

type Turn = TaskRecord & { options: { conversation_id: string; chat_role: string } };
export default function Chat() {
  const { token } = useLocalAuth();
  const [goal, setGoal] = useState('');
  const [mode, setMode] = useState('mock');
  const [role, setRole] = useState('coder');
  const [history, setHistory] = useState<Turn[]>([]);
  const [selected, setSelected] = useState<Turn | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const conversation = selected?.options.conversation_id;
  useEffect(() => { if (!token) return; const controller = new AbortController(); void taskRequest<Turn[]>('/chat/history', token, { signal: controller.signal }).then(setHistory).catch(() => { if (!controller.signal.aborted) setError('HISTORY_FAILED'); }); return () => controller.abort(); }, [token]);
  useEffect(() => {
    setEvents([]); if (!selected || !token) return;
    const controller = new AbortController(); const id = selected.task_id;
    void taskStream(id, token, controller.signal, item => setEvents(old => [...old.filter(v => v.id !== item.id), item]), () => {
      void taskRequest<Turn>(`/tasks/${id}`, token, { signal: controller.signal }).then(setSelected).catch(() => {});
    }); return () => controller.abort();
  }, [selected?.task_id, token]);
  const streamed = events.filter(e => e.kind === 'model_delta').map(e => String(e.payload.text || '')).join('');
  return <><LocalAuthForm /><div className="notice">P5 · {mode === 'mock' ? 'MOCK：明确的模拟回答，不调用外部 API。' : 'REAL：使用服务端配置的真实模型，缺配置/预算或调用失败会显示错误。'} 流式输出通过持久化 SSE 展示，会话历史保存在项目数据库。</div>
    {error && <p role="alert" className="error-text">{error}</p>}
    {token && <><section className="panel"><h2>AI Chat</h2><form className="p4-form" onSubmit={e => {
      e.preventDefault(); setBusy(true); setError('');
      void taskRequest<Turn>('/chat', token, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ goal, workflow: 'chat', execution_mode: mode,
        chat_role: role, require_approval: false, conversation_id: conversation || null }) }).then(turn => { setSelected(turn); setHistory(old => [turn, ...old]); setGoal(''); })
        .catch(e => setError(e instanceof Error ? e.message : 'CHAT_FAILED')).finally(() => setBusy(false));
    }}><label>对话模式<select aria-label="对话模式" value={mode} onChange={e => setMode(e.target.value)}><option value="mock">Mock</option><option value="real">Real</option></select></label>
      <label>对话模型角色<select aria-label="对话模型角色" value={role} onChange={e => setRole(e.target.value)}>{['planner', 'coder', 'researcher', 'reviewer'].map(r => <option key={r}>{r}</option>)}</select></label>
      <label>消息<textarea aria-label="消息" required maxLength={12000} value={goal} onChange={e => setGoal(e.target.value)} /></label>
      <button disabled={busy}>发送消息</button><button type="button" onClick={() => setSelected(null)}>新会话</button>
    </form></section><section className="panel"><h2>回答与进度</h2>{selected && <><p data-testid="chat-status">{selected.is_mock ? 'MOCK' : 'REAL'} · {selected.status}</p><pre data-testid="chat-answer">{selected.result?.summary || streamed || '等待 Worker 执行'}</pre>
      <p>{selected.error_code}</p><button onClick={() => { void taskRequest(`/tasks/${selected.task_id}/cancel`, token, { method: 'POST' }).catch(() => setError('CANCEL_FAILED')); }}>取消当前回答</button></>}
    </section><section className="panel"><h2>会话历史</h2><div className="p4-list">{history.map(turn => <button key={turn.task_id} onClick={() => { setSelected(turn); setMode(turn.is_mock ? 'mock' : 'real'); }}>{turn.is_mock ? 'MOCK' : 'REAL'} · {turn.goal} · {turn.options.conversation_id}</button>)}</div></section></>}
  </>;
}
