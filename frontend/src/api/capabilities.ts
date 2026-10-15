import { taskRequest } from './tasks';

export type ToolName = 'notes.read' | 'notes.write';
export type SkillRef = { skill_id: string; version: string };
export type Skill = SkillRef & {
  content_hash: string; status: string; source: string; generation: number; approval_id: string | null;
  manifest: { description: string; instructions: string; tools: ToolName[]; required_permissions: string[]; dependencies: (SkillRef & { content_hash: string })[] };
};
export type Call = {
  call_id: string; tool: ToolName; resource: string; status: string; operation_hash: string; approval_id: string | null;
  arguments: Record<string, unknown>; result: Record<string, unknown> | null; error_code: string | null; skill: SkillRef | null;
};
export type Approval = { approval_id: string; target_id: string; action: string; status: string; operation_hash: string; expires_at: string };
export type Review = Approval & { target: Record<string, unknown>; dependency_closure?: Record<string, unknown>[] };
export type Grant = { tool: ToolName; resource: string; allowed: boolean; generation: number };
export type Catalog = { configured: boolean; transport: string; policy_version: string; daily_call_limit: number; timeout_seconds: number;
  tools: { name: ToolName; version: string; high_risk: boolean; inputSchema: Record<string, unknown>; outputSchema: Record<string, unknown> }[] };
export type Audit = { id: string; event: string; target_id: string; details: Record<string, unknown> };

export const capabilitiesApi = {
  catalog: (token: string, signal?: AbortSignal) => taskRequest<Catalog>('/mcp/tools', token, { signal }),
  grants: (token: string, signal?: AbortSignal) => taskRequest<Grant[]>('/mcp/permissions', token, { signal }),
  grant: (token: string, body: { tool: ToolName; resource: string; allowed: boolean }) => taskRequest<Grant>('/mcp/permissions', token, { method: 'PUT', body: JSON.stringify({ tool: body.tool, resource: body.resource, allowed: body.allowed }) }),
  calls: (token: string, signal?: AbortSignal) => taskRequest<Call[]>('/mcp/calls', token, { signal }),
  prepare: (token: string, tool: ToolName, args: Record<string, unknown>, skill?: SkillRef) => taskRequest<Call>('/mcp/calls', token,
    { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ tool, arguments: args, skill: skill ? { skill_id: skill.skill_id, version: skill.version } : null }) }),
  execute: (token: string, id: string) => taskRequest<Call>(`/mcp/calls/${encodeURIComponent(id)}/execute`, token, { method: 'POST' }),
  reconcile: (token: string, id: string) => taskRequest<Call>(`/mcp/calls/${encodeURIComponent(id)}/reconcile`, token, { method: 'POST' }),
  skills: (token: string, signal?: AbortSignal) => taskRequest<Skill[]>('/skills', token, { signal }),
  candidate: (token: string, manifest: unknown, source: string) => taskRequest<Skill>('/skills/candidates', token, { method: 'POST', body: JSON.stringify({ manifest, source }) }),
  action: (token: string, skill: SkillRef, action: string) => taskRequest<Skill>(`/skills/${encodeURIComponent(skill.skill_id)}/${encodeURIComponent(skill.version)}/actions`, token,
    { method: 'POST', body: JSON.stringify({ action }) }),
  approvals: (token: string, signal?: AbortSignal) => taskRequest<Approval[]>('/capabilities/approvals', token, { signal }),
  review: (token: string, id: string, signal?: AbortSignal) => taskRequest<Review>(`/capabilities/approvals/${encodeURIComponent(id)}/review`, token, { signal }),
  decide: (token: string, approval: Approval, decision: string) => taskRequest<Approval>(`/capabilities/approvals/${encodeURIComponent(approval.approval_id)}/decision`, token,
    { method: 'POST', body: JSON.stringify({ decision, operation_hash: approval.operation_hash }) }),
  audit: (token: string, signal?: AbortSignal) => taskRequest<Audit[]>('/capabilities/audit', token, { signal }),
};
