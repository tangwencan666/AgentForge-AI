"""Attest one disposable S1 PostgreSQL/Redis instance before business access.

The manifest is a locator, never authority by itself. Docker identity, labels,
published loopback ports and mounts are checked before test settings are read.
No model credential or issuer token is read, inherited or returned.
"""
from contextlib import contextmanager
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from urllib.parse import urlsplit
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERSION = 1
APPROVED_IMAGES = {
    "postgres": "sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685",
    "redis": "sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf",
}
LABEL = "ai.agentforge.maint-s1"
FORBIDDEN_PORTS = frozenset({5432, 6379, 8000, 5173, 15432, 16379, 18100, 15173,
    18120, 18121, 25432, 26379, 28100, 25173, 28120, 28121})
OS_NAMES = ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP",
    "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
SAFE_ENV = {
    "AGENTFORGE_ENVIRONMENT": "test", "AGENTFORGE_REAL_CALLS_ENABLED": "false",
    "AGENTFORGE_SINGLE_USE_PERMITS_ENABLED": "false", "AGENTFORGE_REAL_WORKER_MODE": "deny",
    "AGENTFORGE_REAL_DAILY_BUDGET_USD": "0", "AGENTFORGE_REAL_TEST_BUDGET_USD": "0",
    "AGENTFORGE_REAL_MAX_RETRIES": "0", "AGENTFORGE_MODEL_CREDENTIALS_ENV_ONLY": "true",
    "AGENTFORGE_EXTERNAL_MODELS_BLOCKED": "1", "LANGCHAIN_TRACING_V2": "false",
    "LANGSMITH_TRACING": "false", "PYTHONDONTWRITEBYTECODE": "1",
}
SETTINGS_NAMES = frozenset(SAFE_ENV) | frozenset({
    "AGENTFORGE_DATABASE_URL", "AGENTFORGE_REDIS_URL", "AGENTFORGE_ADMIN_TOKEN",
    "AGENTFORGE_TENANT_ID", "AGENTFORGE_SANDBOX_RUNNER_URL", "AGENTFORGE_SANDBOX_RUNNER_TOKEN",
    "AGENTFORGE_SANDBOX_APPROVER_TOKEN", "AGENTFORGE_MCP_SERVER_TOKEN",
    "AGENTFORGE_CAPABILITY_APPROVER_TOKEN", "BACKEND_PORT", "FRONTEND_PORT",
    "AGENTFORGE_ALLOWED_MODEL_HOSTS", "AGENTFORGE_MODEL_CREDENTIAL_HOSTS", "AGENTFORGE_MODEL_PRICES",
})
_ID = re.compile(r"[a-f0-9]{64}\Z")
_IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")
_LEASES = {}
_LEASES_LOCK = threading.Lock()
NETWORK_OPTIONS = {'com.docker.network.bridge.enable_icc': 'false',
    'com.docker.network.bridge.enable_ip_masquerade': 'false',
    'com.docker.network.bridge.host_binding_ipv4': '127.0.0.1',
    'com.docker.network.enable_ipv4': 'true', 'com.docker.network.enable_ipv6': 'false'}
NETWORK_TEMPLATE = ('{"id":{{json .Id}},"name":{{json .Name}},"labels":{{json .Labels}},'
    '"internal":{{json .Internal}},"driver":{{json .Driver}},"options":{{json .Options}}}')
IMAGE_TEMPLATE = '{"id":{{json .Id}},"os":{{json .Os}},"entrypoint":{{json .Config.Entrypoint}},"volumes":{{json .Config.Volumes}}}'
CONTAINER_TEMPLATE = ('{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},'
    '"labels":{{json .Config.Labels}},"ports":{{json .HostConfig.PortBindings}},'
    '"mounts":{{json .Mounts}},"tmpfs":{{json .HostConfig.Tmpfs}},"network":{{json .HostConfig.NetworkMode}},'
    '"networks":{{json .NetworkSettings.Networks}},'
    '"published_ports":{{json .NetworkSettings.Ports}},'
    '"privileged":{{json .HostConfig.Privileged}},"restart":{{json .HostConfig.RestartPolicy.Name}},'
    '"running":{{json .State.Running}},"state":{{json .State.Status}},'
    '"health":{{with (index .State "Health")}}{{json .Status}}{{else}}null{{end}}}')


