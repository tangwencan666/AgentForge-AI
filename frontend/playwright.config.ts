import { defineConfig } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

// A locator is not authorization. The fixed Python verifier attests disposable
// Docker identities and settings before any spec can import dotenv or make HTTP.
const root = path.resolve(import.meta.dirname, '..');
const manifest = process.env.AGENTFORGE_S1_MANIFEST;
if (!manifest) throw new Error('S1_ISOLATION_MANIFEST_REQUIRED');
const forbidden = new Set(['AGENTFORGE_DATABASE_URL', 'AGENTFORGE_REDIS_URL', 'AGENTFORGE_ADMIN_TOKEN',
  'AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN']);
if (Object.keys(process.env).some(name => forbidden.has(name) || /^AGENTFORGE_MODEL_(CODER|PLANNER|RESEARCHER|REVIEWER)_KEY$/.test(name))) {
  throw new Error('S1_SETTINGS_OVERRIDE_FORBIDDEN');
}
const osNames = ['SystemRoot', 'WINDIR', 'PATH', 'PATHEXT', 'COMSPEC', 'TEMP', 'TMP',
  'APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH'];
const environment: NodeJS.ProcessEnv = {};
for (const name of osNames) if (process.env[name] !== undefined) environment[name] = process.env[name];
let verified: { status: string; settings_path: string; run_directory: string; ports: { frontend: number } };
try {
  verified = JSON.parse(execFileSync(path.join(root, '.venv/Scripts/python.exe'),
    ['-B', path.join(root, 'scripts/s1_isolation.py'), 'validate', '--manifest', path.resolve(manifest)],
    { cwd: root, env: environment, windowsHide: true, encoding: 'utf8', timeout: 30000,
      stdio: ['ignore', 'pipe', 'pipe'] }));
} catch {
  throw new Error('S1_ISOLATION_UNVERIFIED');
}
if (verified.status !== 'READY' || !process.env.AGENTFORGE_SETTINGS_FILE
    || path.resolve(process.env.AGENTFORGE_SETTINGS_FILE) !== path.resolve(verified.settings_path)) {
  throw new Error('S1_SETTINGS_REFERENCE_MISMATCH');
}
const frontendPort = verified.ports.frontend;
if (!Number.isInteger(frontendPort) || frontendPort < 1024 || frontendPort > 65535 || frontendPort === 15173) {
  throw new Error('S1_FRONTEND_PORT_FORBIDDEN');
}
export default defineConfig({
  // Runner isolation remains separately authorized; offline Stub has its own config.
  testIgnore: ['sandbox.spec.ts'],
  testDir: './tests', workers: 1,
  reporter: [['list'], ['json', { outputFile: path.join(verified.run_directory, 'browser.json') }]],
  outputDir: path.join(verified.run_directory, 'browser-results'),
  use: { baseURL: `http://127.0.0.1:${frontendPort}`, browserName: 'chromium',
    channel: 'msedge', headless: true, trace: 'off' },
});
