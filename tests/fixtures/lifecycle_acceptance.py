"""Isolated, offline lifecycle acceptance; every model credential here is fake.

This helper launches only lifecycle_dummy.py, never AgentForge services. Persistent
FakeBackend rows exercise the real manifest/lock code across independent Python
processes. The native dummy probe separately checks Windows creation identity.
"""
import argparse
import ast
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "scripts"))
import lifecycle_manager as lifecycle

FAKE_KEY = "offline-fake-coder-key-no-provider-access-" + uuid4().hex
SYSTEM_NAMES = ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP",
    "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def public_environment():
    """No copy/items or credential reads, including in the pytest parent."""
    return {name: os.environ[name] for name in SYSTEM_NAMES if name in os.environ}


@contextmanager
def coder_name():
    assert "AGENTFORGE_MODEL_CODER_KEY" not in os.environ
    os.environ["AGENTFORGE_MODEL_CODER_KEY"] = FAKE_KEY
    try:
        yield
    finally:
        del os.environ["AGENTFORGE_MODEL_CODER_KEY"]


def refused(code, operation):
    try:
        operation()
    except lifecycle.LifecycleError as error:
        assert error.code == code
    else:
        raise AssertionError("Expected lifecycle refusal")


class FakeBackend:
    """No processes/ports/DB; only nonsecret identity rows in this test root."""
    is_test = True
    ports = {"backend": 28100, "frontend": 25173}

    def __init__(self, root):
        self.root = Path(root)
        self.rows = self.root / "fake-processes"
        self.rows.mkdir(parents=True, exist_ok=True)
        self.launches = []
        self.terminations = []
        self.before_launch = None

    def _path(self, pid):
        return self.rows / (str(pid) + ".json")

    def discover(self):
        return [json.loads(path.read_text(encoding="utf-8")) for path in self.rows.glob("*.json")]

    def inspect(self, pid):
        path = self._path(pid)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def launch(self, spec):
        self.launches.append(spec)
        if self.before_launch:
            callback, self.before_launch = self.before_launch, None
            callback()
        identity = {"pid": int(uuid4().hex[:7], 16) + 400000000,
            "created": time.time_ns(), "executable": str(self.root / "offline-python.exe"),
            "command_line": "offline-fake-process --instance-id " + spec["instance_id"],
            "instance_id": spec["instance_id"], "role": spec["role"]}
        self._path(identity["pid"]).write_text(json.dumps(identity), encoding="utf-8")
        return identity

    def terminate(self, identity):
        current = self.inspect(identity["pid"])
        if current is None:
            return
        assert lifecycle.identity_matches(identity, current)
        self.terminations.append(identity["instance_id"])
        self._path(identity["pid"]).unlink()

    def healthy(self, identity, spec):
        return lifecycle.identity_matches(identity, self.inspect(identity["pid"]))


