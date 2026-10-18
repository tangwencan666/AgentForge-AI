"""Native lifecycle v2: OS token identity and live authenticated observation.

Legacy manifests are never migrated or taken over by this module. The current
main instance remains untouched until a separately authorized deployment.
"""
import ctypes
from contextlib import contextmanager
import hashlib
import json
import os
import re
import socket
from pathlib import Path
import sys
import time
from uuid import UUID, uuid4

from lifecycle_manager import (_LegacyLifecycleManager, NativeBackend, LifecycleError,
    SAFE_ENV, ROLES, _local_path, _atomic_json, operation_lock, identity_matches)
from lifecycle_windows import process_identity, same_identity, WindowsIdentityError
from lifecycle_channel import probe, ChannelError, IDENTITY_KEYS


VERSION = 2
PUBLIC_CONFIGURATION = ("mode", "settings_path", "settings_stat", "ports", "config_digest", "policy")
FAILURE_REASONS = frozenset({'PROCESS_DISCOVERY_FAILED', 'PORT_OCCUPIED', 'RUNTIME_MISSING',
    'WINDOWS_IDENTITY_UNVERIFIED', 'START_UNCERTAIN', 'IDENTITY_MISMATCH',
    'CONTROL_CHANNEL_UNVERIFIED', 'CONTROL_CHANNEL_REQUIRED', 'CONTROL_BINDING_MISMATCH',
    'APPLICATION_NOT_READY', 'LIFECYCLE_OPERATION_FAILED'})


