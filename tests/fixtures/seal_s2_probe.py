"""Offline S2 probe. Never loads real app configuration, credentials or services."""
import argparse
import builtins
import contextlib
import importlib.abc
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import time
import types

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "scripts"))
BUSINESS_MODULES = {"app", "dotenv", "alembic", "sqlalchemy", "redis", "psycopg", "asyncpg", "httpx", "docker"}
SYSTEM_NAMES = ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP",
    "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")


class BusinessBlocked(BaseException):
    pass


class ImportBarrier(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self):
        self.blocked = []

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in BUSINESS_MODULES:
            return importlib.util.spec_from_loader(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        return types.ModuleType(spec.name)

    def exec_module(self, module):
        # Pure import declarations are permitted. Nothing from the real app,
        # driver or Settings implementation is executed: business access is a
        # poison symbol that fails before configuration/DB/network can occur.
        barrier = self
        class Symbol:
            def __init__(self, name):
                self.name = name
            def __getattr__(self, name):
                return Symbol(self.name + "." + name)
            def __call__(self, *args, **kwargs):
                barrier.blocked.append(self.name)
                raise BusinessBlocked("BUSINESS_CALL_BEFORE_REFUSAL")
            def __iter__(self):
                barrier.blocked.append(self.name)
                raise BusinessBlocked("BUSINESS_DATA_BEFORE_REFUSAL")
        module.__path__ = []
        module.__getattr__ = lambda name: Symbol(module.__name__ + "." + name)


class FakeBackend:
    is_test = True
    ports = {"backend": 28108, "frontend": 25178}

    def __init__(self):
        self.rows = {}
        self.launches = []
        self.terminations = []

    def discover(self):
        return list(self.rows.values())

    def inspect(self, pid):
        return self.rows.get(pid)

    def launch(self, spec):
        self.launches.append(spec)
        row = {"pid": 400000000 + len(self.launches), "created": time.time_ns(),
            "executable": str(Path(spec["root"]) / "offline-python.exe"),
            "instance_id": spec["instance_id"], "role": spec["role"], "command_line": "offline-only"}
        self.rows[row["pid"]] = row
        return row

    def terminate(self, identity):
        self.terminations.append(identity["instance_id"])
        self.rows.pop(identity["pid"], None)

    def healthy(self, identity, spec):
        return identity["pid"] in self.rows


def isolated_root(directory):
    root = directory / "guard-project"
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "work/p5-live-preflight").mkdir(parents=True, exist_ok=True)
    (root / "work/p5-live-preflight/.env").touch()
    (root / ".env").touch()
    return root


def load_policy(root):
    barrier = ImportBarrier()
    sys.meta_path.insert(0, barrier)
    # Importing dotenv is pure. Its parser/writer calls are the actual guarded
    # boundary; an explicit library stub rejects those without reading files.
    dotenv = types.ModuleType("dotenv")
    def forbidden_dotenv(*args, **kwargs):
        barrier.blocked.append("dotenv-operation")
        raise BusinessBlocked("DOTENV_OPERATION_BEFORE_REFUSAL")
    dotenv.dotenv_values = dotenv.set_key = dotenv.load_dotenv = forbidden_dotenv
    sys.modules["dotenv"] = dotenv
    import lifecycle_manager
    import maintenance_policy
    backend = FakeBackend()
    manager = lifecycle_manager.LifecycleManager(root, backend=backend)
    factory_calls = []
    def factory(selected_root):
        assert Path(selected_root).resolve() == root.resolve()
        factory_calls.append(str(root))
        return manager
    maintenance_policy.PROJECT_ROOT = root
    maintenance_policy.LifecycleManager = factory
    return maintenance_policy, lifecycle_manager, manager, backend, factory_calls, barrier


def protected(manager):
    assert not any(name.startswith("AGENTFORGE_MODEL_") for name in os.environ)
    os.environ["AGENTFORGE_MODEL_CODER_KEY"] = "explicit-fake-seal-s2-key-no-external-access"
    try:
        manager.start(mode="coder", models_only=True)
    finally:
        del os.environ["AGENTFORGE_MODEL_CODER_KEY"]


def snapshot(root):
    paths = [root / ".env", root / "work/p5-live-preflight/.env", root / "work/lifecycle/manifest.json"]
    return {str(path): path.read_bytes() if path.is_file() else None for path in paths}


