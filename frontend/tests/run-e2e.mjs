import { mkdirSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { spawnSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '../..');
const forbidden = new Set(['AGENTFORGE_DATABASE_URL', 'AGENTFORGE_REDIS_URL', 'AGENTFORGE_ADMIN_TOKEN',
  'AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN']);
if (Object.keys(process.env).some(name => forbidden.has(name) || /^AGENTFORGE_MODEL_(CODER|PLANNER|RESEARCHER|REVIEWER)_KEY$/.test(name))) {
  throw new Error('S1_SETTINGS_OVERRIDE_FORBIDDEN');
}
const manifest = process.env.AGENTFORGE_S1_MANIFEST;
const settings = process.env.AGENTFORGE_SETTINGS_FILE;
if (!manifest || !settings) throw new Error('S1_ISOLATION_MANIFEST_REQUIRED');
const options = process.argv.slice(2);
if (options.length > 1 || options.length === 1 && options[0] !== '--list') {
  throw new Error('S1_BROWSER_ARGUMENTS_FORBIDDEN');
}
const environment = {};
for (const name of ['SystemRoot', 'WINDIR', 'PATH', 'PATHEXT', 'COMSPEC', 'TEMP', 'TMP',
  'APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH']) {
  if (process.env[name] !== undefined) environment[name] = process.env[name];
}
const checked = spawnSync(join(root, '.venv/Scripts/python.exe'),
  ['-B', join(root, 'scripts/s1_isolation.py'), 'validate', '--manifest', resolve(manifest)],
  { cwd: root, env: environment, windowsHide: true, encoding: 'utf8', timeout: 30000,
    stdio: ['ignore', 'pipe', 'pipe'] });
let verified;
try {
  if (checked.error || checked.status !== 0) throw new Error();
  verified = JSON.parse(checked.stdout);
  if (verified.status !== 'READY' || resolve(settings) !== resolve(verified.settings_path)) throw new Error();
} catch {
  throw new Error('S1_ISOLATION_UNVERIFIED');
}
const temporary = join(verified.run_directory, 'browser-temp');
mkdirSync(temporary, { recursive: true });
environment.TEMP = temporary;
environment.TMP = temporary;
environment.AGENTFORGE_S1_MANIFEST = verified.manifest_path;
environment.AGENTFORGE_SETTINGS_FILE = verified.settings_path;
environment.AGENTFORGE_RUN_INTEGRATION = '1';
const result = spawnSync(process.execPath, [join(root, 'frontend/node_modules/@playwright/test/cli.js'),
  'test', '--config=playwright.config.ts', ...options], {
  cwd: join(root, 'frontend'), stdio: 'inherit', env: environment, windowsHide: true,
});
process.exit(result.status ?? 1);
