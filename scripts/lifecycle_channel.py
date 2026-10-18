"""Authenticated local observation channel; it has no command/stop operation.

Windows supplies both peer PIDs. Process token/logon identity and raw creation
time are verified independently of JSON. All I/O is bounded overlapped I/O.
"""
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import struct
import threading
import time
from uuid import UUID

from lifecycle_windows import WindowsIdentityError, process_identity, same_identity, winapi


IDENTITY_KEYS = ("pid", "created", "executable", "user_sid", "logon_sid", "session_id")
BINDING_KEYS = ("instance_id", "generation", "role", "mode", "protected", "config_digest")
STATES = {"STARTING", "READY_PROTECTED", "READY_MOCK", "STOPPING", "RECOVERY_REQUIRED"}
MAX_MESSAGE = 8192
REQUEST_LIFETIME_MS = 5000
_RETAINED_IO = []


class ChannelError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD), ("hEvent", wintypes.HANDLE)]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


def _api():
    kernel, security = winapi()
    definitions = {
        "CreateNamedPipeW": ([wintypes.LPCWSTR] + [wintypes.DWORD] * 6 + [ctypes.POINTER(SECURITY_ATTRIBUTES)], wintypes.HANDLE),
        "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
        "ConnectNamedPipe": ([wintypes.HANDLE, ctypes.POINTER(OVERLAPPED)], wintypes.BOOL),
        "DisconnectNamedPipe": ([wintypes.HANDLE], wintypes.BOOL),
        "ReadFile": ([wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)], wintypes.BOOL),
        "WriteFile": ([wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)], wintypes.BOOL),
        "CreateEventW": ([ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "GetOverlappedResult": ([wintypes.HANDLE, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(wintypes.DWORD), wintypes.BOOL], wintypes.BOOL),
        "CancelIoEx": ([wintypes.HANDLE, ctypes.POINTER(OVERLAPPED)], wintypes.BOOL),
        "GetNamedPipeClientProcessId": ([wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)], wintypes.BOOL),
        "GetNamedPipeServerProcessId": ([wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)], wintypes.BOOL),
    }
    for name, (arguments, result) in definitions.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    security.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    return kernel, security


def _invalid(handle):
    return handle in (None, 0, ctypes.c_void_p(-1).value)


def _root_id(root):
    absolute = Path(os.path.abspath(root))
    for part in (*reversed(absolute.parents), absolute):
        try:
            meta = part.lstat()
        except FileNotFoundError:
            continue
        if part.is_symlink() or getattr(meta, "st_file_attributes", 0) & 0x400:
            raise ChannelError("IPC_ROOT_UNVERIFIED")
    return hashlib.sha256(os.path.normcase(str(absolute)).encode("utf-8")).hexdigest()[:24]


def pipe_name(root, snapshot):
    try:
        instance = str(UUID(snapshot["instance_id"]))
        generation = snapshot["generation"]
        if instance != snapshot["instance_id"] or type(generation) is not int or not 1 <= generation <= 2**63 - 1:
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ChannelError("IPC_SNAPSHOT_INVALID") from None
    return r"\\.\pipe\agentforge.lifecycle.v2." + _root_id(root) + "." + instance + "." + str(generation)


def _validate_snapshot(root, snapshot):
    fields = set(BINDING_KEYS) | set(IDENTITY_KEYS) | {"state", "pipe", "protocol"}
    if not isinstance(snapshot, dict) or set(snapshot) != fields:
        raise ChannelError("IPC_SNAPSHOT_INVALID")
    if (snapshot["protocol"] != 1 or type(snapshot["protocol"]) is not int
            or snapshot["pipe"] != pipe_name(root, snapshot)
            or snapshot["role"] not in {"backend", "worker"} or snapshot["mode"] not in {"coder", "mock"}
            or type(snapshot["protected"]) is not bool or snapshot["protected"] != (snapshot["mode"] == "coder")
            or snapshot["state"] not in STATES):
        raise ChannelError("IPC_SNAPSHOT_INVALID")
    if (snapshot["state"] == "READY_PROTECTED" and not snapshot["protected"]
            or snapshot["state"] == "READY_MOCK" and snapshot["protected"]):
        raise ChannelError("IPC_SNAPSHOT_INVALID")
    if snapshot["config_digest"] is not None and not re.fullmatch(r"[0-9a-f]{64}", str(snapshot["config_digest"])):
        raise ChannelError("IPC_SNAPSHOT_INVALID")
    for name in ("pid", "created", "session_id"):
        if type(snapshot[name]) is not int or snapshot[name] < (0 if name == "session_id" else 1):
            raise ChannelError("IPC_SNAPSHOT_INVALID")
    for name in ("user_sid", "logon_sid"):
        if not isinstance(snapshot[name], str) or not re.fullmatch(r"S-1-\d+(?:-\d+)+", snapshot[name]):
            raise ChannelError("IPC_SNAPSHOT_INVALID")
    if not isinstance(snapshot["executable"], str) or not snapshot["executable"]:
        raise ChannelError("IPC_SNAPSHOT_INVALID")


