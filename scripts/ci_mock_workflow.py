"""Run only on an attested disposable GitHub-hosted Linux job; no local mode."""
import asyncio
from datetime import datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from uuid import UUID, uuid4

from ci_mock_isolation import attest_services, hosted_context, install_guard, require

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'work/mock-ci'
CONTEXT_NAMES = ('GITHUB_ACTIONS', 'RUNNER_ENVIRONMENT', 'RUNNER_OS', 'GITHUB_REPOSITORY',
                 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_WORKSPACE',
                 'AGENTFORGE_CI_POSTGRES_ID', 'AGENTFORGE_CI_REDIS_ID')


def runtime_environment():
    names = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'LD_LIBRARY_PATH') + CONTEXT_NAMES
    environment = {name: os.environ[name] for name in names if name in os.environ}
    environment.update(PYTHONPATH=str(ROOT / 'backend'), PYTHONUNBUFFERED='1',
                       LANGCHAIN_TRACING_V2='false', LANGSMITH_TRACING='false',
                       AGENTFORGE_EXTERNAL_MODELS_BLOCKED='1')
    return environment


def child(mode):
    _, services = attest_services(ROOT, os.environ)
    config = json.load(sys.stdin)
    ports = [services[role]['port'] for role in ('postgres', 'redis')]
    require(config['ports'] == ports and config['api_port'] not in ports, 'CI_CHILD_ENDPOINT_MISMATCH')
    install_guard(ROOT, ports + [config['api_port']], child=True)
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.core.config import Settings
    # Only this CI process uses explicit test settings; the audit hook also
    # rejects dotenv reads. No application validation or authority is disabled.
    Settings.model_config = {**Settings.model_config, 'env_file': None}
    settings = Settings(_env_file=None, **config['settings'])
    require(settings.database_url.get_secret_value() == config['database_url']
            and settings.redis_url.get_secret_value() == config['redis_url'], 'CI_CHILD_SETTINGS_MISMATCH')
    require(not settings.real_calls_enabled and not settings.single_use_permits_enabled
            and settings.real_worker_mode == 'deny' and settings.real_daily_budget_usd == 0
            and settings.real_test_budget_usd == 0 and settings.daily_mock_budget_usd > 0
            and settings.sandbox_runner_token is None and settings.sandbox_image_id is None,
            'CI_CHILD_UNSAFE_POLICY')
    for key, value in config['settings'].items():
        os.environ['AGENTFORGE_' + key.upper()] = json.dumps(value) if isinstance(value, (dict, bool)) else str(value)
    if mode == 'migrate':
        # Migration authority is restricted to the database provisioned below.
        async def verify():
            import asyncpg
            connection = await asyncpg.connect(config['database_url'].replace('postgresql+asyncpg:', 'postgresql:'))
            try:
                require(await connection.fetchval('SELECT instance FROM ci_guard.identity') == config['instance'],
                        'CI_DATABASE_IDENTITY_MISMATCH')
                require(not await connection.fetchval('SELECT rolsuper FROM pg_roles WHERE rolname=current_user'),
                        'CI_APPLICATION_SUPERUSER_FORBIDDEN')
                require(await connection.fetchval("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'") == 0,
                        'CI_MIGRATION_REQUIRES_EMPTY_DATABASE')
            finally:
                await connection.close()
        asyncio.run(verify())
        from alembic.config import Config
        from alembic import command
        command.upgrade(Config(str(ROOT / 'backend/alembic.ini')), 'head')
    elif mode == 'api':
        import uvicorn
        from app.main import create_app
        uvicorn.run(create_app(settings), host='127.0.0.1', port=config['api_port'], access_log=False)
    elif mode == 'worker':
        from app.workers.main import main
        asyncio.run(main())
    else:
        raise RuntimeError('CI_CHILD_MODE_INVALID')