def deny_side_effects(root):
    allowed_lock = os.path.normcase(str(root / "work/lifecycle/operation.lock"))
    blocked = []
    state = {"active": True}
    def audit(event, args):
        if not state["active"]:
            return
        if event in {"subprocess.Popen", "os.system", "socket.connect", "socket.bind", "sqlite3.connect",
                "os.remove", "os.rename", "os.rmdir", "shutil.rmtree"}:
            blocked.append(event)
            raise BusinessBlocked("SIDE_EFFECT_BEFORE_REFUSAL")
        if event == "os.mkdir":
            target = os.path.normcase(str(Path(args[0]).absolute()))
            # Lifecycle lock directory mkdir(exist_ok=True) is coordination only.
            if target != os.path.normcase(str(root / "work/lifecycle")):
                blocked.append(event)
                raise BusinessBlocked("BUSINESS_DIRECTORY_BEFORE_REFUSAL")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0]))
            target = os.path.normcase(str(path.absolute()))
            flags = args[2] or 0
            if path.name == ".env" or path.name.startswith(".env."):
                blocked.append("dotenv-file")
                raise BusinessBlocked("SETTINGS_READ_BEFORE_REFUSAL")
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND) and target != allowed_lock:
                blocked.append("file-write")
                raise BusinessBlocked("BUSINESS_FILE_WRITE_BEFORE_REFUSAL")
    sys.addaudithook(audit)
    return blocked, state


def expected_refusal(lifecycle, operation, accepted=None):
    try:
        result = operation()
        if inspect.iscoroutine(result):
            try:
                result.send(None)
            finally:
                result.close()
    except lifecycle.LifecycleError as error:
        if accepted is not None:
            assert error.code in accepted
        return error.code
    raise AssertionError("EXPECTED_MAINTENANCE_REFUSAL")


def entry_probe(directory, payload, direct):
    root = isolated_root(directory)
    policy, lifecycle, manager, backend, factory_calls, barrier = load_policy(root)
    protected(manager)
    for original_script in (PROJECT / "scripts").glob("*.py"):
        (root / "scripts" / original_script.name).write_bytes(original_script.read_bytes())
    script = root / "scripts" / payload["script"]
    before = snapshot(root)
    trace = []
    original = policy.maintenance_operation
    @contextlib.contextmanager
    def tracked(selected_root, operation):
        assert Path(selected_root).resolve() == root.resolve()
        trace.append(operation)
        with original(selected_root, operation) as scope:
            yield scope
    policy.maintenance_operation = tracked
    args = payload.get("arguments", [])
    sys.argv = [str(script)] + (args if not direct else [])
    if script.name == "bootstrap-sandbox.py" and direct:
        sys.argv += ["--image-id", "sha256:" + "a" * 64]
    if script.name == "migrate.py" and direct:
        sys.argv += ["upgrade"]
    deny, audit_state = deny_side_effects(root)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if direct:
                namespace = runpy.run_path(str(script), run_name="seal_s2_imported_entry")
                function = namespace[payload["function"]]
                arguments = [root if value == "__FIXTURE_ROOT__" else value for value in payload["arguments"]]
                codes = {"MAINTENANCE_CONTEXT_REQUIRED"} if payload.get("expect_existing_context_required") else None
                expected_refusal(lifecycle, lambda: function(*arguments, **payload["keywords"]), codes)
            else:
                try:
                    runpy.run_path(str(script), run_name="__main__")
                except lifecycle.LifecycleError:
                    pass
                except SystemExit as exit_status:
                    assert exit_status.code not in (None, 0)
                else:
                    raise AssertionError("CLI_DID_NOT_REFUSE")
    finally:
        audit_state["active"] = False
    if payload.get("expect_existing_context_required"):
        assert not trace, "HELPER_MUST_NOT_CREATE_NEW_AUTHORITY"
        assert not factory_calls
    else:
        assert trace, "MISSING_SHARED_MAINTENANCE_BOUNDARY"
    if "expected_operation" in payload:
        assert trace[0] == payload["expected_operation"]
    assert not deny and not barrier.blocked
    assert snapshot(root) == before
    assert len(backend.launches) == 2 and not backend.terminations