class NativeDummyBackend(FakeBackend):
    """Only the dedicated offline fixture runs; no production entrypoint."""
    def __init__(self, root):
        super().__init__(root)
        self.children = {}
        self.launched_identities = {}

    def launch(self, spec):
        self.launches.append(spec)
        ready = self.root / "dummy-ready" / (spec["instance_id"] + ".json")
        # Windows venv python.exe can be a redirector parent. The stdlib-only
        # dummy uses the base interpreter so Popen owns the actual child PID.
        command = [getattr(sys, "_base_executable", sys.executable), "-I", str(PROJECT / "tests/fixtures/lifecycle_dummy.py"),
            "--ready-file", str(ready), "--instance-id", spec["instance_id"],
            "--role", spec["role"], "--lifetime-seconds", "20"]
        child = subprocess.Popen(command, cwd=self.root, env=None, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=FLAGS)
        self.children[spec["instance_id"]] = child
        launched = lifecycle.process_facts(child.pid)
        assert launched
        self.launched_identities[spec["instance_id"]] = {**launched,
            "instance_id": spec["instance_id"], "role": spec["role"]}
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            assert child.poll() is None
            time.sleep(.02)
        assert ready.exists()
        claim = json.loads(ready.read_text(encoding="utf-8"))
        assert claim["pid"] == child.pid
        assert claim["service_starts"] == claim["database_calls"] == claim["external_model_calls"] == 0
        facts = lifecycle.process_facts(child.pid)
        assert facts and facts["created"] == claim["created"]
        identity = {**facts, "instance_id": spec["instance_id"], "role": spec["role"],
            "command_line": "offline-dummy --instance-id " + spec["instance_id"]}
        self._path(child.pid).write_text(json.dumps(identity), encoding="utf-8")
        return identity

    def inspect(self, pid):
        saved = super().inspect(pid)
        if not saved:
            return None
        actual = lifecycle.process_facts(pid)
        return {**saved, **actual} if actual else None

    def discover(self):
        return [current for saved in super().discover() if (current := self.inspect(saved["pid"]))]

    def terminate(self, identity):
        assert lifecycle.identity_matches(identity, self.inspect(identity["pid"]))
        lifecycle.NativeBackend(self.root).terminate(identity)
        self.children[identity["instance_id"]].wait(timeout=5)
        self.terminations.append(identity["instance_id"])
        self._path(identity["pid"]).unlink(missing_ok=True)

    def finish(self):
        for instance, child in self.children.items():
            if child.poll() is None:
                identity = self.launched_identities.get(instance)
                assert identity and identity["instance_id"] == instance
                lifecycle.NativeBackend(self.root).terminate(identity)
            child.wait(timeout=5)


STUB_OBSERVATION = '''import json
import os
from pathlib import Path
import time

def observe(role):
    import lifecycle_runtime
    lifecycle_runtime.ready(role)
    root = Path(__file__).resolve().parents[1]
    flags = ("AGENTFORGE_REAL_CALLS_ENABLED", "AGENTFORGE_SINGLE_USE_PERMITS_ENABLED",
        "AGENTFORGE_REAL_WORKER_MODE", "AGENTFORGE_REAL_DAILY_BUDGET_USD",
        "AGENTFORGE_REAL_TEST_BUDGET_USD", "AGENTFORGE_EXTERNAL_MODELS_BLOCKED", "AGENTFORGE_REAL_MAX_RETRIES")
    result = {"pid": os.getpid(), "fixture_only": True,
        "coder_name_present": "AGENTFORGE_MODEL_CODER_KEY" in os.environ,
        "issuer_name_present": "AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN" in os.environ,
        "policy": {name: os.environ.get(name) for name in flags}}
    target = root / "work" / ("offline-observation-" + role + ".json")
    target.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
'''

STUB_UVICORN = '''from http.server import BaseHTTPRequestHandler, HTTPServer
import time
from offline_observation import observe

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"fixture_only":true,"status":"offline-lifecycle-test"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass

def run(app, *, factory, host, port, **kwargs):
    assert host == "127.0.0.1" and factory and app == "app.main:create_app"
    observe("backend")
    server = HTTPServer((host, port), Handler)
    server.timeout = .2
    deadline = time.monotonic() + 300
    with server:
        while time.monotonic() < deadline:
            server.handle_request()
'''

STUB_WORKER = '''import time
from offline_observation import observe

observe("worker")
deadline = time.monotonic() + 300
while time.monotonic() < deadline:
    time.sleep(.1)
'''


