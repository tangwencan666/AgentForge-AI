"""Fixed local maintenance permissions; never overrides a protected instance.

CLI leases last through imports, execution and finally/atexit. Exported operations
also acquire the same guard, so importing a legacy module grants no write access.
This controls cooperating project scripts, not arbitrary code run by their owner.
"""
import atexit
import asyncio
from contextlib import contextmanager
import functools
import inspect
import os
from pathlib import Path
import sys
import time
import threading
from uuid import uuid4

from lifecycle_manager import LifecycleError, LifecycleManager

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_OPERATIONS = frozenset({
    "bootstrap.local", "bootstrap.sandbox", "bootstrap.sandbox.rotate", "bootstrap.p4",
    "preflight.prepare", "configure.coder", "state.inspect", "state.hold",
    "migrate.check", "migrate.current", "migrate.upgrade", "runner.pause", "runner.restore",
    "permit.verify", "permit.restoration", "database.verify", "database.owner",
    "model.observe", "dependency.freeze", "regression.run",
})
RETIRED_OPERATIONS = frozenset({
    "permit.prepare", "permit.backup", "permit.migrate", "permit.rehearsal",
    "database.rehearsal", "probe.mock",
})
APPROVAL_OPERATIONS = frozenset({
    "bootstrap.sandbox.rotate", "state.hold", "migrate.upgrade", "runner.pause", "runner.restore",
})
_CLI_LEASES = []
_ACTIVE_OPERATIONS = {}
_CONTEXT_OWNERS = {}


@contextmanager
def _logical_owner():
    """Do not treat unrelated asyncio tasks as thread-reentrant lock owners."""
    thread = (os.getpid(), threading.get_ident())
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    current = _CONTEXT_OWNERS.get(thread)
    # A synchronous CLI lease may enter asyncio.run in the same thread. Bind
    # its first nested async operation for that operation's lifetime; competing
    # tasks are then different owners and must fail rather than share authority.
    if current is not None and current[0] is not task and not (current[0] is None and task is not None):
        raise LifecycleError("LOCK_BUSY")
    depth = current[1] if current is not None else 0
    _CONTEXT_OWNERS[thread] = (task, depth + 1)
    try:
        yield
    finally:
        if current is not None:
            _CONTEXT_OWNERS[thread] = current
        else:
            _CONTEXT_OWNERS.pop(thread, None)


def _approve(operation, state):
    if not sys.stdin.isatty():
        raise LifecycleError("MAINTENANCE_APPROVAL_REQUIRED")
    challenge = "MAINTAIN " + str(uuid4())
    started = time.monotonic()
    print("Local maintenance: " + operation + "; generation=" + str(state["generation"]))
    answer = input("Type exactly " + challenge + " within 60 seconds: ")
    if answer != challenge or time.monotonic() - started > 60:
        raise LifecycleError("MAINTENANCE_APPROVAL_REQUIRED")


@contextmanager
def maintenance_operation(root, operation):
    if operation in RETIRED_OPERATIONS:
        raise LifecycleError("LEGACY_MAINTENANCE_RETIRED")
    if operation not in ALLOWED_OPERATIONS:
        raise LifecycleError("MAINTENANCE_OPERATION_FORBIDDEN")
    if Path(root).resolve() != PROJECT_ROOT:
        raise LifecycleError("MAINTENANCE_PROJECT_MISMATCH")
    manager = LifecycleManager(PROJECT_ROOT)
    # The manager refuses protected records before opening its state directory,
    # then repeats all identity/capacity checks under the actual OS lock.
    with _logical_owner(), manager.maintenance_session() as state:
        key = (os.getpid(), threading.get_ident(), operation)
        previous = _ACTIVE_OPERATIONS.get(key, 0)
        if operation in APPROVAL_OPERATIONS and not previous:
            _approve(operation, state)
            # Human input does not turn a changed/unknown identity into approval.
            refreshed = manager._load()
            manager._check(refreshed)
            if refreshed != state:
                raise LifecycleError("MAINTENANCE_STATE_CHANGED")
        manager._audit("maintenance:" + operation, list(state["entries"].values()))
        _ACTIVE_OPERATIONS[key] = previous + 1
        try:
            yield state
        finally:
            if previous:
                _ACTIVE_OPERATIONS[key] = previous
            else:
                _ACTIVE_OPERATIONS.pop(key, None)


def maintenance_action(operation):
    """Decorate sync or async exported functions; keep the lock across awaits."""
    def decorate(function):
        def selected(args, kwargs):
            return operation(args, kwargs) if callable(operation) else operation
        if inspect.iscoroutinefunction(function):
            @functools.wraps(function)
            async def asynchronous(*args, **kwargs):
                with maintenance_operation(PROJECT_ROOT, selected(args, kwargs)):
                    return await function(*args, **kwargs)
            return asynchronous
        @functools.wraps(function)
        def synchronous(*args, **kwargs):
            with maintenance_operation(PROJECT_ROOT, selected(args, kwargs)):
                return function(*args, **kwargs)
        return synchronous
    return decorate


