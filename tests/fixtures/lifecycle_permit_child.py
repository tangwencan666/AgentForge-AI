"""Fixed permit crash fixture, never a launcher for main or Coder services.

The disposable S1 resource lease is held throughout each child's lifetime. Only the
reviewed fixture path and three fixture modes are accepted; no command override,
credential copying, external PID, process-name kill or PowerShell stop is exposed.
"""
import ctypes
import importlib
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID

OS_NAMES = ('SystemRoot', 'WINDIR', 'PATH', 'PATHEXT', 'COMSPEC', 'TEMP', 'TMP',
            'APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH')


def lifecycle_module(root):
    """Reuse the manager's private lock ownership, including its CLI import."""
    expected = (Path(root) / 'scripts/lifecycle_manager.py').resolve()
    existing = []
    for name in ('lifecycle_manager', 'scripts.lifecycle_manager', '__main__'):
        module = sys.modules.get(name)
        file = getattr(module, '__file__', None)
        if file and Path(file).resolve() == expected and hasattr(module, 'maintenance_guard'):
            if module not in existing:
                existing.append(module)
    if len(existing) > 1:
        raise RuntimeError('LIFECYCLE_MODULE_AMBIGUOUS')
    if existing:
        return existing[0]
    sys.path.insert(0, str(expected.parent))
    module = importlib.import_module('lifecycle_manager')
    if Path(module.__file__).resolve() != expected:
        raise RuntimeError('LIFECYCLE_MODULE_MISMATCH')
    return module


def fixture_environment(root):
    """Only named OS variables and newly attested disposable settings are used."""
    verified = isolated_context(root)
    from s1_isolation import build_test_environment
    return build_test_environment(root, Path(verified['manifest_path']))


def isolated_context(root):
    """Reject main/legacy settings before creating processes or touching data."""
    root = Path(root).resolve()
    if root != Path(__file__).resolve().parents[2]:
        raise RuntimeError('FIXTURE_ROOT_INVALID')
    locator = os.environ.get('AGENTFORGE_S1_MANIFEST')
    if not locator:
        raise RuntimeError('S1_ISOLATION_MANIFEST_REQUIRED')
    sys.path.insert(0, str(root / 'scripts'))
    from s1_isolation import validate_isolation
    verified = validate_isolation(root, Path(locator))
    selected = os.environ.get('AGENTFORGE_SETTINGS_FILE')
    if (not selected or Path(selected).resolve() != Path(verified['settings_path']).resolve()
            or any(name in os.environ for name in ('AGENTFORGE_DATABASE_URL', 'AGENTFORGE_REDIS_URL'))):
        raise RuntimeError('S1_SETTINGS_REFERENCE_MISMATCH')
    return verified


def same_facts(saved, observed):
    return bool(saved and observed and saved['pid'] == observed['pid']
                and saved['created'] == observed['created']
                and os.path.normcase(saved['executable']) == os.path.normcase(observed['executable']))


def windows_arguments(command):
    """Parse metadata with the Windows argument parser; never execute it."""
    from ctypes import wintypes
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    arguments = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not arguments:
        raise RuntimeError('FIXTURE_COMMAND_UNVERIFIED')
    try:
        return [arguments[index] for index in range(count.value)]
    finally:
        kernel.LocalFree(arguments)


