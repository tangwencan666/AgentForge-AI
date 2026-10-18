"""Project-only maintenance environment; model credential values are never parsed."""
import argparse
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'work/p5-live-preflight'
ENV_FILE = DIRECTORY / '.env'
OS_NAMES = ('SystemRoot', 'WINDIR', 'PATH', 'PATHEXT', 'COMSPEC', 'TEMP', 'TMP', 'APPDATA',
            'LOCALAPPDATA', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'DOCKER_HOST', 'DOCKER_CONTEXT',
            'DOCKER_CONFIG', 'HOME', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData', 'ALLUSERSPROFILE', 'SystemDrive')
ISSUER_NAME = 'AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN'
MODEL_POLICY_NAMES = frozenset({'AGENTFORGE_MODEL_PRICES', 'AGENTFORGE_MODEL_CREDENTIAL_HOSTS',
                                'AGENTFORGE_MODEL_CREDENTIALS_ENV_ONLY'})
SERVICE_NAMES = frozenset({'COMPOSE_PROJECT_NAME', 'POSTGRES_PORT', 'REDIS_PORT', 'BACKEND_PORT',
                           'FRONTEND_PORT', 'SANDBOX_RUNNER_PORT', 'POSTGRES_PASSWORD',
                           'APP_DB_PASSWORD', 'REDIS_PASSWORD'})
# Inspect a declaration's name before passing any selected line to dotenv. A
# quoted/lowercase name and a declaration without '=' must not conceal authority.
DECLARATION = re.compile(r"^\s*(?:export\s+)?(?:'([A-Za-z_][A-Za-z0-9_]*)'|([A-Za-z_][A-Za-z0-9_]*))(?=\s*(?:=|#|$))")


class PreflightError(RuntimeError):
    """Static diagnostic codes only, never dotenv input or credential values."""


def credential_name(name):
    name = name.upper()
    return name == ISSUER_NAME or name.startswith('AGENTFORGE_MODEL_') and name not in MODEL_POLICY_NAMES


def declaration_name(line):
    match = DECLARATION.match(line)
    return (match.group(1) or match.group(2)).upper() if match else None


def prepare_allowed_names():
    from app.core.config import Settings
    names = {'AGENTFORGE_' + name.upper() for name in Settings.model_fields} | SERVICE_NAMES
    # The issuer is a Settings field, but is not maintenance service authority.
    # Keep this filter independent of core/config's model-reference classifier.
    return frozenset(name for name in names if not credential_name(name))


def require_service_only_file(path):
    """Read declaration names only; refuse existing secrets without parsing them."""
    if not path.exists():
        return
    with path.open(encoding='utf-8-sig') as stream:
        for opaque_line in stream:
            name = declaration_name(opaque_line)
            if name and credential_name(name):
                raise PreflightError('SERVICE_FILE_CREDENTIAL_DECLARATION_FORBIDDEN')


def prepare():
    # Direct imports/calls receive the same protection as the CLI entry point.
    from maintenance_policy import maintenance_operation
    with maintenance_operation(ROOT, 'preflight.prepare'):
        return _prepare_service_configuration()


def _prepare_service_configuration():
    if ISSUER_NAME in os.environ:
        raise PreflightError('ISSUER_AUTHORITY_FORBIDDEN_IN_PREPARATION')
    require_service_only_file(ENV_FILE)
    allowed = prepare_allowed_names()
    selected, declared = [], set()
    with (ROOT / '.env').open(encoding='utf-8-sig') as stream:
        for opaque_line in stream:
            name = declaration_name(opaque_line)
            if name == ISSUER_NAME:
                raise PreflightError('ISSUER_DECLARATION_FORBIDDEN_IN_PREPARATION')
            if name and credential_name(name):
                declared.add(name)
                continue  # No value extraction, interpolation, validation, copying or output.
            if name in allowed:
                selected.append(opaque_line)
    values = dict(dotenv_values(stream=io.StringIO(''.join(selected)), interpolate=False))
    values = {key.upper(): value for key, value in values.items() if key.upper() in allowed and value is not None}
    for name in allowed:
        if name in os.environ: values[name] = os.environ[name]
    if any('${' in value for value in values.values()):
        raise RuntimeError('Interpolated service configuration is not accepted in maintenance')
    from urllib.parse import urlsplit
    db = urlsplit(values['AGENTFORGE_DATABASE_URL'])
    redis = urlsplit(values['AGENTFORGE_REDIS_URL'])
    assert db.hostname == '127.0.0.1' and db.port == int(values.get('POSTGRES_PORT', '15432')) and db.path == '/agentforge'
    assert redis.hostname == '127.0.0.1' and redis.port == int(values.get('REDIS_PORT', '16379')) and redis.path == '/0'
    assert values.get('COMPOSE_PROJECT_NAME', 'agentforge-p1') == 'agentforge-p1'
    original = {key: values.get(key, 'default') for key in ('AGENTFORGE_REAL_CALLS_ENABLED',
        'AGENTFORGE_REAL_DAILY_BUDGET_USD', 'AGENTFORGE_REAL_TEST_BUDGET_USD', 'AGENTFORGE_REAL_TEST_MAX_CALLS')}
    values.update(AGENTFORGE_REAL_CALLS_ENABLED='false', AGENTFORGE_REAL_DAILY_BUDGET_USD='0',
                  AGENTFORGE_REAL_TEST_BUDGET_USD='0', AGENTFORGE_REAL_TEST_MAX_CALLS='1')
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text(''.join(key + '=' + json.dumps(value, ensure_ascii=False) + '\n' for key, value in sorted(values.items())), encoding='utf-8')
    names = declared | {name for name in os.environ if credential_name(name)}
    names.update('AGENTFORGE_MODEL_' + role + '_KEY' for role in ('PLANNER', 'CODER', 'RESEARCHER', 'REVIEWER'))
    record = {'original_policy': original, 'maintenance_real_calls_enabled': False, 'maintenance_budgets_usd': '0',
              'credential_presence': {name: {'process_variable_exists': name in os.environ, 'dotenv_name_declared': name in declared} for name in sorted(names)},
              'model_credential_values': 'not_parsed_or_copied', 'project_database': 'agentforge', 'settings_path': str(ENV_FILE)}
    (DIRECTORY / 'preparation.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps(record))
    return record


def trusted_command(arguments, cwd):
    """A fixed maintenance/observation launcher, never a general shell bridge."""
    if cwd != '.' or len(arguments) < 2:
        raise PreflightError('COMMAND_SCOPE_REQUIRED')
    executable, *tail = arguments
    python = ROOT / '.venv/Scripts/python.exe'
    candidate = Path(executable)
    if executable != 'python' and (candidate if candidate.is_absolute() else ROOT / candidate).resolve() != python.resolve():
        raise PreflightError('PROJECT_PYTHON_REQUIRED')
    flags = ['-B'] if tail and tail[0] == '-B' else []
    if flags:
        tail = tail[1:]
    if not tail:
        raise PreflightError('TRUSTED_SCRIPT_REQUIRED')
    script, *options = tail
    candidate = Path(script)
    selected = (candidate if candidate.is_absolute() else ROOT / candidate).resolve()
    scripts = {name: (ROOT / 'scripts' / name).resolve() for name in (
        'lifecycle.py', 'check_secrets.py', 'test-offline.py', 'check-coder-local.py', 'migrate.py')}
    name = next((name for name, path in scripts.items() if path == selected), None)
    permitted = (
        name == 'lifecycle.py' and len(options) == 3 and options[:2] == ['maintenance-run', '--phase']
        and options[2] in {'p2', 'p3', 'p4', 'p5'}
        or name == 'check_secrets.py' and options == ['--no-local-secrets']
        or name == 'test-offline.py' and tuple(options) in {(), ('--frontend',), ('--browser',)}
        or name == 'check-coder-local.py' and tuple(options) in {(), ('--before-restart',)}
        or name == 'migrate.py' and tuple(options) in {('check',), ('current',)}
    )
    if not permitted:
        raise PreflightError('COMMAND_NOT_ALLOWLISTED')
    return [str(python), *flags, str(selected), *options]


def run(arguments, cwd, selected=None):
    command = trusted_command(list(arguments), cwd)
    env_file = Path(selected).resolve() if selected else ENV_FILE
    if not env_file.is_relative_to(ROOT / 'work') or env_file.name != '.env' or not env_file.is_file():
        raise PreflightError('SERVICE_FILE_REQUIRED')
    require_service_only_file(env_file)
    environment = {name: os.environ[name] for name in OS_NAMES if name in os.environ}
    environment.update(AGENTFORGE_SETTINGS_FILE=str(env_file), AGENTFORGE_EXTERNAL_MODELS_BLOCKED='1',
        AGENTFORGE_REAL_MAX_RETRIES='0', AGENTFORGE_MODEL_CREDENTIALS_ENV_ONLY='true',
        AGENTFORGE_RUN_INTEGRATION='1', AGENTFORGE_RUN_SANDBOX='1', PYTHONIOENCODING='utf-8',
        PYTHONPATH=os.pathsep.join((str(ROOT / 'backend'), str(ROOT / 'tests/fixtures'))),
        LANGCHAIN_TRACING_V2='false', LANGSMITH_TRACING='false', COMPOSE_DISABLE_ENV_FILE='1')
    if (env_file.parent / 'compose.yaml').is_file():
        environment['AGENTFORGE_COMPOSE_FILE'] = str(env_file.parent / 'compose.yaml')
    result = subprocess.run(command, cwd=ROOT / cwd, env=environment)
    return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('--cwd', choices=['.', 'frontend'], default='.')
    parser.add_argument('--settings-file')
    options, command = parser.parse_known_args(argv)
    if command and command[0] == '--': command.pop(0)
    try:
        if options.action == 'prepare':
            if command or options.settings_file is not None or options.cwd != '.':
                raise PreflightError('PREPARATION_ARGUMENTS_FORBIDDEN')
            prepare()
            return 0
        if not command:
            raise PreflightError('COMMAND_REQUIRED')
        return run(command, options.cwd, options.settings_file)
    except Exception as exc:
        print('Preflight operation failed: ' + type(exc).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
