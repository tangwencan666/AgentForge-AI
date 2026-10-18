"""Synchronous Docker lifecycle, run in a thread; no host subprocess execution."""
from dataclasses import dataclass, field
import json
import hashlib
from queue import Queue, Empty
import socket
import struct
from threading import Event
from time import monotonic
from uuid import UUID
from app.sandbox.policy import (OWNER_LABEL, EXECUTION_LABEL, OUTPUT_LIMIT, SUMMARY_LIMIT,
    PolicyViolation, create_options, verify_attestation, verify_container)
from app.schemas.sandbox import POLICY_VERSION, ResourceLimits

ERROR_TYPES = {"APIError", "DockerException", "TypeError", "ValueError", "OSError", "TimeoutError",
    "ReadTimeout", "ConnectionError", "HTTPError", "PermissionError", "InvalidArgument", "InvalidVersion",
    "NotFound", "ImageNotFound", "KeyError", "AttributeError", "JSONDecodeError", "PolicyViolation"}
ATTESTATION_FIELDS = {"uid", "gid", "root_read_only", "seccomp", "no_new_privileges", "cap_eff", "cap_prm",
    "cap_inh", "cap_amb", "memory_max", "memory_swap_max", "pids_max", "interfaces", "cpu_quota", "cpu_period"}


def safe_error_type(exc):
    kind = type(exc).__name__
    return kind if kind in ERROR_TYPES else "CONTROL_PLANE_ERROR"


@dataclass
class DriverResult:
    status: str = "failed"
    exit_code: int | None = None
    stdout: bytes = b""
    stderr: bytes = b""
    duration_ms: int | None = None
    resource_usage: dict = field(default_factory=dict)
    container_id: str | None = None
    cleanup_status: str = "not_created"
    failure_reason: str | None = None


