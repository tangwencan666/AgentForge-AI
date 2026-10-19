"""Policy unit tests. These doubles are not Docker isolation evidence."""
from copy import deepcopy
from contextlib import nullcontext
from datetime import timedelta
from decimal import Decimal
import hashlib
from queue import Queue
from threading import Event
from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.sandbox.driver import DockerDriver
from app.sandbox.policy import (SECCOMP, PolicyViolation, create_options, operation_digest,
    validate_execution, validate_image, verify_attestation, verify_container, assert_runner_lease)
from app.schemas.sandbox import POLICY_VERSION, ResourceLimits
from app.services.tasks import now

IMAGE = "sha256:" + "a" * 64


def policy_only_authority(driver):
    """Explicit unit double isolates P3 IO/limits tests from the DB authority.

    These tests are NOT proof of ownership. S3A database/SDK-Stub tests use the
    actual coordinator/bridge; a production driver without authority is denied.
    """
    driver._authority = lambda: True
    driver._before = lambda *args, **kwargs: {}
    driver.dispatch_window = nullcontext
    return driver


def facts():
    task = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), options={"execution_mode": "sandbox"}, is_mock=False)
    row = SimpleNamespace(id=uuid4(), tenant_id=task.tenant_id, task_id=task.id, language="python", code="print(1)",
        timeout_seconds=30, resource_limits=ResourceLimits().model_dump(), policy_version=POLICY_VERSION,
        reserved_cpu_seconds=Decimal("15"), requester="local-admin", approval_reference=uuid4())
    row.code_hash = hashlib.sha256(row.code.encode()).hexdigest()
    row.operation_hash = operation_digest(row.code_hash, row.language, row.timeout_seconds, row.resource_limits, IMAGE)
    approval = SimpleNamespace(id=row.approval_reference, task_id=task.id, tenant_id=task.tenant_id,
        operation_hash=row.operation_hash, policy_version=POLICY_VERSION, status="approved",
        decided_by="sandbox-reviewer", expires_at=now() + timedelta(seconds=60))
    settings = SimpleNamespace(sandbox_image_id=IMAGE, sandbox_daily_cpu_seconds=Decimal(3600))
    return row, approval, task, settings


def test_approval_hash_binds_all_execution_parameters():
    row, approval, task, settings = facts()
    assert validate_execution(row, approval, task, settings).cpu == 0.5
    for value in [row.code_hash + "x", "javascript", 31, {**row.resource_limits, "memory_mb": 256}, "sha256:" + "b" * 64]:
        args = [row.code_hash, row.language, row.timeout_seconds, row.resource_limits, IMAGE]
        index = [row.code_hash + "x", "javascript", 31, {**row.resource_limits, "memory_mb": 256}, "sha256:" + "b" * 64].index(value)
        args[index] = value
        assert operation_digest(*args) != row.operation_hash


@pytest.mark.parametrize("target,field,value", [
    ("approval", "status", "pending"), ("approval", "status", "rejected"),
    ("approval", "decided_by", "local-admin"), ("approval", "policy_version", "p2-plan-v1"),
    ("approval", "expires_at", now() - timedelta(seconds=1)), ("approval", "operation_hash", "bad"),
    ("row", "code", "print(2)"), ("row", "language", "shell"),
    ("row", "resource_limits", {"cpu": 2, "memory_mb": 512, "pids": 64}),
    ("row", "resource_limits", {"cpu": 0.5, "memory_mb": 128, "pids": 32, "privileged": True}),
    ("row", "reserved_cpu_seconds", Decimal(0)), ("task", "is_mock", True),
])
def test_durable_tampering_and_missing_permission_are_rejected(target, field, value):
    row, approval, task, settings = facts()
    setattr({"row": row, "approval": approval, "task": task}[target], field, value)
    with pytest.raises(PolicyViolation):
        validate_execution(row, approval, task, settings)


@pytest.mark.parametrize("image", ["python:latest", "alpine", "sha256:short", "", None])
def test_only_immutable_approved_image_ids_are_accepted(image):
    with pytest.raises(PolicyViolation):
        validate_image(image)