class NativeStubBackend(lifecycle.NativeBackend):
    """Run the unchanged production bootstrap against trusted stdlib stubs."""
    is_test = True

    def __init__(self, root):
        super().__init__(root)
        assert hasattr(self, "python_executable")
        # This is an internal test dependency, never a production CLI override.
        self.python_executable = Path(sys.executable)
        self.owned = {}
        self.launches = []
        held = []
        try:
            for _ in range(2):
                item = socket.socket()
                item.bind(("127.0.0.1", 0))
                held.append(item)
            self.ports = dict(zip(("backend", "frontend"), (item.getsockname()[1] for item in held)))
        finally:
            for item in held:
                item.close()

    def launch(self, spec):
        self.launches.append(spec)
        try:
            identity = super().launch(spec)
            self.owned[spec["instance_id"]] = identity
            return identity
        finally:
            ready = Path(spec["state_dir"]) / "ready" / (spec["instance_id"] + ".json")
            if ready.is_file():
                claim = json.loads(ready.read_text(encoding="utf-8"))
                actual = self.inspect(claim["pid"])
                if claim.get("instance_id") == spec["instance_id"] and lifecycle.identity_matches(claim, actual):
                    self.owned[spec["instance_id"]] = actual

    def finish(self):
        for identity in self.owned.values():
            actual = self.inspect(identity["pid"])
            if actual is not None:
                assert lifecycle.identity_matches(identity, actual)
                super().terminate(identity)


def setup_native_chain(directory):
    # Only these current, trusted production modules are copied. No dotenv or
    # production settings are copied; the service .env files are empty.
    root = directory / "synthetic-project"
    (root / "scripts").mkdir(parents=True)
    for name in ("lifecycle_manager.py", "managed_service.py", "lifecycle.py", "lifecycle_v2.py",
                 "lifecycle_windows.py", "lifecycle_channel.py", "lifecycle_runtime.py"):
        (root / "scripts" / name).write_bytes((PROJECT / "scripts" / name).read_bytes())
    (root / "backend/app/workers").mkdir(parents=True)
    (root / "backend/app/__init__.py").touch()
    (root / "backend/app/workers/__init__.py").touch()
    (root / "backend/app/workers/main.py").write_text(STUB_WORKER, encoding="utf-8")
    (root / "backend/uvicorn.py").write_text(STUB_UVICORN, encoding="utf-8")
    (root / "backend/offline_observation.py").write_text(STUB_OBSERVATION, encoding="utf-8")
    (root / "work/p5-live-preflight").mkdir(parents=True)
    (root / "work/p5-live-preflight/.env").touch()
    (root / ".env").touch()
    (root / "config").mkdir()
    (root / "config/deepseek-coder-local.json").write_text("{}", encoding="utf-8")
    backend = NativeStubBackend(root)
    return lifecycle.LifecycleManager(root, backend=backend), backend


def observations(backend, expected_coder):
    result = []
    for role in ("backend", "worker"):
        path = backend.root / "work" / ("offline-observation-" + role + ".json")
        deadline = time.monotonic() + 8
        while not path.is_file() and time.monotonic() < deadline:
            time.sleep(.05)
        item = json.loads(path.read_text(encoding="utf-8"))
        assert item["fixture_only"] is True and item["coder_name_present"] is expected_coder
        assert not item["issuer_name_present"]
        assert item["policy"] == {name: lifecycle.SAFE_ENV[name] for name in item["policy"]}
        assert item["pid"] == next(value["pid"] for value in backend.owned.values() if value["role"] == role)
        result.append(item)
    return result


def native_scope_is_empty(backend):
    deadline = time.monotonic() + 5
    while backend.discover() and time.monotonic() < deadline:
        time.sleep(.05)
    assert not backend.discover()


def setup(directory, native=False):
    root = directory / "synthetic-project"
    (root / "work/p5-live-preflight").mkdir(parents=True, exist_ok=True)
    (root / "work/p5-live-preflight/.env").touch()
    (root / ".env").touch()
    (root / "config").mkdir(exist_ok=True)
    (root / "config/deepseek-coder-local.json").write_text("{}", encoding="utf-8")
    backend = NativeDummyBackend(root) if native else FakeBackend(root)
    return lifecycle.LifecycleManager(root, backend=backend), backend


def saved_bytes(manager):
    return manager.manifest_path.read_bytes()


def protected(manager):
    with coder_name():
        state = manager.start(mode="coder", models_only=True)
    assert set(state["entries"]) == {"backend", "worker"}
    assert all(entry["protected"] and entry["mode"] == "coder" for entry in state["entries"].values())
    return state


