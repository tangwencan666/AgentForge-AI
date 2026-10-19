"""Disposable Windows lifecycle v2 acceptance helper, never the main project.

Production scripts are copied byte-for-byte into a generated root. Only stdlib
HTTP/Worker stubs execute there. No application database, Redis or Docker exists.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[2]
MODULES = ("lifecycle_manager.py", "lifecycle_v2.py", "lifecycle.py", "managed_service.py",
           "lifecycle_windows.py", "lifecycle_channel.py", "lifecycle_runtime.py")
OS_NAMES = ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP",
            "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
FAKE_KEY = "s1-offline-fictional-key-" + uuid4().hex
_TEST_JOB = None


def bind_disposable_job():
    """Only this fixture and descendants die if its supervisor times out.

The unnamed handle stays non-inheritable and open until this process exits;
it is deliberately never used for main API/Worker or foreign processes.
"""
    global _TEST_JOB
    class Basic(ctypes.Structure):
        _fields_ = [("ProcessTime", ctypes.c_longlong), ("JobTime", ctypes.c_longlong),
                    ("Flags", wintypes.DWORD), ("Minimum", ctypes.c_size_t), ("Maximum", ctypes.c_size_t),
                    ("Active", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                    ("Priority", wintypes.DWORD), ("Scheduling", wintypes.DWORD)]
    class Counters(ctypes.Structure):
        _fields_ = [("value" + str(index), ctypes.c_ulonglong) for index in range(6)]
    class Extended(ctypes.Structure):
        _fields_ = [("Basic", Basic), ("IO", Counters), ("ProcessMemory", ctypes.c_size_t),
                    ("JobMemory", ctypes.c_size_t), ("PeakProcess", ctypes.c_size_t), ("PeakJob", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    _TEST_JOB = kernel.CreateJobObjectW(None, None)
    if not _TEST_JOB:
        raise RuntimeError("FIXTURE_JOB_REQUIRED")
    limits = Extended()
    limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(_TEST_JOB, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        raise RuntimeError("FIXTURE_JOB_REQUIRED")
    if not kernel.AssignProcessToJobObject(_TEST_JOB, kernel.GetCurrentProcess()):
        raise RuntimeError("FIXTURE_JOB_REQUIRED")


def witnessed_job_identity(pid, windows):
    """Kernel membership of this fresh, unnamed test Job on the held handle.

    A forwarding launcher may have exited before CIM reports its final child;
    job membership remains authoritative without guessing ancestry from a PID.
    This helper cannot authorize a process outside this fixture's own Job.
    """
    if not _TEST_JOB:
        raise RuntimeError('FIXTURE_JOB_REQUIRED')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel.IsProcessInJob.restype = wintypes.BOOL
    with windows.query_process(pid) as handle:
        identity = windows.identity_from_handle(handle)
        member = wintypes.BOOL()
        if not kernel.IsProcessInJob(handle, _TEST_JOB, ctypes.byref(member)) or not member.value:
            raise RuntimeError('FIXTURE_JOB_MEMBERSHIP_REQUIRED')
        if not windows.same_identity(identity, windows.identity_from_handle(handle)):
            raise RuntimeError('FIXTURE_IDENTITY_CHANGED')
        return identity

OBSERVE = '''import json,os,time
from pathlib import Path
def observe(role):
    root=Path(__file__).resolve().parents[1]
    names=('AGENTFORGE_REAL_CALLS_ENABLED','AGENTFORGE_SINGLE_USE_PERMITS_ENABLED',
      'AGENTFORGE_REAL_WORKER_MODE','AGENTFORGE_REAL_DAILY_BUDGET_USD','AGENTFORGE_REAL_TEST_BUDGET_USD',
      'AGENTFORGE_REAL_MAX_RETRIES','AGENTFORGE_EXTERNAL_MODELS_BLOCKED')
    value={'pid':os.getpid(),'coder_present':'AGENTFORGE_MODEL_CODER_KEY' in os.environ,
      'issuer_present':'AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN' in os.environ,
      'policy':{name:os.environ.get(name) for name in names},'model_calls':0,'database_calls':0,'stub':True}
    (root/'work'/('observed-'+role+'.json')).write_text(json.dumps(value),encoding='utf-8')
'''
API = '''from http.server import BaseHTTPRequestHandler,HTTPServer
import time,lifecycle_runtime
from offline_observe import observe
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data=b'{"stub":true}'
        self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def log_message(self,*args):pass
def run(app,*,factory,host,port,**kwargs):
    if host!='127.0.0.1' or app!='app.main:create_app':raise RuntimeError('FIXTURE_SCOPE_INVALID')
    with HTTPServer((host,port),Handler) as server:
        server.timeout=.1;observe('backend');lifecycle_runtime.ready('backend')
        end=time.monotonic()+900
        while time.monotonic()<end:server.handle_request()
'''
WORKER = '''import time,lifecycle_runtime
from offline_observe import observe
observe('worker');lifecycle_runtime.ready('worker')
end=time.monotonic()+900
while time.monotonic()<end:time.sleep(.1)
'''


def setup(directory):
    root = directory / "isolated-project"
    (root / "scripts").mkdir(parents=True)
    hashes = {}
    for name in MODULES:
        content = (PROJECT / "scripts" / name).read_bytes()
        (root / "scripts" / name).write_bytes(content)
        hashes[name] = hashlib.sha256(content).hexdigest()
    (root / ".venv/Scripts").mkdir(parents=True)
    shutil.copyfile(PROJECT / ".venv/Scripts/python.exe", root / ".venv/Scripts/python.exe")
    shutil.copyfile(PROJECT / ".venv/pyvenv.cfg", root / ".venv/pyvenv.cfg")
    (root / "backend/app/workers").mkdir(parents=True)
    (root / "backend/app/__init__.py").touch()
    (root / "backend/app/workers/__init__.py").touch()
    (root / "backend/app/workers/main.py").write_text(WORKER, encoding="utf-8")
    (root / "backend/uvicorn.py").write_text(API, encoding="utf-8")
    (root / "backend/offline_observe.py").write_text(OBSERVE, encoding="utf-8")
    (root / "work/p5-live-preflight").mkdir(parents=True)
    (root / "work/p5-live-preflight/.env").touch()
    (root / ".env").touch()
    (root / "config").mkdir()
    (root / "config/deepseek-coder-local.json").write_text("{}", encoding="utf-8")
    held = []
    try:
        for _ in range(2):
            item = socket.socket()
            item.bind(("127.0.0.1", 0))
            held.append(item)
        ports = dict(zip(("BACKEND_PORT", "FRONTEND_PORT"), (str(item.getsockname()[1]) for item in held)))
    finally:
        for item in held:
            item.close()
    sys.path.insert(0, str(root / "scripts"))
    import lifecycle_manager as lifecycle
    import lifecycle_windows as windows
    import lifecycle_v2 as v2
    os.environ.update(ports)
    return root, hashes, lifecycle, windows, v2


def refused(operation, codes):
    try:
        operation()
    except Exception as error:
        assert getattr(error, "code", None) in codes, "Unexpected normalized refusal"
        return error.code
    raise AssertionError("Operation unexpectedly accepted")


def assert_live(manager, windows, state):
    for entry in state["entries"].values():
        assert windows.same_identity(entry, windows.process_identity(entry["pid"]))
        assert manager.backend.verify(entry, ready=True)["state"] == "READY_PROTECTED"


def tracked_backend(root, lifecycle, windows):
    class Backend(lifecycle.NativeBackend):
        is_test = True  # Only the in-process human-confirmation callback is replaced.
        def __init__(self):
            super().__init__(root)
            self.owned = {}
            self.launchers = {}

        def launch(self, spec):
            original = subprocess.Popen
            def capture(argv, *args, **kwargs):
                child = original(argv, *args, **kwargs)
                if isinstance(argv, list) and str(root / "scripts/managed_service.py") in argv:
                    self.launchers[spec["instance_id"]] = windows.process_identity(child.pid)
                return child
            subprocess.Popen = capture
            try:
                identity = super().launch(spec)
                self.owned[spec["instance_id"]] = {**identity, **windows.process_identity(identity["pid"])}
                return identity
            finally:
                subprocess.Popen = original

        def cleanup(self):
            # A failed launch can be resolved only by this operation's captured
            # kernel launcher identity and its still-live direct child chain.
            for item in self.discover():
                launcher = self.launchers.get(item["instance_id"])
                assert launcher is not None, "Unconfirmed fixture ownership; cleanup refused"
                if item["pid"] == launcher["pid"]:
                    assert item["created"] == launcher["created"]
                else:
                    assert item["parent_pid"] == launcher["pid"]
                    assert windows.same_identity(launcher, windows.process_identity(launcher["pid"]))
                actual = windows.process_identity(item["pid"])
                assert item["created"] == actual["created"]
                self.owned[item["instance_id"]] = {**item, **actual}
            for identity in self.owned.values():
                current = self.inspect(identity["pid"])
                if current is not None:
                    assert lifecycle.identity_matches(identity, current)
                    assert windows.same_identity(identity, windows.process_identity(identity["pid"]))
                    self.terminate(identity)
            assert not self.discover(), "Fixture process cleanup incomplete"
    return Backend()


def protected(root, lifecycle, windows, v2):
    backend = tracked_backend(root, lifecycle, windows)
    manager = lifecycle.LifecycleManager(root, backend=backend)
    evidence = []
    try:
        os.environ["AGENTFORGE_MODEL_CODER_KEY"] = FAKE_KEY
        state = manager.start("coder", models_only=True)
        assert state["version"] == 2 and set(state["entries"]) == {"backend", "worker"}
        assert_live(manager, windows, state)
        original = manager.manifest_path.read_bytes()
        again = manager.start("coder", models_only=True, restart_models=True)
        assert original == manager.manifest_path.read_bytes() and state == again
        evidence += ["native_sid_ipc_ready", "dedicated_start_idempotent"]
        del os.environ["AGENTFORGE_MODEL_CODER_KEY"]
        refused(lambda: manager.stop(models_only=True), {"PROTECTED_INSTANCE"})
        refused(lambda: manager.start("mock", models_only=True), {"PROTECTED_INSTANCE"})
        try:
            raise RuntimeError("synthetic-maintenance-test-failure")
        except RuntimeError:
            pass
        finally:
            refused(lambda: manager.restart_worker(), {"PROTECTED_INSTANCE"})
        assert_live(manager, windows, state)
        evidence += ["keyless_cannot_replace", "test_finally_cannot_restart"]

        tampered = json.loads(original)
        for entry in tampered["entries"].values():
            entry.update(mode="mock", protected=False, lifecycle_state="READY_MOCK")
            entry["control"].update(mode="mock", protected=False, state="READY_MOCK")
            entry["control"]["config_digest"] = v2.configuration_digest(entry)
        lifecycle._atomic_json(manager.manifest_path, tampered)
        os.environ["AGENTFORGE_CODER_KEY_PRESENT"] = "false"
        refused(lambda: manager.stop(models_only=True), {"CONTROL_CHANNEL_UNVERIFIED", "CONTROL_BINDING_MISMATCH"})
        manager.manifest_path.write_bytes(original)
        del os.environ["AGENTFORGE_CODER_KEY_PRESENT"]
        assert_live(manager, windows, state)
        evidence.append("forged_manifest_cannot_stop")

        tampered = json.loads(original)
        entry = tampered["entries"]["worker"]
        entry["generation"] += 10
        lifecycle._atomic_json(manager.manifest_path, tampered)
        refused(lambda: manager.status(), {"CONTROL_BINDING_MISMATCH"})
        manager.manifest_path.write_bytes(original)
        evidence.append("generation_tampering_rejected")

        saved_time = v2.time
        clock = SimpleNamespace(offset=0)
        v2.time = SimpleNamespace(time=lambda: saved_time.time() + clock.offset,
                                  monotonic=lambda: saved_time.monotonic() + clock.offset, sleep=saved_time.sleep)
        old_challenge = []
        def expire(scope):
            old_challenge.append(scope["challenge"])
            clock.offset = 61
            return scope["challenge"]
        try:
            refused(lambda: manager.manual_stop(confirmation=expire), {"APPROVAL_REQUIRED"})
        finally:
            v2.time = saved_time
        refused(lambda: manager.manual_stop(confirmation=lambda _: old_challenge[0]), {"APPROVAL_REQUIRED"})
        assert_live(manager, windows, state)
        approvals = [json.loads(path.read_text()) for path in (manager.directory / "approvals").glob("*.json")]
        assert len(approvals) == 2 and all(item["status"] == "EXPIRED" for item in approvals)
        evidence += ["approval_expiration_rejected", "approval_replay_rejected"]

        tampered = json.loads(original)
        tampered["entries"]["worker"].update(status="unknown", lifecycle_state="RECOVERY_REQUIRED")
        lifecycle._atomic_json(manager.manifest_path, tampered)
        refused(lambda: manager.start("mock", models_only=True), {"START_UNCERTAIN"})
        assert json.loads(manager.manifest_path.read_text())["entries"]["worker"]["protected"] is True
        manager.manifest_path.write_bytes(original)
        evidence.append("uncertain_state_retains_protection")

        # Deliberate crash of this fixture's witnessed Worker only. No automatic
        # relaunch or downgrade may follow an actual process disappearance.
        worker = state["entries"]["worker"]
        assert windows.same_identity(backend.owned[worker["instance_id"]], windows.process_identity(worker["pid"]))
        backend.terminate(worker)
        os.environ["AGENTFORGE_MODEL_CODER_KEY"] = FAKE_KEY
        refused(lambda: manager.start("coder", models_only=True), {"PROTECTED_INSTANCE"})
        del os.environ["AGENTFORGE_MODEL_CODER_KEY"]
        assert json.loads(manager.manifest_path.read_text())["entries"]["worker"]["protected"] is True
        assert backend.inspect(worker["pid"]) is None
        evidence.append("real_worker_crash_no_automatic_relaunch")

        stopped = manager.manual_stop(confirmation=lambda scope: scope["challenge"])
        assert all(entry["lifecycle_state"] == "STOPPED_PROTECTED" for entry in stopped["entries"].values())
        approvals = [json.loads(path.read_text()) for path in (manager.directory / "approvals").glob("*.json")]
        assert sum(item["status"] == "CONSUMED" for item in approvals) == 1
        refused(lambda: manager.start("mock", models_only=True), {"PROTECTED_INSTANCE"})
        evidence += ["approval_consumed_before_stop", "stopped_protection_retained"]
        for role in ("backend", "worker"):
            observed = json.loads((root / "work" / ("observed-" + role + ".json")).read_text())
            assert observed["coder_present"] and not observed["issuer_present"] and observed["stub"]
            assert observed["policy"] == {name: lifecycle.SAFE_ENV[name] for name in observed["policy"]}
        for path in (root / "work").rglob("*"):
            if path.is_file():
                assert FAKE_KEY.encode() not in path.read_bytes(), "Fake credential leaked"
        evidence += ["closed_budget_permit_egress_preserved", "fake_credential_not_logged"]
    finally:
        os.environ.pop("AGENTFORGE_MODEL_CODER_KEY", None)
        backend.cleanup()
    return evidence


def legacy(root, lifecycle, windows, v2):
    manager = lifecycle.LifecycleManager(root)
    manager.directory.mkdir(parents=True)
    old = {"version": 1, "project_root": str(root), "generation": 7, "entries": {}}
    lifecycle._atomic_json(manager.manifest_path, old)
    before = manager.manifest_path.read_bytes(), manager.manifest_path.stat().st_mtime_ns
    files_before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in manager.directory.iterdir() if path.is_file()}
    refused(lambda: manager.start("mock", models_only=True), {"LEGACY_INSTANCE_UNVERIFIED"})
    refused(lambda: manager.status(), {"LEGACY_INSTANCE_UNVERIFIED"})
    assert before == (manager.manifest_path.read_bytes(), manager.manifest_path.stat().st_mtime_ns)
    assert files_before == {path.name: (path.read_bytes(), path.stat().st_mtime_ns)
                            for path in manager.directory.iterdir() if path.is_file()}
    assert not manager.backend.discover()
    return ["legacy_manifest_no_adoption_or_migration"]


def identity(root, lifecycle, windows, v2):
    """Real own processes: wrong FILETIME/Token must fail before TerminateProcess.

    This does not claim Windows was forced to recycle a particular PID.
    """
    try:
        witnessed_job_identity(os.getppid(), windows)
    except RuntimeError as error:
        assert str(error) == 'FIXTURE_JOB_MEMBERSHIP_REQUIRED'
    else:
        raise AssertionError('A process outside this test Job was accepted')
    backend = tracked_backend(root, lifecycle, windows)
    manager = lifecycle.LifecycleManager(root, backend=backend)
    try:
        state = manager.start('mock', models_only=True)
        worker = state['entries']['worker']
        actual = windows.process_identity(worker['pid'])
        refused(lambda: backend.terminate({**worker, 'created': worker['created'] + 10}), {'IDENTITY_MISMATCH'})
        assert windows.same_identity(actual, windows.process_identity(worker['pid']))
        refused(lambda: backend.terminate({**worker, 'user_sid': 'S-1-5-21-111111-222222-333333-9999'}), {'IDENTITY_MISMATCH'})
        assert windows.same_identity(actual, windows.process_identity(worker['pid']))
        stopped = manager.stop(models_only=True)
        assert all(item['status'] == 'stopped' for item in stopped['entries'].values())
    finally:
        backend.cleanup()
    return ['foreign_job_member_refused', 'real_handle_wrong_filetime_refused', 'real_handle_wrong_token_refused',
            'witnessed_worker_survived_invalid_stop']


def race(root, lifecycle, windows, v2):
    helper = root / "scripts/race-start.ps1"
    helper.write_text("param([string]$Barrier)\n$ErrorActionPreference='Stop'\n"
        "$until=(Get-Date).AddSeconds(15)\nwhile (-not (Test-Path -LiteralPath $Barrier)) { "
        "if ((Get-Date) -gt $until) { exit 9 }; Start-Sleep -Milliseconds 10 }\n"
        "& (Join-Path $PSScriptRoot '../.venv/Scripts/python.exe') -I -B "
        "(Join-Path $PSScriptRoot 'lifecycle.py') start --mode mock --models-only\nexit $LASTEXITCODE\n", encoding="utf-8")
    barrier = root / "work/race-go"
    environment = {name: os.environ[name] for name in OS_NAMES if name in os.environ}
    environment.update({name: os.environ[name] for name in ("BACKEND_PORT", "FRONTEND_PORT")})
    backend = lifecycle.NativeBackend(root)
    children = []
    streams = []
    proven = {}
    root_text = str(root).replace("'", "''")
    def collect():
        rows = backend._query("processes", "$rows=@(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { "
            "$_.Name -eq 'python.exe' -and $_.CommandLine -and $_.CommandLine.IndexOf('" + root_text + "',[StringComparison]::OrdinalIgnoreCase) -ge 0 } "
            "| ForEach-Object { [ordered]@{ProcessId=[int]$_.ProcessId;ParentProcessId=[int]$_.ParentProcessId;"
            "CommandLine=$_.CommandLine;CreationFileTime=$_.CreationDate.ToFileTimeUtc()} })")
        for row in rows:
            try:
                actual = witnessed_job_identity(int(row['ProcessId']), windows)
            except windows.WindowsIdentityError:
                continue  # Process already exited; never terminate that PID.
            if actual['created'] // 10 != row['CreationFileTime'] // 10:
                raise RuntimeError('FIXTURE_IDENTITY_CHANGED')
            proven[actual['pid']] = actual
    try:
        for index in range(2):
            # Drain to files: a successful manifest exceeds the Windows pipe
            # buffer. Waiting for exit before reading PIPE would deadlock.
            output = (root / 'work' / ('race-' + str(index) + '.stdout')).open('w', encoding='utf-8')
            error = (root / 'work' / ('race-' + str(index) + '.stderr')).open('w', encoding='utf-8')
            streams.extend((output, error))
            child = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-File", str(helper), "-Barrier", str(barrier)],
                cwd=root, env=environment, stdin=subprocess.DEVNULL, stdout=output, stderr=error,
                text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            children.append(child)
            proven[child.pid] = windows.process_identity(child.pid)
        barrier.write_text("start", encoding="ascii")
        deadline = time.monotonic() + 120
        while any(child.poll() is None for child in children) and time.monotonic() < deadline:
            collect()
            time.sleep(.03)
        assert all(child.poll() is not None for child in children), "Isolated race timed out"
        collect()  # Include a final child whose launcher has just exited.
        for stream in streams:
            stream.close()
        results = [((root / 'work' / ('race-' + str(index) + '.stdout')).read_text(encoding='utf-8'),
                    (root / 'work' / ('race-' + str(index) + '.stderr')).read_text(encoding='utf-8'))
                   for index in range(len(children))]
        (root / "work/race-results.json").write_text(json.dumps([
            {"returncode": child.returncode, "stdout": out, "stderr": err}
            for child, (out, err) in zip(children, results)], sort_keys=True), encoding="utf-8")
        assert all(child.returncode in (0, 2) for child in children) and any(child.returncode == 0 for child in children)
        for child, (out, _) in zip(children, results):
            if child.returncode != 0:
                assert json.loads(out)["code"] == "LOCK_BUSY"
        manifest = json.loads((root / "work/lifecycle/manifest.json").read_text())
        observed = backend.discover()
        assert len(observed) == 2 and {item["role"] for item in observed} == {"backend", "worker"}
        for item in observed:
            assert item["pid"] in proven and windows.same_identity(proven[item["pid"]], windows.process_identity(item["pid"]))
            assert manifest["entries"][item["role"]]["instance_id"] == item["instance_id"]
        # Fixed production CLI is a separate verified controller, not a fake
        # bool or environment authority. It stops only this proven test root.
        result = subprocess.run([str(root / ".venv/Scripts/python.exe"), "-I", "-B", str(root / "scripts/lifecycle.py"),
            "stop", "--models-only"], cwd=root, env=environment, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0, "Verified isolated CLI stop failed"
    finally:
        for stream in streams:
            stream.close()
        # The private Job's kernel membership also covers a witnessed child
        # after its original launcher exits. Never use a PID/name-only fallback.
        collect()
        for item in backend.discover():
            assert item["pid"] in proven, "Unconfirmed race child; cleanup refused"
            actual = windows.process_identity(item["pid"])
            assert windows.same_identity(proven[item["pid"]], actual)
            backend.terminate({**item, **actual})
        for child in children:
            if child.poll() is None:
                actual = windows.process_identity(child.pid)
                assert windows.same_identity(proven[child.pid], actual)
                backend.terminate(actual)
            child.wait(timeout=5)
        assert not backend.discover()
    return ["two_real_powershell_launchers", "at_most_one_api_and_worker", "separate_verified_controller_stop"]


def main():
    bind_disposable_job()
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=("protected", "legacy", "race", "identity"))
    parser.add_argument("directory", type=Path)
    arguments = parser.parse_args()
    directory = arguments.directory.resolve()
    if not directory.is_relative_to(PROJECT / "work/maint-s1") or directory.exists():
        raise RuntimeError("FIXTURE_DIRECTORY_INVALID")
    for parent in directory.parents:
        if parent.exists() and (parent.is_symlink() or getattr(parent.lstat(), "st_file_attributes", 0) & 0x400):
            raise RuntimeError("FIXTURE_DIRECTORY_INVALID")
    directory.mkdir(parents=True)
    assert not any(name.startswith("AGENTFORGE_MODEL_") for name in os.environ)
    root, hashes, lifecycle, windows, v2 = setup(directory)
    executed = globals()[arguments.scenario](root, lifecycle, windows, v2)
    report = {"scenario": arguments.scenario, "passed": True, "checks": executed, "source_sha256": hashes,
              "native_windows_processes": True, "application_transport": "stdlib-stub",
              "real_applications_started": 0, "database_calls": 0, "external_model_calls": 0,
              "cleanup_verified": True}
    if arguments.scenario == "protected":
        report["expiration_test_clock"] = "isolated-61-second-offset"
    (directory / "result.json").write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