def inspection(execution_id):
    limits = ResourceLimits().model_dump()
    opts = create_options(IMAGE, execution_id, limits)
    return {"Image": IMAGE, "Mounts": [], "Config": {"User": opts["user"], "Cmd": opts["command"],
        "Entrypoint": [], "Labels": opts["labels"]}, "HostConfig": {
        "NetworkMode": "none", "Privileged": False, "ReadonlyRootfs": True, "CapDrop": ["ALL"],
        "CapAdd": None, "SecurityOpt": opts["security_opt"], "NanoCpus": opts["nano_cpus"],
        "Memory": opts["mem_limit"], "MemorySwap": opts["memswap_limit"], "PidsLimit": 32,
        "Binds": None, "Mounts": None, "Devices": [], "PidMode": "", "IpcMode": "private",
        "LogConfig": {"Type": "none"}, "Tmpfs": opts["tmpfs"]}}


@pytest.mark.parametrize("field,value", [("NetworkMode", "host"), ("Privileged", True), ("ReadonlyRootfs", False),
    ("CapAdd", ["SYS_ADMIN"]), ("PidsLimit", 0), ("MemorySwap", -1), ("Binds", ["/:/host"]),
    ("SecurityOpt", ["seccomp=unconfined"]), ("NanoCpus", 0), ("IpcMode", "container:another"), ("UTSMode", "host"),
    ("PortBindings", {"8080/tcp": [{"HostPort": "8888"}]})])
def test_docker_mutated_policy_is_rejected_before_code(field, value):
    execution_id = uuid4()
    attrs = inspection(execution_id)
    verify_container(attrs, IMAGE, ResourceLimits().model_dump(), execution_id)
    attrs["HostConfig"][field] = value
    with pytest.raises(PolicyViolation):
        verify_container(attrs, IMAGE, ResourceLimits().model_dump(), execution_id)


def test_attestation_requires_runtime_limits_not_just_docker_configuration():
    data = {"uid": 10001, "gid": 10001, "root_read_only": True, "seccomp": 2, "no_new_privileges": 1,
        "cap_eff": "0000000000000000", "cap_prm": "0000000000000000", "cap_inh": "0000000000000000", "cap_amb": "0000000000000000",
        "memory_max": 128 * 1024 * 1024, "memory_swap_max": 0, "pids_max": 32, "interfaces": ["lo"],
        "cpu_quota": 50000, "cpu_period": 100000}
    verify_attestation(data, ResourceLimits().model_dump())
    for field, value in {"seccomp": 0, "uid": 0, "memory_max": 9999999999, "pids_max": 9999,
                         "cpu_quota": 100000, "memory_swap_max": 100, "interfaces": ["lo", "eth0"]}.items():
        with pytest.raises(PolicyViolation):
            verify_attestation({**data, field: value}, ResourceLimits().model_dump())


def test_seccomp_excludes_namespace_and_host_attack_syscalls():
    allowed = {name for rule in SECCOMP["syscalls"] if rule["action"] == "SCMP_ACT_ALLOW" for name in rule["names"]}
    assert not allowed & {"mount", "unshare", "setns", "bpf", "ptrace", "keyctl", "perf_event_open", "clone3"}
    clone = next(rule for rule in SECCOMP["syscalls"] if rule["names"] == ["clone"])
    assert clone["args"][0]["op"] == "SCMP_CMP_MASKED_EQ"
    assert clone["args"][0]["valueTwo"] == 0
    families = {rule["args"][0]["value"] for rule in SECCOMP["syscalls"] if "socket" in rule["names"]}
    assert 40 not in families and 38 not in families  # AF_VSOCK / AF_ALG


def test_ioctl_only_allows_terminal_query_and_close_on_exec():
    rules = [rule for rule in SECCOMP["syscalls"] if "ioctl" in rule["names"] and rule["action"] == "SCMP_ACT_ALLOW"]
    assert len(rules) == 2
    assert {rule["args"][0]["value"] for rule in rules} == {0x5401, 0x5451}
    assert all(rule["args"] == [{"index": 1, "value": rule["args"][0]["value"], "op": "SCMP_CMP_EQ"}] for rule in rules)
    assert SECCOMP["defaultAction"] == "SCMP_ACT_ERRNO"


@pytest.mark.parametrize("owner,status,offset_seconds,valid", [
    ("runner", "running", 15, True),
    ("runner", "starting", -1, False),
    ("runner", "running", None, False),
    ("other", "running", 15, False),
    ("runner", "needs_reconciliation", 15, False),
])
def test_runner_lease_cannot_be_revived_or_inject_after_expiration(owner, status, offset_seconds, valid):
    at = now()
    lease = at + timedelta(seconds=offset_seconds) if offset_seconds is not None else None
    row = SimpleNamespace(runner_owner=owner, status=status, runner_lease_until=lease)
    if valid:
        assert_runner_lease(row, "runner", at)
    else:
        with pytest.raises(PolicyViolation, match="RUNNER_LEASE_LOST"):
            assert_runner_lease(row, "runner", at)


