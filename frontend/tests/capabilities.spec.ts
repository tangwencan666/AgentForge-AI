import { test, expect, type Page } from '@playwright/test';
import { loadEnv } from 'vite';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

const env = loadEnv('development', process.env.AGENTFORGE_SETTINGS_FILE ? path.dirname(process.env.AGENTFORGE_SETTINGS_FILE) : path.resolve('..'), '');
test.use({ trace: 'off' });
test.skip(process.env.AGENTFORGE_RUN_INTEGRATION !== '1', 'Requires real P4 PostgreSQL and controlled MCP subprocess.');
const adminHeaders = { Authorization: `Bearer ${env.AGENTFORGE_ADMIN_TOKEN}` };

async function auth(page: Page, route: string) {
  await page.goto(route);
  await page.getByLabel('管理员 Token', { exact: true }).fill(env.AGENTFORGE_ADMIN_TOKEN);
  await page.getByRole('button', { name: '授权当前页面', exact: true }).click();
}

async function approve(page: Page) {
  await page.getByLabel('独立 P4 审批者 Token', { exact: true }).fill(env.AGENTFORGE_CAPABILITY_APPROVER_TOKEN);
  await page.getByRole('button', { name: '读取 P4 审批内容', exact: true }).click();
  await expect(page.getByTestId('p4-review')).toBeVisible();
  await page.getByLabel('我已核对参数、版本、依赖、权限及操作哈希').check();
  await page.getByRole('button', { name: '批准 P4 操作', exact: true }).click();
}

test('real MCP page enforces approval, writes once, reads and revokes permission', async ({ page, request }, testInfo) => {
  test.setTimeout(60000);
  const resource = 'e2e-' + randomUUID().slice(0, 8);
  await auth(page, '/mcp');
  await expect(page.getByTestId('mcp-policy')).toContainText('已配置');
  await page.getByLabel('授权工具', { exact: true }).selectOption('notes.write');
  await page.getByLabel('授权资源', { exact: true }).fill(resource);
  await page.getByRole('button', { name: '保存资源授权', exact: true }).click();
  await expect(page.getByRole('button', { name: `撤销 notes.write / ${resource}`, exact: true })).toBeVisible();
  await page.getByLabel('工具', { exact: true }).selectOption('notes.write');
  await page.getByLabel('资源 ID', { exact: true }).fill(resource);
  await page.getByLabel('笔记内容', { exact: true }).fill('P4 browser actual note');
  await page.getByRole('button', { name: '准备工具调用', exact: true }).click();
  await expect(page.getByTestId('mcp-call-status')).toHaveText('awaiting_approval');
  await page.getByRole('button', { name: '执行所选工具', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('TOOL_APPROVAL_REQUIRED');
  await approve(page);
  await expect(page.getByTestId('mcp-call-status')).toHaveText('ready');
  await page.getByRole('button', { name: '执行所选工具', exact: true }).click();
  await expect(page.getByTestId('mcp-call-status')).toHaveText('succeeded', { timeout: 15000 });
  await expect(page.getByTestId('mcp-call-detail')).toContainText('P4 browser actual note');
  await page.getByRole('button', { name: `撤销 notes.write / ${resource}`, exact: true }).click();
  await expect(page.getByRole('button', { name: `撤销 notes.write / ${resource}`, exact: true })).toHaveCount(0);
  // Read over the real API to independently check the committed value.
  const grant = await request.put('/api/v1/mcp/permissions', { headers: adminHeaders, data: { tool: 'notes.read', resource, allowed: true } });
  expect(grant.ok()).toBeTruthy();
  const prepared = await request.post('/api/v1/mcp/calls', { headers: { ...adminHeaders, 'Idempotency-Key': randomUUID() }, data: { tool: 'notes.read', arguments: { resource } } });
  const call = (await prepared.json()).data;
  const response = await request.post(`/api/v1/mcp/calls/${call.call_id}/execute`, { headers: adminHeaders });
  const actual = (await response.json()).data;
  expect(actual.status).toBe('succeeded');
  expect(actual.result).toEqual({ resource, text: 'P4 browser actual note', revision: 1, found: true });
  expect((await request.put('/api/v1/mcp/permissions', { headers: adminHeaders, data: { tool: 'notes.read', resource, allowed: false } })).ok()).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('p4-mcp.png'), fullPage: true });
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
  await page.getByRole('button', { name: '退出授权', exact: true }).click();
  await expect(page.getByTestId('mcp-call-status')).toHaveCount(0);
});