def approval(scope):
    assert scope["action"] == "stop" and len(scope["instances"]) == 2
    return scope["challenge"]


def case_fake_coder_protected_start(directory):
    manager, backend = setup_native_chain(directory)
    try:
        os.environ["AGENTFORGE_REAL_CALLS_ENABLED"] = "true"
        os.environ["AGENTFORGE_SINGLE_USE_PERMITS_ENABLED"] = "true"
        os.environ["AGENTFORGE_REAL_DAILY_BUDGET_USD"] = "999"
        state = protected(manager)
        assert len(backend.owned) == 2
        observations(backend, expected_coder=True)
        # NativeBackend validates that the actual registered PID owns the port.
        assert backend._listeners(backend.ports["backend"]) == [state["entries"]["backend"]["pid"]]
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:" + str(backend.ports["backend"]) + "/health/ready", timeout=3) as response:
            assert json.loads(response.read())["fixture_only"] is True
        before = saved_bytes(manager)
        def no_key_maintenance():
            with manager.maintenance_session():
                raise AssertionError("A native protected instance cannot enter maintenance")
        refused("PROTECTED_INSTANCE", no_key_maintenance)
        with coder_name():
            manager.start(mode="coder", restart_models=True)
        assert saved_bytes(manager) == before and len(backend.launches) == 2
        manager.manual_stop(confirmation=approval)
        assert all(lifecycle.process_facts(entry["pid"]) is None for entry in state["entries"].values())
        native_scope_is_empty(backend)
        for path in manager.directory.rglob("*.log"):
            assert FAKE_KEY.encode() not in path.read_bytes()
    finally:
        backend.finish()


def case_keyless_maintenance_rejected(directory):
    manager, backend = setup(directory)
    protected(manager)
    before = saved_bytes(manager)
    entered = False
    def maintenance():
        nonlocal entered
        with manager.maintenance_session():
            entered = True
    refused("PROTECTED_INSTANCE", maintenance)
    assert not entered and not backend.terminations and saved_bytes(manager) == before


def case_keyless_test_stop_rejected(directory):
    manager, backend = setup(directory)
    protected(manager)
    before = saved_bytes(manager)
    for operation in (lambda: manager.stop(), lambda: manager.stop(models_only=True),
            lambda: manager.stop(worker_only=True), manager.restart_worker):
        refused("PROTECTED_INSTANCE", operation)
        assert saved_bytes(manager) == before and len(backend.launches) == 2 and not backend.terminations
    refused("APPROVAL_REQUIRED", lambda: manager.manual_stop(confirmation=lambda scope: "wrong"))
    assert saved_bytes(manager) == before


def case_finally_cannot_replace_protected(directory):
    manager, backend = setup(directory)
    protected(manager)
    before = saved_bytes(manager)
    seen = []
    try:
        refused("PROTECTED_INSTANCE", lambda: manager.start(mode="mock", models_only=True, restart_models=True))
        raise RuntimeError("Synthetic maintenance failure")
    except RuntimeError:
        seen.append("synthetic_failure")
    finally:
        for operation in (lambda: manager.stop(worker_only=True), manager.restart_worker,
                lambda: manager.start(mode="mock", models_only=True, restart_models=True)):
            refused("PROTECTED_INSTANCE", operation)
            seen.append("refused")
    assert len(seen) == 4 and not backend.terminations and len(backend.launches) == 2
    assert saved_bytes(manager) == before


def contender(directory):
    manager, backend = setup(directory)
    try:
        manager.start(mode="mock", models_only=True, restart_models=True)
    except lifecycle.LifecycleError as error:
        return {"code": error.code, "launches": len(backend.launches), "terminations": len(backend.terminations)}
    return {"code": "UNEXPECTED_SUCCESS", "launches": len(backend.launches)}


