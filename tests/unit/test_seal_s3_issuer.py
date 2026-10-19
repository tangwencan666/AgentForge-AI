"""SEAL-S3: isolated work fixtures, fake authority and no real subprocesses."""
from contextlib import contextmanager
from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

from dotenv.main import dotenv_values as parse_controlled_dotenv
import pytest


ROOT = Path(__file__).resolve().parents[2]
ISSUER = 'AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN'
MODEL_KEY = 'AGENTFORGE_MODEL_CODER_KEY'
FAKE_ISSUER = 'EXPLICIT_FAKE_ISSUER_FOR_OFFLINE_UNIT_TEST_ONLY'
FAKE_MODEL = 'EXPLICIT_FAKE_MODEL_FOR_OFFLINE_UNIT_TEST_ONLY'
BASE = ('AGENTFORGE_DATABASE_URL=postgresql+asyncpg://agentforge:unit-only@127.0.0.1:15432/agentforge\n'
        'AGENTFORGE_REDIS_URL=redis://:unit-only@127.0.0.1:16379/0\n'
        'COMPOSE_PROJECT_NAME=agentforge-p1\n')


class NameOnlySecrets:
    """A credential lookup fails the test before its fake value can be obtained."""
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.reads = []

    def __contains__(self, name):
        return name in self.values

    def __iter__(self):
        return iter(self.values)

    def __getitem__(self, name):
        if name == ISSUER or name.startswith('AGENTFORGE_MODEL_') and name not in {
            'AGENTFORGE_MODEL_PRICES', 'AGENTFORGE_MODEL_CREDENTIAL_HOSTS', 'AGENTFORGE_MODEL_CREDENTIALS_ENV_ONLY'
        }:
            raise AssertionError('Credential value lookup is forbidden in this fixture')
        self.reads.append(name)
        return self.values[name]