def helper_scope_probe(directory, payload):
    root = isolated_root(directory)
    policy, lifecycle, manager, backend, calls, barrier = load_policy(root)
    for source in (PROJECT / "scripts").glob("*.py"):
        (root / "scripts" / source.name).write_bytes(source.read_bytes())
    source = root / "scripts" / payload["script"]
    sys.argv = [str(source)]
    namespace = runpy.run_path(str(source), run_name="seal_s2_helper_scope")
    if payload["operation"] in {"runner.pause", "runner.restore"}:
        fake_terminal()
        builtins.input = challenge_from_prompt
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        with policy.maintenance_operation(root, payload["operation"]):
            deny, audit_state = deny_side_effects(root)
            original_run = subprocess.run
            observed = []
            def explicit_subprocess_stub(arguments, **keywords):
                assert list(arguments) == payload["arguments"]
                assert Path(keywords["cwd"]).resolve() == root
                observed.append(list(arguments))
                return types.SimpleNamespace(returncode=0, stdout="explicit-offline-docker-reply\n")
            try:
                if payload.get("explicit_stub_allowed"):
                    subprocess.run = explicit_subprocess_stub
                    result = namespace["command"](*payload["arguments"], **payload["keywords"])
                    assert result == "explicit-offline-docker-reply"
                    assert observed == [payload["arguments"]]
                else:
                    expected_refusal(lifecycle,
                        lambda: namespace["command"](*payload["arguments"], **payload["keywords"]),
                        {"MAINTENANCE_CONTEXT_REQUIRED", "MAINTENANCE_COMMAND_FORBIDDEN"})
            finally:
                subprocess.run = original_run
                audit_state["active"] = False
    assert not deny and not barrier.blocked
    assert not backend.launches and not backend.terminations


def contender(directory, root):
    policy, lifecycle, manager, backend, calls, barrier = load_policy(root)
    try:
        with policy.maintenance_operation(root, "bootstrap.local"):
            code = "LOCK_ACQUIRED"
    except lifecycle.LifecycleError as error:
        code = error.code
    return {"code": code}