def _deadline(timeout):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 10:
        raise ChannelError("IPC_TIMEOUT_INVALID")
    return time.monotonic() + timeout


def _io(handle, kind, payload, deadline, stop=None):
    if time.monotonic() >= deadline or stop is not None and stop.is_set():
        raise ChannelError("IPC_TIMEOUT")
    kernel, _ = _api()
    event = kernel.CreateEventW(None, True, False, None)
    if not event:
        raise ChannelError("IPC_UNAVAILABLE")
    overlapped = OVERLAPPED(hEvent=event)
    transferred = wintypes.DWORD()
    buffer = (ctypes.create_string_buffer(payload) if kind == "write" else
              ctypes.create_string_buffer(payload) if kind == "read" else None)
    pending = False
    retained = False
    try:
        if kind == "connect":
            succeeded = kernel.ConnectNamedPipe(handle, ctypes.byref(overlapped))
        elif kind == "read":
            succeeded = kernel.ReadFile(handle, buffer, payload, ctypes.byref(transferred), ctypes.byref(overlapped))
        else:
            succeeded = kernel.WriteFile(handle, buffer, len(payload), ctypes.byref(transferred), ctypes.byref(overlapped))
        if not succeeded:
            error = ctypes.get_last_error()
            if kind == "connect" and error == 535:  # already connected before ConnectNamedPipe
                return b""
            if error != 997:
                raise ChannelError("IPC_DISCONNECTED")
            pending = True
        while pending:
            if (stop is not None and stop.is_set()) or time.monotonic() >= deadline:
                raise ChannelError("IPC_TIMEOUT")
            result = kernel.WaitForSingleObject(event, min(25, max(1, int((deadline - time.monotonic()) * 1000))))
            if result == 258:
                continue
            if result != 0:
                raise ChannelError("IPC_UNAVAILABLE")
            pending = False
            if not kernel.GetOverlappedResult(handle, ctypes.byref(overlapped), ctypes.byref(transferred), False):
                raise ChannelError("IPC_DISCONNECTED")
        if time.monotonic() >= deadline or stop is not None and stop.is_set():
            raise ChannelError("IPC_TIMEOUT")
        return buffer.raw[:transferred.value] if kind == "read" else transferred.value
    finally:
        if pending:
            kernel.CancelIoEx(handle, ctypes.byref(overlapped))
            # CancelIoEx is not completion. Never free buffers still owned by
            # the kernel, even in the exceptional cancellation failure case.
            if kernel.WaitForSingleObject(event, 1000) != 0:
                _RETAINED_IO.append((overlapped, buffer, event))
                retained = True
        if not retained:
            kernel.CloseHandle(event)
        else:
            # This endpoint must never be reused after uncertain cancellation.
            # Retain only OS I/O buffers (no request credentials exist here).
            raise ChannelError("IPC_CANCEL_UNCERTAIN")


def _read_exact(handle, count, deadline, stop=None):
    parts = bytearray()
    while len(parts) < count:
        chunk = _io(handle, "read", count - len(parts), deadline, stop)
        if not chunk:
            raise ChannelError("IPC_DISCONNECTED")
        parts.extend(chunk)
    return bytes(parts)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _receive(handle, deadline, stop=None):
    size = struct.unpack("<I", _read_exact(handle, 4, deadline, stop))[0]
    if not 1 <= size <= MAX_MESSAGE:
        raise ChannelError("IPC_MESSAGE_INVALID")
    try:
        value = json.loads(_read_exact(handle, size, deadline, stop).decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError):
        raise ChannelError("IPC_MESSAGE_INVALID") from None
    if not isinstance(value, dict):
        raise ChannelError("IPC_MESSAGE_INVALID")
    return value


def _send(handle, value, deadline, stop=None):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if not 1 <= len(data) <= MAX_MESSAGE:
        raise ChannelError("IPC_MESSAGE_INVALID")
    framed = struct.pack("<I", len(data)) + data
    if _io(handle, "write", framed, deadline, stop) != len(framed):
        raise ChannelError("IPC_DISCONNECTED")


def _peer_identity(handle, server_side):
    kernel, _ = _api()
    pid = wintypes.ULONG()
    function = kernel.GetNamedPipeClientProcessId if server_side else kernel.GetNamedPipeServerProcessId
    if not function(handle, ctypes.byref(pid)):
        raise ChannelError("IPC_PEER_UNVERIFIED")
    try:
        return process_identity(int(pid.value))
    except WindowsIdentityError:
        raise ChannelError("IPC_PEER_UNVERIFIED") from None