class IsolationError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def checked_path(path):
    candidate = Path(os.path.abspath(path))
    for component in (*reversed(candidate.parents), candidate):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if component.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise IsolationError("S1_REPARSE_PATH_REFUSED")
    return candidate


def runtime_environment():
    return {name: os.environ[name] for name in OS_NAMES if name in os.environ}


def expected_labels(root, instance_id, role):
    return {LABEL: "1", LABEL + ".root": str(checked_path(root)),
        LABEL + ".instance": instance_id, LABEL + ".role": role}


def _host_source_matches(source, expected):
    """Docker Desktop may expose its exact host-path mapping in inspect."""
    expected = str(checked_path(expected))
    candidates = {expected.replace("\\", "/").lower()}
    normalized = expected.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", normalized):
        suffix = normalized[0].lower() + normalized[2:]
        candidates.update({"/run/desktop/mnt/host/" + suffix.lower(), "/host_mnt/" + suffix.lower()})
    return isinstance(source, str) and source.replace("\\", "/").lower() in candidates


def _require(condition, code="S1_MANIFEST_INVALID"):
    if not condition:
        raise IsolationError(code)


def validate_manifest(root, manifest_path, document, *, require_ready=True):
    """Pure schema/path checks. This does NOT attest or authorize resource access."""
    root, target = checked_path(root), checked_path(manifest_path)
    _require(target.name == "isolation.json" and target.parent.parent == root / "work/maint-s1")
    try:
        instance_id = str(UUID(target.parent.name))
    except (ValueError, TypeError):
        raise IsolationError("S1_MANIFEST_INVALID") from None
    _require(instance_id == target.parent.name)
    _require(isinstance(document, dict) and set(document) == {
        "version", "instance_id", "project_root", "status", "ports", "resources", "network",
        "database_name", "tenant_id", "settings_path", "created_at"})
    _require(document["version"] == VERSION and document["instance_id"] == instance_id)
    _require(document["project_root"] == str(root) and document["database_name"] == "agentforge")
    _require(document["tenant_id"] == instance_id)
    _require(document["settings_path"] == str(target.parent / ".env"))
    _require(isinstance(document["created_at"], str) and len(document["created_at"]) < 64)
    _require(document["status"] in {"PREPARING", "READY", "CLEANING", "CLEANED", "RECOVERY_REQUIRED"})
    if require_ready:
        _require(document["status"] == "READY", "S1_NOT_READY")
    ports = document["ports"]
    _require(isinstance(ports, dict) and set(ports) == {"postgres", "redis", "backend", "frontend", "runner"})
    _require(all(type(p) is int and 30000 <= p <= 65535 and p not in FORBIDDEN_PORTS for p in ports.values()), "S1_PORT_REFUSED")
    _require(len(set(ports.values())) == len(ports), "S1_PORT_REFUSED")
    resources = document["resources"]
    _require(isinstance(resources, dict) and set(resources) <= {"postgres", "redis"})
    if require_ready:
        _require(set(resources) == {"postgres", "redis"})
    for role, value in resources.items():
        _require(isinstance(value, dict) and set(value) == {"id", "name", "image_id"})
        _require(isinstance(value["id"], str) and bool(_ID.fullmatch(value["id"])))
        _require(value["name"] == f"agentforge-s1-{instance_id}-{role}")
        _require(value["image_id"] == APPROVED_IMAGES[role], "S1_CACHED_IMAGE_REQUIRED")
    network = document["network"]
    _require(network is None or isinstance(network, dict) and set(network) == {"id", "name"})
    if network is not None:
        _require(isinstance(network["id"], str) and bool(_ID.fullmatch(network["id"])))
        _require(network["name"] == f"agentforge-s1-{instance_id}")
    if require_ready:
        _require(network is not None)
    return {"version": VERSION, "instance_id": instance_id, "run_directory": str(target.parent),
        "manifest_path": str(target), "settings_path": document["settings_path"],
        "ports": dict(ports), "database_name": "agentforge", "tenant_id": instance_id,
        "resources": resources, "status": document["status"], "real_calls_enabled": False}