def case_concurrent_start_cannot_overwrite(directory):
    manager, backend = setup(directory)
    observed = []
    def concurrent():
        env = public_environment()
        command = [sys.executable, "-I", str(Path(__file__).resolve()), "--scenario", "_contender", "--directory", str(directory)]
        result = subprocess.run(command, env=env, cwd=PROJECT, capture_output=True, text=True, timeout=10, creationflags=FLAGS)
        assert result.returncode == 0
        observed.append(json.loads(result.stdout))
    backend.before_launch = concurrent
    state = protected(manager)
    assert observed == [{"code": "LOCK_BUSY", "launches": 0, "terminations": 0}]
    assert all(entry["protected"] for entry in state["entries"].values())
    assert len(backend.launches) == 2 and not backend.terminations
    before = saved_bytes(manager)
    concurrent()
    assert observed[-1] == {"code": "PROTECTED_INSTANCE", "launches": 0, "terminations": 0}
    assert saved_bytes(manager) == before
    failed_lock = directory / "failed-lock"
    original_open = lifecycle.os.open
    def denied_open(*args, **kwargs):
        raise PermissionError("Controlled offline lock-open failure")
    lifecycle.os.open = denied_open
    try:
        try:
            with lifecycle.operation_lock(failed_lock):
                raise AssertionError("Open failure must refuse the lock")
        except PermissionError:
            pass
    finally:
        lifecycle.os.open = original_open
    # A failed acquisition cannot leave a reentrant owner that skips the real
    # OS lock on the next call. An independent child must still be excluded.
    with lifecycle.operation_lock(failed_lock):
        command = [sys.executable, "-I", str(Path(__file__).resolve()), "--scenario", "_lock_contender", "--directory", str(failed_lock)]
        result = subprocess.run(command, env=public_environment(), cwd=PROJECT, capture_output=True,
            text=True, timeout=10, creationflags=FLAGS)
        assert result.returncode == 0 and json.loads(result.stdout) == {"code": "LOCK_BUSY"}


def case_reused_pid_is_never_terminated(directory):
    manager, backend = setup(directory)
    state = manager.start(mode="mock", models_only=True)
    entry = state["entries"]["worker"]
    changed = backend.inspect(entry["pid"])
    changed["created"] += 1
    backend._path(entry["pid"]).write_text(json.dumps(changed), encoding="utf-8")
    before = saved_bytes(manager)
    for operation in (manager.status, manager.stop, manager.restart_worker):
        refused("IDENTITY_MISMATCH", operation)
    assert not backend.terminations and saved_bytes(manager) == before
    native, dummy = setup(directory / "native", native=True)
    try:
        actual = native.start(mode="mock", models_only=True)["entries"]["worker"]
        refused("IDENTITY_MISMATCH", lambda: lifecycle.NativeBackend(dummy.root).terminate({**actual, "created": actual["created"] + 1}))
        assert lifecycle.process_facts(actual["pid"])["created"] == actual["created"]
        native.stop()
    finally:
        dummy.finish()


