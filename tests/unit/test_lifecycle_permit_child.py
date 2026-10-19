"""Offline doubles only: no real child, CIM, services, DB, dotenv or key reads."""
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'work/maint-s1/450b430f-b4ce-4aa6-aac6-e2c41083ca43'
spec = importlib.util.spec_from_file_location('permit_child_offline_tests', ROOT / 'tests/fixtures/lifecycle_permit_child.py')
child = importlib.util.module_from_spec(spec)
spec.loader.exec_module(child)


class NamedEnvironment:
    def __init__(self, values):
        self.values = values

    def __contains__(self, name):
        assert name in {*child.OS_NAMES, 'AGENTFORGE_SETTINGS_FILE', 'AGENTFORGE_DATABASE_URL',
                        'AGENTFORGE_REDIS_URL'}, 'Do not probe credential values in this helper'
        return name in self.values

    def __getitem__(self, name):
        assert name in child.OS_NAMES, 'Do not resolve inherited credential or database values'
        return self.values[name]

    def get(self, name, default=None):
        assert name in {'AGENTFORGE_SETTINGS_FILE', 'AGENTFORGE_S1_MANIFEST'}, 'Only public locators are readable'
        return self.values.get(name, default)

    def __iter__(self):
        raise AssertionError('Never enumerate/copy the whole process environment')


def isolated_environment(monkeypatch, selected=None):
    values = {'SystemRoot': 'explicit-os-runtime', 'PATH': 'explicit-runtime-path',
              'AGENTFORGE_SETTINGS_FILE': str(selected or RUN / '.env'),
              'AGENTFORGE_S1_MANIFEST': str(RUN / 'isolation.json'),
              'AGENTFORGE_MODEL_CODER_KEY': 'explicit-fake-must-never-be-read',
              'AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN': 'explicit-fake-must-never-be-read'}
    monkeypatch.setattr(child, 'os', SimpleNamespace(name='nt', path=os.path, pathsep=os.pathsep,
        environ=NamedEnvironment(values)))
    verified = {'manifest_path': str(RUN / 'isolation.json'), 'run_directory': str(RUN),
                'settings_path': str(RUN / '.env')}
    def validate(root, manifest):
        assert root == ROOT and manifest == RUN / 'isolation.json'
        return verified
    def environment(root, manifest):
        validate(root, manifest)
        public = {name: child.os.environ[name] for name in child.OS_NAMES if name in child.os.environ}
        public.update(AGENTFORGE_S1_MANIFEST=verified['manifest_path'],
            AGENTFORGE_SETTINGS_FILE=verified['settings_path'], AGENTFORGE_EXTERNAL_MODELS_BLOCKED='1',
            AGENTFORGE_REAL_MAX_RETRIES='0')
        return public
    monkeypatch.setitem(sys.modules, 's1_isolation', SimpleNamespace(validate_isolation=validate,
        build_test_environment=environment, isolation_lease=lambda *_: FakeGuard([])))
    return values


def test_fixture_environment_uses_named_os_values_and_service_file_only(monkeypatch):
    isolated_environment(monkeypatch)
    environment = child.fixture_environment(ROOT)
    assert environment['SystemRoot'] == 'explicit-os-runtime'
    assert environment['AGENTFORGE_EXTERNAL_MODELS_BLOCKED'] == '1'
    assert environment['AGENTFORGE_REAL_MAX_RETRIES'] == '0'
    assert 'AGENTFORGE_MODEL_CODER_KEY' not in environment
    assert 'AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN' not in environment
    assert 'AGENTFORGE_DATABASE_URL' not in environment
    assert 'must-never-be-read' not in repr(environment)


@pytest.mark.parametrize('relative', ['.env', 'work/p5-live-preflight/.env', 'work/other/.env'])
def test_fixture_refuses_nonisolated_settings_without_opening_them(monkeypatch, relative):
    isolated_environment(monkeypatch, ROOT / relative)
    with pytest.raises(RuntimeError, match='S1_SETTINGS_REFERENCE_MISMATCH'):
        child.fixture_environment(ROOT)


class FakeLauncher:
    pid = 101

    def __init__(self, events):
        self.events = events
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.events.append('launcher_handle_terminate')
        self.returncode = 125

    def wait(self, timeout=None):
        self.events.append('launcher_handle_wait')
        return self.returncode


class FakeGuard:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append('guard_enter')

    def __exit__(self, *_):
        self.events.append('guard_exit')


def owned_double(monkeypatch):
    events = []
    owner = child.PermitProcessChild.__new__(child.PermitProcessChild)
    owner.root = ROOT
    owner.tenant = str(uuid4())
    owner.mode = 'claimed'
    owner.python = ROOT / '.venv/Scripts/python.exe'
    owner.helper = ROOT / 'tests/fixtures/permit_process_worker.py'
    owner.directory = RUN / 'permit-process-tests' / owner.tenant
    owner.process = FakeLauncher(events)
    owner.launcher_facts = {'pid': 101, 'created': 100, 'executable': str(owner.python)}
    owner.child_facts = {'pid': 202, 'created': 200, 'executable': str(owner.python)}
    owner.closed = False
    owner.guard = FakeGuard(events)
    owner.guard.__enter__()
    owner.manager = SimpleNamespace(process_facts=lambda pid: dict(owner.child_facts),
        NativeBackend=lambda root: SimpleNamespace(terminate=lambda identity: events.append(('child_handle_terminate', dict(identity)))))
    row = {'ProcessId': 202, 'ParentProcessId': 101, 'ExecutablePath': str(owner.python), 'CommandLine': 'explicit-fixed-fixture-command'}
    monkeypatch.setattr(owner, '_rows', lambda: [row])
    monkeypatch.setattr(child, 'windows_arguments', lambda command: [str(owner.python), str(owner.helper), owner.tenant, owner.mode, str(owner.directory)])
    return owner, events, row


