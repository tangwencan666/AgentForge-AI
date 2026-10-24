import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { browserEnvironment } from './environment';
import type { TaskRecord } from '../../src/api/tasks';

type Call = NonNullable<TaskRecord['calls']>[number] & {
  provider: string; started_at: string; finished_at: string | null;
};
type StoredTask = Omit<TaskRecord, 'calls'> & { calls: Call[] };
const environment = browserEnvironment();
const evidence = path.resolve('..', 'work/browser-ci');

async function api<T>(request: APIRequestContext, route: string): Promise<T> {
  const response = await request.get('/api/v1' + route, {
    headers: { Authorization: 'Bearer ' + environment.adminToken },
  });
  expect(response.status()).toBe(200);
  return (await response.json()).data as T;
}

async function authorize(page: Page) {
  const field = page.getByLabel('管理员 Token', { exact: true });
  await expect(field).toHaveAttribute('type', 'password');
  await expect(field).toHaveCSS('color', 'rgba(0, 0, 0, 0)');
  await field.fill(environment.adminToken);
  await page.getByRole('button', { name: '授权当前页面', exact: true }).click();
  await expect(field).toHaveCount(0);
}

function signature(task: StoredTask) {
  return task.calls.map(({ operation_id, role, state, started_at, finished_at }) =>
    ({ operation_id, role, state, started_at, finished_at })).sort((a, b) => a.operation_id.localeCompare(b.operation_id));
}