def configuration_digest(spec):
    """Only public configuration/metadata; never hash dotenv or Key contents."""
    return hashlib.sha256(json.dumps({key: spec[key] for key in PUBLIC_CONFIGURATION},
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def lifecycle_state(entry):
    return {"starting": "STARTING", "running": "READY_PROTECTED" if entry["protected"] else "READY_MOCK",
        "stopping": "STOPPING", "stopped": "STOPPED_PROTECTED" if entry["protected"] else "STOPPED",
        "unknown": "RECOVERY_REQUIRED"}[entry["status"]]


def actor_identity():
    try:
        value = process_identity(os.getpid())
        if value is None:
            raise WindowsIdentityError("PROCESS_IDENTITY_UNVERIFIED")
        return value
    except WindowsIdentityError:
        raise LifecycleError("WINDOWS_IDENTITY_UNVERIFIED") from None


def same_owner(first, second):
    return all(first.get(key) == second.get(key) for key in ("user_sid", "logon_sid", "session_id"))


def valid_identity(value):
    return (isinstance(value, dict) and set(value) == set(IDENTITY_KEYS)
        and all(type(value.get(key)) is int and value[key] >= (0 if key == "session_id" else 1)
                for key in ("pid", "created", "session_id"))
        and isinstance(value.get("executable"), str) and Path(value["executable"]).is_absolute()
        and all(isinstance(value.get(key), str) and re.fullmatch(r"S-1-\d+(?:-\d+)+", value[key])
                for key in ("user_sid", "logon_sid")))


def _command_arguments(command):
    """Windows argv parser, not substring authorization. Output is never logged."""
    from ctypes import wintypes
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    arguments = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not arguments:
        raise LifecycleError("CONTROLLER_IDENTITY_UNVERIFIED")
    try:
        return [arguments[index] for index in range(count.value)]
    finally:
        kernel.LocalFree(arguments)


def controller_peer(root, creator, peer):
    """Original creator or an exact fixed CLI under the same Windows logon.

The pipe itself cannot terminate a process. This check rejects ordinary client
flags and arbitrary Python commands; malicious same-user code is outside the
cooperating-script threat boundary.
"""
    if not same_owner(creator, peer) or os.path.normcase(creator["executable"]) != os.path.normcase(peer["executable"]):
        return False
    if same_identity(creator, peer):
        return True
    try:
        rows = NativeBackend._query("processes", "$rows=@(Get-CimInstance Win32_Process -Filter 'ProcessId="
            + str(int(peer["pid"])) + "' -ErrorAction Stop | Select-Object ProcessId,CommandLine)")
        if len(rows) != 1 or rows[0].get("ProcessId") != peer["pid"]:
            return False
        args = _command_arguments(rows[0]["CommandLine"])
        index = 1
        while index < len(args) and args[index] in {"-I", "-B"}:
            index += 1
        if index >= len(args) or _local_path(args[index]) != _local_path(Path(root) / "scripts/lifecycle.py"):
            return False
        # Exact CLI script, not `-c`, `-m`, substring or an executable supplied
        # through the protocol. Its parser owns the finite operation vocabulary.
        return same_identity(peer, process_identity(peer["pid"]))
    except (LifecycleError, WindowsIdentityError, KeyError, ValueError, TypeError, OSError):
        return False


class VerifiedBackend:
    """Add live proofs without replacing the reviewed Windows discovery code."""
    def __init__(self, backend):
        self.inner = backend
        self.root = backend.root
        self.is_test = getattr(backend, "is_test", False)

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _enrich(self, item):
        if item is None:
            return None
        try:
            actual = process_identity(item["pid"])
            if actual is None or any(item[key] != actual[key] for key in ("pid", "created")) or os.path.normcase(item["executable"]) != os.path.normcase(actual["executable"]):
                raise LifecycleError("IDENTITY_MISMATCH")
            if not same_owner(actor_identity(), actual):
                raise LifecycleError("WINDOWS_OWNER_MISMATCH")
            return {**item, **actual}
        except WindowsIdentityError:
            raise LifecycleError("WINDOWS_IDENTITY_UNVERIFIED") from None

    def inspect(self, pid):
        return self._enrich(self.inner.inspect(pid))

    def discover(self):
        return [self._enrich(item) for item in self.inner.discover()]

    def verify(self, entry, *, ready=False):
        # Live IPC proves role/root/generation; do not spawn a CIM subprocess
        # for every message. Kernel token + creation identity are still checked
        # on both sides of the handshake, and again on the termination handle.
        try:
            actual = process_identity(entry["pid"])
        except WindowsIdentityError:
            raise LifecycleError("WINDOWS_IDENTITY_UNVERIFIED") from None
        if not actual or not same_identity(entry, actual) or not same_owner(actor_identity(), actual):
            raise LifecycleError("IDENTITY_MISMATCH")
        if entry["role"] == "frontend":
            return None  # Node has no model credentials; OS identity remains required.
        expected = entry.get("control")
        if not isinstance(expected, dict):
            raise LifecycleError("CONTROL_CHANNEL_REQUIRED")
        binding = {"instance_id": entry["instance_id"], "generation": entry["generation"],
            "role": entry["role"], "mode": entry["mode"], "protected": entry["protected"],
            "config_digest": configuration_digest(entry)}
        if any(expected.get(key) != value for key, value in binding.items()) or not same_identity(expected, actual):
            raise LifecycleError("CONTROL_BINDING_MISMATCH")
        try:
            fresh = probe(expected, self.root, actual, timeout=5)
        except (ChannelError, WindowsIdentityError):
            raise LifecycleError("CONTROL_CHANNEL_UNVERIFIED") from None
        if any(fresh.get(key) != value for key, value in binding.items()):
            raise LifecycleError("CONTROL_BINDING_MISMATCH")
        if not same_identity(actual, process_identity(entry["pid"])):
            raise LifecycleError("IDENTITY_MISMATCH")
        if ready and fresh["state"] != ("READY_PROTECTED" if entry["protected"] else "READY_MOCK"):
            raise LifecycleError("APPLICATION_NOT_READY")
        return fresh

    def launch(self, spec):
        identity = self._enrich(self.inner.launch(spec))
        if spec["role"] == "frontend":
            return identity
        # File is only a locator. Kernel peer identity and live binding prove it.
        try:
            candidate = json.loads(_local_path(Path(spec["state_dir"]) / "ready" / (spec["instance_id"] + ".json")).read_text(encoding="utf-8"))
            identity["control"] = candidate["control"]
        except (KeyError, OSError, ValueError, TypeError):
            raise LifecycleError("CONTROL_CHANNEL_REQUIRED") from None
        self.verify({**spec, **identity})
        return identity

    def healthy(self, identity, spec):
        try:
            self.verify(identity, ready=True)
        except LifecycleError as error:
            if error.code == "APPLICATION_NOT_READY":
                return False
            raise
        if spec["role"] == "worker":
            return True  # Live authenticated application-ready state, not PID alone.
        if set(self.inner._listeners(spec["ports"][spec["role"]])) != {identity["pid"]}:
            return False
        try:
            with socket.create_connection(("127.0.0.1", spec["ports"][spec["role"]]), timeout=1):
                return True
        except OSError:
            return False

    def terminate(self, identity):
        self.verify(identity)
        self.inner.terminate(identity)  # Same held handle checks token + FILETIME.


class LifecycleManagerV2(_LegacyLifecycleManager):
    def __init__(self, root, backend=None, state_dir=None):
        native = backend or NativeBackend(_local_path(root))
        super().__init__(root, backend=VerifiedBackend(native), state_dir=state_dir)

    def _preflight_format(self):
        # Reject legacy or corrupt metadata before even creating/opening a lock
        # in an existing deployment. The inherited operation loads it again
        # under the OS lock, so this preliminary read grants no authority.
        self._load()

    def start(self, mode="mock", models_only=False, restart_models=False):
        self._preflight_format()
        return super().start(mode, models_only, restart_models)

    def stop(self, models_only=False, worker_only=False):
        self._preflight_format()
        return super().stop(models_only, worker_only)

    def restart_worker(self):
        self._preflight_format()
        return super().restart_worker()

    def status(self):
        self._preflight_format()
        return super().status()

    @contextmanager
    def maintenance_session(self):
        self._preflight_format()
        with super().maintenance_session() as state:
            yield state

    def _load(self):
        path = _local_path(self.manifest_path)
        if not path.exists():
            return {"version": VERSION, "project_root": str(self.root), "generation": 0, "entries": {}}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("version") == 1:
                raise LifecycleError("LEGACY_INSTANCE_UNVERIFIED")
            if (set(value) != {"version", "project_root", "generation", "entries"} or value["version"] != VERSION
                    or value["project_root"] != str(self.root) or type(value["generation"]) is not int or value["generation"] < 0
                    or not isinstance(value["entries"], dict) or set(value["entries"]) - set(ROLES)):
                raise ValueError
            for role, entry in value["entries"].items():
                allowed = {"root", "state_dir", "role", "mode", "protected", "instance_id", "settings_path", "settings_stat", "ports",
                    "config_digest", "policy", "status", "manager_pid", "manager_created", "pid", "created", "executable", "parent_pid",
                    "stopped_identity", "generation", "lifecycle_state", "creator", "user_sid", "logon_sid", "session_id", "control"}
                if not isinstance(entry, dict) or set(entry) - allowed or entry["role"] != role:
                    raise ValueError
                if entry["mode"] not in {"mock", "coder"} or type(entry["protected"]) is not bool or entry["protected"] != (entry["mode"] == "coder") or role == "frontend" and entry["protected"]:
                    raise ValueError
                UUID(entry["instance_id"])
                if type(entry["generation"]) is not int or entry["generation"] < 1 or entry["lifecycle_state"] != lifecycle_state(entry):
                    raise ValueError
                if entry["root"] != str(self.root) or entry["state_dir"] != str(self.directory) or entry["policy"] != SAFE_ENV:
                    raise ValueError
                settings = _local_path(entry["settings_path"])
                if not settings.is_relative_to(self.root) or settings.name != ".env":
                    raise ValueError
                if set(entry["settings_stat"]) != {"size", "mtime_ns", "inode"} or any(type(v) is not int or v < 0 for v in entry["settings_stat"].values()):
                    raise ValueError
                if set(entry["ports"]) != {"backend", "frontend"} or len(set(entry["ports"].values())) != 2 or any(type(v) is not int or not 1024 <= v <= 65535 for v in entry["ports"].values()):
                    raise ValueError
                if entry["config_digest"] is not None and (not isinstance(entry["config_digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["config_digest"])):
                    raise ValueError
                creator = entry["creator"]
                if not valid_identity(creator) or creator["pid"] != entry["manager_pid"] or creator["created"] != entry["manager_created"]:
                    raise ValueError
                if entry["status"] == "running" and not valid_identity({key: entry.get(key) for key in IDENTITY_KEYS}):
                    raise ValueError
                if entry["status"] == "running" and role != "frontend" and not isinstance(entry.get("control"), dict):
                    raise ValueError
                if "parent_pid" in entry and (type(entry["parent_pid"]) is not int or entry["parent_pid"] < 0):
                    raise ValueError
                if "stopped_identity" in entry:
                    stopped = entry["stopped_identity"]
                    if (not isinstance(stopped, dict) or set(stopped) != {"pid", "created", "executable"}
                            or type(stopped["pid"]) is not int or stopped["pid"] < 1
                            or type(stopped["created"]) is not int or stopped["created"] < 1
                            or not isinstance(stopped["executable"], str) or not Path(stopped["executable"]).is_absolute()):
                        raise ValueError
                if not same_owner(creator, actor_identity()):
                    raise LifecycleError("WINDOWS_OWNER_MISMATCH")
            return value
        except (KeyError, TypeError, ValueError, AttributeError, OSError):
            raise LifecycleError("MANIFEST_INVALID") from None

    def _save(self, manifest):
        if manifest["version"] != VERSION:
            raise LifecycleError("LEGACY_INSTANCE_UNVERIFIED")
        for entry in manifest["entries"].values():
            entry["lifecycle_state"] = lifecycle_state(entry)
        super()._save(manifest)

    def _spec(self, role, mode, instance=None):
        return {**super()._spec(role, mode, instance), "generation": self._load()["generation"] + 1,
            "creator": actor_identity()}

    def _check(self, manifest):
        if manifest["version"] != VERSION:
            raise LifecycleError("LEGACY_INSTANCE_UNVERIFIED")
        known = super()._check(manifest)
        for entry in known.values():
            self.backend.verify(entry, ready=True)
        return known

    def _start_roles(self, manifest, roles, mode):
        # The core persists intent before launch. Wrap launch to carry verified
        # native/IPC identity into the entry before its health check is evaluated.
        for role in roles:
            spec = self._spec(role, mode)
            previous = manifest["entries"].get(role)
            if previous and previous["status"] == "running" and self.backend.inspect(previous["pid"]) is not None:
                if not self._same_configuration(previous, spec) or not self.backend.healthy(previous, spec):
                    raise LifecycleError("CONFIGURATION_MISMATCH")
                continue
            if previous and previous["protected"] and previous["status"] != "stopped":
                raise LifecycleError("PROTECTED_INSTANCE")
            actor = spec["creator"]
            intent = {**spec, "status": "starting", "lifecycle_state": "STARTING", "manager_pid": actor["pid"], "manager_created": actor["created"]}
            self._audit("start_intent", [intent])
            manifest["entries"][role] = intent
            self._save(manifest)
            try:
                identity = self.backend.launch(spec)
                if identity.get("role") != role or identity.get("instance_id") != spec["instance_id"]:
                    raise LifecycleError("IDENTITY_MISMATCH")
                intent.update({key: identity[key] for key in (*IDENTITY_KEYS, "parent_pid", "control") if key in identity})
                deadline = time.monotonic() + 30
                while not self.backend.healthy(intent, spec):
                    if time.monotonic() >= deadline:
                        raise LifecycleError("APPLICATION_NOT_READY")
                    time.sleep(.1)
                intent["status"] = "running"
                self._save(manifest)
                self._audit("ready", [intent])
            except Exception as error:
                # Unverified channel/identity => preserve evidence, never discover
                # and kill a candidate. A verified partial launch may be cleaned.
                if intent.get("pid"):
                    try:
                        self.backend.verify(intent)
                        self._audit("failed_start_cleanup", [intent])
                        self.backend.terminate(intent)
                        intent["status"] = "stopped"
                    except Exception:
                        intent["status"] = "unknown"
                else:
                    intent["status"] = "unknown"
                self._save(manifest)
                reason = error.code if isinstance(error, LifecycleError) and error.code in FAILURE_REASONS else 'LIFECYCLE_OPERATION_FAILED'
                self._audit('start_failed', [intent], reason=reason)
                raise LifecycleError("START_UNCERTAIN") from None

    def _stop_entries(self, manifest, entries, approval=None):
        for entry in entries:
            if entry.get("pid") and self.backend.inspect(entry["pid"]) is not None:
                self.backend.verify(entry)
        return super()._stop_entries(manifest, entries, approval)

    def _manual_candidates(self, manifest, roles):
        entries = super()._manual_candidates(manifest, roles)
        for entry in entries:
            if entry.get("pid") and self.backend.inspect(entry["pid"]) is not None:
                # Recovery of a recorded intent uses its locator, followed by live
                # OS-authenticated proof. UUID alone never grants termination.
                if not entry.get("control"):
                    try:
                        location = _local_path(self.directory / "ready" / (entry["instance_id"] + ".json"))
                        entry["control"] = json.loads(location.read_text(encoding="utf-8"))["control"]
                    except (OSError, ValueError, KeyError):
                        raise LifecycleError("CONTROL_CHANNEL_REQUIRED") from None
                actual = self.backend.inspect(entry["pid"])
                if actual is None:
                    raise LifecycleError("IDENTITY_MISMATCH")
                entry.update({key: actual[key] for key in IDENTITY_KEYS})
                self.backend.verify(entry)
        return entries

    def _audit(self, action, entries, approval=None, reason=None):
        self.directory.mkdir(parents=True, exist_ok=True)
        record = {"event_id": str(uuid4()), "time": time.time(), "action": action, "actor": actor_identity(),
            "instances": [{key: entry.get(key) for key in ("role", "instance_id", "generation", "pid", "created", "protected", "lifecycle_state")} for entry in entries]}
        if approval:
            record["approval_id"] = approval
        if reason is not None:
            if reason not in FAILURE_REASONS:
                raise LifecycleError('AUDIT_UNAVAILABLE')
            record['reason'] = reason
        try:
            with _local_path(self.directory / "audit.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            raise LifecycleError("AUDIT_UNAVAILABLE") from None

    def manual_stop(self, confirmation=None, models_only=True):
        self._preflight_format()
        if not self.backend.is_test and (not sys.stdin.isatty() or confirmation is not None):
            raise LifecycleError("APPROVAL_REQUIRED")
        with operation_lock(self.directory):
            state = self._load()
            roles = {"backend", "worker"} if models_only else set(ROLES)
            entries = self._manual_candidates(state, roles)
            if not entries:
                return state
            scope = {"action": "stop", "state_dir": str(self.directory), "generation": state["generation"],
                "instances": [{key: entry.get(key) for key in ("role", "instance_id", "generation", "pid", "created", "status")} for entry in entries],
                "actor": actor_identity(), "approval_id": str(uuid4()), "expires_at": time.time() + 60}
            directory = _local_path(self.directory / "approvals")
            directory.mkdir(exist_ok=True)
            path = _local_path(directory / (scope["approval_id"] + ".json"))
            _atomic_json(path, {**scope, "status": "ISSUED"})
            self._audit("maintenance_issued", entries, scope["approval_id"])
            challenge = "STOP " + scope["approval_id"]
            started = time.monotonic()
            if confirmation is not None:
                answer = confirmation({**scope, "challenge": challenge})
            else:
                print(json.dumps(scope, sort_keys=True))
                answer = input("Type exactly " + challenge + " within 60 seconds: ")
            if answer != challenge or time.monotonic() - started > 60 or time.time() > scope["expires_at"]:
                _atomic_json(path, {**scope, "status": "EXPIRED"})
                self._audit("maintenance_rejected", entries, scope["approval_id"])
                raise LifecycleError("APPROVAL_REQUIRED")
            # Only this in-memory scope can consume the durable record. No load-
            # approval-ID CLI exists; editing a JSON record creates no authority.
            persisted = json.loads(path.read_text(encoding="utf-8"))
            refreshed = self._load()
            verified = self._manual_candidates(refreshed, roles)
            if (persisted != {**scope, "status": "ISSUED"} or state != refreshed or entries != verified
                    or not same_identity(scope["actor"], actor_identity())):
                raise LifecycleError("MAINTENANCE_STATE_CHANGED")
            # Native identity/IPC reconciliation can take time. Authority must
            # still be live after those checks, at the consumption boundary.
            if time.monotonic() - started > 60 or time.time() > scope['expires_at']:
                _atomic_json(path, {**scope, 'status': 'EXPIRED'})
                self._audit('maintenance_rejected', entries, scope['approval_id'])
                raise LifecycleError('APPROVAL_REQUIRED')
            _atomic_json(path, {**scope, "status": "CONSUMED", "consumed_at": time.time()})
            self._audit("maintenance_consumed", entries, scope["approval_id"])
            for entry in verified:
                state["entries"][entry["role"]] = entry
            self._stop_entries(state, verified, scope["approval_id"])
            return state
