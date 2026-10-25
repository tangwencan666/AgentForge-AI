"""Real dedicated Compose integration, exclusively on disposable hosted Ubuntu."""
from datetime import datetime
from decimal import Decimal
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from ci_vm_common import (DEMO, REPORT, ROOT, attest, docker, environment,
                          require, write_json)

PREFIX = 'agentforge-vm-mock-'
SERVICES = {'postgres': 'postgres', 'redis': 'redis', 'backend': 'api',
            'worker': 'worker', 'frontend': 'frontend'}


def decode_sse(text):
    frames = []
    for block in text.replace('\r\n', '\n').split('\n\n'):
        fields = dict(line.split(': ', 1) for line in block.splitlines() if ': ' in line)
        if 'id' in fields:
            row = json.loads(fields['data'])
            require(int(fields['id']) == row['id'], 'VM_CI_SSE_ID_MISMATCH')
            frames.append(row)
    return frames


def wait_for(operation, predicate, code, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = operation()
        if predicate(value):
            return value
        time.sleep(0.25)
    raise RuntimeError('VM_CI_TIMEOUT_' + code)


class Stack:
    def __init__(self, filename, values):
        self.filename, self.values = filename, values
        self.secrets = [values[key] for key in values if 'PASSWORD' in key or 'TOKEN' in key]
        self.env = {**environment(), 'COMPOSE_DISABLE_ENV_FILE': '1'}

    def redact(self, text):
        for value in self.secrets:
            text = text.replace(value, '[REDACTED]')
        return text

    def compose(self, *args, timeout=240, record=False):
        result = subprocess.run(['/usr/bin/docker', '--host', 'unix:///run/docker.sock', 'compose',
            '--env-file', str(self.filename), '--project-directory', str(DEMO),
            '-f', str(DEMO / 'compose.yaml'), *args], cwd=ROOT, env=self.env,
            capture_output=True, text=True, timeout=timeout)
        if record or result.returncode:
            with (REPORT / 'compose-steps.log').open('a') as file:
                file.write(self.redact(result.stdout + result.stderr) + '\n')
        require(result.returncode == 0, 'VM_CI_COMPOSE_FAILED_SEE_REDACTED_LOGS')
        return result.stdout

    def container(self, service):
        row, = json.loads(docker('container', 'inspect', PREFIX + SERVICES[service]))
        require(row['Config']['Labels'].get('ai.agentforge.instance') == self.values['VM_MOCK_INSTANCE_ID'],
                'VM_CI_CONTAINER_IDENTITY_MISMATCH')
        return row

    def query(self, sql):
        # Static SQL only, on this freshly labelled job's official PG container.
        row = self.container('postgres')
        return docker('exec', row['Id'], 'psql', '--no-psqlrc', '--username', 'postgres',
                      '--dbname', 'agentforge', '-At', '--command', sql).strip()

    def collect(self):
        for service in SERVICES:
            try:
                row = self.container(service)
                result = subprocess.run(['/usr/bin/docker', '--host', 'unix:///run/docker.sock',
                    'logs', '--tail', '500', row['Id']], env=self.env, capture_output=True,
                    text=True, timeout=15)
                (REPORT / (service + '.log')).write_text(self.redact(result.stdout + result.stderr))
            except Exception:
                pass

    def cleanup(self):
        # Only resources with the exact new instance marker may be removed.
        for kind in ('container', 'network', 'volume'):
            listed = docker(kind, 'ls', *(['-a'] if kind == 'container' else []),
                            '--filter', 'label=ai.agentforge.instance=' + self.values['VM_MOCK_INSTANCE_ID'],
                            '--format', '{{.ID}}' if kind == 'container' else '{{.Name}}').splitlines()
            for identity in listed:
                row, = json.loads(docker(kind, 'inspect', identity))
                labels = row['Config']['Labels'] if kind == 'container' else row['Labels']
                require(labels.get('ai.agentforge.instance') == self.values['VM_MOCK_INSTANCE_ID'],
                        'VM_CI_CLEANUP_IDENTITY_MISMATCH')
        self.compose('--profile', 'app', '--profile', 'migration', 'down', '--volumes', '--remove-orphans', record=True)


def validate_config(config, lock):
    require(set(config['services']) == {*SERVICES, 'migrate'}, 'VM_CI_SERVICE_SET')
    require(all(not service.get('ports') and not service.get('build')
                and not service.get('privileged') and not service.get('network_mode')
                and service.get('read_only') and service['pull_policy'] == 'never'
                for service in config['services'].values()), 'VM_CI_UNSAFE_COMPOSE')
    require(all(network['internal'] and not network.get('external')
                for network in config['networks'].values()), 'VM_CI_INTERNAL_NETWORK_REQUIRED')
    require(all(not volume.get('external') for volume in config['volumes'].values()), 'VM_CI_NEW_VOLUMES_REQUIRED')
    for name in ('backend', 'worker', 'migrate'):
        require(config['services'][name]['image'] == lock['artifacts']['backend']['image_id'], 'VM_CI_BACKEND_IMAGE')
    require(config['services']['frontend']['image'] == lock['artifacts']['frontend']['image_id'], 'VM_CI_FRONTEND_IMAGE')
    require(all(config['services'][name]['image'] == lock['official_dependencies'][name]['image_id']
                for name in ('postgres', 'redis')), 'VM_CI_OFFICIAL_DEPENDENCY_IMAGE')


def scenarios(stack, origin, result):
    opener = build_opener(ProxyHandler({}))
    headers = {'Authorization': 'Bearer ' + stack.values['VM_MOCK_ADMIN_TOKEN']}

    def request(method, path, expected=200, body=None, extra=None, raw=False):
        outgoing = Request(origin + path, method=method, headers={**headers, **(extra or {})})
        if body is not None:
            outgoing.data = json.dumps(body).encode()
            outgoing.add_header('Content-Type', 'application/json')
        try:
            response = opener.open(outgoing, timeout=12)
        except HTTPError as error:
            response = error
        with response:
            require(response.status == expected, 'VM_CI_HTTP_' + str(response.status) + '_' + path)
            content = response.read().decode()
        return content if raw else json.loads(content)['data']

    require('<html' in request('GET', '/', raw=True).lower(), 'VM_CI_FRONTEND_HTML')
    require('ready' in request('GET', '/health/ready', raw=True).lower(), 'VM_CI_API_READY')
    state = wait_for(lambda: request('GET', '/api/v1/models/runtime-status'),
                     lambda state: state['worker_available'] and state['configuration_consistent'], 'WORKER')
    for observation in (state['api'], state['worker']):
        policy = observation['policy']
        require(policy['external_calls_blocked'] and not policy['real_calls_enabled']
                and not policy['permit_issuance_enabled'] and policy['real_worker_mode'] == 'deny'
                and Decimal(policy['daily_budget_usd']) == 0 and Decimal(policy['test_budget_usd']) == 0
                and not observation['coder_credential_present'], 'VM_CI_POLICY_NOT_CLOSED')
    result['frontend_api_worker'] = {'status': 'PASS', 'configuration_consistent': True,
                                    'real_calls_enabled': False, 'permit_enabled': False, 'real_budget': '0'}

    def create():
        value = request('POST', '/api/v1/tasks', expected=202,
            extra={'Idempotency-Key': str(uuid4())}, body={
                'goal': 'Hosted VM image Mock workflow; never execute generated code',
                'execution_mode': 'mock', 'workflow': 'agents', 'require_approval': True,
                'timeout_seconds': 180, 'max_budget_usd': '1', 'max_calls': 8,
                'mock_options': {'latency_ms': 100}})
        require(value['is_mock'], 'VM_CI_TASK_NOT_MOCK')
        return value['task_id']

    def task(identity):
        value = request('GET', '/api/v1/tasks/' + identity)
        require(value['status'] not in {'failed', 'timed_out', 'limit_exceeded'}, 'VM_CI_TASK_FAILED')
        return value

    def waiting(identity):
        wait_for(lambda: task(identity), lambda value: value['status'] == 'waiting_approval', 'WAIT_APPROVAL')
        for _ in range(8):
            value = task(identity)
            require(value['status'] == 'waiting_approval' and len(value['calls']) == 1
                    and value['calls'][0]['role'] == 'planner' and value['calls'][0]['state'] == 'completed',
                    'VM_CI_PREAPPROVAL_EXECUTION')
            time.sleep(0.25)
        require(int(stack.query("SELECT count(*) FROM graph_checkpoints WHERE task_id='" + identity + "'")) > 0,
                'VM_CI_CHECKPOINT_MISSING')

    identity = create()
    result['create_returns_202'] = {'status': 'PASS', 'task_id': identity}
    waiting(identity)
    result['planner_waits_no_later_roles'] = {'status': 'PASS', 'observation_seconds': 2, 'roles': ['planner']}
    # Read from the actual SSE proxy while the task is still waiting.
    with opener.open(Request(origin + '/api/v1/tasks/' + identity + '/events', headers=headers), timeout=10) as stream:
        require(stream.headers['content-type'].startswith('text/event-stream'), 'VM_CI_LIVE_SSE_TYPE')
        while True:
            line = stream.readline().decode()
            require(line != '', 'VM_CI_LIVE_SSE_CLOSED')
            if line.startswith('id: '):
                live_id = int(line[4:])
                break
    approval = next(row for row in request('GET', '/api/v1/approvals') if row['task_id'] == identity)
    request('POST', '/api/v1/approvals/' + approval['approval_id'] + '/decision',
            body={'decision': 'approved', 'operation_hash': approval['operation_hash']})
    completed = wait_for(lambda: task(identity), lambda value: value['status'] == 'succeeded', 'SUCCEEDED')
    calls = {row['role']: row for row in completed['calls']}
    require(len(completed['calls']) == 4 and set(calls) == {'planner', 'coder', 'researcher', 'reviewer'}, 'VM_CI_ROLE_SET')
    require(all(row['state'] == 'completed' and row['is_mock'] and row['provider'] == 'mock'
                for row in calls.values()), 'VM_CI_NONMOCK_OPERATION')
    for role in ('coder', 'researcher'):
        require(datetime.fromisoformat(calls['planner']['finished_at']) <= datetime.fromisoformat(calls[role]['started_at'])
                and datetime.fromisoformat(calls[role]['finished_at']) <= datetime.fromisoformat(calls['reviewer']['started_at']),
                'VM_CI_ROLE_ORDER')
    require(Decimal(completed['usage']['real_cost_usd']) == 0 and not completed['tools'], 'VM_CI_REAL_COST_OR_TOOL')
    result['approved_task_succeeded'] = {'status': 'PASS', 'roles': list(calls), 'mock_result': completed['result'],
                                        'real_cost_usd': '0'}
    replay = request('GET', '/api/v1/tasks/' + identity + '/events', raw=True)
    require('event: completed' in replay, 'VM_CI_SSE_COMPLETED')
    ids = [row['id'] for row in decode_sse(replay)]
    require(len(ids) > 4 and ids == sorted(set(ids)), 'VM_CI_SSE_SEQUENCE')
    cursor = ids[len(ids) // 2]
    resumed = request('GET', '/api/v1/tasks/' + identity + '/events', extra={'Last-Event-ID': str(cursor)}, raw=True)
    require([row['id'] for row in decode_sse(resumed)] == [value for value in ids if value > cursor], 'VM_CI_SSE_RESUME')
    result['sse'] = {'status': 'PASS', 'events': len(ids), 'live_first_id': live_id, 'resume_cursor': cursor, 'suffix_exact': True}

    cancelled = create()
    waiting(cancelled)
    request('POST', '/api/v1/tasks/' + cancelled + '/cancel')
    wait_for(lambda: task(cancelled), lambda value: value['status'] == 'cancelled', 'CANCELLED')
    for _ in range(8):
        value = task(cancelled)
        require(value['status'] == 'cancelled' and [row['role'] for row in value['calls']] == ['planner'], 'VM_CI_CANCEL_EXECUTED')
        time.sleep(0.25)
    result['cancel_waiting'] = {'status': 'PASS', 'roles': ['planner'], 'task_id': cancelled}
    safety = {}
    for table, condition in [('model_operations', "NOT is_mock OR provider <> 'mock'"),
                              ('sandbox_executions', 'true'), ('execution_permits', 'true')]:
        safety[table] = int(stack.query('SELECT count(*) FROM ' + table + ' WHERE ' + condition))
    safety['real_cost_usd'] = stack.query('SELECT COALESCE(sum(cost_used+cost_reserved+test_cost_used+test_cost_reserved),0) FROM tenant_real_usage')
    require(all(safety[key] == 0 for key in ('model_operations', 'sandbox_executions', 'execution_permits'))
            and Decimal(safety['real_cost_usd']) == 0, 'VM_CI_FORBIDDEN_PERSISTED_EFFECT')
    result['safety'] = {'status': 'PASS', **safety, 'sandbox_configured': False, 'mock_budget_usd': '10', 'mock_token_limit': 1000000}


def main():
    run, revision = attest()
    lock = json.loads((REPORT / 'images.resolved.json').read_text())
    require(lock['build_status'] == 'BUILT' and lock['build_revision'] == revision, 'VM_CI_IMAGES_NOT_CURRENT')
    # Refuse pre-existing resource names before creating any data or credentials.
    for kind in ('container', 'network', 'volume'):
        names = docker(kind, 'ls', *(['-a'] if kind == 'container' else []), '--format', '{{.Names}}' if kind == 'container' else '{{.Name}}')
        require(not any(name.startswith(PREFIX) for name in names.splitlines()), 'VM_CI_RESOURCE_COLLISION')
    result = {'run': run, 'build_commit': revision, 'conclusion': 'FAIL', 'scenarios': {}}
    details = result['scenarios']
    values = {'VM_MOCK_INSTANCE_ID': str(uuid4()),
              **{key: secrets.token_hex(32) for key in ('VM_MOCK_APP_PASSWORD', 'VM_MOCK_REDIS_PASSWORD',
                                                       'VM_MOCK_ADMIN_TOKEN', 'VM_MOCK_POSTGRES_PASSWORD')},
              'VM_MOCK_BACKEND_IMAGE': lock['artifacts']['backend']['image_id'],
              'VM_MOCK_FRONTEND_IMAGE': lock['artifacts']['frontend']['image_id'],
              'VM_MOCK_POSTGRES_IMAGE': lock['official_dependencies']['postgres']['image_id'],
              'VM_MOCK_REDIS_IMAGE': lock['official_dependencies']['redis']['image_id']}
    for key, value in values.items():
        if 'PASSWORD' in key or 'TOKEN' in key:
            print('::add-mask::' + value, flush=True)
    with tempfile.TemporaryDirectory(prefix='vm-mock-private-', dir=os.environ['RUNNER_TEMP']) as temporary:
        filename = Path(temporary) / 'demo.inputs'
        filename.write_text(''.join(key + '=' + value + '\n' for key, value in values.items()))
        filename.chmod(0o600)
        stack = Stack(filename, values)
        started = False
        try:
            config = json.loads(stack.compose('--profile', 'data', '--profile', 'migration', '--profile', 'app', 'config', '--format', 'json'))
            validate_config(config, lock)
            details['compose_config'] = {'status': 'PASS', 'published_ports': 0, 'internal_networks': 2}
            started = True
            stack.compose('--profile', 'data', 'up', '-d', '--wait', '--wait-timeout', '120', 'postgres', 'redis', record=True)
            require(stack.query("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'") == '0', 'VM_CI_DATABASE_NOT_EMPTY')
            require(stack.query('SELECT instance::text FROM vm_demo_guard.identity') == values['VM_MOCK_INSTANCE_ID'], 'VM_CI_FRESH_DATABASE_MARKER')
            details['data_services'] = {'status': 'PASS', 'postgres': 'healthy', 'redis': 'healthy', 'fresh_public_tables': 0}
            stack.compose('--profile', 'migration', 'run', '--rm', '--no-deps', 'migrate', record=True)
            require(stack.query('SELECT version_num FROM alembic_version') == '0010_sandbox_maintenance', 'VM_CI_MIGRATION_VERSION')
            details['migration'] = {'status': 'PASS', 'fresh_marked_database_only': True, 'version': '0010_sandbox_maintenance'}
            stack.compose('--profile', 'app', 'up', '-d', '--wait', '--wait-timeout', '150', 'backend', 'worker', 'frontend', record=True)
            observed = {}
            for service in SERVICES:
                row = stack.container(service)
                require(not row['HostConfig'].get('PortBindings') and not row['HostConfig']['Privileged']
                        and row['HostConfig']['ReadonlyRootfs'] and row['State']['Health']['Status'] == 'healthy', 'VM_CI_CONTAINER_ISOLATION')
                expected = (lock['official_dependencies'][service]['image_id'] if service in ('postgres', 'redis')
                            else lock['artifacts']['frontend' if service == 'frontend' else 'backend']['image_id'])
                require(row['Image'] == expected, 'VM_CI_RUNNING_IMAGE_ID_MISMATCH')
                observed[service] = {'id': row['Id'], 'image_id': row['Image'], 'health': row['State']['Health']['Status'],
                                      'memory_limit': row['HostConfig']['Memory'], 'networks': list(row['NetworkSettings']['Networks'])}
            for name in ('data', 'web'):
                network, = json.loads(docker('network', 'inspect', PREFIX + name))
                require(network['Internal'] and network['Labels'].get('ai.agentforge.instance') == values['VM_MOCK_INSTANCE_ID'], 'VM_CI_NETWORK_IDENTITY')
            frontend = stack.container('frontend')
            address = frontend['NetworkSettings']['Networks'][PREFIX + 'web']['IPAddress']
            require(ipaddress.ip_address(address).is_private, 'VM_CI_FRONTEND_IP')
            result['isolation'] = {'instance': values['VM_MOCK_INSTANCE_ID'], 'containers': observed,
                                    'published_ports': 0, 'network_internal': True, 'generated_code_executed': False}
            backend = stack.container('backend')
            result['runtime_versions'] = json.loads(docker('exec', backend['Id'], 'python', '-c',
                'import json,platform,sys; release=platform.freedesktop_os_release(); '
                'print(json.dumps({"python":sys.version.split()[0],"libc":platform.libc_ver(),'
                '"image_os":release.get("ID"),"image_os_version":release.get("VERSION_ID"),'
                '"shared_host_kernel":platform.release(),"architecture":platform.machine()}))'))
            result['runtime_versions']['postgres'] = stack.query('SELECT version()')
            result['runtime_versions']['redis'] = docker('exec', stack.container('redis')['Id'], 'redis-server', '--version').strip()
            result['runtime_versions']['frontend_alpine'] = docker('exec', frontend['Id'], 'cat', '/etc/alpine-release').strip()
            scenarios(stack, 'http://' + address + ':8080', details)
            result['conclusion'] = 'PASS'
        except Exception as error:
            result['failure'] = {'type': type(error).__name__, 'code': str(error) if type(error) is RuntimeError else 'SEE_REDACTED_LOGS'}
            raise
        finally:
            stack.collect()
            if started:
                try:
                    stack.cleanup()
                    result['cleanup'] = 'PASS'
                except Exception:
                    result['cleanup'] = 'FAIL'
                    result['conclusion'] = 'FAIL'
            write_json('compose-result.json', result)
            print(json.dumps(result, indent=2))
    require(result['conclusion'] == 'PASS', 'VM_CI_INTEGRATION_FAILED')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Hosted Compose failed: ' + (str(error) if type(error) is RuntimeError else type(error).__name__))
        raise SystemExit(1) from None
