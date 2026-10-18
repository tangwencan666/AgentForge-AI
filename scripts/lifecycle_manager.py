"""Project-local lifecycle control. Protects cooperating launchers, not Windows admins.

No model credential values are accessed. Real subprocesses inherit their parent's
environment natively. Every supported launcher must use this manager.
"""
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
from uuid import UUID, uuid4


VERSION = 1
ROLES = ("backend", "worker", "frontend")
MODEL_NAMES = frozenset("AGENTFORGE_MODEL_" + role + "_KEY" for role in ("CODER", "PLANNER", "RESEARCHER", "REVIEWER"))
NON_CREDENTIAL_MODEL_NAMES = frozenset({"AGENTFORGE_MODEL_PRICES", "AGENTFORGE_MODEL_CREDENTIAL_HOSTS", "AGENTFORGE_MODEL_CREDENTIALS_ENV_ONLY"})
ISSUER_NAME = "AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN"
SAFE_ENV = {
    "AGENTFORGE_REAL_CALLS_ENABLED": "false", "AGENTFORGE_SINGLE_USE_PERMITS_ENABLED": "false",
    "AGENTFORGE_REAL_WORKER_MODE": "deny", "AGENTFORGE_REAL_DAILY_BUDGET_USD": "0",
    "AGENTFORGE_REAL_TEST_BUDGET_USD": "0", "AGENTFORGE_REAL_MAX_RETRIES": "0",
    "AGENTFORGE_MODEL_CREDENTIALS_ENV_ONLY": "true", "AGENTFORGE_EXTERNAL_MODELS_BLOCKED": "1",
    "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false",
}
_LOCK_OWNERS = {}
_LOCK_OWNERS_GUARD = threading.Lock()
_MAINTENANCE_OWNERS = {}
QUERY_OS_NAMES = ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP",
    "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")


class LifecycleError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _local_path(path):
    """Reject reparse points before resolution, including existing ancestors."""
    result = Path(os.path.abspath(path))
    for component in (*reversed(result.parents), result):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        if component.is_symlink() or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise LifecycleError("REPARSE_PATH_FORBIDDEN")
    return result


def _atomic_json(path, value):
    """The lock file is separate and is never replaced or unlinked."""
    path = _local_path(path)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def credential_names():
    """Iterate names only; never call environ.items/copy or read model values."""
    return frozenset(name for name in os.environ if (name.startswith("AGENTFORGE_MODEL_") and name not in NON_CREDENTIAL_MODEL_NAMES) or name == ISSUER_NAME)


def check_environment(mode):
    names = credential_names()
    if mode == "mock":
        if names:
            raise LifecycleError("MODEL_CREDENTIALS_FORBIDDEN")
    elif mode == "coder":
        if "AGENTFORGE_MODEL_CODER_KEY" not in names:
            raise LifecycleError("CODER_CREDENTIAL_REQUIRED")
        if names - {"AGENTFORGE_MODEL_CODER_KEY"}:
            raise LifecycleError("MODEL_CREDENTIALS_FORBIDDEN")
    else:
        raise LifecycleError("MODE_INVALID")