def test_approved_create_options_are_accepted_by_installed_docker_sdk_without_daemon():
    from docker.models.containers import _create_container_args
    options = create_options(IMAGE, uuid4(), ResourceLimits().model_dump())
    assert options["use_config_proxy"] is False
    args = _create_container_args({**options, "version": "1.53"})
    assert args["host_config"]["NetworkMode"] == "none"
    assert args["host_config"]["ReadonlyRootfs"] is True
    assert args["host_config"]["MemorySwap"] == args["host_config"]["Memory"]


def test_docker_unavailable_fails_closed_without_host_code_or_raw_error(capsys):
    class Unavailable:
        def ping(self):
            raise RuntimeError("private-password-and-code")
    driver = policy_only_authority(DockerDriver(IMAGE, client=Unavailable()))
    result = driver.run(uuid4(), "raise RuntimeError('would run on host')", ResourceLimits().model_dump(), 1, Event(), Event(), Queue())
    assert result.status == "failed" and result.failure_reason == "DOCKER_UNAVAILABLE"
    assert result.container_id is None and result.cleanup_status == "not_created"
    assert result.stdout == result.stderr == b""
    assert "private-password" not in repr(result) and capsys.readouterr().out == ""


@pytest.mark.parametrize("outcome,expected_status,expected_cleanup", [
    ("response_lost_created", "needs_reconciliation", "unconfirmed"),
    ("daemon_unreachable", "needs_reconciliation", "unconfirmed"),
    ("authoritative_absent", "needs_reconciliation", "unconfirmed"),
])
def test_unknown_create_result_never_assumes_container_absent(monkeypatch, outcome, expected_status, expected_cleanup):
    import sys
    from types import ModuleType
    # Isolated SDK error double allows this policy fault test before SDK installation.
    errors = ModuleType("docker.errors")
    class NotFound(Exception):
        pass
    errors.NotFound = NotFound
    errors.APIError = type("APIError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "docker.errors", errors)
    execution_id = uuid4()
    container = SimpleNamespace(id="c" * 64, name="agentforge-p3-exec-" + execution_id.hex,
        attrs={"Config": {"Labels": {"agentforge.sandbox.policy": POLICY_VERSION,
              "agentforge.sandbox.execution": str(execution_id)}}, "State": {"Running": False}})
    removed = []
    container.reload = lambda: None
    container.remove = lambda **kwargs: removed.append(container.id)
    class Containers:
        def create(self, **kwargs):
            raise TimeoutError("daemon response lost")
        def get(self, name):
            if outcome == "daemon_unreachable":
                raise TimeoutError("daemon unavailable")
            if outcome == "authoritative_absent" or removed:
                raise NotFound()
            return container
    driver = policy_only_authority(DockerDriver(IMAGE, client=SimpleNamespace(containers=Containers())))
    driver.health = lambda: True
    result = driver.run(execution_id, "print(1)", ResourceLimits().model_dump(), 1, Event(), Event(), Queue())
    assert (result.status, result.cleanup_status) == (expected_status, expected_cleanup)
    assert removed == []  # No durable ID: never infer ownership from a name.


def test_cleanup_handles_container_exit_between_inspect_and_kill():
    from docker.errors import APIError, NotFound
    execution_id = uuid4()
    state = {"Running": True}
    removed = []
    labels = {"agentforge.sandbox.policy": POLICY_VERSION, "agentforge.sandbox.execution": str(execution_id)}
    container = SimpleNamespace(id="c" * 64, name="agentforge-p3-exec-" + execution_id.hex,
        attrs={"Config": {"Labels": labels}, "State": state})
    container.reload = lambda: None
    def kill():
        state["Running"] = False
        raise APIError("static test race", response=SimpleNamespace(status_code=409))
    container.kill = kill
    container.remove = lambda **kwargs: removed.append(container.id)
    def get(name):
        raise NotFound("authoritative test absence")
    driver = policy_only_authority(DockerDriver(IMAGE, client=SimpleNamespace(containers=SimpleNamespace(get=get))))
    assert driver.remove(container) is True and removed == [container.id]


def test_trusted_startup_stderr_is_bounded_and_never_authorizes_code():
    import struct
    from docker.errors import NotFound
    execution_id = uuid4()
    attrs = inspection(execution_id)
    attrs["State"] = {"Running": False}
    removed = []
    container = SimpleNamespace(id="c" * 64, name="agentforge-p3-exec-" + execution_id.hex, attrs=attrs)
    container.reload = lambda: None
    container.start = lambda: attrs["State"].update(Running=True)
    container.kill = lambda: attrs["State"].update(Running=False)
    container.remove = lambda **kwargs: removed.append(container.id)
    messages = [b"Traceback (trusted startup)\n", b"ModuleNotFoundError: trusted image component\n"]
    frames = [bytes([2, 0, 0, 0]) + struct.pack(">I", len(body)) + body for body in messages] + [b""]
    class FakeSocket:
        def settimeout(self, value):
            pass
        def recv(self, size):
            return frames.pop(0)
        def sendall(self, value):
            pytest.fail("Unverified launcher must not receive untrusted code")
        def close(self):
            attrs["State"]["Running"] = False
    def get(name):
        if removed:
            raise NotFound("authoritative test absence")
        return container
    fake_client = SimpleNamespace(containers=SimpleNamespace(create=lambda **kwargs: container, get=get),
        api=SimpleNamespace(attach_socket=lambda *args, **kwargs: FakeSocket()))
    driver = policy_only_authority(DockerDriver(IMAGE, client=fake_client))
    driver.health = lambda: True
    permit = Event()
    permit.set()  # Unit double authorizes only trusted launcher start.
    queue = Queue()
    result = driver.run(execution_id, "print('must not run')", ResourceLimits().model_dump(), 1, Event(), permit, queue)
    assert result.status == "failed" and result.failure_reason == "RUNTIME_ISOLATION_UNVERIFIED"
    assert result.stderr == b"".join(messages) and result.stdout == b""
    assert result.cleanup_status == "removed" and queue.qsize() == 1


def test_output_limit_survives_natural_exit_race_at_primary_kill():
    import json
    import struct
    from docker.errors import APIError, NotFound
    from app.sandbox.policy import OUTPUT_LIMIT
    execution_id = uuid4()
    attrs = inspection(execution_id)
    attrs["State"] = {"Running": False, "OOMKilled": False}
    removed, injected = [], []
    container = SimpleNamespace(id="c" * 64, name="agentforge-p3-exec-" + execution_id.hex, attrs=attrs)
    container.reload = lambda: None
    container.start = lambda: attrs["State"].update(Running=True)
    def kill():
        attrs["State"]["Running"] = False
        raise APIError("static natural-exit race", response=SimpleNamespace(status_code=409))
    container.kill = kill
    container.wait = lambda **kwargs: {"StatusCode": 0}
    container.remove = lambda **kwargs: removed.append(container.id)
    attestation = {"uid": 10001, "gid": 10001, "root_read_only": True, "seccomp": 2, "no_new_privileges": 1,
        "cap_eff": "0000000000000000", "cap_prm": "0000000000000000", "cap_inh": "0000000000000000", "cap_amb": "0000000000000000",
        "memory_max": 128 * 1024 * 1024, "memory_swap_max": 0, "pids_max": 32, "interfaces": ["lo"],
        "cpu_quota": 50000, "cpu_period": 100000}
    bodies = [("AGENTFORGE_ATTEST:" + json.dumps(attestation) + "\n").encode(), b"x" * OUTPUT_LIMIT, b"x"]
    frames = [bytes([1, 0, 0, 0]) + struct.pack(">I", len(body)) + body for body in bodies]
    permit = Event()
    permit.set()
    class FakeSocket:
        def settimeout(self, value):
            pass
        def recv(self, size):
            if len(frames) == 3:
                permit.set()  # Explicit unit double authorizes after trusted facts.
            return frames.pop(0)
        def sendall(self, value):
            injected.append(value)
        def close(self):
            pass
    def get(name):
        if removed:
            raise NotFound("authoritative test absence")
        return container
    fake_client = SimpleNamespace(containers=SimpleNamespace(create=lambda **kwargs: container, get=get),
        api=SimpleNamespace(attach_socket=lambda *args, **kwargs: FakeSocket()))
    driver = policy_only_authority(DockerDriver(IMAGE, client=fake_client))
    driver.health = lambda: True
    result = driver.run(execution_id, "print('bounded test')", ResourceLimits().model_dump(), 1, Event(), permit, Queue())
    assert result.status == "output_limit" and result.failure_reason == "OUTPUT_LIMIT"
    assert result.resource_usage["output_truncated"] is True and result.resource_usage["output_bytes"] == OUTPUT_LIMIT + 1
    assert result.cleanup_status == "removed" and len(injected) == 1 and removed == [container.id]