def case_exited_identity_is_safely_cleared(directory):
    manager, backend = setup(directory)
    state = protected(manager)
    for entry in state["entries"].values():
        backend._path(entry["pid"]).unlink()  # The isolated fake processes have exited.
    before = saved_bytes(manager)
    refused("PROTECTED_INSTANCE", lambda: manager.start(mode="mock", models_only=True))
    assert saved_bytes(manager) == before
    cleared = manager.manual_stop(confirmation=approval)
    assert all(entry["status"] == "stopped" for entry in cleared["entries"].values())
    # A human stop grants no keyless test/finally permission to replace Coder.
    refused("PROTECTED_INSTANCE", lambda: manager.start(mode="mock", models_only=True))
    refused("PROTECTED_INSTANCE", manager.restart_worker)
    def stopped_maintenance():
        with manager.maintenance_session():
            raise AssertionError("Protected tombstone cannot authorize business mutation")
    refused("PROTECTED_INSTANCE", stopped_maintenance)
    with coder_name():
        started = manager.start(mode="coder", models_only=True)
    assert all(entry["protected"] and entry["status"] == "running" for entry in started["entries"].values())
    assert {entry["instance_id"] for entry in started["entries"].values()}.isdisjoint(
        entry["instance_id"] for entry in state["entries"].values())
    assert not backend.terminations  # No nonexistent or unrelated PID was killed.
    uncertain, fake = setup(directory / "uncertain")
    interrupted = protected(uncertain)
    for entry in interrupted["entries"].values():
        entry["status"] = "unknown"
        for name in ("pid", "created", "executable", "command_line", "parent_pid"):
            entry.pop(name, None)
    uncertain._save(interrupted)
    refused("START_UNCERTAIN", lambda: uncertain.start(mode="mock", models_only=True))
    ended = uncertain.manual_stop(confirmation=approval)
    assert all(entry["protected"] and entry["status"] == "stopped" for entry in ended["entries"].values())
    assert len(fake.terminations) == 2 and not fake.discover()
    refused("PROTECTED_INSTANCE", uncertain.restart_worker)


def case_mock_without_protected_starts(directory):
    manager, backend = setup(directory)
    state = manager.start(mode="mock")
    assert set(state["entries"]) == {"backend", "worker", "frontend"}
    assert len(backend.launches) == 3 and all(not entry["protected"] for entry in state["entries"].values())
    manager.stop()
    assert len(backend.terminations) == 3
    with coder_name():
        refused("MODEL_CREDENTIALS_FORBIDDEN", lambda: manager.start(mode="mock"))
    refused("CODER_CREDENTIAL_REQUIRED", lambda: manager.start(mode="coder"))
    native, stub = setup_native_chain(directory / "native-mock")
    try:
        actual = native.start(mode="mock", models_only=True)
        assert len(stub.owned) == 2 and all(not entry["protected"] for entry in actual["entries"].values())
        observations(stub, expected_coder=False)
        native.stop()
        native_scope_is_empty(stub)
    finally:
        stub.finish()


def case_refusal_has_no_business_side_effects(directory):
    manager, backend = setup(directory)
    protected(manager)
    task = backend.root / "task-state-sentinel.json"
    task.write_text('{"task_id":"offline-only","budget":"0","status":"unchanged"}', encoding="utf-8")
    before_task, before_manifest = task.read_bytes(), saved_bytes(manager)
    def forbidden(event, args):
        if event in {"socket.connect", "sqlite3.connect", "subprocess.Popen"}:
            raise AssertionError("Rejected operations must not access services or launch processes")
    sys.addaudithook(forbidden)
    refused("PROTECTED_INSTANCE", manager.stop)
    refused("PROTECTED_INSTANCE", lambda: manager.start(mode="mock", models_only=True, restart_models=True))
    def maintenance():
        with manager.maintenance_session():
            task.write_text("changed", encoding="utf-8")
    refused("PROTECTED_INSTANCE", maintenance)
    assert task.read_bytes() == before_task and saved_bytes(manager) == before_manifest
    assert not backend.terminations and len(backend.launches) == 2
    assert not any(name == "app" or name.startswith(("app.", "sqlalchemy", "redis", "psycopg")) for name in sys.modules)


def case_credentials_do_not_enter_evidence(directory):
    manager, backend = setup(directory)
    sentinel = b"offline-private-settings-sentinel-not-a-real-key"
    (backend.root / "work/p5-live-preflight/.env").write_bytes(sentinel)
    protected(manager)
    refused("PROTECTED_INSTANCE", manager.stop)
    for path in manager.directory.rglob("*"):
        if path.is_file():
            contents = path.read_bytes()
            assert FAKE_KEY.encode() not in contents and sentinel not in contents
    for spec in backend.launches:
        assert FAKE_KEY not in json.dumps(spec)
    source = (PROJECT / "scripts/lifecycle_manager.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    credential = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "credential_names")
    assert not any(isinstance(node, ast.Subscript) for node in ast.walk(credential))
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"items", "copy", "values", "get"} for node in ast.walk(credential))