def child_contender(directory, root):
    environment = {name: os.environ[name] for name in SYSTEM_NAMES if name in os.environ}
    command = [sys.executable, "-B", "-I", str(Path(__file__).resolve()), "--mode", "contender",
        "--directory", str(directory), "--payload", json.dumps({"root": str(root)})]
    result = subprocess.run(command, env=environment, cwd=PROJECT, capture_output=True, text=True,
        timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0
    return json.loads(result.stdout)["code"]


def fake_terminal():
    class Terminal(io.StringIO):
        def isatty(self):
            return True
    sys.stdin = Terminal()


def challenge_from_prompt(prompt):
    match = re.search(r"MAINTAIN [0-9a-f-]{36}", prompt)
    assert match
    return match.group()


def scenario_probe(directory, scenario):
    root = isolated_root(directory)
    policy, lifecycle, manager, backend, calls, barrier = load_policy(root)
    if scenario == "clean_allowed":
        with policy.maintenance_operation(root, "bootstrap.local"):
            (root / "offline-marker.json").write_text('{"fixture_only":true}', encoding="utf-8")
        assert calls and not backend.launches and not backend.terminations
    elif scenario == "unknown_record":
        manager.start(mode="mock", models_only=True)
        record = manager._load()
        record["entries"]["worker"]["status"] = "unknown"
        manager._save(record)
        before = snapshot(root)
        expected_refusal(lifecycle, lambda: enter_operation(policy, root, "bootstrap.local"), {"START_UNCERTAIN"})
        assert snapshot(root) == before and not backend.terminations
    elif scenario == "concurrent_lock":
        with policy.maintenance_operation(root, "bootstrap.local"):
            assert child_contender(directory, root) == "LOCK_BUSY"
        assert child_contender(directory, root) == "LOCK_ACQUIRED"
    elif scenario == "finally_cannot_restore":
        protected(manager)
        before = snapshot(root)
        try:
            expected_refusal(lifecycle, lambda: enter_operation(policy, root, "state.inspect"), {"PROTECTED_INSTANCE"})
            raise RuntimeError("CONTROLLED_OFFLINE_FAILURE")
        except RuntimeError:
            pass
        finally:
            for operation in ("runner.restore", "state.hold", "migrate.upgrade", "bootstrap.local"):
                expected_refusal(lifecycle, lambda: enter_operation(policy, root, operation), {"PROTECTED_INSTANCE"})
        assert snapshot(root) == before and not backend.terminations
    elif scenario == "async_action_holds_lock":
        class PauseOnce:
            def __await__(self):
                yield None
        @policy.maintenance_action("bootstrap.local")
        async def body():
            await PauseOnce()
            return "FIXTURE_COMPLETE"
        coroutine = body()
        assert inspect.iscoroutine(coroutine)
        try:
            coroutine.send(None)
            assert child_contender(directory, root) == "LOCK_BUSY"
            try:
                coroutine.send(None)
            except StopIteration as result:
                assert result.value == "FIXTURE_COMPLETE"
            else:
                raise AssertionError("ASYNC_FIXTURE_DID_NOT_FINISH")
        finally:
            coroutine.close()
        assert child_contender(directory, root) == "LOCK_ACQUIRED"
    elif scenario == "unknown_operation":
        expected_refusal(lifecycle, lambda: enter_operation(policy, root, "shell.exec"))
        assert not calls
    elif scenario == "risky_requires_confirmation":
        sys.stdin = io.StringIO()
        for operation in ("state.hold", "runner.pause", "runner.restore", "migrate.upgrade"):
            expected_refusal(lifecycle, lambda: enter_operation(policy, root, operation), {"MAINTENANCE_APPROVAL_REQUIRED"})
        assert not backend.launches and not backend.terminations
    elif scenario == "root_mismatch":
        # Merely pass a foreign path; the factory must never reach it.
        expected_refusal(lifecycle, lambda: enter_operation(policy, root / "foreign", "bootstrap.local"), {"MAINTENANCE_PROJECT_MISMATCH"})
        assert not calls
    elif scenario == "credential_environment_refused":
        os.environ["AGENTFORGE_MODEL_CODER_KEY"] = "explicit-fake-seal-s2-key-no-external-access"
        expected_refusal(lifecycle, lambda: enter_operation(policy, root, "bootstrap.local"), {"MODEL_CREDENTIALS_FORBIDDEN"})
    elif scenario == "risky_confirmation_is_one_use":
        fake_terminal()
        challenges = []
        def confirm(prompt):
            challenges.append(challenge_from_prompt(prompt))
            return challenges[0]
        builtins.input = confirm
        assert enter_operation(policy, root, "runner.pause") == "ENTERED"
        expected_refusal(lifecycle, lambda: enter_operation(policy, root, "runner.restore"), {"MAINTENANCE_APPROVAL_REQUIRED"})
        assert len(challenges) == 2 and challenges[0] != challenges[1]
    elif scenario == "confirmation_revalidates_state":
        fake_terminal()
        def changed(prompt):
            state = manager._load()
            manager._save(state)  # Controlled mutation of this fake manifest only.
            return challenge_from_prompt(prompt)
        builtins.input = changed
        expected_refusal(lifecycle, lambda: enter_operation(policy, root, "runner.restore"), {"MAINTENANCE_STATE_CHANGED"})
    elif scenario == "confirmation_expires":
        fake_terminal()
        builtins.input = challenge_from_prompt
        ticks = iter((0, 61))
        original = policy.time.monotonic
        policy.time.monotonic = lambda: next(ticks)
        try:
            expected_refusal(lifecycle, lambda: enter_operation(policy, root, "runner.restore"), {"MAINTENANCE_APPROVAL_REQUIRED"})
        finally:
            policy.time.monotonic = original
    elif scenario == "body_error_releases_lock":
        try:
            with policy.maintenance_operation(root, "bootstrap.local"):
                raise RuntimeError("CONTROLLED_OFFLINE_BODY_FAILURE")
        except RuntimeError as error:
            assert str(error) == "CONTROLLED_OFFLINE_BODY_FAILURE"
        else:
            raise AssertionError("BODY_FAILURE_WAS_MASKED")
        assert child_contender(directory, root) == "LOCK_ACQUIRED"
    elif scenario == "cli_lease_lasts_until_exit":
        environment = {name: os.environ[name] for name in SYSTEM_NAMES if name in os.environ}
        command = [sys.executable, "-B", "-I", str(Path(__file__).resolve()), "--mode", "lease-owner",
            "--directory", str(directory), "--payload", json.dumps({"root": str(root)})]
        result = subprocess.run(command, env=environment, cwd=PROJECT, capture_output=True, text=True,
            timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == 0 and json.loads(result.stdout) == {"code": "CLI_LEASE_HELD"}
        assert child_contender(directory, root) == "LOCK_ACQUIRED"
    elif scenario == "different_async_tasks_cannot_reenter":
        import asyncio
        async def exercise():
            entered, release = asyncio.Event(), asyncio.Event()
            nested = []
            @policy.maintenance_action("bootstrap.local")
            async def first():
                entered.set()
                await release.wait()
                with policy.maintenance_operation(root, "dependency.freeze"):
                    nested.append("same-task-allowed")
            @policy.maintenance_action("dependency.freeze")
            async def second():
                raise AssertionError("DIFFERENT_TASK_ENTERED_HELD_MAINTENANCE_SCOPE")
            owner = asyncio.create_task(first())
            await entered.wait()
            try:
                try:
                    await second()
                except lifecycle.LifecycleError as error:
                    assert error.code == "LOCK_BUSY"
                else:
                    raise AssertionError("DIFFERENT_ASYNC_TASK_REENTERED")
            finally:
                release.set()
                await owner
            assert nested == ["same-task-allowed"]
            with policy.maintenance_operation(root, "bootstrap.local"):
                pass
        asyncio.run(exercise())
    elif scenario == "synchronous_cli_hands_off_to_async_without_reapproval":
        import asyncio
        fake_terminal()
        approvals = []
        def confirm(prompt):
            approvals.append(challenge_from_prompt(prompt))
            return approvals[-1]
        builtins.input = confirm
        completed = []
        @policy.maintenance_action("runner.pause")
        async def asynchronous_entry():
            with policy.maintenance_operation(root, "runner.pause"):
                completed.append("async-body")
        with policy.maintenance_operation(root, "runner.pause"):
            assert len(approvals) == 1
            asyncio.run(asynchronous_entry())
            with policy.maintenance_operation(root, "runner.pause"):
                completed.append("restored-sync-owner")
        assert completed == ["async-body", "restored-sync-owner"] and len(approvals) == 1
    elif scenario == "synchronous_cli_handoff_still_excludes_other_tasks":
        import asyncio
        async def exercise():
            entered, release = asyncio.Event(), asyncio.Event()
            @policy.maintenance_action("bootstrap.local")
            async def owner():
                entered.set()
                await release.wait()
            first = asyncio.create_task(owner())
            await entered.wait()
            try:
                expected_refusal(lifecycle,
                    lambda: enter_operation(policy, root, "bootstrap.local"), {"LOCK_BUSY"})
            finally:
                release.set()
                await first
        with policy.maintenance_operation(root, "bootstrap.local"):
            asyncio.run(exercise())
            with policy.maintenance_operation(root, "bootstrap.local"):
                pass
    else:
        raise AssertionError("UNKNOWN_OFFLINE_SCENARIO")
    assert not barrier.blocked


def enter_operation(policy, root, operation):
    with policy.maintenance_operation(root, operation):
        return "ENTERED"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("entry", "direct", "operation", "scenario", "contender", "lease-owner", "helper-scope"))
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--payload", required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    assert directory.is_relative_to((PROJECT / "work/seal-fixes").resolve())
    assert not any(name.startswith("AGENTFORGE_MODEL_") for name in os.environ)
    payload = json.loads(args.payload)
    if args.mode == "contender":
        root = Path(payload["root"]).resolve()
        assert root.is_relative_to(directory)
        print(json.dumps(contender(directory, root), sort_keys=True))
        return
    if args.mode == "lease-owner":
        root = Path(payload["root"]).resolve()
        assert root.is_relative_to(directory)
        policy, lifecycle, manager, backend, calls, barrier = load_policy(root)
        source = root / "scripts/bootstrap_local.py"
        source.write_text("# Trusted offline CLI lease owner only\n", encoding="utf-8")
        sys.argv = [str(source)]
        policy.cli_gate(source, "__main__")
        assert child_contender(directory, root) == "LOCK_BUSY"
        print(json.dumps({"code": "CLI_LEASE_HELD"}))
        return
    if args.mode in {"entry", "direct"}:
        entry_probe(directory, payload, args.mode == "direct")
    elif args.mode == "helper-scope":
        helper_scope_probe(directory, payload)
    elif args.mode == "operation":
        root = isolated_root(directory)
        policy, lifecycle, manager, backend, calls, barrier = load_policy(root)
        protected(manager)
        before = snapshot(root)
        retired = {"permit.prepare", "permit.backup", "permit.migrate", "permit.rehearsal", "database.rehearsal", "probe.mock"}
        code = "LEGACY_MAINTENANCE_RETIRED" if payload["operation"] in retired else "PROTECTED_INSTANCE"
        expected_refusal(lifecycle, lambda: enter_operation(policy, root, payload["operation"]), {code})
        assert snapshot(root) == before and not backend.terminations and not barrier.blocked
    else:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            scenario_probe(directory, payload["scenario"])
    print(json.dumps({"passed": True, "real_services_started": 0, "database_calls": 0,
        "external_model_calls": 0}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        line = error.__traceback__
        while line and line.tb_next:
            line = line.tb_next
        print(json.dumps({"passed": False, "error_type": type(error).__name__, "line": line.tb_lineno if line else 0}))
        raise SystemExit(1) from None