def test_owned_child_stops_verified_child_then_only_its_launcher_handle(monkeypatch):
    owner, events, _ = owned_double(monkeypatch)
    identity = dict(owner.child_facts)
    owner.stop()
    assert events == ['guard_enter', ('child_handle_terminate', identity),
                      'launcher_handle_terminate', 'launcher_handle_wait', 'guard_exit']
    owner.stop()
    assert events.count('guard_exit') == 1


@pytest.mark.parametrize('failure', ['unreadable', 'creation_changed', 'executable_changed', 'command_unverified'])
def test_changed_or_unreadable_child_is_never_terminated_but_owned_launcher_is_cleaned(monkeypatch, failure):
    owner, events, row = owned_double(monkeypatch)
    observed = dict(owner.child_facts)
    if failure == 'unreadable':
        def denied(_):
            raise RuntimeError('FIXTURE_IDENTITY_QUERY_FAILED')
        owner.manager.process_facts = denied
    else:
        if failure == 'creation_changed': observed['created'] += 1
        if failure == 'executable_changed': observed['executable'] = str(ROOT / 'unrelated-python.exe')
        if failure == 'command_unverified': row['ParentProcessId'] = 999
        owner.manager.process_facts = lambda _: observed
    with pytest.raises(RuntimeError):
        owner.stop()
    assert not any(isinstance(event, tuple) for event in events)
    assert 'launcher_handle_terminate' in events and events[-1] == 'guard_exit'


def test_exited_child_is_not_terminated_again(monkeypatch):
    owner, events, _ = owned_double(monkeypatch)
    owner.manager.process_facts = lambda _: None
    owner.stop()
    assert not any(isinstance(event, tuple) for event in events)
    assert events[-1] == 'guard_exit'


@pytest.mark.parametrize('argument', ['helper', 'tenant', 'mode', 'directory', 'extra'])
def test_only_exact_fixed_fixture_arguments_are_accepted(monkeypatch, argument):
    owner, _, row = owned_double(monkeypatch)
    args = [str(owner.python), str(owner.helper), owner.tenant, owner.mode, str(owner.directory)]
    index = {'helper': 1, 'tenant': 2, 'mode': 3, 'directory': 4}.get(argument)
    if index is None: args.append('--override')
    else: args[index] = 'unapproved-argument'
    monkeypatch.setattr(child, 'windows_arguments', lambda _: args)
    assert owner._validate(row, owner.child_facts) is False


def test_bind_refuses_external_pid_without_acquiring_a_termination_target(monkeypatch):
    owner, events, _ = owned_double(monkeypatch)
    original = dict(owner.child_facts)
    with pytest.raises(RuntimeError, match='FIXTURE_CHILD_UNVERIFIED'):
        owner.bind(999)
    assert owner.child_facts == original and not any(isinstance(event, tuple) for event in events)


def test_fixture_constructor_builds_only_its_reviewed_command_and_strips_environment(monkeypatch):
    isolated_environment(monkeypatch)
    events, calls = [], []
    launcher = FakeLauncher(events)
    manager = SimpleNamespace(process_facts=lambda pid: {'pid': pid, 'created': 100, 'executable': str(ROOT / '.venv/Scripts/python.exe')})
    monkeypatch.setattr(sys.modules['s1_isolation'], 'isolation_lease', lambda *_: FakeGuard(events))
    monkeypatch.setattr(child, 'lifecycle_module', lambda _: manager)
    monkeypatch.setattr(child.PermitProcessChild, '_discover', lambda _: None)
    def fake_launch(arguments, **options):
        calls.append((arguments, options))
        return launcher
    monkeypatch.setattr(child.subprocess, 'Popen', fake_launch)
    tenant = str(uuid4())
    owned = child.PermitProcessChild(ROOT, tenant, 'claimed')
    arguments, options = calls[0]
    assert arguments == [str(ROOT / '.venv/Scripts/python.exe'), str(ROOT / 'tests/fixtures/permit_process_worker.py'),
                         tenant, 'claimed', str(RUN / 'permit-process-tests' / tenant)]
    assert 'AGENTFORGE_MODEL_CODER_KEY' not in options['env']
    assert 'AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN' not in options['env']
    owned.stop()
    assert events[-1] == 'guard_exit'


@pytest.mark.parametrize('mode', ['shell', '--force', 'main', 'coder'])
def test_unapproved_mode_never_reaches_process_launch(monkeypatch, mode):
    isolated_environment(monkeypatch)
    def forbidden(*_, **__):
        raise AssertionError('Process creation is forbidden in this rejection test')
    monkeypatch.setattr(child.subprocess, 'Popen', forbidden)
    with pytest.raises(RuntimeError, match='FIXTURE_ARGUMENTS_INVALID'):
        child.PermitProcessChild(ROOT, str(uuid4()), mode)
