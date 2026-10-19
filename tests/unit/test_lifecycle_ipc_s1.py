"""S1 real Windows named-pipe tests. No app, DB, Docker or model is started.

Child processes inherit only an OS-name allowlist, never parent credentials.
Run with an isolated pytest base directory under work/maint-s1.
"""
import ctypes
from ctypes import wintypes
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import secrets
import struct
import subprocess
import sys
import time
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import lifecycle_channel as channel
import lifecycle_windows as windows

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Actual Windows token and pipe APIs required")
OS_NAMES = ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP",
            "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")


def binding():
    return {"instance_id": str(uuid4()), "generation": 1, "role": "worker", "mode": "coder",
            "protected": True, "config_digest": "a" * 64, "state": "STARTING"}


@pytest.fixture
def server(tmp_path):
    identity = windows.process_identity(os.getpid())
    with channel.ControlServer(tmp_path, binding(), lambda peer: windows.same_identity(identity, peer)) as service:
        service.set_ready()
        yield service


def request(service, **overrides):
    snapshot = service.snapshot
    return {"protocol": 1, "action": "observe", "instance_id": snapshot["instance_id"],
            "generation": snapshot["generation"], "nonce": secrets.token_hex(32),
            "issued_ms": time.time_ns() // 1_000_000, **overrides}


def raw_probe(service, message, wrong_confirmation=False):
    kernel, _ = channel._api()
    deadline = channel._deadline(2)
    handle = channel._connect(service.snapshot["pipe"], deadline)
    try:
        channel._send(handle, message, deadline)
        reply = channel._receive(handle, deadline)
        values = {key: reply[key] for key in ("protocol", "nonce", "challenge", "generation")}
        if wrong_confirmation:
            values["challenge"] = "0" * 64
        channel._send(handle, {**values, "action": "confirm"}, deadline)
        result = channel._receive(handle, deadline)
        channel._send(handle, {**values, "action": "complete"}, deadline)
        return result
    finally:
        kernel.CloseHandle(handle)


def test_process_security_uses_os_token_and_raw_creation_time():
    identity = windows.process_identity(os.getpid())
    assert identity["pid"] == os.getpid() and identity["created"] > 0
    assert identity["logon_sid"].startswith("S-1-5-5-")
    assert Path(identity["executable"]).is_file()
    with windows.query_process(os.getpid()) as held:
        assert windows.same_identity(identity, windows.identity_from_handle(held))
    assert windows.process_security(os.getpid()) == {key: identity[key] for key in ("user_sid", "logon_sid", "session_id")}


@pytest.mark.parametrize("pid", [0, -1, True, "1", 2**40])
def test_invalid_pid_cannot_become_identity(pid):
    with pytest.raises(windows.WindowsIdentityError):
        windows.process_identity(pid)


def test_actual_named_pipe_observation_has_fixed_mode_and_generation(server):
    snapshot = channel.probe(server.snapshot, server.root, windows.process_identity(os.getpid()))
    assert snapshot == server.snapshot
    assert snapshot["state"] == "READY_PROTECTED"


@pytest.mark.parametrize("key,value", [("created", 1), ("user_sid", "S-1-5-21-1"),
    ("session_id", 99999), ("executable", r"C:\untrusted.exe"), ("pid", 4)])
def test_expected_os_identity_cannot_be_forged(server, key, value):
    expected = {**windows.process_identity(os.getpid()), key: value}
    with pytest.raises(channel.ChannelError, match="IPC_PEER_UNVERIFIED"):
        channel.probe(server.snapshot, server.root, expected)


def test_forged_protection_record_cannot_override_live_snapshot(server, monkeypatch):
    monkeypatch.setenv("AGENTFORGE_CODER_KEY_PRESENT", "false")
    forged = {**server.snapshot, "mode": "mock", "protected": False, "state": "READY_MOCK"}
    with pytest.raises(channel.ChannelError, match="IPC_SNAPSHOT_MISMATCH"):
        channel.probe(forged, server.root, windows.process_identity(os.getpid()))


def test_duplicate_endpoint_creation_refused(server):
    with pytest.raises(channel.ChannelError, match="IPC_ENDPOINT_UNAVAILABLE"):
        channel.ControlServer(server.root, {key: server.snapshot[key] for key in channel.BINDING_KEYS}, lambda _: True).start()


@pytest.mark.parametrize("override", [{"action": "stop"}, {"generation": 2}, {"generation": True},
    {"instance_id": str(uuid4())}, {"issued_ms": 0}, {"issued_ms": 2**63},
    {"nonce": "bad"}, {"protocol": True}, {"extra": "unauthorized"}])
def test_expired_forged_and_command_messages_rejected(server, override):
    with pytest.raises(channel.ChannelError):
        raw_probe(server, request(server, **override))
    assert server.snapshot["state"] == "READY_PROTECTED"


def test_nonce_replay_rejected(server):
    message = request(server)
    assert raw_probe(server, message)["action"] == "snapshot"
    with pytest.raises(channel.ChannelError):
        raw_probe(server, message)


def test_wrong_challenge_rejected(server):
    with pytest.raises(channel.ChannelError):
        raw_probe(server, request(server), wrong_confirmation=True)


def test_oversized_message_fails_before_body_read(server):
    kernel, _ = channel._api()
    deadline = channel._deadline(2)
    handle = channel._connect(server.snapshot["pipe"], deadline)
    try:
        channel._io(handle, "write", struct.pack("<I", channel.MAX_MESSAGE + 1), deadline)
        with pytest.raises(channel.ChannelError):
            channel._receive(handle, deadline)
    finally:
        kernel.CloseHandle(handle)


def test_peer_validator_rejects_real_connected_process(tmp_path):
    with channel.ControlServer(tmp_path, binding(), lambda _: False) as service:
        with pytest.raises(channel.ChannelError):
            channel.probe(service.snapshot, tmp_path, windows.process_identity(os.getpid()))


def test_idle_or_silent_client_does_not_block_close(tmp_path):
    service = channel.ControlServer(tmp_path, binding(), lambda _: True).start()
    kernel, _ = channel._api()
    handle = channel._connect(service.snapshot["pipe"], channel._deadline(1))
    try:
        started = time.monotonic()
        service.close()
        assert time.monotonic() - started < 2
        assert not service._thread.is_alive()
    finally:
        kernel.CloseHandle(handle)


def test_disconnected_endpoint_times_out_bounded(tmp_path):
    service = channel.ControlServer(tmp_path, binding(), lambda _: True)
    started = time.monotonic()
    with pytest.raises(channel.ChannelError, match="IPC_TIMEOUT"):
        channel.probe(service.snapshot, tmp_path, windows.process_identity(os.getpid()), timeout=.1)
    assert time.monotonic() - started < 1


def test_parallel_actual_pipe_clients_get_separate_challenges(server):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: channel.probe(server.snapshot, server.root,
            windows.process_identity(os.getpid()), timeout=5), range(8)))
    assert all(result == server.snapshot for result in results)