@contextmanager
def operation_lock(directory):
    directory = _local_path(directory)
    key = os.path.normcase(str(directory))
    owner = (os.getpid(), threading.get_ident())
    with _LOCK_OWNERS_GUARD:
        previous = _LOCK_OWNERS.get(key)
        if previous:
            if previous["owner"] != owner or not previous["acquired"]:
                raise LifecycleError("LOCK_BUSY")
            previous["depth"] += 1
        else:
            _LOCK_OWNERS[key] = {"owner": owner, "depth": 1, "acquired": False}
    if previous:
        try:
            yield
        finally:
            with _LOCK_OWNERS_GUARD:
                _LOCK_OWNERS[key]["depth"] -= 1
        return
    descriptor = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # O_CREAT without O_TRUNC, stable inode; crash/handle close releases OS lock.
        descriptor = os.open(_local_path(directory / "operation.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        if os.name == "nt":
            import msvcrt
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError:
                raise LifecycleError("LOCK_BUSY") from None
        else:
            import fcntl
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise LifecycleError("LOCK_BUSY") from None
        with _LOCK_OWNERS_GUARD:
            _LOCK_OWNERS[key]["acquired"] = True
        try:
            yield
        finally:
            if os.name == "nt":
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        # Close releases a lock even if explicit unlock failed. Never expose a
        # pending/failed lock as a reentrant owner.
        with _LOCK_OWNERS_GUARD:
            _LOCK_OWNERS[key]["acquired"] = False
        if descriptor is not None:
            os.close(descriptor)
        with _LOCK_OWNERS_GUARD:
            _LOCK_OWNERS.pop(key, None)


def _win32():
    if os.name != "nt":
        raise LifecycleError("PLATFORM_UNSUPPORTED")
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel, wintypes


def process_facts(pid):
    """Immutable OS creation identity; no environment or process-memory access."""
    kernel, types = _win32()
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return None
        raise LifecycleError("PROCESS_QUERY_FAILED")
    try:
        wait = kernel.WaitForSingleObject(handle, 0)
        if wait == 0:
            return None
        if wait != 258:
            raise LifecycleError("PROCESS_QUERY_FAILED")
        created, exited, cpu_kernel, cpu_user = (types.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(cpu_kernel), ctypes.byref(cpu_user)):
            raise LifecycleError("PROCESS_QUERY_FAILED")
        size = types.DWORD(32768)
        name = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
            raise LifecycleError("PROCESS_QUERY_FAILED")
        return {"pid": int(pid), "created": (created.dwHighDateTime << 32) | created.dwLowDateTime,
                "executable": name.value}
    finally:
        kernel.CloseHandle(handle)


def identity_matches(saved, observed):
    return bool(observed and saved["pid"] == observed["pid"] and saved["created"] == observed["created"]
        and os.path.normcase(saved["executable"]) == os.path.normcase(observed["executable"])
        and saved["instance_id"] == observed.get("instance_id") and saved["role"] == observed.get("role"))


class NativeBackend:
    is_test = False

    def __init__(self, root):
        self.root = Path(root)
        self.python_executable = self.root / ".venv/Scripts/python.exe"

    @staticmethod
    def _query(kind, body):
        """Accept an explicit, complete query success, never absence of errors.

        A PowerShell non-terminating error otherwise lets ConvertTo-Json return
        an apparently successful empty result. Empty stdout and stderr output
        are also failures; raw diagnostics never leave this boundary.
        """
        if kind not in {"processes", "listeners"}:
            raise LifecycleError("PROCESS_DISCOVERY_FAILED")
        command = ("$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; "
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); $Error.Clear(); try { "
            + body + "; if ($Error.Count -ne 0) { exit 3 }; "
            + "$envelope=[ordered]@{version=1;query='" + kind + "';success=$true;rows=@($rows)}; "
            "ConvertTo-Json -InputObject $envelope -Depth 5 -Compress -ErrorAction Stop; exit 0 "
            "} catch { exit 3 }")
        try:
            # Queries need OS runtime configuration only. Never inherit or read
            # model credentials, issuer authority or service configuration.
            environment = {name: os.environ[name] for name in QUERY_OS_NAMES if name in os.environ}
            result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="strict",
                env=environment, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if (type(result.returncode) is not int or result.returncode != 0 or not isinstance(result.stderr, str)
                    or result.stderr != "" or not isinstance(result.stdout, str) or not result.stdout.strip()):
                raise LifecycleError("PROCESS_DISCOVERY_FAILED")
            envelope = json.loads(result.stdout)
            if (not isinstance(envelope, dict) or set(envelope) != {"version", "query", "success", "rows"}
                    or type(envelope["version"]) is not int or envelope["version"] != 1
                    or envelope["query"] != kind or envelope["success"] is not True or not isinstance(envelope["rows"], list)):
                raise LifecycleError("PROCESS_DISCOVERY_FAILED")
            return envelope["rows"]
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, TypeError):
            raise LifecycleError("PROCESS_DISCOVERY_FAILED") from None

    def _rows(self):
        # Query command lines only for project-owned executables/modules. Never
        # inspect environment blocks or emit command lines to the calling user.
        bootstrap = str(self.root / "scripts/managed_service.py").replace("'", "''")
        venv = str(self.root / ".venv/Scripts/python.exe").replace("'", "''")
        vite = str(self.root / "frontend/node_modules/vite/bin/vite.js").replace("'", "''")
        query = ("$b='" + bootstrap + "'; $v='" + venv + "'; $f='" + vite + "'; "
            "$candidates=@(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $_.Name -in @('python.exe','node.exe') }); "
            "foreach ($candidate in $candidates) { if ([string]::IsNullOrWhiteSpace($candidate.ExecutablePath) -or "
            "[string]::IsNullOrWhiteSpace($candidate.CommandLine) -or $null -eq $candidate.CreationDate) "
            "{ throw 'CandidateMetadataUnavailable' } }; $rows=@($candidates | Where-Object { "
            "$_.Name -in @('python.exe','node.exe') -and ((($_.ExecutablePath -eq $v) -and (-not $_.CommandLine)) -or ($_.CommandLine -and ("
            "$_.CommandLine.IndexOf($b,[StringComparison]::OrdinalIgnoreCase) -ge 0 -or "
            "$_.CommandLine.IndexOf($f,[StringComparison]::OrdinalIgnoreCase) -ge 0 -or "
            "(($_.CommandLine.IndexOf($v,[StringComparison]::OrdinalIgnoreCase) -ge 0) -and "
            "($_.CommandLine -match 'app.workers.main|app.main:create_app')))))"
            "} | ForEach-Object { if ($null -eq $_.CreationDate) { throw 'CreationIdentityUnavailable' }; "
            "[ordered]@{ProcessId=[int]$_.ProcessId;ParentProcessId=[int]$_.ParentProcessId;"
            "ExecutablePath=$_.ExecutablePath;CommandLine=$_.CommandLine;CreationFileTime=$_.CreationDate.ToFileTimeUtc()} })")
        rows = self._query("processes", query)
        seen = set()
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {"ProcessId", "ParentProcessId", "ExecutablePath", "CommandLine", "CreationFileTime"}
                    or type(row["ProcessId"]) is not int or row["ProcessId"] <= 0 or row["ProcessId"] in seen
                    or type(row["ParentProcessId"]) is not int or row["ParentProcessId"] < 0
                    or type(row["CreationFileTime"]) is not int or row["CreationFileTime"] <= 0
                    or not isinstance(row["ExecutablePath"], str) or not row["ExecutablePath"]
                    or not isinstance(row["CommandLine"], str) or not row["CommandLine"]):
                raise LifecycleError("PROCESS_DISCOVERY_FAILED")
            seen.add(row["ProcessId"])
        return rows

    def _identity(self, row):
        before = process_facts(row["ProcessId"])
        if before is None:
            return None
        # CIM's DMTF timestamp is quantized to microseconds. Keep raw 100ns
        # equality between the two OS reads, and compare CIM at its precision.
        if (before["created"] // 10 != row["CreationFileTime"] // 10
                or os.path.normcase(before["executable"]) != os.path.normcase(row["ExecutablePath"])):
            raise LifecycleError("IDENTITY_MISMATCH")
        facts = process_facts(row["ProcessId"])
        if facts is None:
            return None
        if (facts["pid"] != before["pid"] or facts["created"] != before["created"]
                or os.path.normcase(facts["executable"]) != os.path.normcase(before["executable"])):
            raise LifecycleError("IDENTITY_MISMATCH")
        command = row.get("CommandLine") or ""
        instance = re.search(r"--instance-id\s+([0-9a-f-]{36})(?:\s|$)", command)
        role = re.search(r"--role\s+(backend|worker|frontend)(?:\s|$)", command)
        frontend = re.search(r"--title=agentforge-frontend-([0-9a-f-]{36})(?:\s|$)", command)
        return {**facts, "command_line": command, "instance_id": instance.group(1) if instance else "",
                "role": role.group(1) if role else "frontend" if frontend else "legacy",
                "parent_pid": int(row.get("ParentProcessId") or 0)} | ({"instance_id": frontend.group(1)} if frontend else {})

    def discover(self):
        identities = [identity for row in self._rows() if (identity := self._identity(row)) is not None]
        # Windows venv forwarding executable remains alive while its actual base
        # Python child runs. Exclude only a proven same-instance forwarding parent.
        venv = os.path.normcase(str(self.python_executable))
        return [item for item in identities if not (os.path.normcase(item["executable"]) == venv
            and item["instance_id"] and any(child["parent_pid"] == item["pid"]
                and child["created"] >= item["created"] and child["instance_id"] == item["instance_id"]
                and child["role"] == item["role"] for child in identities))]

    def inspect(self, pid):
        for row in self._rows():
            if int(row["ProcessId"]) == int(pid):
                return self._identity(row)
        if process_facts(pid) is not None:
            # A live PID absent from this query cannot be declared dead. This
            # includes partial/withheld metadata and a PID reused by another app.
            raise LifecycleError("PROCESS_IDENTITY_UNVERIFIED")
        return None

    def launch(self, spec):
        ready = _local_path(Path(spec["state_dir"]) / "ready" / (spec["instance_id"] + ".json"))
        ready.parent.mkdir(parents=True, exist_ok=True)
        python = Path(self.python_executable)
        if not python.is_file():
            raise LifecycleError("RUNTIME_MISSING")
        argv = [str(python), "-I", str(self.root / "scripts/managed_service.py"),
                "--instance-id", spec["instance_id"], "--role", spec["role"], "--mode", spec["mode"],
                "--state-dir", spec["state_dir"], "--settings-path", spec["settings_path"],
                "--port", str(spec["ports"].get(spec["role"], 0))]
        if "generation" in spec:
            argv.extend(("--generation", str(spec["generation"])))
        if spec["role"] == "frontend":
            vite = self.root / "frontend/node_modules/vite/bin/vite.js"
            if not vite.is_file():
                raise LifecycleError("RUNTIME_MISSING")
            argv = ["node", "--title=agentforge-frontend-" + spec["instance_id"], str(vite),
                "--host", "127.0.0.1", "--port", str(spec["ports"]["frontend"]), "--strictPort"]
        if spec["role"] in {"backend", "frontend"} and self._listeners(spec["ports"][spec["role"]]):
            raise LifecycleError("PORT_OCCUPIED")
        logs = _local_path(Path(spec["state_dir"]) / "logs")
        logs.mkdir(exist_ok=True)
        # No env=dict/copy: Windows inherits the parent's environment natively.
        with _local_path(logs / (spec["instance_id"] + ".log")).open("ab") as out:
            child = subprocess.Popen(argv, cwd=self.root / "frontend" if spec["role"] == "frontend" else self.root, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                env=None, close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        launcher = process_facts(child.pid)
        if launcher is None:
            raise LifecycleError("START_UNCERTAIN")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if spec["role"] == "frontend":
                observed = self.inspect(child.pid)
                if observed and observed["instance_id"] == spec["instance_id"] and observed["role"] == "frontend":
                    return observed
            if ready.exists():
                try:
                    claim = json.loads(ready.read_text(encoding="utf-8"))
                    observed = self.inspect(claim["pid"])
                    if claim.get("instance_id") == spec["instance_id"] and identity_matches(claim, observed):
                        # Bind the handshake to the Popen process or its proven
                        # Windows venv forwarding child, never a matching UUID alone.
                        if observed["pid"] == launcher["pid"]:
                            if observed["created"] != launcher["created"]:
                                raise LifecycleError("IDENTITY_MISMATCH")
                        else:
                            current_parent = process_facts(launcher["pid"])
                            if (observed.get("parent_pid") != launcher["pid"] or not current_parent
                                    or current_parent["created"] != launcher["created"]):
                                raise LifecycleError("IDENTITY_MISMATCH")
                        return observed
                except (ValueError, KeyError, OSError):
                    raise LifecycleError("START_UNCERTAIN") from None
            if child.poll() is not None:
                break
            time.sleep(0.1)
        raise LifecycleError("START_UNCERTAIN")

    def terminate(self, identity):
        kernel, types = _win32()
        handle = kernel.OpenProcess(0x1000 | 0x100000 | 0x1, False, identity["pid"])
        if not handle:
            if ctypes.get_last_error() == 87:
                return
            raise LifecycleError("STOP_UNCERTAIN")
        try:
            created, exited, cpu_kernel, cpu_user = (types.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(cpu_kernel), ctypes.byref(cpu_user)):
                raise LifecycleError("STOP_UNCERTAIN")
            actual = (created.dwHighDateTime << 32) | created.dwLowDateTime
            if actual != identity["created"]:
                raise LifecycleError("IDENTITY_MISMATCH")
            size = types.DWORD(32768)
            executable = ctypes.create_unicode_buffer(size.value)
            if not kernel.QueryFullProcessImageNameW(handle, 0, executable, ctypes.byref(size)):
                raise LifecycleError("STOP_UNCERTAIN")
            if os.path.normcase(executable.value) != os.path.normcase(identity["executable"]):
                raise LifecycleError("IDENTITY_MISMATCH")
            if "user_sid" in identity:
                # The v2 manager supplies token identity. Verify on this SAME
                # termination handle, not on a second PID lookup.
                from lifecycle_windows import identity_from_handle, same_identity
                current = identity_from_handle(handle)
                if not same_identity(identity, current):
                    raise LifecycleError("IDENTITY_MISMATCH")
            if kernel.WaitForSingleObject(handle, 0) != 0:
                if not kernel.TerminateProcess(handle, 125):
                    if kernel.WaitForSingleObject(handle, 0) != 0:
                        raise LifecycleError("STOP_UNCERTAIN")
                if kernel.WaitForSingleObject(handle, 10000) != 0:
                    raise LifecycleError("STOP_UNCERTAIN")
        finally:
            kernel.CloseHandle(handle)

    def healthy(self, identity, spec):
        if not identity_matches(identity, self.inspect(identity["pid"])):
            return False
        if spec["role"] == "worker":
            return True  # Identity/liveness, not a claim of DB/model readiness.
        port = spec["ports"][spec["role"]]
        if set(self._listeners(port)) != {identity["pid"]}:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            return False

    def _listeners(self, port):
        # Query the table successfully before filtering. Asking the cmdlet for
        # an unused LocalPort can itself produce a NoMatch error.
        command = ("$rows=@(Get-NetTCPConnection -ErrorAction Stop | Where-Object { "
            "$_.State -eq 'Listen' -and $_.LocalPort -eq " + str(int(port))
            + " } | Select-Object -ExpandProperty OwningProcess)")
        pids = self._query("listeners", command)
        if any(type(pid) is not int or pid <= 0 for pid in pids):
            raise LifecycleError("PROCESS_DISCOVERY_FAILED")
        return pids


class LifecycleManager:
    def __init__(self, root, backend=None, state_dir=None):
        self.root = _local_path(root)
        self.backend = backend or NativeBackend(self.root)
        self.directory = _local_path(state_dir if state_dir else self.root / "work/lifecycle")
        if not self.directory.is_relative_to(self.root):
            raise LifecycleError("STATE_DIRECTORY_FORBIDDEN")
        if not getattr(self.backend, "is_test", False) and self.directory != self.root / "work/lifecycle":
            raise LifecycleError("STATE_DIRECTORY_FORBIDDEN")
        self.manifest_path = self.directory / "manifest.json"

    def _load(self):
        path = _local_path(self.manifest_path)
        if not path.exists():
            return {"version": VERSION, "project_root": str(self.root), "generation": 0, "entries": {}}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if set(value) != {"version", "project_root", "generation", "entries"}:
                raise ValueError
            if value["version"] != VERSION or Path(value["project_root"]).resolve() != self.root or type(value["generation"]) is not int:
                raise ValueError
            entries = value["entries"]
            if not isinstance(entries, dict) or set(entries) - set(ROLES):
                raise ValueError
            for role, entry in entries.items():
                allowed = {"root", "state_dir", "role", "mode", "protected", "instance_id", "settings_path", "settings_stat", "ports",
                    "config_digest", "policy", "status", "manager_pid", "manager_created", "pid", "created", "executable", "parent_pid", "stopped_identity"}
                if not isinstance(entry, dict) or set(entry) - allowed:
                    raise ValueError
                if (entry["role"] != role or entry["mode"] not in {"mock", "coder"} or type(entry["protected"]) is not bool
                        or entry["protected"] != (entry["mode"] == "coder") or entry["protected"] and role == "frontend"):
                    raise ValueError
                UUID(entry["instance_id"])
                if entry["root"] != str(self.root) or entry["state_dir"] != str(self.directory) or entry["policy"] != SAFE_ENV:
                    raise ValueError
                settings = _local_path(entry["settings_path"])
                if not settings.is_relative_to(self.root) or settings.name != ".env":
                    raise ValueError
                if (set(entry["settings_stat"]) != {"size", "mtime_ns", "inode"}
                        or any(type(number) is not int or number < 0 for number in entry["settings_stat"].values())):
                    raise ValueError
                if (set(entry["ports"]) != {"backend", "frontend"} or len(set(entry["ports"].values())) != 2
                        or any(type(port) is not int or not 1024 <= port <= 65535 for port in entry["ports"].values())):
                    raise ValueError
                if entry["config_digest"] is not None and not re.fullmatch("[0-9a-f]{64}", entry["config_digest"]):
                    raise ValueError
                if type(entry["manager_pid"]) is not int or type(entry["manager_created"]) is not int:
                    raise ValueError
                if entry["status"] not in {"starting", "running", "stopping", "stopped", "unknown"}:
                    raise ValueError
                if entry["status"] == "running" and (type(entry["pid"]) is not int or type(entry["created"]) is not int or not isinstance(entry["executable"], str)):
                    raise ValueError
                if "stopped_identity" in entry and (set(entry["stopped_identity"]) != {"pid", "created", "executable"}
                        or type(entry["stopped_identity"]["pid"]) is not int or type(entry["stopped_identity"]["created"]) is not int
                        or not isinstance(entry["stopped_identity"]["executable"], str)):
                    raise ValueError
            return value
        except (ValueError, KeyError, TypeError, OSError):
            raise LifecycleError("MANIFEST_INVALID") from None

    def _save(self, manifest):
        manifest["generation"] += 1
        _atomic_json(self.manifest_path, manifest)

    def _audit(self, action, entries, approval=None):
        self.directory.mkdir(parents=True, exist_ok=True)
        record = {"event_id": str(uuid4()), "time": time.time(), "action": action,
            "instances": [{key: entry.get(key) for key in ("role", "instance_id", "pid", "created", "protected")} for entry in entries]}
        if approval:
            record["approval_id"] = approval
        try:
            with _local_path(self.directory / "audit.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            raise LifecycleError("AUDIT_UNAVAILABLE") from None

    def _check(self, manifest):
        known = {}
        for entry in manifest["entries"].values():
            if entry["status"] in {"starting", "stopping", "unknown"}:
                raise LifecycleError("START_UNCERTAIN")
            if entry["status"] == "running":
                observed = self.backend.inspect(entry["pid"])
                if observed is not None and not identity_matches(entry, observed):
                    raise LifecycleError("IDENTITY_MISMATCH")
                if observed:
                    known[entry["pid"]] = entry
        for observed in self.backend.discover():
            if observed["pid"] not in known or not identity_matches(known[observed["pid"]], observed):
                raise LifecycleError("UNMANAGED_PROCESS")
        return known

    def _spec(self, role, mode, instance=None):
        settings = os.environ.get("AGENTFORGE_SETTINGS_FILE")
        if not settings:
            settings = self.root / ("work/p5-live-preflight/.env" if mode == "coder" else ".env")
        settings = _local_path(settings)
        if not settings.is_relative_to(self.root) or settings.name != ".env" or not settings.is_file():
            raise LifecycleError("SETTINGS_INVALID")
        try:
            ports = getattr(self.backend, "ports", None) or {"backend": int(os.environ.get("BACKEND_PORT", "18100")),
                "frontend": int(os.environ.get("FRONTEND_PORT", "15173"))}
            if set(ports) != {"backend", "frontend"} or any(type(port) is not int or not 1024 <= port <= 65535 for port in ports.values()) or len(set(ports.values())) != 2:
                raise ValueError
        except (ValueError, TypeError):
            raise LifecycleError("SETTINGS_INVALID") from None
        config = _local_path(self.root / "config/deepseek-coder-local.json")
        digest = hashlib.sha256(config.read_bytes()).hexdigest() if mode == "coder" and config.exists() else None
        metadata = settings.stat()
        return {"root": str(self.root), "state_dir": str(self.directory), "role": role, "mode": mode,
            "protected": mode == "coder", "instance_id": instance or str(uuid4()), "settings_path": str(settings),
            "settings_stat": {"size": metadata.st_size, "mtime_ns": metadata.st_mtime_ns, "inode": metadata.st_ino},
            "ports": ports, "config_digest": digest, "policy": dict(SAFE_ENV)}

    @staticmethod
    def _same_configuration(entry, spec):
        return all(entry.get(key) == spec.get(key) for key in ("mode", "settings_path", "settings_stat", "ports", "config_digest", "policy"))

    def _stop_entries(self, manifest, entries, approval=None):
        if not entries:
            return
        self._audit("manual_stop" if approval else "stop", entries, approval)
        for entry in entries:
            entry["status"] = "stopping"
        self._save(manifest)
        for entry in entries:
            try:
                observed = self.backend.inspect(entry["pid"]) if entry.get("pid") else None
                if observed is not None:
                    if not identity_matches(entry, observed):
                        raise LifecycleError("IDENTITY_MISMATCH")
                    self.backend.terminate(entry)
            except Exception:
                entry["status"] = "unknown"
                self._save(manifest)
                raise LifecycleError("STOP_UNCERTAIN") from None
            entry["status"] = "stopped"
            if entry.get("pid"):
                entry["stopped_identity"] = {key: entry[key] for key in ("pid", "created", "executable")}
            for key in ("pid", "created", "executable", "command_line", "parent_pid"):
                entry.pop(key, None)
            self._save(manifest)

    def _start_roles(self, manifest, roles, mode):
        for role in roles:
            spec = self._spec(role, mode)
            previous = manifest["entries"].get(role)
            if previous and previous["status"] == "running" and self.backend.inspect(previous["pid"]) is not None:
                if not self._same_configuration(previous, spec) or not self.backend.healthy(previous, spec):
                    raise LifecycleError("CONFIGURATION_MISMATCH")
                continue
            # A protected prior instance does not lose protection merely because it
            # is down. Explicit manual acknowledgement is required before replacing.
            if previous and previous["protected"] and previous["status"] != "stopped":
                raise LifecycleError("PROTECTED_INSTANCE")
            intent = {**spec, "status": "starting", "manager_pid": os.getpid(), "manager_created": process_facts(os.getpid())["created"] if os.name == "nt" else None}
            self._audit("start_intent", [intent])
            manifest["entries"][role] = intent
            self._save(manifest)
            try:
                identity = self.backend.launch(spec)
                if identity.get("role") != role or identity.get("instance_id") != spec["instance_id"] or not identity_matches(identity, self.backend.inspect(identity["pid"])):
                    raise LifecycleError("IDENTITY_MISMATCH")
                intent.update({key: identity[key] for key in ("pid", "created", "executable", "parent_pid") if key in identity})
                intent["status"] = "running"
                self._save(manifest)
                deadline = time.monotonic() + 15
                while not self.backend.healthy(intent, spec):
                    if time.monotonic() >= deadline:
                        raise LifecycleError("HEALTH_CHECK_FAILED")
                    time.sleep(0.1)
            except Exception:
                # No adopting/discover-and-kill after an uncertain launch. Cleanup
                # is restricted to the exact identity returned by this launch.
                if intent.get("pid") and identity_matches(intent, self.backend.inspect(intent["pid"])):
                    try:
                        self._audit("failed_start_cleanup", [intent])
                        self.backend.terminate(intent)
                        intent["status"] = "stopped"
                    except Exception:
                        intent["status"] = "unknown"
                else:
                    intent["status"] = "unknown"
                self._save(manifest)
                raise LifecycleError("START_UNCERTAIN") from None

    def _start_scope(self, manifest, roles, mode):
        previous = {entry["instance_id"] for entry in manifest["entries"].values()}
        try:
            self._start_roles(manifest, roles, mode)
        except Exception:
            # Roll back only identities newly confirmed by this invocation.
            # Unknown launches remain blocked for explicit human reconciliation.
            created = [entry for entry in manifest["entries"].values()
                       if entry["instance_id"] not in previous and entry["status"] == "running"]
            try:
                self._stop_entries(manifest, created)
            except Exception:
                pass  # _stop_entries persists unknown and continues fail-closed.
            raise LifecycleError("START_UNCERTAIN") from None

    def start(self, mode="mock", models_only=False, restart_models=False):
        check_environment(mode)
        if mode == "coder" and not models_only:
            models_only = True
        if restart_models and not models_only:
            raise LifecycleError("SCOPE_INVALID")
        with operation_lock(self.directory):
            manifest = self._load()
            known = self._check(manifest)
            protected = [entry for entry in manifest["entries"].values() if entry["protected"] and entry["status"] != "stopped"]
            if protected:
                if mode != "coder":
                    raise LifecycleError("PROTECTED_INSTANCE")
                # A repeated dedicated launch can only reuse healthy matching
                # protected instances; restart_models grants no override.
                if any(entry["pid"] not in known or not self._same_configuration(entry, self._spec(entry["role"], mode))
                       or not self.backend.healthy(entry, self._spec(entry["role"], mode)) for entry in protected):
                    raise LifecycleError("PROTECTED_INSTANCE")
                if {entry["role"] for entry in protected} != {"backend", "worker"}:
                    raise LifecycleError("PROTECTED_INSTANCE")
                return manifest
            if mode == "mock" and any(entry["protected"] for entry in manifest["entries"].values()):
                raise LifecycleError("PROTECTED_INSTANCE")
            roles = ("backend", "worker") if models_only else ROLES
            # Validate the whole scope before the first mutation.
            for role in roles:
                spec = self._spec(role, mode)
                previous = manifest["entries"].get(role)
                if previous and previous["status"] == "running" and previous["pid"] in known:
                    if not self._same_configuration(previous, spec) and not restart_models:
                        raise LifecycleError("CONFIGURATION_MISMATCH")
            if restart_models:
                self._stop_entries(manifest, [entry for entry in known.values() if entry["role"] in roles])
            self._start_scope(manifest, roles, mode)
            return manifest

    def stop(self, models_only=False, worker_only=False):
        check_environment("mock")
        with operation_lock(self.directory):
            manifest = self._load()
            known = self._check(manifest)
            roles = {"worker"} if worker_only else {"backend", "worker"} if models_only else set(ROLES)
            entries = [entry for entry in manifest["entries"].values() if entry["role"] in roles and entry["status"] != "stopped"]
            if any(entry["protected"] for entry in entries):
                raise LifecycleError("PROTECTED_INSTANCE")
            self._stop_entries(manifest, [entry for entry in entries if entry.get("pid") in known])
            return manifest

    def restart_worker(self):
        check_environment("mock")
        with operation_lock(self.directory):
            manifest = self._load()
            known = self._check(manifest)
            if any(entry["protected"] for entry in manifest["entries"].values()):
                raise LifecycleError("PROTECTED_INSTANCE")
            self._spec("worker", "mock")
            self._stop_entries(manifest, [entry for entry in known.values() if entry["role"] == "worker"])
            self._start_scope(manifest, ("worker",), "mock")
            return manifest

    def status(self):
        with operation_lock(self.directory):
            manifest = self._load()
            self._check(manifest)
            return manifest

    def _manual_candidates(self, manifest, roles):
        """Resolve only for an explicit human stop; never adopt or relaunch.

        An interrupted launch may have no recorded PID. A single discovered
        bootstrap with that persisted UUID/role can be presented for approval.
        It is not made a running managed instance, and ambiguity is refused.
        """
        discovered = self.backend.discover()
        known = {}
        candidates = []
        for original in manifest["entries"].values():
            if original["status"] == "stopped":
                continue
            uncertain = original["status"] in {"starting", "stopping", "unknown"}
            if uncertain and original["role"] not in roles:
                raise LifecycleError("START_UNCERTAIN")
            if uncertain and not getattr(self.backend, "is_test", False):
                parent = process_facts(original["manager_pid"])
                if parent and parent["created"] == original["manager_created"]:
                    raise LifecycleError("START_MANAGER_ACTIVE")
            entry = dict(original)
            observed = self.backend.inspect(entry["pid"]) if entry.get("pid") else None
            if observed is not None and not identity_matches(entry, observed):
                raise LifecycleError("IDENTITY_MISMATCH")
            matches = [item for item in discovered if item.get("instance_id") == entry["instance_id"]
                       and item.get("role") == entry["role"]]
            if len(matches) > 1:
                raise LifecycleError("IDENTITY_AMBIGUOUS")
            if uncertain and not entry.get("pid") and matches:
                observed = matches[0]
                entry.update({key: observed[key] for key in ("pid", "created", "executable", "parent_pid") if key in observed})
            if matches and (observed is None or not identity_matches(entry, matches[0])):
                raise LifecycleError("IDENTITY_MISMATCH")
            if observed:
                known[observed["pid"]] = entry
            if original["role"] in roles:
                candidates.append(entry)
        for observed in discovered:
            if observed["pid"] not in known or not identity_matches(known[observed["pid"]], observed):
                raise LifecycleError("UNMANAGED_PROCESS")
        return candidates

    @contextmanager
    def maintenance_session(self):
        key = os.path.normcase(str(self.directory))
        owner = (os.getpid(), threading.get_ident())
        # The outer trusted guard has already checked a clean environment. A
        # same-thread test may subsequently add a synthetic key to its fixture.
        # This process-local map is never exported to children or environment.
        with _LOCK_OWNERS_GUARD:
            previous = _MAINTENANCE_OWNERS.get(key)
            if previous and previous["owner"] == owner:
                previous["depth"] += 1
            elif previous:
                raise LifecycleError("LOCK_BUSY")
        if previous:
            try:
                yield previous["manifest"]
            finally:
                with _LOCK_OWNERS_GUARD:
                    _MAINTENANCE_OWNERS[key]["depth"] -= 1
            return
        check_environment("mock")
        # Read only: reject a protected slot before opening/creating the lock
        # directory. The authoritative check remains inside the OS lock below.
        if any(entry["protected"] for entry in self._load()["entries"].values()):
            raise LifecycleError("PROTECTED_INSTANCE")
        with operation_lock(self.directory):
            manifest = self._load()
            known = self._check(manifest)
            if any(entry["protected"] for entry in manifest["entries"].values()):
                raise LifecycleError("PROTECTED_INSTANCE")
            if any(entry["role"] in {"backend", "worker"} for entry in known.values()):
                raise LifecycleError("LIVE_INSTANCES_PRESENT")
            with _LOCK_OWNERS_GUARD:
                _MAINTENANCE_OWNERS[key] = {"owner": owner, "depth": 1, "manifest": manifest}
            try:
                yield manifest
            finally:
                with _LOCK_OWNERS_GUARD:
                    _MAINTENANCE_OWNERS.pop(key, None)

    def manual_stop(self, confirmation=None, models_only=True):
        if not getattr(self.backend, "is_test", False) and (not sys.stdin.isatty() or confirmation is not None):
            raise LifecycleError("APPROVAL_REQUIRED")
        with operation_lock(self.directory):
            manifest = self._load()
            roles = {"backend", "worker"} if models_only else set(ROLES)
            entries = self._manual_candidates(manifest, roles)
            if not entries:
                return manifest
            scope = {"action": "stop", "state_dir": str(self.directory), "generation": manifest["generation"],
                "instances": [{key: entry.get(key) for key in ("role", "instance_id", "pid", "created", "status")} for entry in entries],
                "approval_id": str(uuid4())}
            challenge = "STOP " + scope["approval_id"]
            started = time.monotonic()
            if confirmation:
                answer = confirmation({**scope, "challenge": challenge})
            else:
                print(json.dumps(scope, sort_keys=True))
                answer = input("Type exactly " + challenge + " within 60 seconds: ")
            if time.monotonic() - started > 60 or answer != challenge:
                raise LifecycleError("APPROVAL_REQUIRED")
            # Re-resolve after the human response while holding the same lock.
            # A candidate exiting/changing identity invalidates this approval.
            verified = self._manual_candidates(manifest, roles)
            if entries != verified:
                raise LifecycleError("IDENTITY_MISMATCH")
            self._audit("manual_stop_authorized", verified, scope["approval_id"])
            for entry in verified:
                manifest["entries"][entry["role"]] = entry
            self._stop_entries(manifest, verified, scope["approval_id"])
            return manifest


@contextmanager
def maintenance_guard(root):
    with LifecycleManager(root).maintenance_session() as state:
        yield state


# Preserve the reviewed v1 algorithm as the reusable core. Every native caller
# (including imported maintenance helpers) resolves to v2. Fake backends are
# explicit in-process test dependencies, never selectable through CLI or env.
_LegacyLifecycleManager = LifecycleManager


class LifecycleManager(_LegacyLifecycleManager):
    def __new__(cls, root, backend=None, state_dir=None):
        if backend is None or isinstance(backend, NativeBackend):
            from lifecycle_v2 import LifecycleManagerV2
            return LifecycleManagerV2(root, backend=backend, state_dir=state_dir)
        return super().__new__(cls)
