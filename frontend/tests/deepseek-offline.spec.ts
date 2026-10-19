import { test, expect } from '@playwright/test';

test('DeepSeek thinking settings persist through the configuration UI with a fake backend', async ({ page }, testInfo) => {
  const roles = ['planner', 'coder', 'researcher', 'reviewer'];
  const slots = roles.map(role => ({ role, provider: 'deepseek', base_url: 'https://api.deepseek.com', model: 'deepseek-flash',
    credential_reference: `env:AGENTFORGE_MODEL_${role.toUpperCase()}_KEY`, enabled: false, temperature: .2,
    max_tokens: 64, timeout: 30, priority: 50, thinking_mode: 'disabled', reasoning_effort: 'high',
    version: 1, credential_configured: false, call_status: 'not_tested' }));
  let saved: Record<string, unknown> = {};
  let blockedTests = 0;
  let unexpected = 0;
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== new URL(String(testInfo.project.use.baseURL)).origin) { unexpected++; await route.abort(); return; }
    if (!url.pathname.startsWith('/api/')) { await route.continue(); return; }
    const reply = (data: unknown) => route.fulfill({ json: { success: true, data } });
    if (url.pathname === '/api/v1/model-slots') { await reply(slots); return; }
    if (url.pathname === '/api/v1/models/policy') {
      await reply({ real_calls_enabled: false, daily_budget_usd: '0', test_budget_usd: '0', test_max_calls: 1, paid_test_status: 'BLOCKED' }); return;
    }
    if (url.pathname === '/api/v1/models/metrics') { await reply({ models: [] }); return; }
    if (['/api/v1/model-slots/planner', '/api/v1/model-slots/coder'].includes(url.pathname) && route.request().method() === 'PUT') {
      const body = route.request().postDataJSON();
      saved = body;
      const index = url.pathname.endsWith('/coder') ? 1 : 0;
      Object.assign(slots[index], body, { version: slots[index].version + 1 });
      await reply(slots[index]); return;
    }
    if (url.pathname === '/api/v1/model-slots/planner/test') {
      blockedTests++;
      await route.fulfill({ status: 409, json: { success: false, error: { code: 'MODEL_TEST_BUDGET_BLOCKED' } } }); return;
    }
    unexpected++;
    await route.abort();
  });
  await page.goto('/models');
  await page.getByLabel('管理员 Token', { exact: true }).fill('OFFLINE-FAKE-ADMIN-NOT-A-REAL-CREDENTIAL');
  await page.getByRole('button', { name: '授权当前页面', exact: true }).click();
  await expect(page.getByTestId('model-policy')).toContainText('BLOCKED');
  for (const role of roles) await expect(page.getByLabel(`${role} thinking_mode`, { exact: true })).toHaveValue('disabled');
  await expect(page.getByLabel('planner reasoning_effort', { exact: true })).toBeDisabled();
  await page.getByLabel('planner thinking_mode', { exact: true }).selectOption('enabled');
  await page.getByLabel('planner reasoning_effort', { exact: true }).selectOption('low');
  await page.getByRole('button', { name: '保存 planner', exact: true }).click();
  await expect.poll(() => saved?.thinking_mode).toBe('enabled');
  await expect(page.getByLabel('planner reasoning_effort', { exact: true })).toHaveValue('low');
  await expect(page.getByText('思考模式下不发送 temperature；不展示或保存思考正文。模式和强度只在保存后生效。').first()).toBeVisible();
  expect(saved?.credential_reference).toBe('env:AGENTFORGE_MODEL_PLANNER_KEY');
  await page.getByRole('button', { name: '测试 planner 真实连接', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('MODEL_TEST_BUDGET_BLOCKED');
  expect(blockedTests).toBe(1);
  await page.screenshot({ path: testInfo.outputPath('p5-live-deepseek-offline.png'), fullPage: true });
  await page.getByLabel('planner provider', { exact: true }).selectOption('mock');
  await page.getByRole('button', { name: '保存 planner', exact: true }).click();
  await expect.poll(() => saved?.provider).toBe('mock');
  expect(saved?.thinking_mode).toBe('disabled');
  expect(saved?.reasoning_effort).toBe('high');
  expect(saved?.credential_reference).toBeNull();
  expect(saved?.base_url).toBeNull();
  await page.getByLabel('coder provider', { exact: true }).selectOption('openai_compatible');
  await expect(page.getByLabel('coder thinking_mode', { exact: true })).toHaveValue('disabled');
  await page.getByRole('button', { name: '保存 coder', exact: true }).click();
  await expect.poll(() => saved?.provider).toBe('openai_compatible');
  expect(saved?.credential_reference).toBe('env:AGENTFORGE_MODEL_CODER_KEY');
  expect(saved?.thinking_mode).toBe('disabled');
  expect(saved?.enabled).toBe(false);
  expect(unexpected).toBe(0);
});