def _docker_json(arguments):
    # An imported read-only helper must not become an unrestricted Docker bridge.
    templates = {"network": NETWORK_TEMPLATE, "container": CONTAINER_TEMPLATE, "image": IMAGE_TEMPLATE}
    _require(isinstance(arguments, (list, tuple)) and len(arguments) == 5 and
        arguments[0] in templates and tuple(arguments[1:3]) == ("inspect", "--format") and
        arguments[3] == templates[arguments[0]] and isinstance(arguments[4], str), "S1_READONLY_COMMAND_REFUSED")
    _require(arguments[4] in APPROVED_IMAGES.values() if arguments[0] == "image" else bool(_ID.fullmatch(arguments[4])),
        "S1_READONLY_COMMAND_REFUSED")
    try:
        result = subprocess.run(["docker", *arguments], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20,
            env=runtime_environment(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode or not result.stdout.strip():
            raise ValueError
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise IsolationError("S1_DOCKER_ATTESTATION_FAILED") from None


def attest_network(root, document):
    record = document["network"]
    _require(record is not None)
    observed = _docker_json(["network", "inspect", "--format", NETWORK_TEMPLATE, record["id"]])
    _require(observed == {"id": record["id"], "name": record["name"],
        "labels": expected_labels(root, document["instance_id"], "network"), "internal": False,
        'driver': 'bridge', 'options': NETWORK_OPTIONS},
        "S1_NETWORK_IDENTITY_MISMATCH")


def attest_container(root, document, role, *, require_running=True):
    record = document["resources"][role]
    observed = _docker_json(["container", "inspect", "--format", CONTAINER_TEMPLATE, record["id"]])
    _require(isinstance(observed, dict) and set(observed) == {"id", "name", "image", "labels", "ports",
        "mounts", "tmpfs", "network", "networks", "published_ports", "privileged", "restart", "running", "state", "health"}, "S1_CONTAINER_IDENTITY_MISMATCH")
    for field, expected in {"id": record["id"], "name": "/" + record["name"], "image": record["image_id"],
            "labels": expected_labels(root, document["instance_id"], role),
            "network": document["network"]["name"], "privileged": False, "restart": "no"}.items():
        _require(observed[field] == expected, "S1_CONTAINER_IDENTITY_MISMATCH")
    networks = observed["networks"]
    _require(isinstance(networks, dict) and set(networks) == {document["network"]["name"]}, "S1_NETWORK_ATTACHMENT_MISMATCH")
    attachment = networks[document["network"]["name"]]
    _require(isinstance(attachment, dict), "S1_NETWORK_ATTACHMENT_MISMATCH")
    prestart = not require_running and observed["running"] is False and observed["state"] == "created"
    _require(attachment.get("NetworkID") == document["network"]["id"] or
        prestart and attachment.get("NetworkID") == "", "S1_NETWORK_ATTACHMENT_MISMATCH")
    port = "5432/tcp" if role == "postgres" else "6379/tcp"
    _require(observed["ports"] == {port: [{"HostIp": "127.0.0.1", "HostPort": str(document["ports"][role])}]}, "S1_PORT_BINDING_MISMATCH")
    actual_ports = observed['published_ports']
    if observed['running'] is True:
        _require(actual_ports == observed['ports'], 'S1_PORT_NOT_PUBLISHED')
    else:
        _require(actual_ports in ({}, {port: None}, {port: []}, observed['ports']), 'S1_PORT_BINDING_MISMATCH')
    if require_running:
        _require(observed["running"] is True and observed["health"] == "healthy", "S1_RESOURCE_NOT_RUNNING")
    directory = checked_path(root) / "work/maint-s1" / document["instance_id"]
    expected_mounts = ({("bind", str(directory / "init.sql"), "/docker-entrypoint-initdb.d/10-s1.sql", False),
        ("tmpfs", "", "/var/lib/postgresql/data", True)} if role == "postgres" else
        {("bind", str(directory / "redis.conf"), "/usr/local/etc/redis/redis.conf", False),
         ("tmpfs", "", "/data", True)})
    data_target, capacity = (("/var/lib/postgresql/data", "536870912") if role == "postgres" else ("/data", "134217728"))
    _require(observed['tmpfs'] == {data_target: 'rw,nosuid,size=' + capacity}, 'S1_MOUNT_MISMATCH')
    # Docker's --tmpfs may be represented solely in HostConfig, including after
    # start. Its exact declaration above remains mandatory in both forms.
    bind_mounts = {item for item in expected_mounts if item[0] == 'bind'}
    _require(isinstance(observed["mounts"], list), "S1_MOUNT_MISMATCH")
    actual = set()
    for mount in observed["mounts"]:
        _require(isinstance(mount, dict), "S1_MOUNT_MISMATCH")
        source = mount.get("Source", "")
        if mount.get("Type") == "bind":
            matches = [row[1] for row in expected_mounts if row[0] == "bind" and _host_source_matches(source, row[1])]
            _require(len(matches) == 1, "S1_MOUNT_MISMATCH")
            source = matches[0]
        actual.add((mount.get("Type"), source, mount.get("Destination"), mount.get("RW")))
    _require(actual in (expected_mounts, bind_mounts) and len(observed['mounts']) == len(actual), 'S1_MOUNT_MISMATCH')


def _read_document(root, manifest_path, *, require_ready=True):
    target = checked_path(manifest_path)
    try:
        _require(target.stat().st_size <= 32768)
        document = json.loads(target.read_text(encoding="utf-8"))
        safe = validate_manifest(root, target, document, require_ready=require_ready)
    except (OSError, ValueError, TypeError, KeyError):
        raise IsolationError("S1_MANIFEST_INVALID") from None
    return document, safe


def read_test_settings(root, document):
    """Only newly generated S1 service secrets; no main dotenv/model values."""
    target = checked_path(document["settings_path"])
    _require(target.parent == checked_path(root) / "work/maint-s1" / document["instance_id"])
    try:
        _require(target.stat().st_size <= 16384, "S1_SETTINGS_INVALID")
        values = {}
        for line in target.read_text(encoding="utf-8").splitlines():
            name, value = line.split("=", 1)
            _require(name in SETTINGS_NAMES and name not in values, "S1_SETTINGS_INVALID")
            values[name] = json.loads(value)
        _require(all(isinstance(value, str) for value in values.values()), "S1_SETTINGS_INVALID")
        for name, expected in SAFE_ENV.items():
            _require(values.get(name) == expected, "S1_SETTINGS_UNSAFE")
        for field, scheme, role, username, path in (
            ("AGENTFORGE_DATABASE_URL", "postgresql+asyncpg", "postgres", "agentforge", "/agentforge"),
            ("AGENTFORGE_REDIS_URL", "redis", "redis", "", "/0")):
            parsed = urlsplit(values[field])
            _require(parsed.scheme == scheme and parsed.hostname == "127.0.0.1" and
                parsed.port == document["ports"][role] and parsed.username == username and
                bool(re.fullmatch(r"s1-test-only-[a-f0-9]{48}", parsed.password or "")) and
                parsed.path == path and not parsed.query and not parsed.fragment,
                "S1_SETTINGS_TARGET_MISMATCH")
        _require(values["AGENTFORGE_TENANT_ID"] == document["tenant_id"], "S1_SETTINGS_TARGET_MISMATCH")
        _require(values["BACKEND_PORT"] == str(document["ports"]["backend"]) and
            values["FRONTEND_PORT"] == str(document["ports"]["frontend"]), "S1_SETTINGS_TARGET_MISMATCH")
        _require(values["AGENTFORGE_SANDBOX_RUNNER_URL"] == "http://127.0.0.1:" + str(document["ports"]["runner"]), "S1_SETTINGS_TARGET_MISMATCH")
        _require(values["AGENTFORGE_ALLOWED_MODEL_HOSTS"] == "api.deepseek.com" and
            values["AGENTFORGE_MODEL_CREDENTIAL_HOSTS"] == values["AGENTFORGE_MODEL_PRICES"] == "{}", "S1_SETTINGS_UNSAFE")
        names = ("AGENTFORGE_ADMIN_TOKEN", "AGENTFORGE_SANDBOX_RUNNER_TOKEN", "AGENTFORGE_SANDBOX_APPROVER_TOKEN",
            "AGENTFORGE_MCP_SERVER_TOKEN", "AGENTFORGE_CAPABILITY_APPROVER_TOKEN")
        _require(all(re.fullmatch(r"s1-test-only-[a-f0-9]{48}", values[name]) for name in names), "S1_SETTINGS_INVALID")
        _require(len({values[name] for name in names}) == len(names), "S1_SETTINGS_INVALID")
    except (OSError, ValueError, TypeError, KeyError):
        raise IsolationError("S1_SETTINGS_INVALID") from None
    return values


@contextmanager
def isolation_lease(root, manifest_path):
    """Keep deletion/reconfiguration excluded throughout a test operation."""
    from lifecycle_manager import operation_lock
    target = checked_path(manifest_path)
    document, _ = _read_document(root, target)
    with operation_lock(target.parent / "resource-lock"):
        refreshed, _ = _read_document(root, target)
        _require(refreshed == document, "S1_MANIFEST_CHANGED")
        safe = validate_isolation(root, target)
        key = os.path.normcase(str(target))
        with _LEASES_LOCK:
            _LEASES[key] = _LEASES.get(key, 0) + 1
        try:
            yield safe
        finally:
            with _LEASES_LOCK:
                _LEASES[key] -= 1
                if not _LEASES[key]:
                    del _LEASES[key]


def has_active_lease(manifest_path):
    """Refuse same-process cleanup even from a reentrant thread/async Task."""
    key = os.path.normcase(str(checked_path(manifest_path)))
    with _LEASES_LOCK:
        return _LEASES.get(key, 0) > 0


def validate_isolation(root, manifest_path):
    """Read-only identity snapshot, also usable by children of a lease owner.

This does not acquire write authority. Test runners must hold isolation_lease
through all business writes and cleanup; a snapshot alone is not a lifetime lock.
"""
    document, safe = _read_document(root, manifest_path)
    attest_network(root, document)
    for role in ("postgres", "redis"):
        attest_container(root, document, role)
    read_test_settings(root, document)
    refreshed, _ = _read_document(root, manifest_path)
    _require(refreshed == document, "S1_MANIFEST_CHANGED")
    return safe


def build_test_environment(root, manifest_path):
    safe = validate_isolation(root, manifest_path)
    env = runtime_environment()
    env.update(SAFE_ENV)
    env.update(AGENTFORGE_S1_MANIFEST=safe["manifest_path"], AGENTFORGE_SETTINGS_FILE=safe["settings_path"],
        PYTHONPATH=os.pathsep.join((str(Path(root) / "backend"), str(Path(root) / "tests/fixtures"), str(Path(root) / "scripts"))),
        PYTHONIOENCODING="utf-8", BACKEND_PORT=str(safe["ports"]["backend"]), FRONTEND_PORT=str(safe["ports"]["frontend"]),
        TEMP=str(Path(safe["run_directory"]) / "temp"), TMP=str(Path(safe["run_directory"]) / "temp"))
    return env


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("action", choices=("validate",))
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_isolation(PROJECT_ROOT, args.manifest), sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except IsolationError as error:
        print(json.dumps({"status": "refused", "code": error.code}))
        raise SystemExit(2) from None
    except Exception:
        print(json.dumps({"status": "refused", "code": "S1_UNAVAILABLE"}))
        raise SystemExit(2) from None