def _same_logon(first, second):
    return all(first.get(key) == second.get(key) for key in ("user_sid", "logon_sid", "session_id"))


class ControlServer:
    def __init__(self, root, identity_snapshot, peer_validator):
        if not callable(peer_validator):
            raise ChannelError("IPC_VALIDATOR_REQUIRED")
        self.root = Path(root)
        self._identity = process_identity(os.getpid())
        allowed = set(BINDING_KEYS) | set(IDENTITY_KEYS) | {"state"}
        if not isinstance(identity_snapshot, dict) or set(identity_snapshot) - allowed:
            raise ChannelError("IPC_SNAPSHOT_INVALID")
        if any(key in identity_snapshot and identity_snapshot[key] != self._identity[key] for key in IDENTITY_KEYS):
            raise ChannelError("IPC_PEER_UNVERIFIED")
        self._snapshot = {**identity_snapshot, **self._identity, "protocol": 1,
                          "pipe": pipe_name(root, identity_snapshot), "state": identity_snapshot.get("state", "STARTING")}
        _validate_snapshot(root, self._snapshot)
        self._validator = peer_validator
        self._stop = threading.Event()
        self._mutex = threading.Lock()
        self._thread = None
        self._handle = None
        self._nonces = {}
        self.error_code = None

    @property
    def snapshot(self):
        with self._mutex:
            return dict(self._snapshot)

    def set_ready(self):
        with self._mutex:
            if self._snapshot["state"] != "STARTING" or self._stop.is_set() or self.error_code:
                raise ChannelError("IPC_STATE_INVALID")
            self._snapshot["state"] = "READY_PROTECTED" if self._snapshot["protected"] else "READY_MOCK"

    def start(self):
        if self._thread is not None or self._stop.is_set():
            raise ChannelError("IPC_STATE_INVALID")
        kernel, security = _api()
        # Specific data/attribute rights omit FILE_CREATE_PIPE_INSTANCE (0x4).
        # CreateFile also needs FILE_READ_ATTRIBUTES for the pipe open.
        descriptor = ctypes.c_void_p()
        sddl = "D:P(A;;0x120083;;;" + self._identity["logon_sid"] + ")(A;;GA;;;SY)"
        if not security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise ChannelError("IPC_ACCESS_CONTROL_UNAVAILABLE")
        try:
            attributes = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), descriptor, False)
            self._handle = kernel.CreateNamedPipeW(self._snapshot["pipe"], 0x3 | 0x40000000 | 0x00080000,
                0x8, 1, MAX_MESSAGE + 4, MAX_MESSAGE + 4, 0, ctypes.byref(attributes))
        finally:
            kernel.LocalFree(descriptor)
        if _invalid(self._handle):
            self._handle = None
            raise ChannelError("IPC_ENDPOINT_UNAVAILABLE")
        self._thread = threading.Thread(target=self._run, name="AgentForge lifecycle observation", daemon=True)
        self._thread.start()
        return self

    def _exchange(self):
        deadline = _deadline(3)
        peer = _peer_identity(self._handle, True)
        if not _same_logon(self._identity, peer) or self._validator(dict(peer)) is not True:
            raise ChannelError("IPC_PEER_UNVERIFIED")
        request = _receive(self._handle, deadline, self._stop)
        fields = {"protocol", "action", "instance_id", "generation", "nonce", "issued_ms"}
        now_ms = time.time_ns() // 1_000_000
        if (set(request) != fields or type(request["protocol"]) is not int or request["protocol"] != 1
                or request["action"] != "observe" or request["instance_id"] != self._snapshot["instance_id"]
                or type(request["generation"]) is not int or request["generation"] != self._snapshot["generation"]
                or not isinstance(request["nonce"], str) or not re.fullmatch(r"[0-9a-f]{64}", request["nonce"])
                or type(request["issued_ms"]) is not int or not 0 <= now_ms - request["issued_ms"] <= REQUEST_LIFETIME_MS):
            raise ChannelError("IPC_MESSAGE_INVALID")
        self._nonces = {nonce: stamp for nonce, stamp in self._nonces.items() if stamp >= now_ms - REQUEST_LIFETIME_MS * 2}
        if request["nonce"] in self._nonces or len(self._nonces) >= 1024:
            raise ChannelError("IPC_REPLAY_REJECTED")
        self._nonces[request["nonce"]] = now_ms
        binding = {"protocol": 1, "nonce": request["nonce"], "challenge": secrets.token_hex(32),
                   "generation": self._snapshot["generation"]}
        _send(self._handle, {**binding, "action": "challenge", "snapshot": self.snapshot}, deadline, self._stop)
        if _receive(self._handle, deadline, self._stop) != {**binding, "action": "confirm"}:
            raise ChannelError("IPC_REPLAY_REJECTED")
        if not same_identity(peer, _peer_identity(self._handle, True)):
            raise ChannelError("IPC_PEER_UNVERIFIED")
        _send(self._handle, {**binding, "action": "snapshot", "snapshot": self.snapshot}, deadline, self._stop)
        if _receive(self._handle, deadline, self._stop) != {**binding, "action": "complete"}:
            raise ChannelError("IPC_MESSAGE_INVALID")

    def _run(self):
        kernel, _ = _api()
        try:
            while not self._stop.is_set():
                try:
                    _io(self._handle, "connect", None, _deadline(1), self._stop)
                    self._exchange()
                except (ChannelError, WindowsIdentityError) as error:
                    # Invalid/expired clients never change state or authorize an
                    # action. Keep only a normalized code, never request contents.
                    if error.code in {"IPC_CANCEL_UNCERTAIN", "IPC_UNAVAILABLE"}:
                        self.error_code = error.code
                        break
                finally:
                    kernel.DisconnectNamedPipe(self._handle)
        except Exception:
            self.error_code = "IPC_UNAVAILABLE"
        finally:
            kernel.CloseHandle(self._handle)
            self._handle = None

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                self.error_code = "IPC_CLOSE_UNCERTAIN"
                raise ChannelError("IPC_CLOSE_UNCERTAIN")

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()