class DockerDriver:
    def __init__(self, image_id, client=None, *, authority=None):
        self.image_id = image_id
        self._client = client
        self.authority = authority

    def _authority(self):
        if self.authority is None:
            raise PolicyViolation('SANDBOX_OWNERSHIP_REQUIRED')
        if self.client().info().get('ID') != self.authority.scope.daemon_id:
            self.authority.refuse(None)
            raise PolicyViolation('SANDBOX_DAEMON_IDENTITY_MISMATCH')
        return self.authority

    def _before(self, action, execution_id=None, container=None, *, operation_hash=None):
        authority = self._authority()
        attrs = None
        if container is not None:
            attrs = container.attrs
            if attrs.get('Id') != container.id:
                raise PolicyViolation('SANDBOX_CONTAINER_ID_MISMATCH')
            try:
                parsed = UUID((attrs.get('Config', {}).get('Labels') or {}).get(EXECUTION_LABEL, ''))
            except (ValueError, TypeError, AttributeError):
                authority.refuse(container.id)
                raise PolicyViolation('SANDBOX_OWNERSHIP_UNVERIFIED') from None
            if execution_id is not None and parsed != execution_id:
                raise PolicyViolation('SANDBOX_OWNERSHIP_UNVERIFIED')
            execution_id = parsed
        return authority.before(action, execution_id, attrs, operation_hash=operation_hash)

    def client(self):
        if self._client is None:
            import docker
            self._client = docker.from_env(timeout=5)
        return self._client

    def dispatch_window(self):
        # Missing/forged authority cannot supply a production dispatch window.
        return self._authority().window()

    def health(self):
        from app.sandbox.policy import validate_image
        validate_image(self.image_id)
        client = self.client()
        client.ping()
        info = client.info()
        if info.get("OSType") != "linux" or info.get("Architecture") not in {"x86_64", "aarch64", "amd64", "arm64"}:
            raise PolicyViolation("DOCKER_PLATFORM_UNVERIFIED")
        image = client.images.get(self.image_id)  # Never pull arbitrary registry images.
        if image.id != self.image_id:
            raise PolicyViolation("IMAGE_NOT_APPROVED")
        return True

    def owned(self):
        authority = self._authority()
        return self.client().containers.list(all=True, filters={'label': authority.scope.filters()})

    def stop_container(self, container):
        """A natural exit between inspect and kill is safe only after reinspection."""
        from docker.errors import APIError
        container.reload()
        self._before('stop', container=container)
        if container.attrs.get("State", {}).get("Running"):
            try:
                container.kill()
            except APIError as exc:
                if exc.status_code != 409:
                    raise
                container.reload()
                if container.attrs.get("State", {}).get("Running"):
                    raise

    def remove(self, container):
        """Confirm removal with daemon inspect. An ambiguous failure must block work."""
        from docker.errors import NotFound
        try:
            container.reload()
            self.stop_container(container)
            self._before('remove', container=container)
            container.remove(force=True, v=True)
        except NotFound:
            pass
        try:
            self.client().containers.get(container.id)
        except NotFound:
            self._before('removed', container=container)
            return True
        return False

    def absence(self, execution_id, container_id):
        """Only a durable immutable ID may be inspected. Never fall back to name."""
        from docker.errors import NotFound
        from app.sandbox.ownership import ID
        if not container_id or not ID.fullmatch(container_id):
            return False
        authority = self._authority()
        authority.before('inspect', execution_id, {'Id': container_id})
        try:
            container = self.client().containers.get(container_id)
        except NotFound:
            authority.before('absent', execution_id, {'Id': container_id})
            return True
        return self.remove(container)

    @staticmethod
    def sample(container, usage):
        stats = container.stats(stream=False)
        cpu = stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage")
        memory = stats.get("memory_stats", {}).get("usage")
        pids = stats.get("pids_stats", {}).get("current")
        if isinstance(cpu, (int, float)):
            usage["cpu_seconds"] = max(usage.get("cpu_seconds") or 0, cpu / 1e9)
        if isinstance(memory, int):
            usage["memory_sample_peak_bytes"] = max(usage.get("memory_sample_peak_bytes") or 0, memory)
        if isinstance(pids, int):
            usage["pids_sample_peak"] = max(usage.get("pids_sample_peak") or 0, pids)

    def run(self, execution_id: UUID, code: str, limits: dict, timeout_seconds: int,
            stop: Event, permit: Event, messages: Queue):
        result = DriverResult(resource_usage={"cpu_seconds": None, "memory_sample_peak_bytes": None,
            "pids_sample_peak": None, "oom_killed": None, "output_bytes": 0, "output_truncated": False})
        container = attached = None
        create_attempted = False
        start = None
        pending = bytearray()
        stdout, stderr = bytearray(), bytearray()
        attest_buffer = bytearray()
        attested = injected = False
        startup_error_at = None
        stage = "health"
        try:
            self._authority()
            self.health()
            if stop.is_set():
                result.status, result.failure_reason = "cancelled", "EXECUTION_STOPPED"
                return result
            from app.sandbox.policy import operation_digest
            input_hash = operation_digest(hashlib.sha256(code.encode()).hexdigest(), 'python',
                                          timeout_seconds, limits, self.image_id)
            with self.dispatch_window():
                ownership_labels = self._before('create', execution_id, operation_hash=input_hash)
                create_attempted = True
                stage = "create"
                options = create_options(self.image_id, execution_id, limits)
                options['labels'].update(ownership_labels)
                container = self.client().containers.create(**options)
            result.container_id, result.cleanup_status = container.id, "pending"
            container.reload()
            stage = "verify"
            verify_container(container.attrs, self.image_id, limits, execution_id)
            self._before('bind', execution_id, container)
            # Metadata is persisted before start. The permit handshake first authorizes
            # trusted launcher start, then separately authorizes code injection.
            messages.put(("created", container.id), timeout=1)
            while not permit.wait(0.1):
                if stop.is_set():
                    result.status, result.failure_reason = "cancelled", "EXECUTION_STOPPED"
                    return result
            permit.clear()
            stage = "attach"
            attached = self.client().api.attach_socket(container.id,
                params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1})
            raw = getattr(attached, "_sock", attached)
            raw.settimeout(0.2)
            stage = "start"
            with self.dispatch_window():
                self._before('start', execution_id, container, operation_hash=input_hash)
                container.start()
            start = monotonic()
            last_sample = start
            while True:
                elapsed = monotonic() - start
                if stop.is_set():
                    result.status, result.failure_reason = "cancelled", "EXECUTION_STOPPED"
                    break
                if startup_error_at is not None and monotonic() - startup_error_at >= 0.5:
                    raise PolicyViolation("RUNTIME_ISOLATION_UNVERIFIED")
                if elapsed > (timeout_seconds if injected else 10):
                    result.status, result.failure_reason = "timed_out", "EXECUTION_TIMEOUT" if injected else "LAUNCHER_TIMEOUT"
                    break
                if attested and not injected and permit.is_set():
                    # Only this write transfers code into the sandbox; it happens once.
                    stage = "inject"
                    with self.dispatch_window():
                        self._before('inject', execution_id, container, operation_hash=input_hash)
                        raw.sendall(json.dumps({"code": code, "timeout_seconds": timeout_seconds}, ensure_ascii=False).encode() + b"\n")
                    permit.clear()
                    injected = True
                    start = monotonic()
                    messages.put(("started", None), timeout=1)
                try:
                    stage = "read"
                    chunk = raw.recv(65536)
                except socket.timeout:
                    chunk = None
                if chunk == b"":
                    break
                if chunk:
                    pending.extend(chunk)
                    while len(pending) >= 8:
                        channel, size = pending[0], struct.unpack(">I", pending[4:8])[0]
                        if channel not in {1, 2} or size > OUTPUT_LIMIT:
                            result.resource_usage["output_frame_channel"] = channel
                            result.resource_usage["output_frame_size"] = size
                            raise PolicyViolation("INVALID_OUTPUT_FRAME")
                        if len(pending) < size + 8:
                            break
                        body = bytes(pending[8:8 + size])
                        del pending[:8 + size]
                        if not attested:
                            if channel != 1:
                                stderr.extend(body[:max(0, SUMMARY_LIMIT - len(stderr))])
                                result.resource_usage["pre_attest_channel"] = channel
                                result.resource_usage["pre_attest_frame_bytes"] = len(body)
                                startup_error_at = startup_error_at or monotonic()
                                continue  # Briefly collect bounded trusted startup diagnostics.
                            if startup_error_at is not None:
                                continue  # Never authorize a launcher which wrote startup errors.
                            attest_buffer.extend(body)
                            result.resource_usage["pre_attest_stdout_bytes"] = len(attest_buffer)
                            result.resource_usage["pre_attest_stdout_sha256"] = hashlib.sha256(attest_buffer).hexdigest()
                            if len(attest_buffer) > SUMMARY_LIMIT:
                                raise PolicyViolation("RUNTIME_ISOLATION_UNVERIFIED")
                            if b"\n" in attest_buffer:
                                line, extra = bytes(attest_buffer).split(b"\n", 1)
                                if not line.startswith(b"AGENTFORGE_ATTEST:") or extra:
                                    raise PolicyViolation("RUNTIME_ISOLATION_UNVERIFIED")
                                attestation = json.loads(line.split(b":", 1)[1])
                                # The immutable launcher runs before untrusted code;
                                # its allowlisted kernel facts are safe diagnostics.
                                result.resource_usage["attestation"] = {
                                    key: value for key, value in attestation.items() if key in ATTESTATION_FIELDS}
                                verify_attestation(attestation, limits)
                                attested = True
                                messages.put(("attested", None), timeout=1)
                            continue
                        result.resource_usage["output_bytes"] += len(body)
                        target = stdout if channel == 1 else stderr
                        # Redaction precedes summary clipping in the persistence layer.
                        # Total captured bytes remain bounded even during floods.
                        target.extend(body[:max(0, OUTPUT_LIMIT - len(target))])
                        if result.resource_usage["output_bytes"] > OUTPUT_LIMIT:
                            result.resource_usage["output_truncated"] = True
                            result.status, result.failure_reason = "output_limit", "OUTPUT_LIMIT"
                            stop.set()
                            break
                if result.failure_reason == "OUTPUT_LIMIT":
                    break
                if monotonic() - last_sample > 0.5:
                    # Metrics are best-effort sampled, not precise billing or peaks.
                    try:
                        self.sample(container, result.resource_usage)
                    except Exception:
                        pass  # Unknown measurement stays null; lifecycle checks continue.
                    container.reload()
                    last_sample = monotonic()
                    if not container.attrs.get("State", {}).get("Running"):
                        # Read buffered output until stream EOF; bounded by watchdog.
                        pass
            if startup_error_at is not None:
                raise PolicyViolation("RUNTIME_ISOLATION_UNVERIFIED")
            self.stop_container(container)
            stage = "wait"
            result.exit_code = container.wait(timeout=5).get("StatusCode")
            container.reload()
            result.resource_usage["oom_killed"] = container.attrs.get("State", {}).get("OOMKilled")
            if result.failure_reason is None:
                if not injected:
                    result.status, result.failure_reason = "failed", "LAUNCHER_FAILED"
                else:
                    result.status = "succeeded" if result.exit_code == 0 else "failed"
                    if result.exit_code == 124:
                        result.status, result.failure_reason = "timed_out", "EXECUTION_TIMEOUT"
                    if result.exit_code:
                        result.failure_reason = result.failure_reason or "CODE_EXIT_NONZERO"
        except PolicyViolation as exc:
            result.status, result.failure_reason = "failed", str(exc)
            result.resource_usage["failure_stage"], result.resource_usage["error_type"] = stage, "PolicyViolation"
            result.resource_usage["policy_error"] = str(exc)
        except Exception as exc:
            if result.failure_reason is None:
                result.status, result.failure_reason = "failed", "DOCKER_UNAVAILABLE"
            result.resource_usage["failure_stage"] = stage
            result.resource_usage["error_type"] = safe_error_type(exc)
        finally:
            if start is not None:
                result.duration_ms = int((monotonic() - start) * 1000)
            result.stdout, result.stderr = bytes(stdout), bytes(stderr)
            if attached is not None:
                try:
                    attached.close()
                except Exception:
                    pass
            if container is not None:
                try:
                    removed = self.remove(container)
                except Exception as exc:
                    removed = False
                    result.resource_usage["cleanup_error_type"] = safe_error_type(exc)
                result.cleanup_status = "removed" if removed else "unconfirmed"
                if not removed:
                    result.status, result.failure_reason = "needs_reconciliation", "CLEANUP_UNCONFIRMED"
                    try:
                        self._before('unknown', execution_id)
                    except Exception:
                        pass  # The exact ID/result remain durable for reconciliation.
            elif create_attempted:
                # Unknown create can hide a real container. No trusted ID was
                # committed, so name/label discovery cannot grant deletion rights.
                try:
                    self._before('unknown', execution_id)
                except Exception as exc:
                    result.resource_usage["cleanup_error_type"] = safe_error_type(exc)
                result.cleanup_status = 'unconfirmed'
                result.status, result.failure_reason = 'needs_reconciliation', 'CLEANUP_UNCONFIRMED'
        return result
