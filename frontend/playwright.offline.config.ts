import { defineConfig } from '@playwright/test';

// No dotenv import, real backend, server tokens or external model requests.
export default defineConfig({
  testDir: './tests', testMatch: 'deepseek-offline.spec.ts', workers: 1,
  reporter: [['list'], ['json', { outputFile: '../work/p5-live-browser-offline.json' }]],
  use: { baseURL: 'http://127.0.0.1:15274', browserName: 'chromium', channel: 'msedge', headless: true, trace: 'off' },
  webServer: { command: 'node tests/offline-server.mjs', url: 'http://127.0.0.1:15274', reuseExistingServer: false },
});