def _connect(name, deadline):
    kernel, _ = _api()
    while time.monotonic() < deadline:
        # Individual data rights, overlapped operation, identification-only SQOS.
        handle = kernel.CreateFileW(name, 0x120003, 0, None, 3, 0x40000000 | 0x00100000 | 0x00010000, None)
        if not _invalid(handle):
            return handle
        if ctypes.get_last_error() not in (2, 231):
            raise ChannelError("IPC_ENDPOINT_UNAVAILABLE")
        time.sleep(min(0.01, max(0, deadline - time.monotonic())))
    raise ChannelError("IPC_TIMEOUT")


def probe(snapshot, root, expected_identity, timeout=3):
    """One fresh observation handshake. Never grants stop or model authority."""
    _validate_snapshot(root, snapshot)
    deadline = _deadline(timeout)
    kernel, _ = _api()
    handle = _connect(pipe_name(root, snapshot), deadline)
    try:
        peer = _peer_identity(handle, False)
        if not same_identity(expected_identity, peer) or not same_identity(snapshot, peer):
            raise ChannelError("IPC_PEER_UNVERIFIED")
        current = process_identity(os.getpid())
        if not _same_logon(current, peer):
            raise ChannelError("IPC_PEER_UNVERIFIED")
        request = {"protocol": 1, "action": "observe", "instance_id": snapshot["instance_id"],
                   "generation": snapshot["generation"], "nonce": secrets.token_hex(32), "issued_ms": time.time_ns() // 1_000_000}
        _send(handle, request, deadline)
        challenge = _receive(handle, deadline)
        fields = {"protocol", "action", "nonce", "challenge", "generation", "snapshot"}
        if (set(challenge) != fields or type(challenge["protocol"]) is not int or challenge["protocol"] != 1
                or challenge["action"] != "challenge" or challenge["nonce"] != request["nonce"]
                or type(challenge["generation"]) is not int or challenge["generation"] != snapshot["generation"]
                or not isinstance(challenge["challenge"], str) or not re.fullmatch(r"[0-9a-f]{64}", challenge["challenge"])):
            raise ChannelError("IPC_MESSAGE_INVALID")
        reported = challenge["snapshot"]
        _validate_snapshot(root, reported)
        if not same_identity(reported, peer) or any(reported[key] != snapshot[key] for key in BINDING_KEYS):
            raise ChannelError("IPC_SNAPSHOT_MISMATCH")
        binding = {key: challenge[key] for key in ("protocol", "nonce", "challenge", "generation")}
        _send(handle, {**binding, "action": "confirm"}, deadline)
        result = _receive(handle, deadline)
        if set(result) != fields or any(result[key] != value for key, value in binding.items()) or result["action"] != "snapshot":
            raise ChannelError("IPC_MESSAGE_INVALID")
        final = result["snapshot"]
        _validate_snapshot(root, final)
        if not same_identity(final, peer) or any(final[key] != snapshot[key] for key in BINDING_KEYS):
            raise ChannelError("IPC_SNAPSHOT_MISMATCH")
        if not same_identity(peer, _peer_identity(handle, False)):
            raise ChannelError("IPC_PEER_UNVERIFIED")
        _send(handle, {**binding, "action": "complete"}, deadline)
        return final
    finally:
        kernel.CloseHandle(handle)
