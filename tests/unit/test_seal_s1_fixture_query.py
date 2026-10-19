"""Strict Permit fixture query faults only; never construct the DB fixture."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "scripts"))
sys.path.insert(0, str(PROJECT / "tests/fixtures"))
import lifecycle_manager as lifecycle
import lifecycle_permit_child as fixture


@pytest.fixture
def owner(monkeypatch):
    # Bypass __init__: it would acquire the real guard and start a DB fixture.
    child = fixture.PermitProcessChild.__new__(fixture.PermitProcessChild)
    child.root = PROJECT / "work/seal-fixes" / ("fixture-query-" + uuid4().hex)
    child.process = SimpleNamespace(pid=654321)
    child.manager = lifecycle

    def forbidden(*args, **kwargs):
        raise AssertionError("No process, guard or OS query is allowed")

    monkeypatch.setattr(fixture.subprocess, "Popen", forbidden)
    monkeypatch.setattr(lifecycle, "process_facts", forbidden)
    monkeypatch.setattr(lifecycle, "maintenance_guard", forbidden)
    return child


def response(rows, *, stderr="", returncode=0):
    return SimpleNamespace(stdout=json.dumps({"version": 1, "query": "processes", "success": True, "rows": rows}),
        stderr=stderr, returncode=returncode)


def install(monkeypatch, value):
    calls = []

    def run(arguments, **options):
        calls.append((arguments, options))
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(lifecycle.subprocess, "run", run)
    return calls


def row(owner, *, child=False):
    return {"ProcessId": owner.process.pid + int(child), "ParentProcessId": owner.process.pid if child else 654320,
        "ExecutablePath": str(owner.root / "offline-python.exe"), "CommandLine": "explicit-offline-fixture-identity"}


@pytest.mark.parametrize("with_matches", [True, False])
def test_fixture_accepts_only_explicit_success_and_scoped_rows(monkeypatch, owner, with_matches):
    rows = [row(owner), row(owner, child=True)] if with_matches else []
    calls = install(monkeypatch, response(rows))
    assert owner._rows() == rows
    command = calls[0][0][-1]
    assert "ProcessId=654321 OR ParentProcessId=654321" in command
    assert "-ErrorAction Stop" in command and "$ErrorActionPreference='Stop'" in command
    assert "$Error.Count -ne 0" in command and "catch { exit 3 }" in command
    assert "AGENTFORGE_FIXTURE_LAUNCHER_PID" not in command


def test_native_query_rejects_unreadable_python_metadata_before_project_filter(monkeypatch, owner):
    calls = install(monkeypatch, response([]))
    assert lifecycle.NativeBackend(owner.root)._rows() == []
    command = calls[0][0][-1]
    scan = command.index("$candidates=@(Get-CimInstance")
    reject = command.index("throw 'CandidateMetadataUnavailable'")
    scope = command.index("$rows=@($candidates | Where-Object")
    assert scan < reject < scope
    for property_name in ("ExecutablePath", "CommandLine", "CreationDate"):
        assert "$candidate." + property_name in command[scan:scope]


@pytest.mark.parametrize("fault", ["empty", "blank", "legacy_list", "false_success", "wrong_query",
    "bool_version", "wrong_rows", "stderr", "nonzero", "invalid_json"])
def test_fixture_query_failure_cannot_become_no_children(monkeypatch, owner, fault):
    value = response([])
    payload = json.loads(value.stdout)
    if fault == "false_success":
        payload["success"] = False
    elif fault == "wrong_query":
        payload["query"] = "listeners"
    elif fault == "bool_version":
        payload["version"] = True
    elif fault == "wrong_rows":
        payload["rows"] = {}
    value.stdout = {"empty": "", "blank": " \n", "legacy_list": "[]", "invalid_json": "{"}.get(fault, json.dumps(payload))
    if fault == "stderr":
        value.stderr = "OFFLINE_PRIVATE_ERROR"
    elif fault == "nonzero":
        value.returncode = 3
    install(monkeypatch, value)
    with pytest.raises(RuntimeError, match="^FIXTURE_IDENTITY_QUERY_FAILED$"):
        owner._rows()


@pytest.mark.parametrize("failure", [PermissionError("OFFLINE_PRIVATE_ERROR"), subprocess.TimeoutExpired("offline-query", 15)])
def test_fixture_maps_transport_failure_to_static_error(monkeypatch, owner, failure):
    install(monkeypatch, failure)
    with pytest.raises(RuntimeError, match="^FIXTURE_IDENTITY_QUERY_FAILED$"):
        owner._rows()


@pytest.mark.parametrize("fault", ["missing", "extra", "duplicate", "bool_pid", "string_pid", "negative_parent",
    "missing_executable", "missing_command", "unrelated"])
def test_fixture_refuses_incomplete_duplicate_or_unrelated_identity_rows(monkeypatch, owner, fault):
    identity = row(owner)
    rows = [identity]
    if fault == "missing":
        del identity["ExecutablePath"]
    elif fault == "extra":
        identity["unverified"] = True
    elif fault == "duplicate":
        rows.append(dict(identity))
    elif fault == "bool_pid":
        identity["ProcessId"] = True
    elif fault == "string_pid":
        identity["ProcessId"] = str(owner.process.pid)
    elif fault == "negative_parent":
        identity["ParentProcessId"] = -1
    elif fault == "missing_executable":
        identity["ExecutablePath"] = None
    elif fault == "missing_command":
        identity["CommandLine"] = None
    else:
        identity["ProcessId"] += 10
        identity["ParentProcessId"] += 10
    install(monkeypatch, response(rows))
    with pytest.raises(RuntimeError, match="^FIXTURE_IDENTITY_QUERY_FAILED$"):
        owner._rows()


@pytest.mark.parametrize("pid", [True, -1, "654321 OR ProcessId=1"])
def test_fixture_does_not_interpolate_unvalidated_launcher_pid(monkeypatch, owner, pid):
    owner.process.pid = pid
    calls = install(monkeypatch, response([]))
    with pytest.raises(RuntimeError, match="^FIXTURE_IDENTITY_QUERY_FAILED$"):
        owner._rows()
    assert not calls


@pytest.mark.parametrize("kind", ["processes", "listeners"])
def test_shared_query_child_environment_never_reads_or_inherits_fake_credentials(monkeypatch, owner, kind):
    class NamedEnvironment:
        values = {"SystemRoot": "offline-system", "PATH": "offline-path",
            "AGENTFORGE_MODEL_CODER_KEY": "FAKE_VALUE_MUST_NOT_BE_READ",
            "AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN": "FAKE_ISSUER_MUST_NOT_BE_READ"}

        def __contains__(self, name):
            assert name in lifecycle.QUERY_OS_NAMES
            return name in self.values

        def __getitem__(self, name):
            assert name in lifecycle.QUERY_OS_NAMES
            return self.values[name]

        def __iter__(self):
            raise AssertionError("Do not enumerate or copy environment values")

    # Substitute the module's OS view, without reading/replacing parent secrets.
    monkeypatch.setattr(lifecycle, "os", SimpleNamespace(environ=NamedEnvironment()))
    value = response([])
    if kind == "listeners":
        value.stdout = json.dumps({"version": 1, "query": kind, "success": True, "rows": []})
    calls = install(monkeypatch, value)
    assert lifecycle.NativeBackend._query(kind, "$rows=@()") == []
    environment = calls[0][1]["env"]
    assert environment == {"SystemRoot": "offline-system", "PATH": "offline-path"}
    assert "FAKE_" not in repr(environment)
