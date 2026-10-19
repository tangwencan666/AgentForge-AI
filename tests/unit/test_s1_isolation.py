"""S1 resource attestations use explicit Docker stubs; no Docker/DB/network IO."""
import copy
import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import s1_isolation as guard
import s1_test_environment as environment


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    root = tmp_path / "project"
    instance = str(uuid4())
    run = root / "work/maint-s1" / instance
    run.mkdir(parents=True)
    ports = dict(postgres=41001, redis=41002, backend=41003, frontend=41004, runner=41005)
    environment.prepare_files(run, instance, ports)
    document = {"version": 1, "instance_id": instance, "project_root": str(root), "status": "READY",
        "ports": ports, "resources": {role: {"id": char * 64, "name": f"agentforge-s1-{instance}-{role}",
            "image_id": environment.APPROVED_IMAGES[role]} for role, char in (("postgres", "a"), ("redis", "b"))},
        "network": {"id": "c" * 64, "name": "agentforge-s1-" + instance}, "database_name": "agentforge",
        "tenant_id": instance, "settings_path": str(run / ".env"), "created_at": "2026-10-16T00:00:00+00:00"}
    path = run / "isolation.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(environment, "ROOT", root)
    rows = {"network": {"id": document["network"]["id"], "name": document["network"]["name"],
        "labels": guard.expected_labels(root, instance, "network"), "internal": False,
        'driver': 'bridge', 'options': dict(guard.NETWORK_OPTIONS)}}
    for role in ("postgres", "redis"):
        bind_file, bind_target, data = (("init.sql", "/docker-entrypoint-initdb.d/10-s1.sql", "/var/lib/postgresql/data")
            if role == "postgres" else ("redis.conf", "/usr/local/etc/redis/redis.conf", "/data"))
        record = document["resources"][role]
        rows[role] = {"id": record["id"], "name": "/" + record["name"], "image": record["image_id"],
            "labels": guard.expected_labels(root, instance, role), "ports": {
                ("5432/tcp" if role == "postgres" else "6379/tcp"): [{"HostIp": "127.0.0.1", "HostPort": str(ports[role])}]},
            "mounts": [{"Type": "bind", "Source": str(run / bind_file), "Destination": bind_target, "RW": False},
                       {"Type": "tmpfs", "Source": "", "Destination": data, "RW": True}],
            "tmpfs": {data: 'rw,nosuid,size=' + ('536870912' if role == 'postgres' else '134217728')},
            "network": document["network"]["name"],
            "published_ports": {('5432/tcp' if role == 'postgres' else '6379/tcp'):
                [{'HostIp': '127.0.0.1', 'HostPort': str(ports[role])}]},
            "networks": {document["network"]["name"]: {"NetworkID": document["network"]["id"]}},
            "privileged": False, "restart": "no", "running": True, "state": "running", "health": "healthy"}
    calls = []
    def inspect(args):
        calls.append(args)
        role = "network" if args[0] == "network" else next(
            role for role in ("postgres", "redis") if document["resources"][role]["id"] == args[-1])
        return copy.deepcopy(rows[role])
    monkeypatch.setattr(guard, "_docker_json", inspect)
    return root, path, document, rows, calls


@pytest.mark.parametrize('created', [True, False])
def test_container_requires_exact_tmpfs_even_if_inspect_omits_mount(isolated, created):
    root, _, document, rows, _ = isolated
    row = rows['postgres']
    if created:
        row.update(running=False, state='created', health=None)
    row['mounts'] = row['mounts'][:1]
    if created:
        row['networks'][document['network']['name']]['NetworkID'] = ''
    guard.attest_container(root, document, 'postgres', require_running=False)
    row['tmpfs'] = {}
    with pytest.raises(guard.IsolationError, match='S1_MOUNT_MISMATCH'):
        guard.attest_container(root, document, 'postgres', require_running=False)


