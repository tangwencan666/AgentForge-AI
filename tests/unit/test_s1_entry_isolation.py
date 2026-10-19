"""Entry validation with explicit verifier doubles; no database/Redis/HTTP calls."""
import importlib.util
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def context(monkeypatch, tmp_path):
    # Remove names only. Never inspect or preserve a real credential value.
    for name in ('AGENTFORGE_DATABASE_URL', 'AGENTFORGE_REDIS_URL',
                 'AGENTFORGE_ADMIN_TOKEN', 'AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN'):
        if name in os.environ:
            pytest.fail('Entry unit tests require a sanitized parent environment')
    for name in ('AGENTFORGE_RUN_INTEGRATION', 'AGENTFORGE_RUN_SANDBOX', 'AGENTFORGE_S1_MANIFEST'):
        monkeypatch.delenv(name, raising=False)  # Public routing metadata only.
    module = load('s1_entry_conftest', 'tests/conftest.py')
    verified = {'status': 'READY', 'settings_path': str(tmp_path / '.env'),
                'manifest_path': str(tmp_path / 'isolation.json'),
                'run_directory': str(tmp_path),
                'ports': {'postgres': 35432, 'redis': 36379, 'backend': 38100, 'frontend': 35173, 'runner': 38120}}
    calls = []
    def verify(root, locator):
        calls.append((root, locator))
        return verified
    @contextmanager
    def lease(root, locator):
        yield verified
    monkeypatch.setitem(sys.modules, 's1_isolation', SimpleNamespace(validate_isolation=verify, isolation_lease=lease))
    monkeypatch.setitem(sys.modules, 'preflight_guards', SimpleNamespace(install_verified_guard=lambda item: None))
    return module, verified, calls


def select(monkeypatch, verified):
    monkeypatch.setenv('AGENTFORGE_S1_MANIFEST', str(Path(verified['run_directory']) / 'isolation.json'))
    monkeypatch.setenv('AGENTFORGE_SETTINGS_FILE', verified['settings_path'])


def test_integration_flag_without_manifest_refuses_before_verification(context, monkeypatch):
    module, _, calls = context
    monkeypatch.setenv('AGENTFORGE_RUN_INTEGRATION', '1')
    with pytest.raises(pytest.UsageError, match='S1_ISOLATION_MANIFEST_REQUIRED'):
        module.pytest_configure(SimpleNamespace())
    assert calls == []


def test_runner_request_is_explicitly_blocked(context, monkeypatch):
    module, verified, calls = context
    select(monkeypatch, verified)
    monkeypatch.setenv('AGENTFORGE_RUN_SANDBOX', '1')
    with pytest.raises(pytest.UsageError, match='S1_RUNNER_ISOLATION_BLOCKED'):
        module._s1_context()
    assert calls == []


@pytest.mark.parametrize('name', ['AGENTFORGE_DATABASE_URL', 'AGENTFORGE_REDIS_URL',
                                 'AGENTFORGE_ADMIN_TOKEN', 'AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN',
                                 'AGENTFORGE_SANDBOX_RUNNER_URL', 'AGENTFORGE_MODEL_CODER_KEY'])
def test_settings_overrides_refuse_before_resource_inspection(context, monkeypatch, name):
    module, verified, calls = context
    select(monkeypatch, verified)
    monkeypatch.setenv(name, 'explicit-fake-override-never-used')
    with pytest.raises(pytest.UsageError, match='S1_SETTINGS_OVERRIDE_FORBIDDEN'):
        module._s1_context()
    assert calls == []


def test_verified_locator_alone_cannot_select_settings(context, monkeypatch):
    module, verified, calls = context
    select(monkeypatch, verified)
    monkeypatch.setenv('AGENTFORGE_SETTINGS_FILE', str(ROOT / '.env'))
    with pytest.raises(pytest.UsageError, match='S1_SETTINGS_REFERENCE_MISMATCH'):
        module._s1_context()
    assert len(calls) == 1


