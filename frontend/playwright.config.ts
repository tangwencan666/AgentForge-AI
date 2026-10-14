import { defineConfig } from '@playwright/test';
import { loadEnv } from 'vite';
import path from 'node:path';
const env = loadEnv('development', path.resolve('..'), '');
export default defineConfig({
  testDir: './tests', workers: 1, reporter: [['list'], ['json', { outputFile: '../work/p1-e2e.json' }]],
  use: { baseURL: `http://127.0.0.1:${env.FRONTEND_PORT || 15173}`, browserName: 'chromium',
    channel: 'msedge', headless: true, trace: 'off' },
});
