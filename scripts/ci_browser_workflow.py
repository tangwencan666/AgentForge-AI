"""Browser extension for the attested hosted Mock stack; no local entrypoint."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlsplit

from ci_mock_isolation import require


def redact_reports(report, config):
    values = {config['settings']['admin_token'], config['database_url'], config['redis_url']}
    values.update(urlsplit(config[name]).password for name in ('database_url', 'redis_url'))
    for path in report.rglob('*'):
        if path.is_file() and path.suffix in {'.log', '.json', '.xml', '.txt', '.html', '.md'}:
            content = path.read_text(encoding='utf-8')
            for value in filter(None, values):
                content = content.replace(value, '[REDACTED_TEST_CREDENTIAL]')
            path.write_text(content, encoding='utf-8')


async def run_browser(root, report, config, processes, environment):
    import httpx
    frontend_origin = f"http://127.0.0.1:{config['frontend_port']}"
    api_origin = f"http://127.0.0.1:{config['api_port']}"
    frontend_environment = {**environment, 'AGENTFORGE_CI_API_ORIGIN': api_origin}
    with (report / 'frontend.log').open('w', encoding='utf-8') as log:
        frontend = subprocess.Popen(['node', str(root / 'frontend/node_modules/vite/bin/vite.js'),
                                     'preview', '--config', 'vite.browser-ci.config.ts',
                                     '--host', '127.0.0.1', '--port', str(config['frontend_port']), '--strictPort'],
                                    cwd=root / 'frontend', env=frontend_environment,
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    processes.append(frontend)
    async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
        for _ in range(100):
            require(frontend.poll() is None, 'CI_FRONTEND_EXITED_SEE_frontend.log')
            try:
                response = await client.get(frontend_origin + '/tasks')
                if response.status_code == 200:
                    break
            except httpx.ConnectError:
                pass
            await asyncio.sleep(0.2)
        else:
            raise RuntimeError('CI_FRONTEND_READY_TIMEOUT')

    # The frontend never receives this path or token. Only the test controller
    # reads a private, transient JSON file outside the uploaded evidence tree.
    temporary_root = Path(environment['RUNNER_TEMP']).resolve()
    require(temporary_root.is_dir() and str(temporary_root).startswith('/home/runner/work/_temp'),
            'CI_PRIVATE_TEMP_REQUIRED')
    browser = None
    try:
        with tempfile.TemporaryDirectory(prefix='agentforge-browser-', dir=temporary_root) as directory:
            path = Path(directory) / 'browser-config.json'
            payload = {'frontend_origin': frontend_origin, 'api_origin': api_origin,
                       'admin_token': config['settings']['admin_token'], 'tenant_id': config['instance'],
                       'run': environment['GITHUB_RUN_ID'] + '-' + environment['GITHUB_RUN_ATTEMPT']}
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as file:
                json.dump(payload, file)
            # Masks action-call diagnostics in the GitHub log. Text artifacts
            # are separately redacted below, and trace/HAR recording is off.
            print('::add-mask::' + payload['admin_token'], flush=True)
            browser_environment = {**environment, 'CI': 'true', 'AGENTFORGE_CI_BROWSER_CONFIG': str(path)}
            with (report / 'playwright.log').open('w', encoding='utf-8') as log:
                browser = subprocess.Popen(['node', 'node_modules/@playwright/test/cli.js', 'test',
                                             '--config=playwright.browser-ci.config.ts'],
                                            cwd=root / 'frontend', env=browser_environment, stdin=subprocess.DEVNULL,
                                            stdout=log, stderr=subprocess.STDOUT)
            processes.append(browser)
            code = await asyncio.to_thread(browser.wait, timeout=240)
            require(code == 0, 'CI_BROWSER_FAILED_SEE_playwright.log')
            result = json.loads((report / 'browser-results.json').read_text(encoding='utf-8'))
            require(result['conclusion'] == 'PASS' and len(result['scenarios']) == 4
                    and all(row['status'] == 'PASS' for row in result['scenarios'].values()),
                    'CI_BROWSER_SCENARIOS_INCOMPLETE')
            require((report / 'mock-workflow.webm').stat().st_size > 0, 'CI_BROWSER_VIDEO_MISSING')
            return result
    finally:
        if browser is not None and browser.poll() is None:
            browser.terminate()
            try:
                await asyncio.to_thread(browser.wait, timeout=10)
            except subprocess.TimeoutExpired:
                browser.kill()
                await asyncio.to_thread(browser.wait, timeout=5)
        redact_reports(report, config)


async def verify_final_safety(config):
    import asyncpg
    connection = await asyncpg.connect(config['database_url'].replace('postgresql+asyncpg:', 'postgresql:'))
    try:
        counters = {}
        for table, condition in [('model_operations', 'NOT is_mock'), ('sandbox_executions', 'true'), ('execution_permits', 'true')]:
            count = await connection.fetchval(f'SELECT count(*) FROM {table} WHERE {condition}')
            require(count == 0, 'CI_BROWSER_FORBIDDEN_RECORD_' + table)
            counters[table] = count
        return {'status': 'PASS', 'forbidden_records': counters, 'real_budgets_usd': '0'}
    finally:
        await connection.close()
