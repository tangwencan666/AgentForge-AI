import { test, expect } from '@playwright/test';
import { loadEnv } from 'vite';
import path from 'node:path';

// Credentials stay in the Node runner and browser memory; tracing is disabled.
const env = loadEnv('development', path.resolve('..'), '');
test.use({ trace: 'off' });
test.skip(process.env.AGENTFORGE_RUN_SANDBOX !== '1', 'Requires explicitly enabled, real Docker P3 integration environment.');

async function authorize(page: import('@playwright/test').Page) {
  await page.goto('/sandbox');
  await page.getByLabel('管理员 Token', { exact: true }).fill(env.AGENTFORGE_ADMIN_TOKEN);
  await page.getByRole('button', { name: '授权当前页面' }).click();
  await expect(page.getByTestId('sandbox-policy')).toBeVisible();
}

test('real Sandbox Center approves and executes Python, reports output and container cleanup', async ({ page }) => {
  test.setTimeout(90000);
  await authorize(page);
  await page.getByLabel('Python 代码', { exact: true }).fill("print('sandbox e2e')");
  await page.getByRole('button', { name: '提交沙箱执行审批' }).click();
  await expect(page.getByTestId('sandbox-status')).toHaveText('waiting_approval', { timeout: 15000 });
  await page.getByLabel('独立沙箱审批者 Token', { exact: true }).fill(env.AGENTFORGE_SANDBOX_APPROVER_TOKEN);
  await page.getByRole('button', { name: '读取待审批代码', exact: true }).click();
  await expect(page.getByTestId('sandbox-source')).toContainText("print('sandbox e2e')");
  await page.getByLabel('我已核对代码哈希、执行内容、限制与风险').check();
  await page.getByRole('button', { name: '批准沙箱执行', exact: true }).click();
  await expect(page.getByTestId('sandbox-status')).toHaveText('succeeded', { timeout: 60000 });
  await expect(page.getByTestId('sandbox-stdout')).toContainText('sandbox e2e');
  await expect(page.getByTestId('sandbox-cleanup-status')).toHaveText('removed', { timeout: 10000 });
  const storage = await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }));
  expect(storage).toEqual({ local: 0, session: 0 });
  await page.getByRole('button', { name: '退出授权' }).click();
  await expect(page.getByTestId('sandbox-status')).toHaveCount(0);
  await expect(page.getByLabel('独立沙箱审批者 Token', { exact: true })).toHaveCount(0);
});

test('real Sandbox Center rejects code execution without launching a container', async ({ page, request }) => {
  test.setTimeout(45000);
  await authorize(page);
  await page.getByLabel('Python 代码', { exact: true }).fill("print('must never execute rejected code')");
  await page.getByRole('button', { name: '提交沙箱执行审批' }).click();
  await expect(page.getByTestId('sandbox-status')).toHaveText('waiting_approval', { timeout: 15000 });
  const executionId = await page.getByTestId('sandbox-execution-id').innerText();
  await page.getByLabel('独立沙箱审批者 Token', { exact: true }).fill(env.AGENTFORGE_SANDBOX_APPROVER_TOKEN);
  await page.getByRole('button', { name: '拒绝沙箱执行', exact: true }).click();
  await expect(page.getByTestId('sandbox-approval-status')).toHaveText('rejected', { timeout: 15000 });
  const response = await request.get(`/api/v1/sandbox/executions/${executionId}`, { headers: { Authorization: `Bearer ${env.AGENTFORGE_ADMIN_TOKEN}` } });
  expect(response.ok()).toBeTruthy();
  const actual = (await response.json()).data;
  expect(actual.container_id).toBeNull();
  expect(actual.stdout_summary || '').not.toContain('must never execute rejected code');
  expect(actual.is_mock).toBe(false);
  await page.reload();
  await expect(page.getByLabel('管理员 Token', { exact: true })).toBeVisible();
});
