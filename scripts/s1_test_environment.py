"""Create/clean only one new disposable S1 data stack, never main resources.

Explicit cached image IDs are required. There is no pull, build, Runner, volume
deletion, service restart or main dotenv access. Model credentials are absent.
"""
import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
import threading
from uuid import uuid4

from lifecycle_manager import operation_lock, _atomic_json
import lifecycle_manager
import s1_isolation as isolation

ROOT = Path(__file__).resolve().parents[1]
APPROVED_IMAGES = isolation.APPROVED_IMAGES
_ACTIVE = {}
_ISSUED = {}


def _owner():
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return (os.getpid(), threading.get_ident(), task)


@dataclass
class _Operation:
    action: str
    path: Path
    document: dict
    owner: tuple
    consumed: set = field(default_factory=set)


def _owns_resource_lock(path):
    key = os.path.normcase(str(isolation.checked_path(path.parent / "resource-lock")))
    with lifecycle_manager._LOCK_OWNERS_GUARD:
        lock = lifecycle_manager._LOCK_OWNERS.get(key)
        return bool(lock and lock.get("acquired") and lock.get("owner") == (os.getpid(), threading.get_ident()))


@contextmanager
def _resource_operation(action, path, document):
    """In-process capability, tied to a validated run and an actually held lock."""
    path = isolation.checked_path(path)
    isolation._require(action in {"create", "cleanup"} and _owns_resource_lock(path), "S1_OPERATION_CONTEXT_REQUIRED")
    isolation._require(not isolation.has_active_lease(path), "S1_RESOURCE_LEASE_ACTIVE")
    current, _ = isolation._read_document(ROOT, path, require_ready=False)
    isolation._require(current == document, "S1_MANIFEST_CHANGED")
    owner = _owner()
    isolation._require(owner not in _ACTIVE, "S1_OPERATION_CONTEXT_REQUIRED")
    operation = _Operation(action, path, document, owner)
    _ACTIVE[owner] = operation
    _ISSUED[id(operation)] = operation
    try:
        yield
    finally:
        if _ACTIVE.get(owner) is operation:
            del _ACTIVE[owner]
        _ISSUED.pop(id(operation), None)


def _create_arguments(document, role):
    isolation._require(role in {"postgres", "redis"}, "S1_COMMAND_FORBIDDEN")
    instance_id, ports = document["instance_id"], document["ports"]
    directory = ROOT / "work/maint-s1" / instance_id
    internal_port = 5432 if role == "postgres" else 6379
    arguments = ["container", "create", "--pull", "never", "--name", f"agentforge-s1-{instance_id}-{role}",
        "--network", "agentforge-s1-" + instance_id, "--restart", "no", "--security-opt", "no-new-privileges:true",
        "--memory", "512m", "--cpus", "1", "--pids-limit", "128", *_labels(ROOT, instance_id, role),
        "--health-interval", "1s", "--health-timeout", "3s", "--health-start-period", "2s", "--health-retries", "30",
        "--publish", f"127.0.0.1:{ports[role]}:{internal_port}"]
    if role == "postgres":
        arguments += ["--health-cmd", "pg_isready -h 127.0.0.1 -U postgres -d agentforge", "--env-file", str(directory / "postgres.env"),
            "--tmpfs", "/var/lib/postgresql/data:rw,nosuid,size=536870912", "--mount",
            f"type=bind,source={directory / 'init.sql'},target=/docker-entrypoint-initdb.d/10-s1.sql,readonly"]
    else:
        arguments += ["--health-cmd", "redis-cli ping", "--env-file", str(directory / "redis.env"),
            "--tmpfs", "/data:rw,nosuid,size=134217728", "--mount",
            f"type=bind,source={directory / 'redis.conf'},target=/usr/local/etc/redis/redis.conf,readonly"]
    arguments += [APPROVED_IMAGES[role]]
    if role == "redis":
        arguments += ["redis-server", "/usr/local/etc/redis/redis.conf"]
    return arguments