def test_valid_stack_returns_only_public_metadata_and_attests_exact_ids(isolated):
    root, path, document, _, calls = isolated
    safe = guard.validate_isolation(root, path)
    assert safe["instance_id"] == document["instance_id"]
    assert safe["database_name"] == "agentforge" and not safe["real_calls_enabled"]
    assert "s1-test-only-" not in json.dumps(safe)
    assert [call[-1] for call in calls] == ["c" * 64, "a" * 64, "b" * 64]
    assert all(".Config.Env" not in " ".join(call) for call in calls)
    assert not (path.parent / "resource-lock").exists()  # Read-only snapshot does not mutate lock state.


@pytest.mark.parametrize("port", sorted(guard.FORBIDDEN_PORTS))
def test_main_and_legacy_ports_are_refused_before_docker(isolated, port):
    root, path, document, _, calls = isolated
    document["ports"]["postgres"] = port
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(guard.IsolationError):
        guard.validate_isolation(root, path)
    assert not calls


@pytest.mark.parametrize("kind", ["labels", "id", "image", "network", "privileged", "restart", "running", "health", "mount", "port", "name"])
def test_forged_resource_metadata_refuses_before_settings_read(isolated, monkeypatch, kind):
    root, path, _, rows, _ = isolated
    item = rows["postgres"]
    changes = {"labels": {}, "id": "e" * 64, "image": "sha256:" + "f" * 64,
        "network": "main-network", "privileged": True, "restart": "always", "running": False,
        "health": "unhealthy", "name": "/agentforge-p1-postgres"}
    if kind in changes:
        item[kind] = changes[kind]
    elif kind == "mount":
        item["mounts"][0]["Source"] = str(root / ".env")
    else:
        item["ports"]["5432/tcp"][0]["HostPort"] = "15432"
    monkeypatch.setattr(guard, "read_test_settings", lambda *_: pytest.fail("settings read before resource trust"))
    with pytest.raises(guard.IsolationError):
        guard.validate_isolation(root, path)


@pytest.mark.parametrize('field,value', [('internal', True), ('driver', 'host'), ('options', {})])
def test_network_without_exact_isolated_bridge_policy_is_refused(isolated, field, value):
    root, path, _, rows, _ = isolated
    rows['network'][field] = value
    with pytest.raises(guard.IsolationError, match="S1_NETWORK_IDENTITY_MISMATCH"):
        guard.validate_isolation(root, path)


def test_declared_but_unpublished_port_refuses_before_settings(isolated, monkeypatch):
    root, path, _, rows, _ = isolated
    rows['postgres']['published_ports'] = {'5432/tcp': []}
    monkeypatch.setattr(guard, 'read_test_settings', lambda *_: pytest.fail('Unavailable port accepted'))
    with pytest.raises(guard.IsolationError, match='S1_PORT_NOT_PUBLISHED'):
        guard.validate_isolation(root, path)


@pytest.mark.parametrize("field,value", [
    ("AGENTFORGE_REAL_CALLS_ENABLED", "true"), ("AGENTFORGE_REAL_DAILY_BUDGET_USD", "0.005"),
    ("AGENTFORGE_REAL_TEST_BUDGET_USD", "0.005"), ("AGENTFORGE_REAL_WORKER_MODE", "permit_only"),
    ("AGENTFORGE_SINGLE_USE_PERMITS_ENABLED", "true"), ("AGENTFORGE_REAL_MAX_RETRIES", "1"),
    ("AGENTFORGE_EXTERNAL_MODELS_BLOCKED", "0"), ("AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN", "fake-issuer-only"),
    ("AGENTFORGE_MODEL_CODER_KEY", "fake-key-only"),
    ("AGENTFORGE_DATABASE_URL", "postgresql+asyncpg://agentforge:test@127.0.0.1:15432/agentforge"),
    ("AGENTFORGE_REDIS_URL", "redis://:test@127.0.0.1:16379/0"),
    ("AGENTFORGE_SANDBOX_RUNNER_URL", "http://127.0.0.1:18120"),
])
def test_settings_cannot_repoint_to_main_or_open_real_execution(isolated, field, value):
    root, path, document, _, _ = isolated
    target = Path(document["settings_path"])
    values = dict(line.split("=", 1) for line in target.read_text().splitlines())
    values[field] = json.dumps(value)
    target.write_text("".join(name + "=" + item + "\n" for name, item in values.items()), encoding="utf-8")
    with pytest.raises(guard.IsolationError):
        guard.validate_isolation(root, path)