test('four browser scenarios against the real isolated Mock stack', async ({ page, request }, testInfo) => {
  const scenarios: Record<string, { status: string; [key: string]: unknown }> = {};
  const report = { conclusion: 'FAIL', automated: true, scenarios };
  const writes: string[] = [];
  const streams: string[] = [];
  page.on('request', outgoing => {
    const url = new URL(outgoing.url());
    if (outgoing.method() === 'POST' && url.pathname.startsWith('/api/v1/')) writes.push(url.pathname);
  });
  page.on('response', response => {
    if (response.status() === 200 && new URL(response.url()).pathname.endsWith('/events')) streams.push(response.url());
  });
  const persist = () => fs.writeFileSync(path.join(evidence, 'browser-results.json'), JSON.stringify(report, null, 2));
  const capture = async (name: string) => {
    const filename = path.join(evidence, 'screenshots', name + '.png');
    fs.mkdirSync(path.dirname(filename), { recursive: true });
    await page.screenshot({ path: filename, mask: [page.getByLabel('管理员 Token', { exact: true })], maskColor: '#111827' });
    await testInfo.attach(name, { path: filename, contentType: 'image/png' });
  };
  let taskId = '';
  let completed: StoredTask;
  const goal = 'Browser CI approved ' + randomUUID();
  try {
    // Cosmetic privacy mask only. It neither changes authentication nor
    // intercepts fetch, tasks, approvals, results, SSE, or any other interface.
    await page.addInitScript(() => {
      document.addEventListener('DOMContentLoaded', () => {
        const style = document.createElement('style');
        style.textContent = 'input[aria-label="管理员 Token"] { color:transparent!important; caret-color:transparent!important; background:#111827!important; text-shadow:none!important; }';
        document.head.appendChild(style);
      });
    });
    await test.step('1. Create Mock task through the page and wait for approval', async () => {
      await page.goto('/tasks');
      await authorize(page);
      await expect(page.getByLabel('执行模式', { exact: true })).toHaveValue('mock');
      await page.getByLabel('任务目标', { exact: true }).fill(goal);
      const created = page.waitForResponse(response => response.request().method() === 'POST'
        && new URL(response.url()).pathname === '/api/v1/tasks');
      await page.getByRole('button', { name: '创建 Mock 任务', exact: true }).click();
      const response = await created;
      expect(response.status()).toBe(202);
      taskId = (await response.json()).data.task_id as string;
      await expect(page.getByTestId('task-status')).toHaveText('waiting_approval');
      await expect(page.getByRole('button', { name: '批准计划', exact: true })).toBeVisible();
      const waiting = await api<StoredTask>(request, '/tasks/' + taskId);
      expect(waiting.is_mock).toBe(true);
      expect(waiting.calls.map(call => [call.role, call.state])).toEqual([['planner', 'completed']]);
      await page.getByTestId('task-status').scrollIntoViewIfNeeded();
      await capture('01-waiting-approval');
      scenarios.create_and_wait = { status: 'PASS', task_id: taskId, http_status: 202, roles: ['planner'] };
      persist();
    });

    await test.step('2. Approve through the page and render the persisted Mock result', async () => {
      await page.getByRole('button', { name: '批准计划', exact: true }).click();
      await expect(page.getByTestId('task-status')).toHaveText('succeeded');
      await expect(page.getByTestId('task-result')).toContainText('[MOCK]');
      await expect(page.getByText('node_completed', { exact: true }).first()).toBeVisible();
      completed = await api<StoredTask>(request, '/tasks/' + taskId);
      expect(completed.calls).toHaveLength(4);
      expect(completed.calls.map(call => call.role).sort()).toEqual(['coder', 'planner', 'researcher', 'reviewer']);
      expect(completed.calls.every(call => call.state === 'completed' && call.is_mock && call.provider === 'mock')).toBe(true);
      expect(Number(completed.usage.real_cost_usd)).toBe(0);
      expect(completed.tools).toEqual([]);
      const ledger = page.locator('pre').filter({ hasText: '"operation_id"' });
      for (const role of ['planner', 'coder', 'researcher', 'reviewer']) await expect(ledger).toContainText(`"role": "${role}"`);
      expect(streams.some(url => url.endsWith('/tasks/' + taskId + '/events'))).toBe(true);
      await page.getByTestId('task-result').scrollIntoViewIfNeeded();
      await capture('02-succeeded-mock-result');
      scenarios.approve_and_succeed = { status: 'PASS', task_id: taskId, roles: completed.calls.map(call => call.role),
        result: completed.result?.summary, real_cost_usd: '0', real_sse_observed: true };
      persist();
    });

    await test.step('3. Reload, reauthorize and inspect the same task without replaying work', async () => {
      const idsBefore = (await api<StoredTask[]>(request, '/tasks')).map(task => task.task_id).sort();
      const writesBefore = writes.length;
      await page.reload();
      await expect(page.getByLabel('管理员 Token', { exact: true })).toBeVisible();
      await expect(page.getByTestId('task-status')).toHaveCount(0);
      expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
      await authorize(page);
      await page.locator('.task-list-item').filter({ hasText: goal }).click();
      await expect(page.getByTestId('task-status')).toHaveText('succeeded');
      await expect(page.getByTestId('task-result')).toHaveText(completed.result!.summary);
      await expect(page.getByText('node_completed', { exact: true }).first()).toBeVisible();
      const restored = await api<StoredTask>(request, '/tasks/' + taskId);
      expect(restored.task_id).toBe(completed.task_id);
      expect(signature(restored)).toEqual(signature(completed));
      expect(restored.result).toEqual(completed.result);
      expect((await api<StoredTask[]>(request, '/tasks')).map(task => task.task_id).sort()).toEqual(idsBefore);
      expect(writes.length).toBe(writesBefore);
      await page.getByTestId('task-result').scrollIntoViewIfNeeded();
      await capture('03-restored-same-result');
      scenarios.reload_and_reauthorize = { status: 'PASS', task_id: taskId, same_result: true,
        same_operation_ids_and_timestamps: true, extra_write_requests: 0, extra_tasks: 0 };
      persist();
    });

    await test.step('4. Cancel another waiting task through the page and observe no later roles', async () => {
      await page.getByLabel('任务目标', { exact: true }).fill('Browser CI cancelled ' + randomUUID());
      const created = page.waitForResponse(response => response.request().method() === 'POST'
        && new URL(response.url()).pathname === '/api/v1/tasks');
      await page.getByRole('button', { name: '创建 Mock 任务', exact: true }).click();
      const response = await created;
      expect(response.status()).toBe(202);
      const cancelledId = (await response.json()).data.task_id as string;
      await expect(page.getByTestId('task-status')).toHaveText('waiting_approval');
      await page.getByRole('button', { name: '取消任务', exact: true }).click();
      await expect(page.getByTestId('task-status')).toHaveText('cancelled');
      for (let cycle = 0; cycle < 8; cycle++) {
        const cancelled = await api<StoredTask>(request, '/tasks/' + cancelledId);
        expect(cancelled.status).toBe('cancelled');
        expect(cancelled.calls.map(call => call.role)).toEqual(['planner']);
        await new Promise(resolve => setTimeout(resolve, 250));
      }
      await page.getByTestId('task-status').scrollIntoViewIfNeeded();
      await capture('04-cancelled-no-later-roles');
      scenarios.cancel_waiting = { status: 'PASS', task_id: cancelledId, roles: ['planner'], observed_seconds: 2 };
      persist();
    });
    report.conclusion = 'PASS';
  } finally {
    persist();
    const video = page.video();
    await page.close();
    if (video) await video.saveAs(path.join(evidence, 'mock-workflow.webm'));
  }
});
