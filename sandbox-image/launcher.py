"""Trusted image entry point: attest, await bounded input, then one isolated child.

This file is never invoked on the Windows host. It contains no Docker client.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import ctypes


def attest():
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    cgroup = Path("/sys/fs/cgroup")
    quota, period = (cgroup / "cpu.max").read_text().split()
    return {"uid": os.getuid(), "gid": os.getgid(), "root_read_only": bool(os.statvfs("/").f_flag & os.ST_RDONLY),
        "seccomp": int(status["Seccomp"]), "no_new_privileges": int(status["NoNewPrivs"]), "cap_eff": status["CapEff"].strip(),
        "cap_prm": status["CapPrm"].strip(), "cap_inh": status["CapInh"].strip(), "cap_amb": status["CapAmb"].strip(),
        "memory_swap_max": int((cgroup / "memory.swap.max").read_text()),
        "interfaces": sorted(path.name for path in Path("/sys/class/net").iterdir()),
        "memory_max": int((cgroup / "memory.max").read_text()), "pids_max": int((cgroup / "pids.max").read_text()),
        "cpu_quota": int(quota), "cpu_period": int(period)}


def main():
    phase = "attest"
    try:
        print("AGENTFORGE_ATTEST:" + json.dumps(attest(), separators=(",", ":")), flush=True)
        phase = "input"
        line = sys.stdin.buffer.readline(300001)
        if not line.endswith(b"\n") or len(line) > 300000:
            return 120
        request = json.loads(line)
        if set(request) != {"code", "timeout_seconds"} or not isinstance(request["code"], str) or not 1 <= len(request["code"].encode()) <= 65536:
            return 120
        timeout = request["timeout_seconds"]
        if type(timeout) is not int or not 1 <= timeout <= 120:
            return 120
        phase = "harden"
        # Same-UID child processes must not inspect/modify the launcher's memory.
        if ctypes.CDLL(None).prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
            return 120
        code_path = Path("/workspace/main.py")
        code_path.write_text(request["code"], encoding="utf-8")
        del request, line
        phase = "spawn"
        child = subprocess.Popen([sys.executable, "-I", "-S", str(code_path)], stdin=subprocess.DEVNULL,
            cwd="/workspace", env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC", "PYTHONUNBUFFERED": "1"},
            start_new_session=True)
        def stop(signum, frame):
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            raise SystemExit(124)
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGALRM, stop)
        signal.alarm(timeout)
        phase = "wait"
        return child.wait()
    except Exception as exc:
        # Runtime errors never print input, environment, file content or traceback.
        allowed = {"ValueError", "TypeError", "OSError", "PermissionError", "FileNotFoundError", "KeyError", "JSONDecodeError"}
        kind = type(exc).__name__
        print("AGENTFORGE_LAUNCHER_ERROR:" + phase + ":" + (kind if kind in allowed else "CONTROL_ERROR"), file=sys.stderr, flush=True)
        return 120


if __name__ == "__main__":
    raise SystemExit(main())