def case_closed_permit_budget_and_egress_preserved(directory):
    manager, backend = setup(directory)
    for name in ("AGENTFORGE_REAL_CALLS_ENABLED", "AGENTFORGE_SINGLE_USE_PERMITS_ENABLED"):
        os.environ[name] = "true"
    os.environ["AGENTFORGE_REAL_DAILY_BUDGET_USD"] = "999"
    protected(manager)
    expected = {"AGENTFORGE_REAL_CALLS_ENABLED": "false", "AGENTFORGE_SINGLE_USE_PERMITS_ENABLED": "false",
        "AGENTFORGE_REAL_WORKER_MODE": "deny", "AGENTFORGE_REAL_DAILY_BUDGET_USD": "0",
        "AGENTFORGE_REAL_TEST_BUDGET_USD": "0", "AGENTFORGE_REAL_MAX_RETRIES": "0",
        "AGENTFORGE_MODEL_CREDENTIALS_ENV_ONLY": "true", "AGENTFORGE_EXTERNAL_MODELS_BLOCKED": "1",
        "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false"}
    assert lifecycle.SAFE_ENV == expected
    assert all(spec["policy"] == expected for spec in backend.launches)
    bootstrap = ast.parse((PROJECT / "scripts/managed_service.py").read_text(encoding="utf-8"))
    policy_loop = [node.lineno for node in ast.walk(bootstrap) if isinstance(node, ast.For)
        and isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Attribute)
        and isinstance(node.iter.func.value, ast.Name) and node.iter.func.value.id == "SAFE_ENV"]
    app_starts = [node.lineno for node in ast.walk(bootstrap) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr in {"run", "run_module", "execv", "execve"}]
    assert policy_loop and app_starts and min(policy_loop) < min(app_starts)
    assert (PROJECT / "backend/migrations/versions/0008_execution_permits.py").is_file()


def case_p3_p4_safety_files_unchanged(directory):
    paths = [PROJECT / item for item in (
        "backend/migrations/versions/0008_execution_permits.py", "backend/app/services/permit_authority.py",
        "backend/app/services/execution_permits.py", "backend/app/services/tool_gateway.py", "backend/app/services/skills.py")]
    paths.extend(path for path in (PROJECT / "backend/app").rglob("*.py") if "sandbox" in path.parts)
    assert len(paths) > 5 and all(path.is_file() for path in paths)
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    manager, backend = setup(directory)
    protected(manager)
    refused("PROTECTED_INSTANCE", manager.stop)
    manager.manual_stop(confirmation=approval)
    refused("PROTECTED_INSTANCE", lambda: manager.start(mode="mock", models_only=True))
    clean_manager, clean_backend = setup(directory / "mock-only")
    clean_manager.start(mode="mock", models_only=True)
    clean_manager.stop()
    after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert before == after


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    assert directory.is_relative_to((PROJECT / "work/lifecycle-tests").resolve())
    assert not any(name.startswith("AGENTFORGE_MODEL_") for name in os.environ)
    if args.scenario == "_contender":
        print(json.dumps(contender(directory), sort_keys=True))
        return
    if args.scenario == "_lock_contender":
        try:
            with lifecycle.operation_lock(directory):
                result = {"code": "LOCK_ACQUIRED"}
        except lifecycle.LifecycleError as error:
            result = {"code": error.code}
        print(json.dumps(result, sort_keys=True))
        return
    function = globals()["case_" + args.scenario]
    function(directory)
    print(json.dumps({"scenario": args.scenario, "passed": True, "real_services_started": 0,
        "database_calls": 0, "external_model_calls": 0}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        # No traceback, exception text, environment or response body is emitted.
        line = error.__traceback__
        while line and line.tb_next:
            line = line.tb_next
        print(json.dumps({"passed": False, "error_type": type(error).__name__, "line": line.tb_lineno if line else 0}))
        raise SystemExit(1) from None
