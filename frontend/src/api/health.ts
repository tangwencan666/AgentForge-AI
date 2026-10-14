export type DependencyStatus = 'up' | 'down' | 'migration_required';
export type ReadyResponse = {
  success: boolean;
  data: { status: 'ready' | 'not_ready'; dependencies: { postgresql: DependencyStatus; redis: DependencyStatus } };
  error: { code: string; message: string } | null;
  request_id: string;
};

export async function fetchReadiness(signal: AbortSignal): Promise<ReadyResponse> {
  const response = await fetch('/health/ready', { signal, cache: 'no-store' });
  if (response.status !== 200 && response.status !== 503) throw new Error('Unexpected service response');
  const body: ReadyResponse = await response.json();
  const statuses = new Set(['up', 'down', 'migration_required']);
  if (!body.data || !['ready', 'not_ready'].includes(body.data.status) ||
      !statuses.has(body.data.dependencies?.postgresql) || !statuses.has(body.data.dependencies?.redis) ||
      typeof body.request_id !== 'string') throw new Error('Invalid health response');
  return body;
}
