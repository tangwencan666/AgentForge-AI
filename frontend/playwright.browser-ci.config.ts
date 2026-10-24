import { defineConfig } from '@playwright/test';
import path from 'node:path';
import { browserEnvironment } from './tests/browser-ci/environment';

const environment = browserEnvironment();
const evidence = path.resolve('..', 'work/browser-ci');

export default defineConfig({
  testDir: './tests/browser-ci', testMatch: 'workflow.spec.ts',
  workers: 1, retries: 0, forbidOnly: true, timeout: 180000,
  expect: { timeout: 30000 },
  outputDir: path.join(evidence, 'playwright'),
  reporter: [['list'], ['junit', { outputFile: path.join(evidence, 'browser.xml') }]],
  use: {
    baseURL: environment.frontendOrigin, browserName: 'chromium', headless: true,
    viewport: { width: 1280, height: 800 },
    video: { mode: 'on', size: { width: 1280, height: 800 } },
    trace: 'off', screenshot: 'off', serviceWorkers: 'block',
    launchOptions: { slowMo: 80 },
  },
});
