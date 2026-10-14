import { test, expect } from '@playwright/test';
import { loadEnv } from 'vite';
import path from 'node:path';

// Test runner only; no credentials are included in the frontend bundle or test output.
const env = loadEnv('development', path.resolve('..'), '');

test('real browser creates a clearly marked Mock task, approves plan and receives SSE result', async ({ page }) => {
  await page.goto('/tasks');
  await page.getByLabel('管理员 Token', { exact:true }).fill(env.AGENTFORGE_ADMIN_TOKEN);
  await page.getByRole('button', { name:'授权当前页面' }).click();
  await page.getByLabel('任务目标', { exact:true }).fill(`P2 browser workflow ${Date.now()}`);
  await page.getByRole('button', { name:'创建 Mock 任务' }).click();
  await expect(page.getByTestId('task-status')).toHaveText('waiting_approval', { timeout:15000 });
  await page.getByRole('button', { name:'批准计划', exact:true }).click();
  await expect(page.getByTestId('task-status')).toHaveText('succeeded', { timeout:15000 });
  await expect(page.getByTestId('task-result')).toContainText('[MOCK]');
  await expect(page.getByText('node_completed', { exact:true }).first()).toBeVisible();
  await page.screenshot({ path:'../work/p2-workflow.png', fullPage:true });
  const storage = await page.evaluate(() => ({ local:localStorage.length, session:sessionStorage.length }));
  expect(storage).toEqual({ local:0, session:0 });
  await page.getByRole('button', { name:'退出授权' }).click();
  await expect(page.getByLabel('管理员 Token', { exact:true })).toBeVisible();
  await expect(page.getByTestId('task-status')).toHaveCount(0);
});

test('approval page reads persisted records and login is cleared by reload', async ({ page }) => {
  await page.goto('/approvals');
  await page.getByLabel('管理员 Token', { exact:true }).fill(env.AGENTFORGE_ADMIN_TOKEN);
  await page.getByRole('button', { name:'授权当前页面' }).click();
  await expect(page.getByText('approved', { exact:true }).first()).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('管理员 Token', { exact:true })).toBeVisible();
});
