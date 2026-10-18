"""Explicit S1 disposable application acceptance; never a main-service launcher.

Only --manifest selects an already-created, attested test stack. No Docker write,
migration, production configuration, real model or arbitrary command is exposed.
Only the attested disposable database may be initialized to revision 0008.
"""
import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import uuid4

from s1_isolation import (PROJECT_ROOT, build_test_environment, checked_path,
                          isolation_lease, read_test_settings, validate_isolation)

MODULES = ('lifecycle.py', 'lifecycle_manager.py', 'lifecycle_v2.py', 'lifecycle_windows.py',
           'lifecycle_channel.py', 'lifecycle_runtime.py', 'managed_service.py')
ROLE_KEYS = frozenset('AGENTFORGE_MODEL_' + role + '_KEY'
                     for role in ('CODER', 'PLANNER', 'RESEARCHER', 'REVIEWER'))


class ApplicationTestError(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise ApplicationTestError(code)


def write_new(path, content):
    """A repeated run may reuse identical prepared source; never replace changes."""
    path = checked_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.is_file() and path.read_bytes() == content, 'S1_EXISTING_FILE_DIFFERS')
        return
    with path.open('xb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def copy_source(source, destination, fingerprints):
    source, destination = checked_path(source), checked_path(destination)
    require(source.is_file(), 'S1_SOURCE_MISSING')
    content = source.read_bytes()
    write_new(destination, content)
    fingerprints[str(source.relative_to(PROJECT_ROOT))] = hashlib.sha256(content).hexdigest()


def child_guard_source(root, manifest):
    # Site processes .pth even for isolated (-I) Python. Failure must terminate:
    # sitecustomize's default "print and continue" behavior would be unsafe.
    docker = shutil.which('docker')
    require(bool(docker) and checked_path(docker).is_file(), 'S1_DOCKER_RUNTIME_MISSING')
    return f'''"""Generated S1-only Python startup guard; contains no secret values."""
import os
import sys
import json
from pathlib import Path
try:
    original = Path({str(PROJECT_ROOT)!r})
    clone = Path({str(root)!r})
    manifest = Path({str(manifest)!r})
    forbidden = {{'AGENTFORGE_DATABASE_URL', 'AGENTFORGE_REDIS_URL', 'AGENTFORGE_ADMIN_TOKEN', 'AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN'}}
    forbidden.update('AGENTFORGE_MODEL_' + role + '_KEY' for role in ('CODER','PLANNER','RESEARCHER','REVIEWER'))
    if any(name in os.environ for name in forbidden):
        raise RuntimeError('S1_CHILD_ENVIRONMENT_FORBIDDEN')
    mcp = sys.orig_argv[1:] == ['-I', '-m', 'app.mcp.server']
    if mcp:
        # Production MCP intentionally has a minimal environment. This fixed
        # disposable bootstrap supplies only the attestation executable lookup;
        # the following checks still bind its connection to this test stack.
        if Path.cwd() != clone:
            raise RuntimeError('S1_MCP_ROOT_MISMATCH')
        os.environ['PATH'] = {str(Path(docker).parent)!r}
    sys.path.insert(0, str(original / 'scripts'))
    from s1_isolation import validate_isolation, checked_path, read_test_settings, SAFE_ENV
    verified = validate_isolation(original, manifest)
    settings = checked_path(clone / 'work/service/.env')
    if mcp:
        values = read_test_settings(original, json.loads(manifest.read_text(encoding='utf-8')))
        if (os.environ.get('AGENTFORGE_MCP_DATABASE_URL') != values['AGENTFORGE_DATABASE_URL']
                or os.environ.get('AGENTFORGE_MCP_SERVER_TOKEN') != values['AGENTFORGE_MCP_SERVER_TOKEN']
                or 'AGENTFORGE_S1_MANIFEST' in os.environ or 'AGENTFORGE_SETTINGS_FILE' in os.environ):
            raise RuntimeError('S1_MCP_TEST_BINDING_MISMATCH')
        os.environ.update(SAFE_ENV)
        os.environ['AGENTFORGE_S1_MANIFEST'] = str(manifest)
        os.environ['AGENTFORGE_SETTINGS_FILE'] = str(settings)
    if (Path(verified['run_directory']) != clone
            or os.environ.get('AGENTFORGE_S1_MANIFEST') != str(manifest)
            or os.environ.get('AGENTFORGE_SETTINGS_FILE') != str(settings)
            or settings.read_bytes() != checked_path(verified['settings_path']).read_bytes()):
        raise RuntimeError('S1_CHILD_SETTINGS_MISMATCH')
    sys.path.insert(0, str(clone / 'backend'))
    sys.path.insert(0, str(original / 'tests/fixtures'))
    from preflight_guards import install_verified_guard
    install_verified_guard(verified)
except BaseException:
    os._exit(78)
'''


def prepare_application(verified, *, browser=False):
    root = checked_path(verified['run_directory'])
    require(root != PROJECT_ROOT and root.is_relative_to(PROJECT_ROOT / 'work/maint-s1'), 'S1_CLONE_ROOT_INVALID')
    # Never adopt or replace a previously started instance, even if stopped.
    require(not (root / 'work/lifecycle/manifest.json').exists(), 'S1_APPLICATION_ALREADY_USED')
    fingerprints = {}
    for name in MODULES:
        copy_source(PROJECT_ROOT / 'scripts' / name, root / 'scripts' / name, fingerprints)
    for source in sorted((PROJECT_ROOT / 'backend/app').rglob('*.py')):
        if '__pycache__' not in source.parts:
            copy_source(source, root / source.relative_to(PROJECT_ROOT), fingerprints)
    for relative in ('.venv/Scripts/python.exe', '.venv/pyvenv.cfg'):
        source = checked_path(PROJECT_ROOT / relative)
        require(source.is_file(), 'S1_RUNTIME_MISSING')
        write_new(root / relative, source.read_bytes())
    service = root / 'work/service/.env'
    # This file contains only newly generated test service credentials. Never
    # read/copy/hash the main dotenv or any model key / issuer token.
    write_new(service, checked_path(verified['settings_path']).read_bytes())
    packages = root / '.venv/Lib/site-packages'
    write_new(packages / 's1_application_guard.py', child_guard_source(root, Path(verified['manifest_path'])).encode())
    pth = str(PROJECT_ROOT / '.venv/Lib/site-packages') + '\nimport s1_application_guard\n'
    write_new(packages / '00_agentforge_s1.pth', pth.encode())
    if browser:
        prepare_frontend(root, verified, fingerprints)
    return root, service, fingerprints


def prepare_frontend(root, verified, fingerprints):
    frontend = root / 'frontend'
    for name in ('package.json', 'index.html'):
        copy_source(PROJECT_ROOT / 'frontend' / name, frontend / name, fingerprints)
    for directory in ('src', 'public'):
        source_directory = PROJECT_ROOT / 'frontend' / directory
        if source_directory.exists():
            for source in sorted(source_directory.rglob('*')):
                if source.is_file():
                    require(not source.name.startswith('.env'), 'S1_FRONTEND_SOURCE_FORBIDDEN')
                    copy_source(source, frontend / source.relative_to(PROJECT_ROOT / 'frontend'), fingerprints)
    modules = checked_path(PROJECT_ROOT / 'frontend/node_modules')
    vite_bin = modules / 'vite/bin/vite.js'
    vite_api = modules / 'vite/dist/node/index.js'
    react_plugin = modules / '@vitejs/plugin-react/dist/index.js'
    require(all(path.is_file() for path in (vite_bin, vite_api, react_plugin)), 'S1_FRONTEND_RUNTIME_MISSING')
    # Fixed dependency shim, not a generic Node command or a junction.
    shim = 'import(' + json.dumps(vite_bin.as_uri()) + ").catch(() => { process.stderr.write('S1_VITE_START_FAILED\\n'); process.exitCode = 1; });\n"
    write_new(frontend / 'node_modules/vite/bin/vite.js', shim.encode())
    router_exports = json.loads((modules / 'react-router/package.json').read_text(encoding='utf-8'))
    router_dom = checked_path(modules / 'react-router' / router_exports['exports']['./dom']['import']['default'])
    require(router_dom.is_file() and router_dom.is_relative_to(modules / 'react-router'), 'S1_FRONTEND_RUNTIME_MISSING')
    # Preserve the installed package's subpath export before its parent alias;
    # a directory alias alone incorrectly resolves react-router/dom to /dom.
    aliases = {'react-router/dom': str(router_dom).replace('\\', '/')}
    aliases.update({name: str(modules / name).replace('\\', '/')
                    for name in ('react', 'react-dom', 'react-router', 'react-router-dom')})
    configuration = {
        'root': str(frontend).replace('\\', '/'), 'envDir': False, 'clearScreen': False, 'logLevel': 'warn',
        'resolve': {'alias': aliases},
        'server': {'host': '127.0.0.1', 'port': verified['ports']['frontend'], 'strictPort': True,
                   'proxy': {key: 'http://127.0.0.1:' + str(verified['ports']['backend'])
                             for key in ('/api', '/health', '/openapi.json')},
                   'fs': {'strict': True, 'allow': [str(frontend), str(modules)]}},
    }
    config = ('import { defineConfig } from ' + json.dumps(vite_api.as_uri()) + ';\n'
              + 'import react from ' + json.dumps(react_plugin.as_uri()) + ';\n'
              + 'const configuration = ' + json.dumps(configuration) + ';\n'
              + 'export default defineConfig({ ...configuration, plugins: [react()] });\n')
    write_new(frontend / 'vite.config.mjs', config.encode())


@contextmanager
def application_environment(verified, service):
    # Child commands inherit natively, but only from an already sanitized
    # dedicated harness. No model/issuer values are inspected or transferred.
    forbidden = ROLE_KEYS | {'AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN', 'AGENTFORGE_DATABASE_URL', 'AGENTFORGE_REDIS_URL', 'AGENTFORGE_ADMIN_TOKEN'}
    require(not any(name in os.environ for name in forbidden), 'S1_PARENT_ENVIRONMENT_FORBIDDEN')
    public_changes = {'AGENTFORGE_SETTINGS_FILE': str(service), 'BACKEND_PORT': str(verified['ports']['backend']),
                      'FRONTEND_PORT': str(verified['ports']['frontend'])}
    previous = {name: os.environ.get(name) for name in public_changes}
    from lifecycle_manager import SAFE_ENV
    for name, value in SAFE_ENV.items():
        require(os.environ.get(name) == value, 'S1_PARENT_POLICY_UNSAFE')
    try:
        os.environ.update(public_changes)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


async def exercise_application(verified, managed, settings):
    import httpx
    endpoint = 'http://127.0.0.1:' + str(verified['ports']['backend'])
    headers = {'Authorization': 'Bearer ' + settings['AGENTFORGE_ADMIN_TOKEN']}
    async with httpx.AsyncClient(base_url=endpoint, headers=headers, trust_env=False, timeout=5) as client:
        ready = await client.get('/health/ready')
        require(ready.status_code == 200, 'S1_APPLICATION_NOT_READY')
        require(ready.json()['data']['dependencies'] == {'postgresql': 'up', 'redis': 'up'}, 'S1_DEPENDENCIES_NOT_READY')
        slots = await client.get('/api/v1/model-slots')
        require(slots.status_code == 200, 'S1_SLOTS_UNAVAILABLE')
        values = slots.json()['data']
        require(len(values) == 4 and all(slot['enabled'] is False for slot in values), 'S1_MODEL_SLOT_UNSAFE')
        deadline = time.monotonic() + 15
        while True:
            response = await client.get('/api/v1/models/runtime-status')
            require(response.status_code == 200, 'S1_RUNTIME_STATUS_UNAVAILABLE')
            state = response.json()['data']
            if state.get('worker_available') and state.get('configuration_consistent'):
                break
            require(time.monotonic() < deadline, 'S1_WORKER_STATUS_TIMEOUT')
            await asyncio.sleep(.2)
        for api_role, role in (('api', 'backend'), ('worker', 'worker')):
            sample = state[api_role]
            require(sample['process_id'] == managed['entries'][role]['pid'] and sample['coder_credential_present'] is False,
                    'S1_RUNTIME_IDENTITY_MISMATCH')
            policy = sample['policy']
            require(policy['real_calls_enabled'] is False and policy['external_calls_blocked'] is True
                    and policy['daily_budget_usd'] == policy['test_budget_usd'] == '0'
                    and policy['real_max_retries'] == 0 and policy['permit_issuance_enabled'] is False,
                    'S1_RUNTIME_POLICY_UNSAFE')
        created = await client.post('/api/v1/tasks', headers={'Idempotency-Key': str(uuid4())}, json={
            'goal': 'S1 isolated lifecycle acceptance: produce a clearly marked Mock result.',
            'execution_mode': 'mock', 'workflow': 'agents', 'require_approval': False,
            'timeout_seconds': 30, 'max_iterations': 1, 'max_calls': 8, 'max_tokens': 8192,
            'max_budget_usd': '.05', 'mock_options': {'latency_ms': 10, 'review_rounds': 0}})
        require(created.status_code in {200, 201, 202}, 'S1_MOCK_TASK_REJECTED')
        task_id = created.json()['data']['task_id']
        deadline = time.monotonic() + 45
        while True:
            response = await client.get('/api/v1/tasks/' + task_id)
            require(response.status_code == 200, 'S1_TASK_STATUS_UNAVAILABLE')
            task = response.json()['data']
            if task['status'] in {'succeeded', 'failed', 'cancelled', 'timed_out', 'limit_exceeded'}:
                break
            require(time.monotonic() < deadline, 'S1_MOCK_TASK_TIMEOUT')
            await asyncio.sleep(.2)
        require(task['status'] == 'succeeded', 'S1_MOCK_TASK_FAILED')
        require({call['role'] for call in task['calls']} == {'planner', 'coder', 'researcher', 'reviewer'}
                and all(call['is_mock'] is True and call['provider'] == 'mock' for call in task['calls']), 'S1_NON_MOCK_CALL_DETECTED')
        require(task['usage']['real_cost_usd'] == '0.00000000', 'S1_NONZERO_REAL_USAGE')
        return {'application_ready': True, 'api_credential_present': False, 'worker_credential_present': False,
                'configuration_consistent': True, 'task_id': task_id, 'task_status': task['status'],
                'roles': sorted({call['role'] for call in task['calls']}), 'all_calls_mock': True,
                'real_cost_usd': task['usage']['real_cost_usd'], 'task_call_count': len(task['calls'])}


def initialize_disposable_database(verified, values):
    """Run existing migrations only for a fresh, attested test database.

    Revision 0001 performs the normal four disabled slot seed for this run's
    tenant. Existing application data is never erased, reset or reseeded.
    """
    from alembic import command
    from alembic.config import Config
    from app.core.config import get_settings
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    settings = get_settings()
    require(settings.tenant_id == verified['tenant_id']
            and settings.database_url.get_secret_value() == values['AGENTFORGE_DATABASE_URL']
            and settings.redis_url.get_secret_value() == values['AGENTFORGE_REDIS_URL'],
            'S1_DATABASE_SETTINGS_MISMATCH')

    async def snapshot():
        engine = create_async_engine(settings.database_url.get_secret_value(), echo=False,
            hide_parameters=True, connect_args={'timeout': 3})
        try:
            async with engine.connect() as connection:
                identity = (await connection.execute(text('SELECT current_database(), current_user'))).one()
                require(tuple(identity) == ('agentforge', 'agentforge'), 'S1_DATABASE_IDENTITY_MISMATCH')
                exists = await connection.scalar(text("SELECT to_regclass('public.alembic_version')"))
                if exists is None:
                    count = await connection.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"))
                    require(count == 0, 'S1_DATABASE_NOT_FRESH')
                    return None
                revision = await connection.scalar(text('SELECT version_num FROM alembic_version'))
                require(revision == '0008_execution_permits', 'S1_DATABASE_REVISION_UNEXPECTED')
                count = await connection.scalar(text('SELECT count(*) FROM model_slots WHERE tenant_id=CAST(:tenant AS uuid) AND enabled=false'),
                    {'tenant': verified['tenant_id']})
                require(count == 4, 'S1_DISABLED_SLOTS_REQUIRED')
                return revision
        finally:
            await engine.dispose()

    before = asyncio.run(snapshot())
    if before is None:
        command.upgrade(Config(str(PROJECT_ROOT / 'backend/alembic.ini')), '0008_execution_permits')
    after = asyncio.run(snapshot())
    require(after == '0008_execution_permits', 'S1_DATABASE_MIGRATION_FAILED')
    return {'migration_version': after, 'disposable_database_initialized': before is None}


def execute(manifest, *, browser=False):
    require(os.name == 'nt', 'S1_WINDOWS_REQUIRED')
    require(not any(name in os.environ for name in ROLE_KEYS | {'AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN'}),
            'S1_MODEL_CREDENTIALS_FORBIDDEN')
    verified = validate_isolation(PROJECT_ROOT, manifest)
    require(os.environ.get('AGENTFORGE_SETTINGS_FILE') == verified['settings_path'], 'S1_SETTINGS_REFERENCE_MISMATCH')
    from lifecycle_manager import LifecycleManager
    result = {'status': 'BLOCKED', 'instance_id': verified['instance_id'], 'external_model_requests': 0,
              'runner_test': 'BLOCKED_SEPARATE_AUTHORIZATION', 'browser_requested': browser,
              'main_services_controlled': False, 'application_cleanup_confirmed': False}
    report = Path(verified['run_directory']) / 'application-report.json'
    require(not report.exists(), 'S1_APPLICATION_REPORT_ALREADY_EXISTS')
    with isolation_lease(PROJECT_ROOT, manifest):
        # This dedicated test supervisor and its descendants only. A crash or
        # outer timeout must not leave its disposable API/Worker/browser alive.
        # Production service management never uses this fixture Job Object.
        sys.path.insert(0, str(PROJECT_ROOT / 'tests/fixtures'))
        from s1_lifecycle_native import bind_disposable_job
        bind_disposable_job()
        # All source/settings writes and process operations occur under this
        # disposable stack's lease, never the main lifecycle directory.
        document = json.loads(checked_path(manifest).read_text(encoding='utf-8'))
        settings = read_test_settings(PROJECT_ROOT, document)
        sys.path.insert(0, str(PROJECT_ROOT / 'backend'))
        sys.path.insert(0, str(PROJECT_ROOT / 'tests/fixtures'))
        from preflight_guards import install_verified_guard
        install_verified_guard(verified)
        result.update(initialize_disposable_database(verified, settings))
        root, service, fingerprints = prepare_application(verified, browser=browser)
        result['source_fingerprints'] = fingerprints
        manager = LifecycleManager(root)
        with application_environment(verified, service):
            try:
                # Read-only diagnostics before persisting a launch intent. These
                # results never authorize a launch: the manager checks again
                # under its own operation lock immediately before each action.
                require(not manager.backend.discover(), 'S1_EXISTING_APPLICATION_REFUSED')
                for role in (('backend', 'frontend') if browser else ('backend',)):
                    require(not manager.backend._listeners(verified['ports'][role]), 'S1_APPLICATION_PORT_OCCUPIED')
                state = manager.start('mock', models_only=not browser)
                result['instances'] = [{key: entry[key] for key in ('role', 'instance_id', 'generation', 'pid', 'created', 'lifecycle_state')}
                                       for entry in state['entries'].values()]
                result.update(asyncio.run(exercise_application(verified, state, settings)))
                if browser:
                    environment = build_test_environment(PROJECT_ROOT, manifest)
                    command = ['node', str(PROJECT_ROOT / 'frontend/tests/run-e2e.mjs')]
                    completed = subprocess.run(command, cwd=PROJECT_ROOT / 'frontend', env=environment,
                        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding='utf-8', errors='replace',
                        timeout=300, creationflags=subprocess.CREATE_NO_WINDOW)
                    # Raw browser failure output may contain filled service
                    # tokens; publish only its exit result and structured report.
                    result['browser_exit_code'] = completed.returncode
                    require(completed.returncode == 0, 'S1_BROWSER_FAILED')
                final_state = manager.status()
                require(final_state == state, 'S1_APPLICATION_IDENTITY_CHANGED')
                result['status'] = 'PASS'
            except Exception as error:
                result['status'] = 'FAIL'
                result['error_type'] = type(error).__name__
                if isinstance(error, ApplicationTestError):
                    result['error_code'] = str(error)
                elif getattr(error, 'code', None) in {'START_UNCERTAIN', 'STOP_UNCERTAIN', 'CONTROL_CHANNEL_UNVERIFIED',
                                                     'APPLICATION_NOT_READY', 'PROCESS_DISCOVERY_FAILED'}:
                    result['error_code'] = error.code
            finally:
                try:
                    stopped = manager.stop(models_only=not browser)
                    result['application_cleanup_confirmed'] = bool(stopped['entries']) and all(
                        entry['status'] == 'stopped' for entry in stopped['entries'].values())
                except Exception as error:
                    result['cleanup_error_type'] = type(error).__name__
                    result['status'] = 'BLOCKED'
                if not result['application_cleanup_confirmed']:
                    result['status'] = 'BLOCKED'
                write_new(report, (json.dumps(result, indent=2, sort_keys=True) + '\n').encode())
    return result


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--browser', action='store_true')
    arguments = parser.parse_args()
    try:
        result = execute(arguments.manifest, browser=arguments.browser)
        print(json.dumps({key: value for key, value in result.items() if key not in {'source_fingerprints', 'instances'}}, sort_keys=True))
        return 0 if result['status'] == 'PASS' else 2
    except Exception as error:
        print(json.dumps({'status': 'BLOCKED', 'error_type': type(error).__name__, 'external_model_requests': 0,
                          'main_services_controlled': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