def require_maintenance_context(operations):
    """Internal helpers cannot create authority by being called directly."""
    thread = (os.getpid(), threading.get_ident())
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    owner = _CONTEXT_OWNERS.get(thread)
    if owner is None or owner[0] is not task:
        raise LifecycleError("MAINTENANCE_CONTEXT_REQUIRED")
    active = frozenset(operation for operation in operations
        if _ACTIVE_OPERATIONS.get((*thread, operation), 0) > 0)
    if not active:
        raise LifecycleError("MAINTENANCE_CONTEXT_REQUIRED")
    return active


def authorize_maintenance_command(group, arguments):
    """Fixed Docker metadata/approved Runner commands, never a shell bridge."""
    scopes = {"permit": {"permit.verify", "permit.restoration"},
        "database": {"database.owner", "database.verify"},
        "runner": {"runner.pause", "runner.restore"}}
    if group not in scopes:
        raise LifecycleError("MAINTENANCE_COMMAND_FORBIDDEN")
    active = require_maintenance_context(scopes[group])
    container = "agentforge-p3-runner" if group == "runner" else "agentforge-p1-postgres"
    permitted = {("docker", "inspect", "--format", template, container) for template in (
        '{{index .Config.Labels "com.docker.compose.project"}}',
        '{{index .Config.Labels "com.docker.compose.project.working_dir"}}')}
    if group == "permit":
        permitted.add(("docker", "ps", "-aq", "--filter", "label=agentforge.sandbox.execution"))
    if group == "runner":
        permitted.update({("docker", "inspect", "--format", "{{.State.Running}}", name)
            for name in (container, "agentforge-permit-tests-runner")})
        permitted.add(("docker", "ps", "-aq", "--filter", "label=agentforge.sandbox.execution"))
        if "runner.pause" in active:
            permitted.add(("docker", "stop", container))
        if "runner.restore" in active:
            permitted.add(("docker", "start", container))
    else:
        permitted.add(("docker", "port", container, "5432/tcp"))
        if group == "database":
            permitted.add(("docker", "exec", container, "psql", "-U", "postgres", "-d", "agentforge",
                "-Atc", "SELECT current_database()"))
    if tuple(arguments) not in permitted:
        raise LifecycleError("MAINTENANCE_COMMAND_FORBIDDEN")


def _entry_operation(name, arguments):
    fixed = {
        "bootstrap_local.py": "bootstrap.local", "bootstrap-p4.py": "bootstrap.p4",
        "configure-deepseek-coder.py": "configure.coder", "prepare-permit-tests.py": "permit.prepare",
        "verify-permit-migration.py": "permit.rehearsal", "verify-permit-deployment.py": "permit.verify",
        "verify-permit-restoration.py": "permit.restoration", "p2-compose-probe.py": "probe.mock",
        "test-real-models.py": "model.observe", "freeze-lock.py": "dependency.freeze",
    }
    if name in fixed:
        return fixed[name]
    if name == "bootstrap-sandbox.py":
        return "bootstrap.sandbox.rotate" if "--replace-approved-image" in arguments else "bootstrap.sandbox"
    if name == "p5-live-state-check.py":
        return "state.hold" if "--stop" in arguments else "state.inspect"
    action = arguments[0] if arguments else ""
    if name == "migrate.py":
        return {"": "migrate.upgrade", "upgrade": "migrate.upgrade", "check": "migrate.check", "current": "migrate.current"}.get(action, "")
    if name == "deploy-permit-database.py":
        return {"backup": "permit.backup", "migrate": "permit.migrate", "verify": "permit.verify"}.get(action, "")
    if name == "p5-live-database-check.py":
        return {"backup": "database.rehearsal", "verify": "database.verify", "owner": "database.owner"}.get(action, "")
    if name == "permit-test-runner-isolation.py":
        return {"pause": "runner.pause", "restore": "runner.restore"}.get(action, "")
    return ""


def cli_gate(source, module_name):
    """No arbitrary command/root/force parameters. Never reads credential values."""
    if module_name != "__main__":
        return
    path = Path(source).resolve()
    if path.parent != PROJECT_ROOT / "scripts":
        raise SystemExit("MAINTENANCE_PROJECT_MISMATCH")
    lease = maintenance_operation(PROJECT_ROOT, _entry_operation(path.name, sys.argv[1:]))
    try:
        lease.__enter__()
    except LifecycleError as error:
        raise SystemExit(error.code) from None
    except Exception:
        raise SystemExit("MAINTENANCE_UNAVAILABLE") from None
    _CLI_LEASES.append(lease)
    atexit.register(lease.__exit__, None, None, None)