def test_build_child_environment_reads_only_os_names(isolated):
    root, path, _, _, _ = isolated
    names = ("AGENTFORGE_MODEL_CODER_KEY", "AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN")
    assert not any(name in os.environ for name in names), "run this unit fixture in a stripped child environment"
    try:
        for name in names:
            os.environ[name] = "explicit-fake-do-not-propagate"
        env = guard.build_test_environment(root, path)
        assert all(name not in env for name in names)
        assert "explicit-fake-do-not-propagate" not in str(env)
        assert env["AGENTFORGE_S1_MANIFEST"] == str(path)
        assert env["AGENTFORGE_REAL_CALLS_ENABLED"] == "false"
    finally:
        for name in names:
            del os.environ[name]


def test_cleanup_refuses_forged_container_without_any_docker_mutation(isolated, monkeypatch):
    _, path, _, rows, _ = isolated
    rows["redis"]["labels"] = {}
    mutations = []
    monkeypatch.setattr(environment, "command", lambda args: mutations.append(args))
    with pytest.raises(guard.IsolationError):
        environment.cleanup(path)
    assert mutations == []


def test_cleanup_uses_only_attested_ids_and_retains_evidence(isolated, monkeypatch):
    _, path, _, _, calls = isolated
    mutations = []
    def command(args):
        environment._authorize_command(args)
        mutations.append(args)
        return ""
    monkeypatch.setattr(environment, "command", command)
    assert environment.cleanup(path)["status"] == "CLEANED"
    assert mutations == [["container", "rm", "--force", "b" * 64],
        ["container", "rm", "--force", "a" * 64], ["network", "rm", "c" * 64]]
    assert json.loads(path.read_text())["status"] == "CLEANED"
    assert path.parent.is_dir() and (path.parent / ".env").is_file()
    assert len(calls) >= 6


@pytest.mark.parametrize("image", ["postgres:16", "redis:7", "sha256:" + "a" * 64, "--pull=always"])
def test_unapproved_or_mutable_image_rejected_without_docker(monkeypatch, image):
    monkeypatch.setattr(guard, "_docker_json", lambda *_: pytest.fail("must reject before Docker"))
    with pytest.raises(guard.IsolationError, match="S1_CACHED_IMAGE_REQUIRED"):
        environment.image_identity(image, "postgres")


def test_docker_template_does_not_extract_environment_or_credentials(isolated):
    root, path, _, _, calls = isolated
    guard.validate_isolation(root, path)
    text = "\n".join(" ".join(call) for call in calls)
    assert ".Config.Env" not in text and "Authorization" not in text and "password" not in text


def test_generated_service_config_contains_no_model_or_issuer_credentials(isolated):
    root, _, document, _, _ = isolated
    values = guard.read_test_settings(root, document)
    assert "AGENTFORGE_MODEL_CODER_KEY" not in values
    assert "AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN" not in values
    assert all(values[key] == value for key, value in guard.SAFE_ENV.items())


def test_environment_locator_alone_does_not_authorize_access(isolated):
    root, path, document, _, calls = isolated
    document["project_root"] = str(root.parent / "main")
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(guard.IsolationError):
        guard.validate_isolation(root, path)
    assert not calls