async def provision(run, services, instance):
    import secrets
    import asyncpg
    from redis.asyncio import Redis
    role = 'ci_' + uuid4().hex
    password, redis_password = secrets.token_hex(32), secrets.token_hex(32)
    postgres = await asyncpg.connect(host='127.0.0.1', port=services['postgres']['port'],
                                    user='postgres', password='ci-bootstrap-' + run, database='agentforge')
    try:
        require(await postgres.fetchval("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'") == 0,
                'CI_FRESH_DATABASE_REQUIRED')
        await postgres.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE")
        await postgres.execute(f'ALTER DATABASE agentforge OWNER TO {role}')
        await postgres.execute(f'ALTER SCHEMA public OWNER TO {role}')
        await postgres.execute(f'CREATE SCHEMA ci_guard AUTHORIZATION {role}')
        await postgres.execute('CREATE TABLE ci_guard.identity (instance text NOT NULL)')
        await postgres.execute('INSERT INTO ci_guard.identity VALUES ($1)', instance)
        await postgres.execute(f'GRANT SELECT ON ci_guard.identity TO {role}')
    finally:
        await postgres.close()
    redis = Redis(host='127.0.0.1', port=services['redis']['port'], decode_responses=True)
    try:
        require(await redis.dbsize() == 0, 'CI_FRESH_REDIS_REQUIRED')
        await redis.config_set('requirepass', redis_password)
    finally:
        await redis.aclose()
    database_url = f"postgresql+asyncpg://{role}:{password}@127.0.0.1:{services['postgres']['port']}/agentforge"
    redis_url = f"redis://:{redis_password}@127.0.0.1:{services['redis']['port']}/0"
    redis = Redis.from_url(redis_url, decode_responses=True)
    try:
        await redis.set('agentforge:ci:identity', instance)
    finally:
        await redis.aclose()
    return {'environment': 'test', 'database_url': database_url, 'redis_url': redis_url,
            'admin_token': secrets.token_hex(32), 'tenant_id': instance,
            'daily_mock_token_limit': 1000000, 'daily_mock_budget_usd': '10',
            'real_calls_enabled': False, 'single_use_permits_enabled': False,
            'real_worker_mode': 'deny', 'real_daily_budget_usd': '0', 'real_test_budget_usd': '0',
            'real_max_retries': 0, 'model_credentials_env_only': True,
            'model_prices': {}, 'model_credential_hosts': {}}


def start_child(mode, config):
    with (REPORT / (mode + '.log')).open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--child', mode],
                                   cwd=ROOT, env=runtime_environment(), stdin=subprocess.PIPE,
                                   stdout=log, stderr=subprocess.STDOUT, text=True)
    process.stdin.write(json.dumps(config))
    process.stdin.close()
    return process


async def wait_for(operation, predicate, name, timeout=45):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        value = await operation()
        if predicate(value):
            return value
        await asyncio.sleep(0.2)
    raise AssertionError('CI_TIMEOUT_' + name)


def decode_sse(text):
    frames = []
    for block in text.replace('\r\n', '\n').split('\n\n'):
        fields = dict(line.split(': ', 1) for line in block.splitlines() if ': ' in line)
        if 'id' in fields:
            row = json.loads(fields['data'])
            require(int(fields['id']) == row['id'], 'CI_SSE_ID_MISMATCH')
            frames.append(row)
    return frames


