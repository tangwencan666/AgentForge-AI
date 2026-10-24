"""Separate hosted-CI boundary; never grants access to the local S1 stack."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def hosted_context(root, environment, platform=sys.platform):
    require(platform == 'linux' and environment.get('GITHUB_ACTIONS') == 'true'
            and environment.get('RUNNER_ENVIRONMENT') == 'github-hosted'
            and environment.get('RUNNER_OS') == 'Linux', 'CI_HOSTED_LINUX_REQUIRED')
    require(environment.get('GITHUB_REPOSITORY') == 'tangwencan666/AgentForge-AI', 'CI_REPOSITORY_MISMATCH')
    require(str(root) == environment.get('GITHUB_WORKSPACE')
            and root == Path('/home/runner/work/AgentForge-AI/AgentForge-AI')
            and not root.is_symlink(), 'CI_WORKSPACE_MISMATCH')
    require(not (root / '.env').exists(), 'CI_PROJECT_ENV_PRESENT')
    run, attempt = environment.get('GITHUB_RUN_ID', ''), environment.get('GITHUB_RUN_ATTEMPT', '')
    require(run.isdecimal() and attempt.isdecimal(), 'CI_RUN_ID_REQUIRED')
    return run + '-' + attempt


def inspect_service(row, role, run):
    require(role in {'postgres', 'redis'}, 'CI_SERVICE_ROLE_INVALID')
    labels = row['Config'].get('Labels') or {}
    require(all(labels.get(k) == v for k, v in {
        'ai.agentforge.ci': 'mock-workflow', 'ai.agentforge.ci.run': run,
        'ai.agentforge.ci.role': role}.items()), 'CI_SERVICE_LABEL_MISMATCH')
    host, state = row['HostConfig'], row['State']
    require(state['Running'] and state.get('Health', {}).get('Status') == 'healthy', 'CI_SERVICE_NOT_HEALTHY')
    require(not host['Privileged'] and host['RestartPolicy']['Name'] == 'no'
            and not host.get('Binds') and not host.get('VolumesFrom'), 'CI_PERSISTENT_OR_PRIVILEGED_SERVICE')
    target, port = ('/var/lib/postgresql/data', '5432/tcp') if role == 'postgres' else ('/data', '6379/tcp')
    require(set(host.get('Tmpfs') or {}) == {target}, 'CI_TMPFS_REQUIRED')
    require(all(mount.get('Type') == 'tmpfs' and mount.get('Destination') == target
                for mount in row.get('Mounts', [])), 'CI_PERSISTENT_MOUNT_FORBIDDEN')
    bindings = row['NetworkSettings']['Ports']
    require(set(bindings) == {port} and len(bindings[port]) == 1, 'CI_PORT_BINDING_INVALID')
    binding = bindings[port][0]
    require(binding['HostIp'] == '127.0.0.1' and binding['HostPort'].isdecimal(), 'CI_LOOPBACK_REQUIRED')
    assigned = int(binding['HostPort'])
    require(30000 <= assigned <= 65535, 'CI_RANDOM_PORT_REQUIRED')
    networks = row['NetworkSettings']['Networks']
    require(len(networks) == 1, 'CI_SERVICE_NETWORK_INVALID')
    network = next(iter(networks.values()))['NetworkID']
    require(re.fullmatch('[a-f0-9]{64}', network) is not None, 'CI_SERVICE_NETWORK_INVALID')
    return assigned, network


def attest_services(root, environment):
    run = hosted_context(root, environment)  # Must precede every Docker call.
    result, rows = {}, {}
    for role in ('postgres', 'redis'):
        identity = environment.get('AGENTFORGE_CI_' + role.upper() + '_ID', '')
        require(re.fullmatch('[a-f0-9]{64}', identity) is not None, 'CI_SERVICE_ID_REQUIRED')
        data = subprocess.check_output(['/usr/bin/docker', 'inspect', identity],
                                       env={'PATH': '/usr/bin:/bin'}, timeout=15)
        row, = json.loads(data)
        require(row['Id'] == identity, 'CI_SERVICE_ID_MISMATCH')
        port, network = inspect_service(row, role, run)
        rows[role] = row
        result[role] = {'id': identity, 'port': port, 'network': network, 'image_id': row['Image']}
    network = result['postgres']['network']
    require(network == result['redis']['network'] and result['postgres']['port'] != result['redis']['port'],
            'CI_SERVICE_NETWORK_MISMATCH')
    observed, = json.loads(subprocess.check_output(['/usr/bin/docker', 'network', 'inspect', network],
                                                  env={'PATH': '/usr/bin:/bin'}, timeout=15))
    require(observed['Id'] == network and observed['Driver'] == 'bridge'
            and set(observed['Containers']) == {r['id'] for r in result.values()}, 'CI_NETWORK_MEMBERSHIP_MISMATCH')
    return run, result


def audit_guard(endpoints, child=False):
    """All Python clients get only the attested test endpoints, never Runner."""
    allowed = frozenset(('127.0.0.1', port) for port in endpoints)

    def audit(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            name = Path(os.fsdecode(args[0])).name
            if name == '.env' or name.startswith('.env.') and name != '.env.example':
                raise RuntimeError('CI_DOTENV_READ_FORBIDDEN')
        if event in {'socket.connect', 'socket.getaddrinfo'}:
            address = args[1] if event == 'socket.connect' else args[:2]
            if not isinstance(address, tuple) or len(address) < 2 or address[:2] not in allowed:
                raise RuntimeError('CI_NETWORK_ENDPOINT_FORBIDDEN')
        if event in {'os.system', 'os.posix_spawn'} or child and event == 'subprocess.Popen':
            raise RuntimeError('CI_CHILD_EXECUTION_FORBIDDEN')

    return audit


def install_guard(root, endpoints, child=False):
    audit = audit_guard(endpoints, child)
    sys.addaudithook(audit)
    return audit