def test_unknown_manifest_state_and_duplicate_port_fail_closed(isolated):
    root, path, document, _, _ = isolated
    document["status"] = "RECOVERY_REQUIRED"
    with pytest.raises(guard.IsolationError, match="S1_NOT_READY"):
        guard.validate_manifest(root, path, document)
    document["status"] = "READY"
    document["ports"]["backend"] = document["ports"]["redis"]
    with pytest.raises(guard.IsolationError, match="S1_PORT_REFUSED"):
        guard.validate_manifest(root, path, document)


def test_create_only_uses_reviewed_images_and_new_instance_resources(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(environment, "ROOT", root)
    monkeypatch.setattr(environment, "image_identity", lambda image, role: image)
    monkeypatch.setattr(environment, "reserve_ports", lambda: dict(postgres=42001, redis=42002, backend=42003, frontend=42004, runner=42005))
    monkeypatch.setattr(guard, "attest_network", lambda *_: None)
    monkeypatch.setattr(guard, "attest_container", lambda *_, **__: None)
    calls = []
    def command(args):
        environment._authorize_command(args)
        calls.append(args)
        if args[:2] == ["network", "create"]:
            return "c" * 64
        if args[:2] == ["container", "create"]:
            return ("a" if "postgres" in args[args.index("--name") + 1] else "b") * 64
        return ""
    monkeypatch.setattr(environment, "command", command)
    safe = environment.create(environment.APPROVED_IMAGES["postgres"], environment.APPROVED_IMAGES["redis"])
    assert safe["status"] == "READY"
    assert len(calls) == 5
    creates = [args for args in calls if args[:2] == ["container", "create"]]
    assert len(creates) == 2 and all(args[args.index("--pull") + 1] == "never" for args in creates)
    assert all("--restart" in args and args[args.index("--restart") + 1] == "no" for args in creates)
    assert all("agentforge-s1-" + safe["instance_id"] in " ".join(args) for args in calls if "create" in args)
    assert "s1-test-only-" not in str(calls) and "runner" not in str(calls)
    assert all("/var/run/docker.sock" not in " ".join(args) for args in calls)
    audit = (Path(safe["run_directory"]) / "resource-audit.jsonl").read_text()
    assert "s1-test-only-" not in audit and "Authorization" not in audit


def test_creation_failure_preserves_owned_intent_without_broad_cleanup(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(environment, "ROOT", root)
    monkeypatch.setattr(environment, "image_identity", lambda image, role: image)
    monkeypatch.setattr(environment, "reserve_ports", lambda: dict(postgres=42001, redis=42002, backend=42003, frontend=42004, runner=42005))
    calls = []
    def unavailable(args):
        environment._authorize_command(args)
        calls.append(args)
        raise guard.IsolationError("S1_RESOURCE_COMMAND_FAILED")
    monkeypatch.setattr(environment, "command", unavailable)
    with pytest.raises(guard.IsolationError):
        environment.create(environment.APPROVED_IMAGES["postgres"], environment.APPROVED_IMAGES["redis"])
    records = list(root.glob("work/maint-s1/*/isolation.json"))
    assert len(records) == 1
    document = json.loads(records[0].read_text())
    assert document["status"] == "RECOVERY_REQUIRED"
    assert document["resources"] == {} and document["network"] is None
    assert len(calls) == 1 and calls[0][:2] == ["network", "create"]


@pytest.mark.parametrize("role", ["postgres", "redis"])
def test_cached_image_requires_reviewed_layout_and_platform(monkeypatch, role):
    row = {"id": environment.APPROVED_IMAGES[role], "os": "linux", "entrypoint": ["docker-entrypoint.sh"],
        "volumes": {"/var/lib/postgresql/data" if role == "postgres" else "/data": {}}}
    monkeypatch.setattr(guard, "_docker_json", lambda _: row)
    assert environment.image_identity(row["id"], role) == row["id"]
    row["volumes"] = {"/unexpected": {}}
    with pytest.raises(guard.IsolationError, match="S1_IMAGE_LAYOUT_UNSUPPORTED"):
        environment.image_identity(row["id"], role)


def test_health_failure_never_becomes_ready(isolated):
    root, path, _, rows, _ = isolated
    rows["redis"]["health"] = "starting"
    with pytest.raises(guard.IsolationError, match="S1_RESOURCE_NOT_RUNNING"):
        guard.validate_isolation(root, path)


def test_forged_manifest_cannot_authorize_an_unreviewed_image(isolated):
    root, path, document, _, calls = isolated
    document["resources"]["postgres"]["image_id"] = "sha256:" + "f" * 64
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(guard.IsolationError, match="S1_CACHED_IMAGE_REQUIRED"):
        guard.validate_isolation(root, path)
    assert calls == []


def test_resource_lease_keeps_owned_lock_while_readonly_child_check_is_allowed(isolated):
    root, path, document, _, _ = isolated
    with guard.isolation_lease(root, path) as safe:
        assert (path.parent / "resource-lock/operation.lock").is_file()
        assert guard.validate_isolation(root, path)["instance_id"] == document["instance_id"]
        assert safe["status"] == "READY"


@pytest.mark.parametrize("arguments", [
    ["stop", "agentforge-p1-postgres"], ["container", "rm", "--force", "a" * 64],
    ["exec", "agentforge-p3-runner", "sh"], ["system", "prune", "--force"],
])
def test_imported_command_requires_live_operation_capability(monkeypatch, arguments):
    monkeypatch.setattr(environment.subprocess, "run", lambda *_a, **_k: pytest.fail("must refuse before subprocess"))
    with pytest.raises(guard.IsolationError, match="S1_OPERATION_CONTEXT_REQUIRED"):
        environment.command(arguments)


def test_forged_context_object_does_not_grant_authority(isolated, monkeypatch):
    _, path, document, _, _ = isolated
    owner = environment._owner()
    forged = environment._Operation("cleanup", path, document, owner)
    monkeypatch.setitem(environment._ACTIVE, owner, forged)
    monkeypatch.setattr(environment.subprocess, "run", lambda *_a, **_k: pytest.fail("forged context escaped"))
    with environment.operation_lock(path.parent / "resource-lock"):
        with pytest.raises(guard.IsolationError, match="S1_OPERATION_CONTEXT_REQUIRED"):
            environment.command(["container", "rm", "--force", "a" * 64])


def test_operation_context_requires_actual_resource_lock(isolated):
    _, path, document, _, _ = isolated
    with pytest.raises(guard.IsolationError, match="S1_OPERATION_CONTEXT_REQUIRED"):
        with environment._resource_operation("cleanup", path, document):
            pytest.fail("unlocked scope admitted")


@pytest.mark.parametrize("arguments", [
    ["container", "rm", "--force", "agentforge-p1-postgres"],
    ["container", "rm", "--force", "f" * 64],
    ["container", "stop", "a" * 64],
    ["container", "start", "a" * 64],
    ["container", "exec", "a" * 64, "sh"],
    ["network", "rm", "c" * 64],  # Attached containers have not yet been removed.
    ["container", "rm", "--force", "a" * 64, "--volumes"],
])
def test_active_cleanup_scope_cannot_expand_argument_or_target(isolated, monkeypatch, arguments):
    _, path, document, _, _ = isolated
    document["status"] = "CLEANING"
    path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(environment.subprocess, "run", lambda *_a, **_k: pytest.fail("unapproved command escaped"))
    with environment.operation_lock(path.parent / "resource-lock"), environment._resource_operation("cleanup", path, document):
        with pytest.raises(guard.IsolationError, match="S1_COMMAND_FORBIDDEN"):
            environment.command(arguments)


def test_exact_cleanup_command_is_one_attempt_and_context_expires(isolated, monkeypatch):
    _, path, document, _, _ = isolated
    document["status"] = "CLEANING"
    path.write_text(json.dumps(document), encoding="utf-8")
    calls = []
    monkeypatch.setattr(environment.subprocess, "run", lambda args, **_k: calls.append(args) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    arguments = ["container", "rm", "--force", "a" * 64]
    with environment.operation_lock(path.parent / "resource-lock"), environment._resource_operation("cleanup", path, document):
        environment.command(arguments)
        with pytest.raises(guard.IsolationError, match="S1_COMMAND_ALREADY_ATTEMPTED"):
            environment.command(arguments)
    with pytest.raises(guard.IsolationError, match="S1_OPERATION_CONTEXT_REQUIRED"):
        environment.command(arguments)
    assert calls == [["docker", *arguments]]


def test_manifest_change_revokes_in_process_command_scope(isolated, monkeypatch):
    _, path, document, _, _ = isolated
    document["status"] = "CLEANING"
    path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(environment.subprocess, "run", lambda *_a, **_k: pytest.fail("changed manifest escaped"))
    with environment.operation_lock(path.parent / "resource-lock"), environment._resource_operation("cleanup", path, document):
        changed = copy.deepcopy(document)
        changed["ports"]["backend"] += 20
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(guard.IsolationError, match="S1_MANIFEST_CHANGED"):
            environment.command(["container", "rm", "--force", "a" * 64])


@pytest.mark.parametrize("arguments", [
    ["stop", "agentforge-p1-postgres"], ["exec", "agentforge-p3-runner", "sh"],
    ["container", "inspect", "--format", "{{json .Config.Env}}", "a" * 64],
    ["container", "inspect", "--format", guard.CONTAINER_TEMPLATE, "agentforge-p1-postgres"],
    ["image", "inspect", "--format", guard.IMAGE_TEMPLATE, "postgres:16"],
])
def test_readonly_helper_is_not_a_docker_or_environment_bridge(monkeypatch, arguments):
    monkeypatch.setattr(guard.subprocess, "run", lambda *_a, **_k: pytest.fail("read-only bridge escaped"))
    with pytest.raises(guard.IsolationError, match="S1_READONLY_COMMAND_REFUSED"):
        guard._docker_json(arguments)


@pytest.mark.parametrize("changed", ["extra", "wrong_id", "missing"])
def test_actual_network_attachments_are_verified(isolated, changed):
    root, path, document, rows, _ = isolated
    if changed == "extra":
        rows["redis"]["networks"]["bridge"] = {"NetworkID": "f" * 64}
    elif changed == "wrong_id":
        rows["redis"]["networks"][document["network"]["name"]]["NetworkID"] = "f" * 64
    else:
        rows["redis"]["networks"] = {}
    with pytest.raises(guard.IsolationError, match="S1_NETWORK_ATTACHMENT_MISMATCH"):
        guard.validate_isolation(root, path)


def test_unstarted_attachment_allows_only_fixed_prestart_network(isolated):
    root, _, document, rows, _ = isolated
    rows["postgres"]["running"] = False
    rows["postgres"]["state"] = "created"
    rows["postgres"]["health"] = None
    rows["postgres"]["networks"][document["network"]["name"]]["NetworkID"] = ""
    guard.attest_container(root, document, "postgres", require_running=False)
    rows["postgres"]["state"] = "exited"
    with pytest.raises(guard.IsolationError, match="S1_NETWORK_ATTACHMENT_MISMATCH"):
        guard.attest_container(root, document, "postgres", require_running=False)


def test_active_lifetime_lease_refuses_cleanup_from_another_logical_task_stub(isolated, monkeypatch):
    root, path, _, _, _ = isolated
    monkeypatch.setattr(environment, "command", lambda *_: pytest.fail("active lease was deleted"))
    # Pure logical-task double: no Windows event-loop self-pipe or real sockets.
    with guard.isolation_lease(root, path):
        monkeypatch.setattr(environment.asyncio, "current_task", lambda: object())
        with pytest.raises(guard.IsolationError, match="S1_RESOURCE_LEASE_ACTIVE"):
            environment.cleanup(path)