def test_verified_disposable_context_is_saved_before_fixtures(context, monkeypatch):
    module, verified, calls = context
    select(monkeypatch, verified)
    monkeypatch.setenv('AGENTFORGE_RUN_INTEGRATION', '1')
    cleanups = []
    config = SimpleNamespace(add_cleanup=cleanups.append)
    module.pytest_configure(config)
    assert config._agentforge_s1_context is verified
    assert len(calls) == 1
    assert len(cleanups) == 1
    cleanups[0]()


def test_resource_inspection_failure_has_no_raw_diagnostics(context, monkeypatch):
    module, verified, _ = context
    select(monkeypatch, verified)
    def failure(*_):
        raise RuntimeError('explicit-fake-sensitive-diagnostic-canary')
    monkeypatch.setattr(sys.modules['s1_isolation'], 'validate_isolation', failure)
    with pytest.raises(pytest.UsageError) as result:
        module._s1_context()
    assert str(result.value) == 'S1_ISOLATION_UNVERIFIED'


def test_no_integration_request_leaves_existing_offline_behavior(context):
    module, _, calls = context
    config = SimpleNamespace()
    module.pytest_configure(config)
    assert calls == []
    assert not hasattr(config, '_agentforge_s1_context')


@pytest.mark.parametrize('host,port', [('127.0.0.1', 15432), ('127.0.0.1', 16379),
    ('127.0.0.1', 18100), ('127.0.0.1', 15173), ('127.0.0.1', 38120),
    ('localhost', 35432), ('::1', 35432), ('api.deepseek.com', 443), ('127.0.0.1', '35432')])
@pytest.mark.parametrize('event', ['socket.connect', 'socket.getaddrinfo'])
def test_guard_rejects_main_runner_public_and_unattested_addresses(context, host, port, event):
    _, verified, _ = context
    guard = load('s1_entry_network', 'tests/fixtures/preflight_guards.py')
    guard._allowed_endpoints = guard.verified_endpoints(verified)
    arguments = (None, (host, port)) if event == 'socket.connect' else (host, port, 0, 0, 0)
    with pytest.raises(RuntimeError, match='S1_NETWORK_ENDPOINT_FORBIDDEN'):
        guard.audit(event, arguments)


@pytest.mark.parametrize('name', ['postgres', 'redis', 'backend', 'frontend'])
def test_guard_accepts_only_verified_disposable_service_ports(context, name):
    _, verified, _ = context
    guard = load('s1_entry_allowed_network', 'tests/fixtures/preflight_guards.py')
    guard._allowed_endpoints = guard.verified_endpoints(verified)
    guard.audit('socket.connect', (None, ('127.0.0.1', verified['ports'][name])))
    guard.audit('socket.getaddrinfo', ('127.0.0.1', verified['ports'][name], 0, 0, 0))


def test_guard_denies_root_dotenv_without_opening_it():
    guard = load('s1_entry_dotenv', 'tests/fixtures/preflight_guards.py')
    with pytest.raises(RuntimeError, match='OFFLINE_PROJECT_ENV_READ_FORBIDDEN'):
        guard.audit('open', (str(ROOT / '.env'), 'r', 0))


