import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
const temporary = resolve('../work/tmp');
mkdirSync(temporary, { recursive: true });
const result = spawnSync(process.execPath, [resolve('node_modules/@playwright/test/cli.js'), 'test', ...process.argv.slice(2)], {
  stdio: 'inherit', env: { ...process.env, TEMP: temporary, TMP: temporary },
});
process.exit(result.status ?? 1);
