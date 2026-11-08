"""New hosted entrypoint; refuses local/self-hosted use before any Docker call."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from ci_mock_isolation import hosted_context, require

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / 'deploy/vm-mock'
REPORT = ROOT / 'work/vm-image-ci/evidence'
ARCHIVES = ROOT / 'work/vm-image-ci/archives'
FORBIDDEN_ENGINES = {'f270beef-fc00-4691-8d57-a6643ad6f7cd',
                     'a2353ec2-7b5f-4343-a16b-8a04bc95ec51'}


def environment():
    # No host application configuration, model keys, Docker context override,
    # Compose dotenv selection or registry credentials are forwarded.
    return {name: os.environ[name] for name in ('PATH', 'HOME', 'LANG', 'LC_ALL')
            if name in os.environ}


def command(arguments, *, env=None, timeout=120, capture=True):
    result = subprocess.run(arguments, cwd=ROOT, env=environment() if env is None else env,
                            capture_output=capture, text=True, timeout=timeout)
    if result.returncode:
        # Keep command arguments/config/secrets out of failure messages.
        raise RuntimeError('VM_CI_COMMAND_FAILED_' + Path(arguments[0]).name)
    return result.stdout if capture else ''


def docker(*args, **kwargs):
    return command(['/usr/bin/docker', '--host', 'unix:///run/docker.sock', *args], **kwargs)


def write_json(name, value):
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def attest():
    run = hosted_context(ROOT, os.environ)
    require(os.environ.get('GITHUB_EVENT_NAME') == 'pull_request', 'VM_CI_PR_REQUIRED')
    info = json.loads(docker('info', '--format', '{{json .}}'))
    require(info['ID'] not in FORBIDDEN_ENGINES and info['OSType'] == 'linux'
            and info['Architecture'] in {'x86_64', 'amd64'}
            and info['Swarm']['LocalNodeState'] == 'inactive', 'VM_CI_ENGINE_MISMATCH')
    revision = command(['git', 'rev-parse', 'HEAD']).strip()
    write_json('host.json', {'run': run, 'build_commit': revision,
        'run_url': 'https://github.com/tangwencan666/AgentForge-AI/actions/runs/' + os.environ['GITHUB_RUN_ID'],
        'engine_id': info['ID'], 'os': info['OperatingSystem'], 'kernel': info['KernelVersion'],
        'architecture': info['Architecture'], 'storage_driver': info['Driver'],
        'cgroup_driver': info['CgroupDriver'], 'cgroup_version': info['CgroupVersion'],
        'security_options': info['SecurityOptions'], 'docker_root_dir': info['DockerRootDir'],
        'docker_version': info['ServerVersion'],
        'compose_version': docker('compose', 'version', '--short').strip()})
    return run, revision
