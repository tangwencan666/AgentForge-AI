import { test, expect } from '@playwright/test';
import { loadEnv } from 'vite';
import path from 'node:path';

const env = loadEnv('development', path.resolve('..'), '');
test.use({ trace: 'off' });
const headers = { Authorization: `Bearer ${env.AGENTFORGE_ADMIN_TOKEN}` };

test('P5 Model Center edits a protected slot, shows usage and blocks unpaid connectivity tests', async ({ page, request }) => {
  const before = (await (await request.get('/api/v1/model-slots', { headers })).json()).data.find((r: { role: string }) => r.role === 'planner');
  await page.goto('/models');
  await page.getByLabel('管理员 Token', { exact: true }).fill(env.AGENTFORGE_ADMIN_TOKEN);
  await page.getByRole('button', { name: '授权当前页面', exact: true }).click();
  await expect(page.getByTestId('model-policy')).toContainText('BLOCKED');
  await page.getByLabel('planner provider', { exact: true }).selectOption('mock');
  await page.getByLabel('planner model', { exact: true }).fill('mock-p5-browser');
  await page.getByLabel('planner priority', { exact: true }).fill('7');
  await page.getByRole('button', { name: '保存 planner', exact: true }).click();
  await expect.poll(async () => (await (await request.get('/api/v1/model-slots', { headers })).json()).data.find((r: { role: string }) => r.role === 'planner').priority).toBe(7);
  await page.getByRole('button', { name: '测试 planner 真实连接', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('MODEL_TEST_BUDGET_BLOCKED');
  await expect(page.getByTestId('model-metrics')).toBeVisible();
  await page.screenshot({ path: '../work/p5-models.png', fullPage: true });
  const current = (await (await request.get('/api/v1/model-slots', { headers })).json()).data.find((r: { role: string }) => r.role === 'planner');
  const { provider, base_url, model, credential_reference, temperature, max_tokens, timeout, enabled, priority } = before;
  expect((await request.put('/api/v1/model-slots/planner', { headers, data: { provider, base_url, model, credential_reference, temperature, max_tokens, timeout, enabled, priority, expected_version: current.version } })).ok()).toBeTruthy();
});

test('P5 AI Chat persists an explicitly Mock conversation and clears credentials on reload', async ({ page }) => {
  await page.goto('/chat');
  await page.getByLabel('管理员 Token', { exact: true }).fill(env.AGENTFORGE_ADMIN_TOKEN);
  await page.getByRole('button', { name: '授权当前页面', exact: true }).click();
  await page.getByLabel('消息', { exact: true }).fill('P5 browser mock conversation');
  await page.getByRole('button', { name: '发送消息', exact: true }).click();
  await expect(page.getByTestId('chat-status')).toContainText('MOCK');
  await expect(page.getByTestId('chat-status')).toContainText('succeeded', { timeout: 15000 });
  await expect(page.getByTestId('chat-answer')).toContainText('[MOCK]');
  await page.screenshot({ path: '../work/p5-chat.png', fullPage: true });
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
  await page.reload();
  await expect(page.getByLabel('管理员 Token', { exact: true })).toBeVisible();
});

test('P5 Task Center exposes real mode and bounded limits without pretending missing credentials work', async ({ page }) => {
  await page.goto('/tasks');
  await page.getByLabel('管理员 Token', { exact: true }).fill(env.AGENTFORGE_ADMIN_TOKEN);
  await page.getByRole('button', { name: '授权当前页面', exact: true }).click();
  await page.getByLabel('执行模式', { exact: true }).selectOption('real');
  await page.getByLabel('任务目标', { exact: true }).fill('P5 missing real credentials must fail');
  await page.getByLabel('最大调用次数', { exact: true }).fill('4');
  await page.getByRole('button', { name: '创建真实任务', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('REAL_CALLS_DISABLED');
});