def test_explicit_pipe_dacl_has_only_logon_and_system(server):
    kernel, security = channel._api()
    security.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    security.GetSecurityInfo.restype = wintypes.DWORD
    security.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [ctypes.c_void_p, wintypes.DWORD,
        wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.ULONG)]
    security.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    descriptor, text = ctypes.c_void_p(), wintypes.LPWSTR()
    assert security.GetSecurityInfo(server._handle, 6, 4, None, None, None, None, ctypes.byref(descriptor)) == 0
    try:
        assert security.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 4, ctypes.byref(text), None)
        rendered = text.value
        assert rendered.count("(A;") == 2
        assert server.snapshot["logon_sid"] in rendered and ";;;SY)" in rendered
        assert ";;;WD)" not in rendered and ";;;AN)" not in rendered
        # Specific mask excludes FILE_CREATE_PIPE_INSTANCE (0x4).
        assert "0x120083" in rendered
    finally:
        if text:
            kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
        kernel.LocalFree(descriptor)


def test_real_child_process_peer_is_verified_without_inheriting_credentials(tmp_path):
    identity = windows.process_identity(os.getpid())
    peers = []
    def validate(peer):
        peers.append(peer)
        return (peer["pid"] != identity["pid"] and peer["user_sid"] == identity["user_sid"]
                and peer["logon_sid"] == identity["logon_sid"] and peer["session_id"] == identity["session_id"]
                and os.path.normcase(peer["executable"]) == os.path.normcase(identity["executable"]))
    with channel.ControlServer(tmp_path, binding(), validate) as service:
        service.set_ready()
        source = ("import json,os,sys; sys.path.insert(0,sys.argv[1]); "
                  "from lifecycle_channel import probe; "
                  "s=json.loads(sys.argv[2]); r=probe(s,sys.argv[3],s); "
                  "assert not any(k.startswith('AGENTFORGE_MODEL_') for k in os.environ); "
                  "print(json.dumps({'pid':os.getpid(),'state':r['state']}))")
        environment = {name: os.environ[name] for name in OS_NAMES if name in os.environ}
        environment["TEMP"] = environment["TMP"] = str(tmp_path)
        child = subprocess.run([sys.executable, "-I", "-B", "-c", source, str(ROOT / "scripts"),
            json.dumps(service.snapshot), str(tmp_path)], cwd=tmp_path, env=environment,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW)
        assert child.returncode == 0, "Isolated IPC child failed; raw output withheld"
        result = json.loads(child.stdout)
        assert result["state"] == "READY_PROTECTED" and peers[0]["pid"] == result["pid"]


def test_duplicate_json_keys_rejected():
    with pytest.raises(ValueError):
        channel._unique_object([("action", "observe"), ("action", "stop")])


def test_expired_io_deadline_refuses_before_touching_handle():
    with pytest.raises(channel.ChannelError, match="IPC_TIMEOUT"):
        channel._io(None, "read", 1, time.monotonic() - 1)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True, 11])
def test_invalid_timeout_rejected(timeout):
    with pytest.raises(channel.ChannelError):
        channel._deadline(timeout)