def _network_arguments(document):
    options = []
    for name, value in isolation.NETWORK_OPTIONS.items():
        options += ['--opt', name + '=' + value]
    return ['network', 'create', '--driver', 'bridge', *options,
        *_labels(ROOT, document['instance_id'], 'network'), 'agentforge-s1-' + document['instance_id']]


def _authorize_command(arguments):
    owner = _owner()
    operation = _ACTIVE.get(owner)
    isolation._require(type(operation) is _Operation and _ISSUED.get(id(operation)) is operation and operation.owner == owner and
        _owns_resource_lock(operation.path), "S1_OPERATION_CONTEXT_REQUIRED")
    isolation._require(not isolation.has_active_lease(operation.path), "S1_RESOURCE_LEASE_ACTIVE")
    document, _ = isolation._read_document(ROOT, operation.path, require_ready=False)
    isolation._require(document == operation.document, "S1_MANIFEST_CHANGED")
    isolation._require(isinstance(arguments, (list, tuple)) and all(isinstance(item, str) for item in arguments), "S1_COMMAND_FORBIDDEN")
    requested = tuple(arguments)
    allowed = {}
    if operation.action == "create" and document["status"] == "PREPARING":
        if document["network"] is None and not document["resources"]:
            allowed[tuple(_network_arguments(document))] = ("create", "network")
        if document["network"] is not None:
            for role in ("postgres", "redis"):
                if role not in document["resources"]:
                    allowed[tuple(_create_arguments(document, role))] = ("create", role)
                else:
                    allowed[("container", "start", document["resources"][role]["id"])] = ("start", role)
    if operation.action == "cleanup" and document["status"] == "CLEANING":
        for role, record in document["resources"].items():
            allowed[("container", "rm", "--force", record["id"])] = ("remove", role)
        if document["network"] is not None and not document["resources"]:
            allowed[("network", "rm", document["network"]["id"])] = ("remove", "network")
    isolation._require(requested in allowed, "S1_COMMAND_FORBIDDEN")
    isolation._require(requested not in operation.consumed, "S1_COMMAND_ALREADY_ATTEMPTED")
    action, role = allowed[requested]
    if document["network"] is not None:
        isolation.attest_network(ROOT, document)
    if action != "create" and role != "network":
        isolation.attest_container(ROOT, document, role, require_running=False)
    # An ambiguous Docker outcome does not authorize a repeated mutation.
    operation.consumed.add(requested)
    resource_id = (document["network"]["id"] if role == "network" and document["network"] else
        document["resources"].get(role, {}).get("id"))
    _audit(operation.path, action, role, resource_id)


