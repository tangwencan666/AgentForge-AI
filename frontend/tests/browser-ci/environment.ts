import fs from 'node:fs';
import path from 'node:path';

export function hostedBrowserContext() {
  if (process.platform !== 'linux' || process.env.GITHUB_ACTIONS !== 'true'
      || process.env.RUNNER_ENVIRONMENT !== 'github-hosted' || process.env.RUNNER_OS !== 'Linux'
      || process.env.GITHUB_REPOSITORY !== 'tangwencan666/AgentForge-AI'
      || process.env.GITHUB_WORKSPACE !== '/home/runner/work/AgentForge-AI/AgentForge-AI') {
    throw new Error('CI_HOSTED_BROWSER_CONTEXT_REQUIRED');
  }
}

export function loopbackOrigin(value: string | undefined) {
  const parsed = new URL(value || 'invalid');
  if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1'
      || Number(parsed.port) < 30000 || parsed.pathname !== '/' || parsed.search || parsed.hash
      || parsed.username || parsed.password) throw new Error('CI_BROWSER_ORIGIN_INVALID');
  return parsed.origin;
}

export function browserEnvironment() {
  hostedBrowserContext();
  const filename = path.resolve(process.env.AGENTFORGE_CI_BROWSER_CONFIG || 'invalid');
  const temporaryRoot = path.resolve(process.env.RUNNER_TEMP || 'invalid');
  const relative = path.relative(temporaryRoot, filename);
  if (path.basename(filename) !== 'browser-config.json' || relative.startsWith('..')
      || path.isAbsolute(relative) || fs.realpathSync(filename) !== filename) {
    throw new Error('CI_PRIVATE_BROWSER_CONFIG_REQUIRED');
  }
  const info = fs.statSync(filename);
  if ((info.mode & 0o077) !== 0 || info.uid !== process.getuid?.()) throw new Error('CI_BROWSER_CONFIG_PERMISSIONS');
  const config = JSON.parse(fs.readFileSync(filename, 'utf8')) as {
    frontend_origin: string; api_origin: string; admin_token: string; tenant_id: string; run: string;
  };
  if (!/^[a-f0-9]{64}$/.test(config.admin_token)
      || config.run !== `${process.env.GITHUB_RUN_ID}-${process.env.GITHUB_RUN_ATTEMPT}`) {
    throw new Error('CI_BROWSER_CONFIG_INVALID');
  }
  const frontendOrigin = loopbackOrigin(config.frontend_origin);
  const apiOrigin = loopbackOrigin(config.api_origin);
  if (frontendOrigin === apiOrigin) throw new Error('CI_BROWSER_ORIGINS_COLLIDE');
  return { frontendOrigin, apiOrigin, adminToken: config.admin_token, tenantId: config.tenant_id };
}
