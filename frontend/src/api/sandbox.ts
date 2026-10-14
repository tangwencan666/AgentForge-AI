import { taskRequest } from './tasks';

export type SandboxLimits = { cpu: number; memory_mb: number; pids: number };
export type SandboxPolicy = {
  policy_version: string; language: 'python';
  limits: { cpu: number[]; memory_mb: number; pids: number; timeout_seconds: number; output_bytes: number };
  max_concurrency: number; tenant_concurrency: number; prewarm_enabled: boolean;
  configured: boolean;
  runner_status: { available: boolean; blocked: boolean; active_executions: number | null };
};
export type SandboxExecution = {
  execution_id: string; task_id: string; language: string; code_hash: string; operation_hash: string;
  status: string; approval_reference: string | null; approval_status: string; policy_version: string;
  timeout_seconds: number; resource_limits: SandboxLimits; created_at: string;
  exit_code: number | null; stdout_summary: string | null; stderr_summary: string | null;
  duration_ms: number | null; resource_usage: Record<string, unknown> | null;
  container_id: string | null; failure_reason: string | null; cleanup_status: string; is_mock: boolean;
};
export type SandboxExecutionInput = {
  language: 'python'; code: string; timeout_seconds: number; resource_limits: SandboxLimits;
};
export type SandboxSource = { language: string; code: string; code_hash: string; operation_hash: string };

export const sandboxApi = {
  policy: (token: string, signal?: AbortSignal) => taskRequest<SandboxPolicy>('/sandbox/policy', token, { signal }),
  list: (token: string, signal?: AbortSignal) => taskRequest<SandboxExecution[]>('/sandbox/executions', token, { signal }),
  detail: (id: string, token: string, signal?: AbortSignal) => taskRequest<SandboxExecution>(`/sandbox/executions/${encodeURIComponent(id)}`, token, { signal }),
  source: (id: string, approverToken: string) => taskRequest<SandboxSource>(`/sandbox/executions/${encodeURIComponent(id)}/source`, approverToken),
  create: (input: SandboxExecutionInput, key: string, token: string) => taskRequest<SandboxExecution>('/sandbox/executions', token, {
    method: 'POST', headers: { 'Idempotency-Key': key }, body: JSON.stringify(input),
  }),
  cancel: (id: string, token: string) => taskRequest<SandboxExecution>(`/sandbox/executions/${encodeURIComponent(id)}/cancel`, token, { method: 'POST' }),
  decide: (execution: SandboxExecution, decision: 'approved' | 'rejected', approverToken: string) => taskRequest<SandboxExecution>(
    `/sandbox/executions/${encodeURIComponent(execution.execution_id)}/decision`, approverToken,
    { method: 'POST', body: JSON.stringify({ decision, operation_hash: execution.operation_hash }) },
  ),
};