@pytest.fixture
def preflight(monkeypatch):
    # Import must not parse argv, read settings or perform a maintenance action.
    spec = importlib.util.spec_from_file_location('seal_s3_preflight_' + uuid4().hex,
                                                ROOT / 'scripts/p5-live-preflight.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    project = ROOT / 'work/seal-fixes/s3' / uuid4().hex
    directory = project / 'work/p5-live-preflight'
    directory.mkdir(parents=True)
    (project / '.env').write_text(BASE, encoding='utf-8')
    (directory / '.env').write_text(BASE, encoding='utf-8')
    monkeypatch.setattr(module, 'ROOT', project)
    monkeypatch.setattr(module, 'DIRECTORY', directory)
    monkeypatch.setattr(module, 'ENV_FILE', directory / '.env')
    # offline_guards intentionally replaces the package facade. Only this
    # fixture's in-memory, already filtered text uses the real dotenv parser.
    monkeypatch.setattr(module, 'dotenv_values', parse_controlled_dotenv)
    environment = NameOnlySecrets({'SystemRoot': 'explicit-os-runtime', 'PATH': 'explicit-runtime-path'})
    monkeypatch.setattr(module, 'os', SimpleNamespace(environ=environment, pathsep=os.pathsep, path=os.path))
    events, children = [], []

    @contextmanager
    def guard(root, operation):
        assert root == project and operation == 'preflight.prepare'
        events.append('guard_enter')
        try:
            yield
        finally:
            events.append('guard_exit')

    monkeypatch.setitem(sys.modules, 'maintenance_policy', SimpleNamespace(maintenance_operation=guard))

    def subprocess_double(arguments, *, cwd, env):
        children.append(SimpleNamespace(arguments=arguments, cwd=cwd, environment=env))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(module, 'subprocess', SimpleNamespace(run=subprocess_double))
    return SimpleNamespace(module=module, project=project, directory=directory,
                           environment=environment, events=events, children=children)


def unchanged(path, previous):
    if path.read_bytes() != previous:
        raise AssertionError('Controlled fixture was unexpectedly overwritten')


def no_secret_output(captured):
    # Never include the fixture value in a diagnostic or an assertion message.
    if FAKE_ISSUER in captured.out + captured.err or FAKE_MODEL in captured.out + captured.err:
        raise AssertionError('Credential fixture appeared in output')


def test_import_has_no_cli_or_settings_side_effects(preflight):
    assert preflight.events == [] and preflight.children == []
    assert not (preflight.directory / 'preparation.json').exists()


def test_allowlist_excludes_issuer_and_all_model_credentials(preflight):
    allowed = preflight.module.prepare_allowed_names()
    assert ISSUER not in allowed and MODEL_KEY not in allowed
    assert all(not preflight.module.credential_name(name) for name in allowed)
    assert preflight.module.MODEL_POLICY_NAMES <= allowed
    assert 'AGENTFORGE_DATABASE_URL' in allowed
    assert preflight.module.credential_name('AGENTFORGE_MODEL_FUTURE_PROVIDER_KEY')


@pytest.mark.parametrize('declaration', [
    ISSUER + '=' + FAKE_ISSUER + '\n',
    'export ' + ISSUER + '="' + FAKE_ISSUER + '"\n',
    ISSUER.lower() + '=' + FAKE_ISSUER + '\n',
    "'" + ISSUER + "'='" + FAKE_ISSUER + "'\n",
    ISSUER + '\n',
], ids=['plain', 'export', 'lowercase', 'quoted', 'valueless'])
@pytest.mark.parametrize('location', ['source', 'target'])
def test_issuer_declaration_refuses_before_dotenv_and_preserves_files(preflight, monkeypatch, capsys,
                                                                    declaration, location):
    module = preflight.module
    source, target = preflight.project / '.env', module.ENV_FILE
    selected = source if location == 'source' else target
    selected.write_text(BASE + declaration, encoding='utf-8')
    before_source, before_target = source.read_bytes(), target.read_bytes()

    def no_parser(*_args, **_kwargs):
        raise AssertionError('Issuer declaration must be rejected before dotenv parsing')

    monkeypatch.setattr(module, 'dotenv_values', no_parser)
    assert module.main(['prepare']) == 1
    assert preflight.events == ['guard_enter', 'guard_exit']
    unchanged(source, before_source)
    unchanged(target, before_target)
    assert not (preflight.directory / 'preparation.json').exists()
    no_secret_output(capsys.readouterr())


def test_issuer_environment_is_rejected_without_resolving_or_removing_it(preflight, monkeypatch, capsys):
    module = preflight.module
    preflight.environment.values[ISSUER] = FAKE_ISSUER
    previous = module.ENV_FILE.read_bytes()

    def no_parser(*_args, **_kwargs):
        raise AssertionError('Issuer environment must be rejected before dotenv parsing')

    monkeypatch.setattr(module, 'dotenv_values', no_parser)
    assert module.main(['prepare']) == 1
    assert ISSUER in preflight.environment.values and preflight.environment.reads == []
    unchanged(module.ENV_FILE, previous)
    no_secret_output(capsys.readouterr())


def test_source_model_values_are_dropped_before_parser_and_environment_override(preflight, monkeypatch, capsys):
    module = preflight.module
    (preflight.project / '.env').write_text(BASE + MODEL_KEY + '=' + FAKE_MODEL + '\n', encoding='utf-8')
    preflight.environment.values[MODEL_KEY] = FAKE_MODEL
    preflight.environment.values['AGENTFORGE_MODEL_FUTURE_PROVIDER_KEY'] = FAKE_MODEL
    preflight.environment.values['AGENTFORGE_REAL_DAILY_BUDGET_USD'] = '1'
    observed = []

    def controlled_parser(*, stream, interpolate):
        text = stream.getvalue()
        if FAKE_MODEL in text or MODEL_KEY in text:
            raise AssertionError('Model credential reached dotenv parser')
        observed.append(True)
        assert interpolate is False
        return parse_controlled_dotenv(stream=stream, interpolate=False)

    monkeypatch.setattr(module, 'dotenv_values', controlled_parser)
    record = module.prepare()
    assert observed == [True] and preflight.events == ['guard_enter', 'guard_exit']
    assert record['credential_presence'][MODEL_KEY] == {'process_variable_exists': True, 'dotenv_name_declared': True}
    assert MODEL_KEY in preflight.environment.values
    content = module.ENV_FILE.read_text(encoding='utf-8')
    if FAKE_MODEL in content or MODEL_KEY in content or ISSUER in content:
        raise AssertionError('Prepared service file contains a credential')
    assert 'AGENTFORGE_REAL_DAILY_BUDGET_USD="0"' in content
    no_secret_output(capsys.readouterr())


def test_existing_model_credential_target_is_preserved_and_refused(preflight, capsys):
    module = preflight.module
    module.ENV_FILE.write_text(BASE + MODEL_KEY + '=' + FAKE_MODEL + '\n', encoding='utf-8')
    previous = module.ENV_FILE.read_bytes()
    assert module.main(['prepare']) == 1
    unchanged(module.ENV_FILE, previous)
    no_secret_output(capsys.readouterr())


def test_protected_refusal_precedes_input_or_target_reads(preflight, monkeypatch, capsys):
    @contextmanager
    def denied(_root, _operation):
        raise RuntimeError('EXPLICIT_PROTECTED_FIXTURE')
        yield

    monkeypatch.setitem(sys.modules, 'maintenance_policy', SimpleNamespace(maintenance_operation=denied))
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        if path.name == '.env':
            raise AssertionError('Maintenance refusal must happen before configuration access')
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', guarded_open)
    assert preflight.module.main(['prepare']) == 1
    assert preflight.children == []
    no_secret_output(capsys.readouterr())


def test_run_drops_parent_issuer_and_model_keys_without_value_reads_or_parent_mutation(preflight, capsys):
    module = preflight.module
    preflight.environment.values.update({ISSUER: FAKE_ISSUER, MODEL_KEY: FAKE_MODEL,
                                         'AGENTFORGE_ADMIN_TOKEN': 'EXPLICIT_FAKE_PARENT_ADMIN'})
    command = ['python', '-B', 'scripts/check-coder-local.py']
    assert module.main(['run', '--settings-file', str(module.ENV_FILE), '--', *command]) == 7
    assert preflight.events == [] and len(preflight.children) == 1
    child = preflight.children[0]
    assert child.arguments == [str(preflight.project / '.venv/Scripts/python.exe'), '-B',
                               str(preflight.project / 'scripts/check-coder-local.py')]
    assert child.cwd == preflight.project
    assert child.environment['AGENTFORGE_SETTINGS_FILE'] == str(module.ENV_FILE)
    assert child.environment['AGENTFORGE_EXTERNAL_MODELS_BLOCKED'] == '1'
    assert child.environment['LANGSMITH_TRACING'] == 'false'
    assert ISSUER not in child.environment and MODEL_KEY not in child.environment
    assert 'AGENTFORGE_ADMIN_TOKEN' not in child.environment
    assert ISSUER in preflight.environment.values and MODEL_KEY in preflight.environment.values
    assert set(preflight.environment.reads) <= set(module.OS_NAMES)
    assert command[0] == 'python'
    no_secret_output(capsys.readouterr())


@pytest.mark.parametrize('name', [ISSUER, MODEL_KEY, 'AGENTFORGE_MODEL_FUTURE_PROVIDER_KEY'])
def test_run_refuses_selected_file_credentials_before_starting_child(preflight, capsys, name):
    module = preflight.module
    module.ENV_FILE.write_text(BASE + name + '=' + FAKE_ISSUER + '\n', encoding='utf-8')
    assert module.main(['run', '--', 'python', 'scripts/check-coder-local.py']) == 1
    assert preflight.children == [] and preflight.events == []
    no_secret_output(capsys.readouterr())


def test_run_retains_selected_clone_compose_and_fixed_frontend_test_entry(preflight):
    module = preflight.module
    (preflight.directory / 'compose.yaml').write_text('name: explicit-unit-double\n', encoding='utf-8')
    assert module.run(['python', 'scripts/test-offline.py', '--frontend'], '.') == 7
    child = preflight.children[0]
    assert child.cwd == preflight.project
    assert child.arguments[1:] == [str(preflight.project / 'scripts/test-offline.py'), '--frontend']
    assert child.environment['AGENTFORGE_COMPOSE_FILE'] == str(preflight.directory / 'compose.yaml')


@pytest.mark.parametrize('scope', ['root_env', 'missing_file', 'wrong_cwd'])
def test_invalid_run_scope_refuses_without_child(preflight, capsys, scope):
    module = preflight.module
    arguments = ['run', '--', 'python', 'scripts/check-coder-local.py']
    if scope == 'root_env':
        arguments = ['run', '--settings-file', str(preflight.project / '.env'), '--', 'python', 'scripts/check-coder-local.py']
    elif scope == 'missing_file':
        arguments = ['run', '--settings-file', str(preflight.project / 'work/missing/.env'), '--', 'python', 'scripts/check-coder-local.py']
    else:
        with pytest.raises(module.PreflightError):
            module.run(['python'], '..')
        return
    assert module.main(arguments) == 1 and preflight.children == []
    no_secret_output(capsys.readouterr())


def test_missing_command_and_child_error_return_static_failure_without_secret_output(preflight, monkeypatch, capsys):
    module = preflight.module
    assert module.main(['run']) == 1

    def failed_child(*_args, **_kwargs):
        raise RuntimeError(FAKE_ISSUER)

    monkeypatch.setattr(module, 'subprocess', SimpleNamespace(run=failed_child))
    assert module.main(['run', '--', 'python', 'scripts/check-coder-local.py']) == 1
    no_secret_output(capsys.readouterr())


@pytest.mark.parametrize('command', [
    ['python', 'scripts/lifecycle.py', 'maintenance-run', '--phase', 'p2'],
    ['python', '-B', 'scripts/lifecycle.py', 'maintenance-run', '--phase', 'p5'],
    ['python', 'scripts/check_secrets.py', '--no-local-secrets'],
    ['python', 'scripts/test-offline.py'],
    ['python', 'scripts/test-offline.py', '--frontend'],
    ['python', 'scripts/test-offline.py', '--browser'],
    ['python', 'scripts/check-coder-local.py'],
    ['python', 'scripts/check-coder-local.py', '--before-restart'],
    ['python', 'scripts/migrate.py', 'check'],
    ['python', 'scripts/migrate.py', 'current'],
])
def test_run_only_accepts_fixed_trusted_scripts_and_reviewed_arguments(preflight, command):
    assert preflight.module.run(command, '.') == 7
    assert len(preflight.children) == 1


@pytest.mark.parametrize('command', [
    ['python', '-c', 'raise SystemExit(0)'],
    ['python', '-m', 'app.workers.main'],
    ['python', 'work/untrusted.py'],
    ['python', 'scripts/p5-live-state-check.py', '--stop'],
    ['python', 'scripts/lifecycle.py', 'start'],
    ['python', 'scripts/lifecycle.py', 'maintenance-run', '--phase', 'p6'],
    ['python', 'scripts/lifecycle.py', 'maintenance-run', '--phase', 'p5', '--force'],
    ['python', 'scripts/check_secrets.py'],
    ['python', 'scripts/test-offline.py', '--frontend', '--browser'],
    ['python', 'scripts/check-coder-local.py', '--unexpected'],
    ['python', 'scripts/migrate.py', 'upgrade'],
    ['python', '-I', 'scripts/migrate.py', 'current'],
    ['python', '-B', '-B', 'scripts/migrate.py', 'current'],
    ['node', 'explicit_double.mjs'],
    ['docker', 'compose', 'down'],
    ['cmd', '/c', 'echo', 'unit-only'],
    ['powershell', '-Command', 'Write-Output', 'unit-only'],
])
def test_run_rejects_arbitrary_interpreter_shell_or_excess_arguments_before_file_reads(preflight, monkeypatch,
                                                                                      capsys, command):
    original_open = Path.open

    def refuse_settings_access(path, *args, **kwargs):
        if path.name == '.env':
            raise AssertionError('Forbidden command must be rejected before settings access')
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', refuse_settings_access)
    assert preflight.module.main(['run', '--', *command]) == 1
    assert preflight.children == [] and preflight.events == []
    no_secret_output(capsys.readouterr())


def test_run_accepts_project_interpreter_path_but_rejects_frontend_cwd(preflight):
    module = preflight.module
    command = [str(preflight.project / '.venv/Scripts/python.exe'), '-B', 'scripts/migrate.py', 'current']
    assert module.run(command, '.') == 7
    with pytest.raises(module.PreflightError):
        module.run(command, 'frontend')
    assert len(preflight.children) == 1


@pytest.fixture
def coder_configuration(preflight, monkeypatch):
    events, calls = [], []
    preflight_policy = sys.modules['maintenance_policy']

    def cli_gate(_source, module_name):
        assert module_name != '__main__'
        events.append('import_gate')

    def maintenance_action(operation):
        assert operation == 'configure.coder'

        def decorate(function):
            async def guarded(*args, **kwargs):
                events.append('guard_enter')
                try:
                    return await function(*args, **kwargs)
                finally:
                    events.append('guard_exit')
            return guarded
        return decorate

    monkeypatch.setitem(sys.modules, 'maintenance_policy', SimpleNamespace(
        cli_gate=cli_gate, maintenance_action=maintenance_action,
        maintenance_operation=preflight_policy.maintenance_operation))
    spec = importlib.util.spec_from_file_location('seal_s3_coder_' + uuid4().hex,
                                                ROOT / 'scripts/configure-deepseek-coder.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', preflight.project)
    monkeypatch.setattr(module, 'os', SimpleNamespace(environ=preflight.environment))
    monkeypatch.setattr(module, 'runtime_env_file', lambda: preflight.module.ENV_FILE)

    def settings_forbidden():
        calls.append('settings')
        raise AssertionError('Settings must not parse a polluted service file')

    def parser_forbidden(*_args, **_kwargs):
        calls.append('dotenv')
        raise AssertionError('Dotenv must not parse a polluted service file')

    def database_forbidden(*_args, **_kwargs):
        calls.append('database')
        raise AssertionError('Configuration tests must never connect to a database')

    monkeypatch.setattr(module, 'Settings', settings_forbidden)
    monkeypatch.setattr(module, 'dotenv_values', parser_forbidden)
    monkeypatch.setattr(module, 'Connections', database_forbidden)
    return SimpleNamespace(module=module, preflight=preflight, events=events, calls=calls)


@pytest.mark.parametrize('declaration', [
    ISSUER + '=' + FAKE_ISSUER + '\n',
    'export ' + ISSUER + '="' + FAKE_ISSUER + '"\n',
    ISSUER.lower() + '=' + FAKE_ISSUER + '\n',
    "'" + ISSUER + "'='" + FAKE_ISSUER + "'\n",
    ISSUER + '\n',
    MODEL_KEY + '=' + FAKE_MODEL + '\n',
    'AGENTFORGE_MODEL_FUTURE_PROVIDER_KEY=' + FAKE_MODEL + '\n',
], ids=['issuer', 'export', 'lowercase', 'quoted', 'valueless', 'coder-key', 'future-model-key'])
async def test_coder_rejects_polluted_service_file_before_settings_dotenv_or_database(coder_configuration,
                                                                                   declaration, capsys):
    fixture = coder_configuration
    target = fixture.preflight.module.ENV_FILE
    target.write_text(BASE + declaration, encoding='utf-8')
    previous = target.read_bytes()
    with pytest.raises(RuntimeError, match='^SERVICE_FILE_CREDENTIAL_DECLARATION_FORBIDDEN$'):
        await fixture.module.main()
    assert fixture.calls == []
    assert fixture.events == ['import_gate', 'guard_enter', 'guard_exit']
    unchanged(target, previous)
    no_secret_output(capsys.readouterr())


@pytest.mark.parametrize('name', [ISSUER, MODEL_KEY])
async def test_coder_parent_authority_is_refused_by_name_without_value_or_settings_access(coder_configuration,
                                                                                        monkeypatch, name, capsys):
    fixture = coder_configuration
    fixture.preflight.environment.values[name] = FAKE_ISSUER

    def no_file_reference():
        raise AssertionError('Parent authority must be refused before looking up a service file')

    monkeypatch.setattr(fixture.module, 'runtime_env_file', no_file_reference)
    with pytest.raises(RuntimeError, match='^CREDENTIAL_AUTHORITY_FORBIDDEN_IN_CONFIGURATION$'):
        await fixture.module.main()
    assert fixture.calls == [] and fixture.preflight.environment.reads == []
    assert name in fixture.preflight.environment.values
    no_secret_output(capsys.readouterr())


def install_clean_coder_doubles(fixture, monkeypatch):
    module, preflight = fixture.module, fixture.preflight
    slot = {'provider': 'openai_compatible', 'base_url': 'https://api.deepseek.com', 'model': 'deepseek-flash',
            'credential_reference': 'env:' + MODEL_KEY, 'enabled': False, 'max_tokens': 64, 'timeout': 30}
    price = {'version': 's3-unit-only', 'currency': 'USD', 'input_per_million': '0.30',
             'output_per_million': '1.20', 'input_upper_bound': 8192, 'output_upper_bound': 64,
             'token_parameter': 'max_tokens'}
    (preflight.project / 'config').mkdir()
    (preflight.project / 'config/deepseek-coder-local.json').write_text(
        json.dumps({'slot': slot, 'price': price}), encoding='utf-8')
    settings = SimpleNamespace(real_calls_enabled=False, real_daily_budget_usd=Decimal(0),
        real_test_budget_usd=Decimal(0), model_credential_hosts={}, model_prices={},
        tenant_id='00000000-0000-4000-8000-000000000001')

    def settings_double():
        fixture.calls.append('settings')
        assert fixture.events[-1] == 'guard_enter'
        return settings

    def parser_double(path, *, interpolate):
        fixture.calls.append('dotenv')
        assert path == preflight.module.ENV_FILE and interpolate is False
        return parse_controlled_dotenv(path, interpolate=False)

    config = module.ModelConfig.model_validate(slot).model_dump()
    rows = [SimpleNamespace(role=role, version=1, **config) for role in ('coder', 'planner', 'researcher', 'reviewer')]

    class TransactionDouble:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class SessionDouble(TransactionDouble):
        def __init__(self):
            self.selects = 0

        def begin(self):
            return TransactionDouble()

        async def scalars(self, _query):
            self.selects += 1
            return SimpleNamespace(all=lambda: [] if self.selects == 1 else rows)

    class ConnectionsDouble:
        def __init__(self, _settings):
            fixture.calls.append('database_double')

        def sessions(self):
            return SessionDouble()

        async def close(self):
            fixture.calls.append('closed_double')

    monkeypatch.setattr(module, 'Settings', settings_double)
    monkeypatch.setattr(module, 'dotenv_values', parser_double)
    monkeypatch.setattr(module, 'Connections', ConnectionsDouble)
    return settings


async def test_preflight_to_coder_clean_service_flow_preserves_references_without_credentials(coder_configuration,
                                                                                            monkeypatch, capsys):
    fixture = coder_configuration
    fixture.preflight.module.prepare()
    install_clean_coder_doubles(fixture, monkeypatch)
    await fixture.module.main()
    target = fixture.preflight.module.ENV_FILE
    prepared = parse_controlled_dotenv(target, interpolate=False)
    assert not any(fixture.module.credential_name(name) for name in prepared)
    assert prepared['AGENTFORGE_REAL_CALLS_ENABLED'] == 'false'
    assert prepared['AGENTFORGE_REAL_DAILY_BUDGET_USD'] == '0'
    assert json.loads(prepared['AGENTFORGE_MODEL_CREDENTIAL_HOSTS'])[MODEL_KEY] == ['api.deepseek.com']
    assert fixture.calls == ['settings', 'dotenv', 'database_double', 'closed_double']
    assert fixture.events == ['import_gate', 'guard_enter', 'guard_exit']
    no_secret_output(capsys.readouterr())


async def test_coder_rechecks_names_before_explicit_dotenv_parser(coder_configuration, monkeypatch, capsys):
    fixture = coder_configuration
    settings = install_clean_coder_doubles(fixture, monkeypatch)
    target = fixture.preflight.module.ENV_FILE

    def settings_double_with_controlled_file_change():
        fixture.calls.append('settings_double')
        target.write_text(BASE + ISSUER + '=' + FAKE_ISSUER + '\n', encoding='utf-8')
        return settings

    monkeypatch.setattr(fixture.module, 'Settings', settings_double_with_controlled_file_change)
    with pytest.raises(RuntimeError, match='^SERVICE_FILE_CREDENTIAL_DECLARATION_FORBIDDEN$'):
        await fixture.module.main()
    assert fixture.calls == ['settings_double']
    no_secret_output(capsys.readouterr())


async def test_coder_preserves_late_polluted_service_file_before_write(coder_configuration, monkeypatch, capsys):
    fixture = coder_configuration
    install_clean_coder_doubles(fixture, monkeypatch)
    original = fixture.module.require_service_only_file
    checks = []
    expected = (BASE + ISSUER + '=' + FAKE_ISSUER + '\n').encode()

    def controlled_check(target):
        checks.append(True)
        if len(checks) == 3:
            target.write_bytes(expected)
        return original(target)

    monkeypatch.setattr(fixture.module, 'require_service_only_file', controlled_check)
    with pytest.raises(RuntimeError, match='^SERVICE_FILE_CREDENTIAL_DECLARATION_FORBIDDEN$'):
        await fixture.module.main()
    assert len(checks) == 3
    assert fixture.calls == ['settings', 'dotenv', 'database_double', 'closed_double']
    unchanged(fixture.preflight.module.ENV_FILE, expected)
    no_secret_output(capsys.readouterr())