class PermitProcessChild:
    def __init__(self, root, tenant, mode):
        if os.name != 'nt':
            raise RuntimeError('FIXTURE_PLATFORM_UNSUPPORTED')
        self.root = Path(root).resolve()
        if self.root != Path(__file__).resolve().parents[2]:
            raise RuntimeError('FIXTURE_ROOT_INVALID')
        self.tenant = str(UUID(tenant))
        if self.tenant != tenant or mode not in {'claimed', 'dispatched', 'recover'}:
            raise RuntimeError('FIXTURE_ARGUMENTS_INVALID')
        self.mode = mode
        self.helper = self.root / 'tests/fixtures/permit_process_worker.py'
        verified = isolated_context(self.root)
        self.directory = Path(verified['run_directory']) / 'permit-process-tests' / self.tenant
        self.python = self.root / '.venv/Scripts/python.exe'
        self.manager = lifecycle_module(self.root)
        self.process = None
        self.launcher_facts = None
        self.child_facts = None
        self.closed = False
        from s1_isolation import isolation_lease
        self.guard = isolation_lease(self.root, Path(verified['manifest_path']))
        self.guard.__enter__()
        try:
            # The fixture itself supplies a visibly fake credential and a virtual
            # transport. No model-key or issuer value is inherited from the caller.
            self.process = subprocess.Popen(
                [str(self.python), str(self.helper), self.tenant, self.mode, str(self.directory)],
                cwd=self.root, env=fixture_environment(self.root), stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            self.launcher_facts = self.manager.process_facts(self.process.pid)
            if not self.launcher_facts:
                raise RuntimeError('FIXTURE_START_UNCERTAIN')
            self._discover()
        except BaseException:
            self.stop()
            raise

    @property
    def pid(self):
        return self.process.pid

    @property
    def returncode(self):
        return self.process.returncode

    def wait(self, timeout=None):
        return self.process.wait(timeout=timeout)

    def _rows(self):
        pid = self.process.pid
        if type(pid) is not int or pid <= 0:
            raise RuntimeError('FIXTURE_IDENTITY_QUERY_FAILED')
        command = ("$rows=@(Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(pid)
            + " OR ParentProcessId=" + str(pid) + "' -ErrorAction Stop | "
            "Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine)")
        try:
            # The shared boundary supplies a strict success envelope and an OS
            # runtime-only environment. No credential/issuer value is inherited.
            rows = self.manager.NativeBackend._query('processes', command)
        except self.manager.LifecycleError:
            raise RuntimeError('FIXTURE_IDENTITY_QUERY_FAILED') from None
        seen = set()
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {'ProcessId', 'ParentProcessId', 'ExecutablePath', 'CommandLine'}
                    or type(row['ProcessId']) is not int or row['ProcessId'] <= 0 or row['ProcessId'] in seen
                    or type(row['ParentProcessId']) is not int or row['ParentProcessId'] < 0
                    or not isinstance(row['ExecutablePath'], str) or not row['ExecutablePath']
                    or not isinstance(row['CommandLine'], str) or not row['CommandLine']
                    or row['ProcessId'] != pid and row['ParentProcessId'] != pid):
                raise RuntimeError('FIXTURE_IDENTITY_QUERY_FAILED')
            seen.add(row['ProcessId'])
        return rows

    def _validate(self, row, facts):
        if not facts or not self.launcher_facts or facts['created'] < self.launcher_facts['created']:
            return False
        pid = int(row.get('ProcessId', -1))
        if pid != facts['pid'] or (pid != self.process.pid and int(row.get('ParentProcessId', -1)) != self.process.pid):
            return False
        if pid == self.process.pid and not same_facts(self.launcher_facts, facts):
            return False
        executable = row.get('ExecutablePath')
        if not executable or os.path.normcase(executable) != os.path.normcase(facts['executable']):
            return False
        arguments = windows_arguments(row.get('CommandLine') or '')
        allowed = {os.path.normcase(str(self.python.resolve())),
                   os.path.normcase(self.launcher_facts['executable']),
                   os.path.normcase(str(Path(sys._base_executable).resolve()))}
        return (len(arguments) == 5 and os.path.normcase(str(Path(arguments[0]).resolve())) in allowed
                and Path(arguments[1]).resolve() == self.helper.resolve()
                and arguments[2:4] == [self.tenant, self.mode]
                and Path(arguments[4]).resolve() == self.directory.resolve())

    def _discover(self):
        candidates = []
        for row in self._rows():
            facts = self.manager.process_facts(int(row['ProcessId']))
            if self._validate(row, facts):
                candidates.append(facts)
        children = [facts for facts in candidates if facts['pid'] != self.process.pid]
        if len(children) > 1:
            raise RuntimeError('FIXTURE_CHILD_AMBIGUOUS')
        if children:
            self.child_facts = children[0]
        elif candidates and not self.child_facts:
            self.child_facts = candidates[0]

    def bind(self, actual_pid):
        """Bind only the PID reported by this fixed fixture's ready record."""
        facts = self.manager.process_facts(actual_pid)
        rows = [row for row in self._rows() if int(row['ProcessId']) == actual_pid]
        if len(rows) != 1 or not self._validate(rows[0], facts):
            raise RuntimeError('FIXTURE_CHILD_UNVERIFIED')
        if self.child_facts and self.child_facts['pid'] != self.process.pid and not same_facts(self.child_facts, facts):
            raise RuntimeError('FIXTURE_CHILD_CHANGED')
        self.child_facts = facts

    def _stop_launcher_handle(self):
        if self.process is not None and self.process.poll() is None:
            # Popen owns this exact process handle, not a freshly looked-up PID.
            self.process.terminate()
            self.process.wait(timeout=10)

    def stop(self):
        if self.closed:
            return
        try:
            if self.process is None:
                return
            # Prevent a launcher that has not yet reported its child from creating
            # another process between discovery and cleanup.
            if self.child_facts is None or self.child_facts['pid'] == self.process.pid:
                self._stop_launcher_handle()
                if self.launcher_facts:
                    self._discover()
            if self.child_facts and self.child_facts['pid'] != self.process.pid:
                observed = self.manager.process_facts(self.child_facts['pid'])
                if observed and not same_facts(self.child_facts, observed):
                    raise RuntimeError('FIXTURE_CHILD_CHANGED')
                if observed:
                    rows = [row for row in self._rows() if int(row['ProcessId']) == observed['pid']]
                    if len(rows) != 1 or not self._validate(rows[0], observed):
                        raise RuntimeError('FIXTURE_CHILD_UNVERIFIED')
                    # Core opens a process handle, rechecks creation FILETIME on
                    # that handle, then terminates/waits on the same handle.
                    self.manager.NativeBackend(self.root).terminate(self.child_facts)
            self._stop_launcher_handle()
        finally:
            try:
                # A refused/changed child identity never licenses killing it, but
                # cleanup must still close our own launcher handle on that path.
                self._stop_launcher_handle()
            finally:
                self.closed = True
                self.guard.__exit__(None, None, None)
