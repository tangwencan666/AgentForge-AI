import { test, expect } from '@playwright/test';

test('Dashboard reads real PostgreSQL and Redis readiness through frontend proxy', async ({ page, request }) => {
  const response = await request.get('/health/ready');
  expect(response.status()).toBe(200);
  const actual = await response.json();
  expect(actual.data.dependencies).toEqual({ postgresql: 'up', redis: 'up' });
  await page.goto('/');
  await expect(page.getByTestId('service-status')).toHaveText('服务就绪');
  await expect(page.getByTestId('postgres-status')).toHaveText('真实连通');
  await expect(page.getByTestId('redis-status')).toHaveText('真实连通');
  await page.screenshot({ path: '../work/dashboard.png', fullPage: true });
});

test('all ten pages are reachable and unimplemented pages are explicit', async ({ page }) => {
  await page.goto('/');
  const routes = [ ['AI Chat', '/chat'], ['Agent Tasks', '/tasks'], ['Model Center', '/models'],
    ['Sandbox Center', '/sandbox'], ['MCP Tools', '/mcp'], ['Skills Center', '/skills'],
    ['Approval Center', '/approvals'], ['Observability', '/observability'], ['Settings', '/settings'], ['Dashboard', '/'] ];
  for (const [name, route] of routes) {
    await page.getByRole('link', { name, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`${route === '/' ? '/$' : route + '$'}`));
    await expect(page.getByRole('heading', { name, exact: true, level: 1 })).toBeVisible();
    if (!['Dashboard', 'Settings', 'Model Center', 'Agent Tasks', 'Approval Center', 'Sandbox Center'].includes(name)) await expect(page.getByText('功能开发中', { exact: true })).toBeVisible();
  }
});

test('frontend HTTP failure is not displayed as ready (explicit UI fault test)', async ({ page }) => {
  await page.route('**/health/ready', route => route.abort());
  await page.goto('/');
  await expect(page.getByTestId('service-status')).toHaveText('无法连接');
  await expect(page.getByTestId('postgres-status')).toHaveText('未确认');
});

test('SPA deep links and model slot definitions work', async ({ page }) => {
  await page.goto('/models');
  for (const role of ['Planner', 'Coder', 'Researcher', 'Reviewer']) await expect(page.getByRole('heading', { name: role })).toBeVisible();
  await expect(page.getByText('未读取', { exact: true })).toHaveCount(4);
});