async def scenarios(config, processes, results):
    import asyncpg
    import httpx
    from redis.asyncio import Redis
    settings = config['settings']
    database = await asyncpg.connect(config['database_url'].replace('postgresql+asyncpg:', 'postgresql:'))
    redis = Redis.from_url(config['redis_url'], decode_responses=True)
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{config['api_port']}", trust_env=False,
                                 headers={'Authorization': 'Bearer ' + settings['admin_token']}, timeout=10) as client:
        async def request(method, path, expected=200, **kwargs):
            response = await client.request(method, path, **kwargs)
            require(response.status_code == expected, 'CI_HTTP_' + str(response.status_code) + '_' + path)
            return response.json()['data']

        async def ready():
            require(all(p.poll() is None for p in processes), 'CI_SERVICE_PROCESS_EXITED')
            try:
                return (await client.get('/health/ready')).status_code
            except httpx.ConnectError:
                return 0

        await wait_for(ready, lambda status: status == 200, 'API_READY')
        state = await wait_for(lambda: request('GET', '/api/v1/models/runtime-status'),
                               lambda data: data['worker_available'] and data['configuration_consistent'], 'WORKER_READY')
        require(not state['api']['coder_credential_present'] and not state['worker']['coder_credential_present'],
                'CI_MODEL_CREDENTIAL_PRESENT')
        require(state['api']['policy']['external_calls_blocked'] and not state['api']['policy']['real_calls_enabled'],
                'CI_REAL_MODEL_POLICY_OPEN')
        require(Decimal(state['api']['policy']['daily_budget_usd']) == 0
                and Decimal(state['api']['policy']['test_budget_usd']) == 0, 'CI_REAL_BUDGET_NOT_ZERO')
        require(await redis.get('agentforge:ci:identity') == config['instance'], 'CI_REDIS_IDENTITY_MISMATCH')
        results['api_and_worker_ready'] = {'status': 'PASS', 'api_pid': state['api']['process_id'],
                                          'worker_pid': state['worker']['process_id']}

        async def create():
            return await request('POST', '/api/v1/tasks', expected=202,
                                 headers={'Idempotency-Key': str(uuid4())},
                                 json={'goal': 'CI explicit Mock approval workflow; do not execute code',
                                       'execution_mode': 'mock', 'workflow': 'agents', 'require_approval': True,
                                       'timeout_seconds': 180, 'max_budget_usd': '1', 'max_calls': 8,
                                       'mock_options': {'latency_ms': 100}})

        async def task(identity):
            value = await request('GET', '/api/v1/tasks/' + identity)
            require(value['status'] not in {'failed', 'timed_out', 'limit_exceeded'},
                    'CI_TASK_FAILED_' + str(value['error_code']))
            return value

        async def waiting(identity):
            value = await wait_for(lambda: task(identity), lambda value: value['status'] == 'waiting_approval', 'APPROVAL_WAIT')
            await wait_for(lambda: database.fetchval('SELECT owner IS NULL FROM agent_tasks WHERE id=$1', UUID(identity)),
                           bool, 'CHECKPOINT_RELEASE')
            # Observe several real Worker scheduling cycles before granting approval.
            for _ in range(8):
                value = await task(identity)
                require(value['status'] == 'waiting_approval' and len(value['calls']) == 1
                        and value['calls'][0]['role'] == 'planner'
                        and value['calls'][0]['state'] == 'completed', 'CI_PREAPPROVAL_EXECUTION')
                await asyncio.sleep(0.25)
            require(await database.fetchval('SELECT count(*) FROM graph_checkpoints WHERE task_id=$1', UUID(identity)) > 0,
                    'CI_CHECKPOINT_NOT_PERSISTED')
            return value

        created = await create()
        identity = created['task_id']
        require(created['is_mock'], 'CI_TASK_NOT_MOCK')
        results['create_returns_202'] = {'status': 'PASS', 'task_id': identity}
        await waiting(identity)
        results['planner_waits_for_approval'] = {'status': 'PASS', 'checkpoint_persisted': True}
        results['no_workers_before_approval'] = {'status': 'PASS', 'observed_seconds': 2, 'roles': ['planner']}
        approvals = await request('GET', '/api/v1/approvals')
        approval = next(a for a in approvals if a['task_id'] == identity)
        require(approval['status'] == 'pending', 'CI_APPROVAL_NOT_PENDING')
        async with asyncio.timeout(10):
            async with client.stream('GET', '/api/v1/tasks/' + identity + '/events') as live:
                require(live.status_code == 200 and live.headers['content-type'].startswith('text/event-stream'),
                        'CI_LIVE_SSE_UNREADABLE')
                async for line in live.aiter_lines():
                    if line.startswith('id: '):
                        live_id = int(line[4:])
                        break
        await request('POST', '/api/v1/approvals/' + approval['approval_id'] + '/decision',
                      json={'decision': 'approved', 'operation_hash': approval['operation_hash']})
        completed = await wait_for(lambda: task(identity), lambda value: value['status'] == 'succeeded', 'WORKFLOW_SUCCESS')
        calls = {call['role']: call for call in completed['calls']}
        require(len(completed['calls']) == 4 and set(calls) == {'planner', 'coder', 'researcher', 'reviewer'}, 'CI_ROLE_SET_INVALID')
        require(all(call['state'] == 'completed' and call['is_mock'] and call['provider'] == 'mock' for call in calls.values()),
                'CI_NONMOCK_OPERATION')
        for role in ('coder', 'researcher'):
            require(datetime.fromisoformat(calls['planner']['finished_at']) <= datetime.fromisoformat(calls[role]['started_at'])
                    and datetime.fromisoformat(calls[role]['finished_at']) <= datetime.fromisoformat(calls['reviewer']['started_at']),
                    'CI_ROLE_ORDER_INVALID')
        require(Decimal(completed['usage']['real_cost_usd']) == 0 and not completed['tools'], 'CI_REAL_COST_OR_TOOL_EXECUTION')
        results['approved_workflow_succeeds'] = {'status': 'PASS', 'roles': list(calls), 'real_cost_usd': '0'}

        replay = await client.get('/api/v1/tasks/' + identity + '/events')
        require(replay.status_code == 200 and 'event: completed' in replay.text, 'CI_SSE_UNREADABLE')
        frames = decode_sse(replay.text)
        ids = [frame['id'] for frame in frames]
        require(len(ids) > 4 and ids == sorted(set(ids)), 'CI_SSE_CURSOR_INVALID')
        cursor = ids[len(ids) // 2]
        resumed = await client.get('/api/v1/tasks/' + identity + '/events', headers={'Last-Event-ID': str(cursor)})
        require(resumed.status_code == 200 and [row['id'] for row in decode_sse(resumed.text)] == [i for i in ids if i > cursor],
                'CI_SSE_RESUME_MISMATCH')
        results['sse_read_and_resume'] = {'status': 'PASS', 'events': len(ids), 'resume_cursor': cursor,
                                          'suffix_exact': True, 'live_first_id': live_id}

        cancelled_id = (await create())['task_id']
        await waiting(cancelled_id)
        cancelled_approval = next(a for a in await request('GET', '/api/v1/approvals') if a['task_id'] == cancelled_id)
        await request('POST', '/api/v1/tasks/' + cancelled_id + '/cancel')
        await wait_for(lambda: task(cancelled_id), lambda value: value['status'] == 'cancelled', 'CANCELLED')
        rejected = await client.post('/api/v1/approvals/' + cancelled_approval['approval_id'] + '/decision',
                                     json={'decision': 'approved', 'operation_hash': cancelled_approval['operation_hash']})
        require(rejected.status_code == 409, 'CI_CANCELLED_APPROVAL_ACCEPTED')
        for _ in range(8):
            value = await task(cancelled_id)
            require(value['status'] == 'cancelled' and [call['role'] for call in value['calls']] == ['planner'],
                    'CI_CANCELLED_TASK_EXECUTED')
            await asyncio.sleep(0.25)
        results['cancel_waiting_stops_later_roles'] = {'status': 'PASS', 'task_id': cancelled_id,
                                                     'late_approval_http': 409, 'roles': ['planner']}
        for table, condition in [('model_operations', 'NOT is_mock'), ('sandbox_executions', 'true'), ('execution_permits', 'true')]:
            require(await database.fetchval(f'SELECT count(*) FROM {table} WHERE {condition}') == 0, 'CI_FORBIDDEN_RECORD_' + table)
        results['safety'] = {'status': 'PASS', 'real_operations': 0, 'sandbox_executions': 0, 'execution_permits': 0,
                             'mock_daily_budget_usd': settings['daily_mock_budget_usd'], 'real_budgets_usd': '0'}
    await redis.aclose()
    await database.close()


async def main():
    run, services = attest_services(ROOT, os.environ)
    REPORT.mkdir(parents=True, exist_ok=True)
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        api_port = reserved.getsockname()[1]
    ports = [services[role]['port'] for role in ('postgres', 'redis')]
    audit = install_guard(ROOT, ports + [api_port])
    for event, args in [('socket.getaddrinfo', ('api.deepseek.com', 443, 0, 0, 0)),
                        ('socket.connect', (None, ('127.0.0.1', 18120))),
                        ('open', (str(ROOT / '.env'), 'r', 0))]:
        try:
            audit(event, args)
        except RuntimeError:
            pass
        else:
            raise RuntimeError('CI_GUARD_SELF_CHECK_FAILED')
    settings = await provision(run, services, str(uuid4()))
    config = {'settings': settings, 'ports': ports, 'api_port': api_port, 'instance': settings['tenant_id'],
              'database_url': settings['database_url'], 'redis_url': settings['redis_url']}
    results = {'isolation': {'status': 'PASS', 'run': run, 'services': services,
                              'network_and_dotenv_guard': True, 'api_port': api_port}}
    processes = []
    try:
        migration = start_child('migrate', config)
        processes.append(migration)
        code = await asyncio.to_thread(migration.wait, timeout=90)
        require(code == 0, 'CI_MIGRATION_FAILED_SEE_migrate.log')
        results['temporary_database_migrated'] = {'status': 'PASS', 'target': 'head', 'new_database_only': True}
        processes.extend([start_child('api', config), start_child('worker', config)])
        await scenarios(config, processes[1:], results)
        results['conclusion'] = 'PASS'
    except Exception as error:
        results['conclusion'] = 'FAIL'
        results['failure'] = {'type': type(error).__name__, 'code': str(error) if isinstance(error, (RuntimeError, AssertionError)) else 'SEE_SERVICE_LOGS'}
        raise
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    await asyncio.to_thread(process.wait, timeout=5)
        (REPORT / 'result.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(json.dumps(results, indent=2), flush=True)


if __name__ == '__main__':
    try:
        # Refuse before asyncio can create even its local event-loop sockets.
        hosted_context(ROOT, os.environ)
        if len(sys.argv) == 3 and sys.argv[1] == '--child':
            child(sys.argv[2])
        else:
            require(len(sys.argv) == 1, 'CI_ARGUMENTS_INVALID')
            asyncio.run(main())
    except Exception as error:
        print('Mock CI refused/failed: ' + (str(error) if isinstance(error, (RuntimeError, AssertionError)) else type(error).__name__), flush=True)
        raise SystemExit(1) from None
