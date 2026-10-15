export type TaskRecord = {
  task_id: string; goal: string; status: string; is_mock: boolean; version: number;
  options?: { workflow?: string; conversation_id?: string; chat_role?: string };
  tools?: { operation_id: string; tool: string; call_id: string | null; sandbox_execution_id: string | null; result: unknown }[];
  plan_hash: string | null; iterations: number; error_code: string | null;
  result: { summary: string } | null;
  usage: { input_output_tokens: number; model_attempts: number; mock_cost_usd: string; real_cost_usd: string; reserved_real_cost_usd?: string; cost_status?: string };
  calls?: { operation_id: string; role: string; state: string; latency_ms: number | null; is_mock: boolean }[];
};
export type Approval = { approval_id: string; task_id: string; operation_hash: string; status: string; is_mock: boolean; type: string };
export type TaskEvent = { id: number; kind: string; payload: Record<string, unknown>; created_at: string };

export async function taskRequest<T>(path: string, token: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { ...options, headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}`, ...options.headers } });
  const body = await response.json();
  if (!response.ok || !body.success) throw new Error(body.error?.code || 'REQUEST_FAILED');
  return body.data as T;
}

const terminal = new Set(['succeeded', 'failed', 'cancelled', 'timed_out', 'limit_exceeded', 'needs_reconciliation']);
export async function taskStream(taskId: string, token: string, signal: AbortSignal, receive: (event: TaskEvent) => void, changed: () => void) {
  let cursor = 0;
  while (!signal.aborted) {
    try {
      const response = await fetch(`/api/v1/tasks/${taskId}/events`, { signal, headers: { Authorization: `Bearer ${token}`, 'Last-Event-ID': String(cursor) } });
      if (!response.ok || !response.body) throw new Error('STREAM_FAILED');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let pending = '';
      while (!signal.aborted) {
        const { done, value } = await reader.read();
        if (done) break;
        pending += decoder.decode(value, { stream: true });
        let boundary;
        while ((boundary = pending.indexOf('\n\n')) >= 0) {
          const block = pending.slice(0, boundary); pending = pending.slice(boundary + 2);
          if (block.includes('event: completed')) { changed(); await reader.cancel(); return; }
          const line = block.split('\n').find(line => line.startsWith('data: '));
          if (line && !block.includes('event: error')) {
            const event: TaskEvent = JSON.parse(line.slice(6));
            if (event.id > cursor) { cursor = event.id; receive(event); changed(); }
          }
        }
      }
    } catch {
      if (signal.aborted) return;
    }
    const task = await taskRequest<TaskRecord>(`/tasks/${taskId}`, token, { signal }).catch(() => null);
    if (task && terminal.has(task.status)) { changed(); return; }
    await new Promise(resolve => window.setTimeout(resolve, 1000));
  }
}
