"""SEAL-S1 offline fault cases: no PowerShell, services, DB or real credentials.

All subprocess/OS observations below are explicit test doubles. Files are kept
only in the project's work/seal-fixes directory, never its live lifecycle state.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "scripts"))
import lifecycle_manager as lifecycle


@pytest.fixture
def isolated_root():
    root = PROJECT / "work/seal-fixes" / ("s1-unit-" + uuid4().hex)
    root.mkdir(parents=True)
    return root


def envelope(kind, rows):
    return json.dumps({"version": 1, "query": kind, "success": True, "rows": rows})


def result(stdout, stderr="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def install_result(monkeypatch, response):
    calls = []

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr(lifecycle.subprocess, "run", run)
    return calls


def invoke(backend, kind):
    return backend._rows() if kind == "processes" else backend._listeners(29431)


@pytest.mark.parametrize("kind", ["processes", "listeners"])
def test_explicit_successful_empty_is_distinct_from_query_failure(monkeypatch, isolated_root, kind):
    calls = install_result(monkeypatch, result(envelope(kind, [])))
    assert invoke(lifecycle.NativeBackend(isolated_root), kind) == []
    command = calls[0][0][-1]
    assert "$ErrorActionPreference='Stop'" in command
    assert "$Error.Count -ne 0" in command and "catch { exit 3 }" in command
    assert "-ErrorAction SilentlyContinue" not in command
    assert calls[0][1]["capture_output"] and calls[0][1]["encoding"] == "utf-8"
    assert calls[0][1]["timeout"] == 15
    if kind == "processes":
        assert "Get-CimInstance Win32_Process -ErrorAction Stop" in command
        assert "CreationDate.ToFileTimeUtc()" in command
        assert "($_.ExecutablePath -eq $v) -and (-not $_.CommandLine)" in command
    else:
        assert "Get-NetTCPConnection -ErrorAction Stop | Where-Object" in command
        assert "$_.LocalPort -eq 29431" in command and "-LocalPort" not in command


@pytest.mark.parametrize("kind", ["processes", "listeners"])
@pytest.mark.parametrize("fault", [
    "empty", "whitespace", "bare_array", "invalid_json", "false_success", "numeric_success",
    "wrong_version", "wrong_kind", "extra_field", "missing_field", "rows_not_list",
    "stderr", "blank_stderr", "nonzero", "stdout_none",
])
def test_query_refuses_uncertain_or_failed_response(monkeypatch, isolated_root, kind, fault):
    payload = {"version": 1, "query": kind, "success": True, "rows": []}
    if fault == "false_success":
        payload["success"] = False
    elif fault == "numeric_success":
        payload["success"] = 1
    elif fault == "wrong_version":
        payload["version"] = True
    elif fault == "wrong_kind":
        payload["query"] = "listeners" if kind == "processes" else "processes"
    elif fault == "extra_field":
        payload["unverified"] = True
    elif fault == "missing_field":
        del payload["success"]
    elif fault == "rows_not_list":
        payload["rows"] = None
    stdout = {"empty": "", "whitespace": " \r\n", "bare_array": "[]", "invalid_json": "{"}.get(fault, json.dumps(payload))
    response = result(None if fault == "stdout_none" else stdout,
        stderr="OFFLINE_FAULT_PRIVATE_TEXT" if fault == "stderr" else " " if fault == "blank_stderr" else "",
        returncode=3 if fault == "nonzero" else 0)
    install_result(monkeypatch, response)
    with pytest.raises(lifecycle.LifecycleError, match="^PROCESS_DISCOVERY_FAILED$") as refused:
        invoke(lifecycle.NativeBackend(isolated_root), kind)
    assert "OFFLINE_FAULT_PRIVATE_TEXT" not in str(refused.value)


@pytest.mark.parametrize("kind", ["processes", "listeners"])
@pytest.mark.parametrize("fault", ["timeout", "permission", "missing_runtime"])
def test_query_transport_failures_are_safe_errors(monkeypatch, isolated_root, kind, fault):
    failure = {"timeout": subprocess.TimeoutExpired("offline-query", 15),
        "permission": PermissionError("OFFLINE_PRIVATE_ERROR"), "missing_runtime": FileNotFoundError("OFFLINE_PRIVATE_ERROR")}[fault]
    install_result(monkeypatch, failure)
    with pytest.raises(lifecycle.LifecycleError, match="^PROCESS_DISCOVERY_FAILED$"):
        invoke(lifecycle.NativeBackend(isolated_root), kind)


def cim_row(root, pid=654321, created=133000000000000120):
    return {"ProcessId": pid, "ParentProcessId": 654320, "ExecutablePath": str(root / "offline-python.exe"),
        "CommandLine": str(root / "scripts/managed_service.py") + " --instance-id " + str(uuid4()) + " --role worker",
        "CreationFileTime": created}


@pytest.mark.parametrize("fault", ["duplicate_pid", "missing_creation", "bool_pid", "missing_executable", "wrong_creation_type"])
def test_cim_rows_require_complete_creation_identity(monkeypatch, isolated_root, fault):
    row = cim_row(isolated_root)
    rows = [row]
    if fault == "duplicate_pid":
        rows.append(dict(row))
    elif fault == "missing_creation":
        del row["CreationFileTime"]
    elif fault == "bool_pid":
        row["ProcessId"] = True
    elif fault == "missing_executable":
        row["ExecutablePath"] = None
    else:
        row["CreationFileTime"] = str(row["CreationFileTime"])
    install_result(monkeypatch, result(envelope("processes", rows)))
    with pytest.raises(lifecycle.LifecycleError, match="^PROCESS_DISCOVERY_FAILED$"):
        lifecycle.NativeBackend(isolated_root)._rows()


def facts_for(row, offset=7):
    return {"pid": row["ProcessId"], "created": row["CreationFileTime"] + offset, "executable": row["ExecutablePath"]}


def test_cim_microsecond_precision_requires_two_identical_raw_os_reads(monkeypatch, isolated_root):
    row = cim_row(isolated_root)
    facts = facts_for(row)
    calls = []

    def observe(pid):
        calls.append(pid)
        return dict(facts)

    monkeypatch.setattr(lifecycle, "process_facts", observe)
    observed = lifecycle.NativeBackend(isolated_root)._identity(row)
    assert observed["created"] == facts["created"] and calls == [row["ProcessId"], row["ProcessId"]]


@pytest.mark.parametrize("fault", ["cim_creation_mismatch", "cim_executable_mismatch", "raw_creation_changed", "raw_executable_changed"])
def test_cim_or_os_identity_races_are_refused(monkeypatch, isolated_root, fault):
    row = cim_row(isolated_root)
    first, second = facts_for(row), facts_for(row)
    if fault == "cim_creation_mismatch":
        first["created"] += 10
    elif fault == "cim_executable_mismatch":
        first["executable"] += ".different"
    elif fault == "raw_creation_changed":
        second["created"] += 1  # Even a change within the same microsecond is unsafe.
    else:
        second["executable"] += ".different"
    observations = iter([first, second])
    monkeypatch.setattr(lifecycle, "process_facts", lambda pid: next(observations))
    with pytest.raises(lifecycle.LifecycleError, match="^IDENTITY_MISMATCH$"):
        lifecycle.NativeBackend(isolated_root)._identity(row)


@pytest.mark.parametrize("still_alive", [True, False])
def test_missing_cim_pid_is_not_assumed_dead(monkeypatch, isolated_root, still_alive):
    backend = lifecycle.NativeBackend(isolated_root)
    monkeypatch.setattr(backend, "_rows", lambda: [])
    row = cim_row(isolated_root)
    monkeypatch.setattr(lifecycle, "process_facts", lambda pid: facts_for(row) if still_alive else None)
    if still_alive:
        with pytest.raises(lifecycle.LifecycleError, match="^PROCESS_IDENTITY_UNVERIFIED$"):
            backend.inspect(row["ProcessId"])
    else:
        assert backend.inspect(row["ProcessId"]) is None


class OfflineBackend:
    is_test = True

    def __init__(self):
        self.terminations = 0

    def discover(self):
        return []

    def inspect(self, pid):
        raise lifecycle.LifecycleError("PROCESS_IDENTITY_UNVERIFIED")

    def terminate(self, identity):
        self.terminations += 1
        raise AssertionError("Unverified process must never be terminated")


def protected_manifest(manager):
    settings = manager.root / "fake-settings/.env"
    settings.parent.mkdir()
    settings.write_text("", encoding="ascii")
    entry = {"root": str(manager.root), "state_dir": str(manager.directory), "role": "worker", "mode": "coder",
        "protected": True, "instance_id": str(uuid4()), "settings_path": str(settings),
        "settings_stat": {"size": 0, "mtime_ns": 0, "inode": 0}, "ports": {"backend": 29431, "frontend": 29432},
        "config_digest": None, "policy": dict(lifecycle.SAFE_ENV), "status": "running", "manager_pid": 654320,
        "manager_created": 133000000000000000, "pid": 654321, "created": 133000000000000127,
        "executable": str(manager.root / "offline-python.exe")}
    return {"version": 1, "project_root": str(manager.root), "generation": 0, "entries": {"worker": entry}}


def test_manual_stop_cannot_mark_unverified_live_identity_dead(isolated_root):
    backend = OfflineBackend()
    manager = lifecycle.LifecycleManager(isolated_root, backend=backend)
    manager.directory.mkdir(parents=True)
    manager._save(protected_manifest(manager))
    before = manager.manifest_path.read_bytes()
    approved = []
    with pytest.raises(lifecycle.LifecycleError, match="^PROCESS_IDENTITY_UNVERIFIED$"):
        manager.manual_stop(confirmation=lambda scope: approved.append(scope) or scope["challenge"])
    assert manager.manifest_path.read_bytes() == before and not approved and backend.terminations == 0


def test_uncertain_stop_persists_unknown_and_protection(isolated_root):
    backend = OfflineBackend()
    manager = lifecycle.LifecycleManager(isolated_root, backend=backend)
    manager.directory.mkdir(parents=True)
    manifest = protected_manifest(manager)
    with pytest.raises(lifecycle.LifecycleError, match="^STOP_UNCERTAIN$"):
        manager._stop_entries(manifest, list(manifest["entries"].values()), approval=str(uuid4()))
    stored = manager._load()["entries"]["worker"]
    assert stored["status"] == "unknown" and stored["protected"] and stored["pid"] == 654321
    assert backend.terminations == 0


def test_protected_maintenance_precheck_does_not_open_or_create_lock(monkeypatch, isolated_root):
    manager = lifecycle.LifecycleManager(isolated_root, backend=OfflineBackend())
    manager.directory.mkdir(parents=True)
    manager._save(protected_manifest(manager))
    before = manager.manifest_path.read_bytes()
    monkeypatch.setattr(lifecycle, "credential_names", lambda: frozenset())

    @contextmanager
    def forbidden_lock(directory):
        raise AssertionError("Protected precheck must refuse before lock I/O")
        yield

    monkeypatch.setattr(lifecycle, "operation_lock", forbidden_lock)
    with pytest.raises(lifecycle.LifecycleError, match="^PROTECTED_INSTANCE$"):
        with manager.maintenance_session():
            raise AssertionError("Protected maintenance body must not run")
    assert manager.manifest_path.read_bytes() == before
    assert {path.name for path in manager.directory.iterdir()} == {"manifest.json"}


def test_maintenance_precheck_is_rechecked_after_lock(monkeypatch, isolated_root):
    manager = lifecycle.LifecycleManager(isolated_root, backend=OfflineBackend())
    protected = protected_manifest(manager)
    empty = {**protected, "entries": {}}
    states = iter([empty, protected])
    monkeypatch.setattr(manager, "_load", lambda: next(states))
    monkeypatch.setattr(manager, "_check", lambda state: {})
    monkeypatch.setattr(lifecycle, "credential_names", lambda: frozenset())
    locks = []

    @contextmanager
    def simulated_lock(directory):
        locks.append(directory)
        yield

    monkeypatch.setattr(lifecycle, "operation_lock", simulated_lock)
    with pytest.raises(lifecycle.LifecycleError, match="^PROTECTED_INSTANCE$"):
        with manager.maintenance_session():
            raise AssertionError("Protected state appearing under lock must refuse")
    assert locks == [manager.directory]