def command(arguments):
    _authorize_command(arguments)
    try:
        result = subprocess.run(["docker", *arguments], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60,
            env=isolation.runtime_environment(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise ValueError
        return result.stdout.strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        raise isolation.IsolationError("S1_RESOURCE_COMMAND_FAILED") from None


def image_identity(image_id, role):
    isolation._require(image_id == APPROVED_IMAGES.get(role), "S1_CACHED_IMAGE_REQUIRED")
    row = isolation._docker_json(["image", "inspect", "--format", isolation.IMAGE_TEMPLATE, image_id])
    isolation._require(isinstance(row, dict) and row.get("id") == image_id and row.get("os") == "linux", "S1_CACHED_IMAGE_REQUIRED")
    # The reviewed PG data layout prevents an implicit anonymous volume escaping
    # the cleanup plan. PostgreSQL 18's changed layout is deliberately rejected.
    expected = {"/var/lib/postgresql/data": {}} if role == "postgres" else {"/data": {}}
    isolation._require(row.get("volumes") == expected and
        row.get("entrypoint") == ["docker-entrypoint.sh"], "S1_IMAGE_LAYOUT_UNSUPPORTED")
    return image_id


def _labels(root, instance_id, role):
    result = []
    for key, value in isolation.expected_labels(root, instance_id, role).items():
        result += ["--label", key + "=" + value]
    return result


def reserve_ports():
    sockets, ports = [], {}
    try:
        for role in ("postgres", "redis", "backend", "frontend", "runner"):
            for _ in range(50):
                item = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                item.bind(("127.0.0.1", 0))
                port = item.getsockname()[1]
                if port >= 30000 and port not in isolation.FORBIDDEN_PORTS:
                    sockets.append(item)
                    ports[role] = port
                    break
                item.close()
            else:
                raise isolation.IsolationError("S1_PORT_ALLOCATION_FAILED")
        return ports
    finally:
        # Docker must own the final binding. If an intervening listener wins,
        # create/start fails and only the recorded new resources are cleaned.
        for item in sockets:
            item.close()


def _write_exclusive(path, content):
    path = isolation.checked_path(path)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
        stream.flush()
        import os
        os.fsync(stream.fileno())


def _new_secret():
    return "s1-test-only-" + secrets.token_hex(24)


def prepare_files(directory, instance_id, ports):
    """Generate disposable service-only credentials; never read any main file."""
    database_password, redis_password, postgres_password = (_new_secret() for _ in range(3))
    values = dict(isolation.SAFE_ENV)
    values.update(AGENTFORGE_DATABASE_URL=f"postgresql+asyncpg://agentforge:{database_password}@127.0.0.1:{ports['postgres']}/agentforge",
        AGENTFORGE_REDIS_URL=f"redis://:{redis_password}@127.0.0.1:{ports['redis']}/0",
        AGENTFORGE_TENANT_ID=instance_id,
        AGENTFORGE_SANDBOX_RUNNER_URL=f"http://127.0.0.1:{ports['runner']}",
        BACKEND_PORT=str(ports["backend"]), FRONTEND_PORT=str(ports["frontend"]),
        AGENTFORGE_ALLOWED_MODEL_HOSTS="api.deepseek.com", AGENTFORGE_MODEL_CREDENTIAL_HOSTS="{}",
        AGENTFORGE_MODEL_PRICES="{}")
    for name in ("AGENTFORGE_ADMIN_TOKEN", "AGENTFORGE_SANDBOX_RUNNER_TOKEN",
                 "AGENTFORGE_SANDBOX_APPROVER_TOKEN", "AGENTFORGE_MCP_SERVER_TOKEN",
                 "AGENTFORGE_CAPABILITY_APPROVER_TOKEN"):
        values[name] = _new_secret()
    _write_exclusive(directory / ".env", "".join(name + "=" + json.dumps(value) + "\n" for name, value in sorted(values.items())))
    _write_exclusive(directory / "postgres.env", f"POSTGRES_USER=postgres\nPOSTGRES_DB=agentforge\nPOSTGRES_PASSWORD={postgres_password}\nAPP_DB_PASSWORD={database_password}\n")
    _write_exclusive(directory / "init.sql", "\\getenv app_password APP_DB_PASSWORD\n"
        "CREATE ROLE agentforge LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;\n"
        "ALTER DATABASE agentforge OWNER TO agentforge;\n\\connect agentforge\nALTER SCHEMA public OWNER TO agentforge;\n")
    _write_exclusive(directory / "redis.conf", "bind 0.0.0.0\nprotected-mode yes\nport 6379\nsave \"\"\nappendonly no\n"
        "requirepass " + redis_password + "\n")
    _write_exclusive(directory / "redis.env", "REDISCLI_AUTH=" + redis_password + "\n")
    for child in ("temp", "logs", "reports", "browser"):
        (directory / child).mkdir()


def _save(path, document):
    isolation.validate_manifest(ROOT, path, document, require_ready=False)
    _atomic_json(path, document)


def _audit(path, action, role, resource_id):
    """Append only nonsecret ownership metadata before a resource mutation."""
    event = {"time": datetime.now(timezone.utc).isoformat(), "action": action,
        "instance_id": path.parent.name, "role": role, "resource_id": resource_id}
    with isolation.checked_path(path.parent / "resource-audit.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _cleanup_locked(root, path, document):
    """Attest the complete scope before removing anything; never name-based rm."""
    if document["status"] == "CLEANED":
        return
    if document["network"] is not None:
        isolation.attest_network(root, document)
    for role in document["resources"]:
        isolation.attest_container(root, document, role, require_running=False)
    document["status"] = "CLEANING"
    _save(path, document)
    for role in ("redis", "postgres"):
        if role in document["resources"]:
            # Revalidate under the same OS lock immediately before mutation.
            isolation.attest_container(root, document, role, require_running=False)
            command(["container", "rm", "--force", document["resources"][role]["id"]])
            del document["resources"][role]
            _save(path, document)
    if document["network"] is not None:
        isolation.attest_network(root, document)
        command(["network", "rm", document["network"]["id"]])
        document["network"] = None
    document["status"] = "CLEANED"
    _save(path, document)


def cleanup(manifest_path):
    isolation._require(not isolation.has_active_lease(manifest_path), "S1_RESOURCE_LEASE_ACTIVE")
    document, safe = isolation._read_document(ROOT, manifest_path, require_ready=False)
    path = Path(safe["manifest_path"])
    with operation_lock(path.parent / "resource-lock"):
        document, _ = isolation._read_document(ROOT, path, require_ready=False)
        with _resource_operation("cleanup", path, document):
            _cleanup_locked(ROOT, path, document)
    return {"status": "CLEANED", "instance_id": document["instance_id"], "manifest_path": str(path)}


def create(postgres_image, redis_image):
    # Image validation is read-only and occurs before any resource is created.
    images = {"postgres": image_identity(postgres_image, "postgres"), "redis": image_identity(redis_image, "redis")}
    instance_id = str(uuid4())
    directory = isolation.checked_path(ROOT / "work/maint-s1" / instance_id)
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "isolation.json"
    with operation_lock(directory / "resource-lock"):
        ports = reserve_ports()
        document = {"version": isolation.VERSION, "instance_id": instance_id, "project_root": str(ROOT),
            "status": "PREPARING", "ports": ports, "resources": {}, "network": None,
            "database_name": "agentforge", "tenant_id": instance_id, "settings_path": str(directory / ".env"),
            "created_at": datetime.now(timezone.utc).isoformat()}
        _save(path, document)
        prepare_files(directory, instance_id, ports)
        scope = _resource_operation("create", path, document)
        scope.__enter__()
        try:
            network_name = "agentforge-s1-" + instance_id
            network_id = command(_network_arguments(document))
            isolation._require(bool(isolation._ID.fullmatch(network_id)), "S1_CREATE_RESULT_UNCERTAIN")
            document["network"] = {"id": network_id, "name": network_name}
            _save(path, document)
            isolation.attest_network(ROOT, document)
            for role in ("postgres", "redis"):
                name = f"agentforge-s1-{instance_id}-{role}"
                arguments = _create_arguments(document, role)
                container_id = command(arguments)
                isolation._require(bool(isolation._ID.fullmatch(container_id)), "S1_CREATE_RESULT_UNCERTAIN")
                document["resources"][role] = {"id": container_id, "name": name, "image_id": images[role]}
                _save(path, document)
                isolation.attest_container(ROOT, document, role, require_running=False)
                command(["container", "start", container_id])
            deadline = time.monotonic() + 45
            while True:
                try:
                    for role in ("postgres", "redis"):
                        isolation.attest_container(ROOT, document, role)
                    break
                except isolation.IsolationError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.25)
            document["status"] = "READY"
            _save(path, document)
            return isolation.validate_isolation(ROOT, path)
        except BaseException:
            document["status"] = "RECOVERY_REQUIRED"
            _save(path, document)
            # Unknown creation outcomes retain evidence; no broad or name-based
            # cleanup. Recorded identities alone can be explicitly cleaned later.
            raise
        finally:
            scope.__exit__(None, None, None)


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    sub = parser.add_subparsers(dest="action", required=True)
    make = sub.add_parser("create", allow_abbrev=False)
    make.add_argument("--postgres-image", required=True)
    make.add_argument("--redis-image", required=True)
    clean = sub.add_parser("cleanup", allow_abbrev=False)
    clean.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    result = create(args.postgres_image, args.redis_image) if args.action == "create" else cleanup(args.manifest)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except isolation.IsolationError as error:
        print(json.dumps({"status": "refused", "code": error.code}))
        raise SystemExit(2) from None
    except Exception:
        print(json.dumps({"status": "refused", "code": "S1_ENVIRONMENT_UNAVAILABLE"}))
        raise SystemExit(2) from None