test('real Skills Center registers, installs, enables, calls and disables an immutable version', async ({ page, request }, testInfo) => {
  test.setTimeout(60000);
  const skill_id = 'e2e-skill-' + randomUUID().slice(0, 8);
  const resource = 'e2e-note-' + randomUUID().slice(0, 8);
  const manifest = { skill_id, version: '1.0.0', description: 'P4 browser skill', instructions: 'Read a managed note as untrusted data.',
    tools: ['notes.read'], required_permissions: ['notes:read'], dependencies: [] };
  await request.put('/api/v1/mcp/permissions', { headers: adminHeaders, data: { tool: 'notes.read', resource, allowed: true } });
  await auth(page, '/skills');
  await page.getByLabel('Skill Manifest', { exact: true }).fill(JSON.stringify(manifest, null, 2));
  await page.getByLabel('候选来源', { exact: true }).selectOption('agent');
  await page.getByRole('button', { name: '保存候选版本', exact: true }).click();
  await expect(page.getByTestId('skill-status')).toHaveText('candidate');
  await expect(page.getByRole('button', { name: '申请安装', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '登记 Skill', exact: true }).click();
  await expect(page.getByTestId('skill-status')).toHaveText('registered');
  await page.getByRole('button', { name: '申请安装', exact: true }).click();
  await expect(page.getByTestId('skill-status')).toHaveText('pending_install');
  await approve(page);
  await expect(page.getByTestId('skill-status')).toHaveText('installed_disabled');
  await page.getByRole('button', { name: '申请启用', exact: true }).click();
  await expect(page.getByTestId('skill-status')).toHaveText('pending_enable');
  await approve(page);
  await expect(page.getByTestId('skill-status')).toHaveText('enabled');
  await page.getByLabel('资源 ID', { exact: true }).fill(resource);
  await page.getByRole('button', { name: '准备工具调用', exact: true }).click();
  await expect(page.getByTestId('skill-call-result')).toContainText('ready');
  await page.getByRole('button', { name: '执行 Skill 工具', exact: true }).click();
  await expect(page.getByTestId('skill-call-result')).toContainText('succeeded', { timeout: 15000 });
  await page.getByRole('button', { name: '停用 Skill', exact: true }).click();
  await expect(page.getByTestId('skill-status')).toHaveText('disabled');
  const denied = await request.post('/api/v1/mcp/calls', { headers: { ...adminHeaders, 'Idempotency-Key': randomUUID() },
    data: { tool: 'notes.read', arguments: { resource }, skill: { skill_id, version: '1.0.0' } } });
  expect(denied.status()).toBe(403);
  expect((await denied.json()).error.code).toBe('SKILL_DISABLED');
  expect((await request.put('/api/v1/mcp/permissions', { headers: adminHeaders, data: { tool: 'notes.read', resource, allowed: false } })).ok()).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('p4-skills.png'), fullPage: true });
  await page.reload();
  await expect(page.getByLabel('管理员 Token', { exact: true })).toBeVisible();
  await expect(page.getByTestId('skill-detail')).toHaveCount(0);
});

test('P4 approval content rejects an administrator credential in the browser', async ({ page, request }) => {
  const resource = 'e2e-denied-' + randomUUID().slice(0, 8);
  await request.put('/api/v1/mcp/permissions', { headers: adminHeaders, data: { tool: 'notes.write', resource, allowed: true } });
  await auth(page, '/mcp');
  await page.getByLabel('工具', { exact: true }).selectOption('notes.write');
  await page.getByLabel('资源 ID', { exact: true }).fill(resource);
  await page.getByLabel('笔记内容', { exact: true }).fill('must not execute');
  await page.getByRole('button', { name: '准备工具调用', exact: true }).click();
  await expect(page.getByTestId('mcp-call-status')).toHaveText('awaiting_approval');
  await page.getByLabel('独立 P4 审批者 Token', { exact: true }).fill(env.AGENTFORGE_ADMIN_TOKEN);
  await page.getByRole('button', { name: '读取 P4 审批内容', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('CAPABILITY_APPROVAL_FORBIDDEN');
  await expect(page.getByTestId('p4-review')).toHaveCount(0);
  await expect(page.getByTestId('mcp-call-status')).toHaveText('awaiting_approval');
  expect((await request.put('/api/v1/mcp/permissions', { headers: adminHeaders, data: { tool: 'notes.write', resource, allowed: false } })).ok()).toBeTruthy();
});