def test_legacy_regression_p3_cannot_start_or_cleanup_runner(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    module = load('s1_entry_regression', 'scripts/lifecycle_regression.py')
    from lifecycle_manager import LifecycleError
    with pytest.raises(LifecycleError, match='S1_RUNNER_ISOLATION_BLOCKED'):
        module.run_phase.__wrapped__(ROOT, 'p3')


def test_regression_failure_never_restores_main_services(context, monkeypatch):
    _, verified, _ = context
    select(monkeypatch, verified)
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    module = load('s1_entry_finally', 'scripts/lifecycle_regression.py')
    from lifecycle_manager import SAFE_ENV
    for name, value in SAFE_ENV.items():
        monkeypatch.setenv(name, value)
    for name in ('AGENTFORGE_RUN_INTEGRATION', 'AGENTFORGE_RUN_SANDBOX'):
        monkeypatch.setenv(name, '0')
    attempts = []
    def forbidden_process(*args, **kwargs):
        attempts.append(True)
        raise AssertionError('No lifecycle or Docker subprocess is permitted')
    def failed_suite(arguments):
        assert '-p' in arguments and 'preflight_guards' in arguments
        raise RuntimeError('explicit offline suite failure')
    monkeypatch.setattr(subprocess, 'run', forbidden_process)
    monkeypatch.setattr(subprocess, 'Popen', forbidden_process)
    monkeypatch.setattr(pytest, 'main', failed_suite)
    with pytest.raises(RuntimeError, match='explicit offline suite failure'):
        module.run_phase.__wrapped__(ROOT, 'p2')
    assert attempts == []


def test_browser_config_rejects_missing_manifest_before_specs():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is unavailable; browser entry execution is unverified')
    names = ('SystemRoot', 'WINDIR', 'PATH', 'PATHEXT', 'COMSPEC', 'TEMP', 'TMP',
             'APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH')
    environment = {name: os.environ[name] for name in names if name in os.environ}
    result = subprocess.run([node, 'node_modules/@playwright/test/cli.js', 'test',
                             '--config=playwright.config.ts', '--list'],
                            cwd=ROOT / 'frontend', env=environment, capture_output=True, text=True,
                            timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode != 0
    assert 'S1_ISOLATION_MANIFEST_REQUIRED' in result.stderr
    assert 'Total:' not in result.stdout


def test_coder_observer_uses_only_fixed_cli_and_named_os_environment(monkeypatch):
    checker = load('s1_entry_coder_observer', 'scripts/check-coder-local.py')
    permitted = {'SystemRoot', 'WINDIR', 'PATH', 'PATHEXT', 'COMSPEC', 'TEMP', 'TMP',
                 'APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH'}
    class NamesOnly:
        def __contains__(self, name):
            assert name in permitted
            return name == 'SystemRoot'
        def __getitem__(self, name):
            assert name == 'SystemRoot'
            return 'explicit-os-runtime'
        def __iter__(self):
            raise AssertionError('Whole environment enumeration is forbidden')
    monkeypatch.setattr(checker, 'os', SimpleNamespace(environ=NamesOnly()))
    calls = []
    def observed(arguments, **options):
        calls.append((arguments, options))
        return SimpleNamespace(returncode=0, stderr='', stdout='{"version":2,"entries":{}}')
    monkeypatch.setattr(checker.subprocess, 'run', observed)
    assert checker.managed_status() == {'version': 2, 'entries': {}}
    arguments, options = calls[0]
    assert arguments == [str(ROOT / '.venv/Scripts/python.exe'), '-B', str(ROOT / 'scripts/lifecycle.py'), 'status']
    assert options['cwd'] == ROOT and options['env'] == {'SystemRoot': 'explicit-os-runtime'}
    assert options.get('shell', False) is False


@pytest.mark.parametrize('result', [
    SimpleNamespace(returncode=2, stderr='', stdout='explicit-fake-diagnostic'),
    SimpleNamespace(returncode=0, stderr='explicit-fake-diagnostic', stdout='{}'),
    SimpleNamespace(returncode=0, stderr='', stdout='{"version":1,"entries":{}}'),
    SimpleNamespace(returncode=0, stderr='', stdout='not-json-explicit-fake-diagnostic')])
def test_coder_observer_refuses_legacy_and_raw_failure_output(monkeypatch, result):
    checker = load('s1_entry_coder_failure', 'scripts/check-coder-local.py')
    monkeypatch.setattr(checker.subprocess, 'run', lambda *args, **kwargs: result)
    with pytest.raises(RuntimeError) as raised:
        checker.managed_status()
    assert str(raised.value) == 'Lifecycle status unavailable or unverified'
