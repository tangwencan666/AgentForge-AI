"""Offline lifecycle child: no application imports, credentials, sockets or DB.

Only non-secret process identity, public safety flags and environment-variable
name presence are written. Test children are short lived even if their owner dies.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import signal
import sys
import time

PROJECT = Path(__file__).resolve().parents[2]


def creation_ticks():
    if os.name != "nt":
        return None
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
    if not kernel.GetProcessTimes(kernel.GetCurrentProcess(), ctypes.byref(created), ctypes.byref(exited),
            ctypes.byref(kernel_time), ctypes.byref(user_time)):
        raise RuntimeError("Offline child process identity unavailable")
    return (created.dwHighDateTime << 32) | created.dwLowDateTime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-file", required=True, type=Path)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--role", choices=["api", "backend", "worker", "frontend"], required=True)
    parser.add_argument("--lifetime-seconds", type=float, default=30)
    args = parser.parse_args()
    ready = args.ready_file.resolve()
    if not ready.is_relative_to((PROJECT / "work").resolve()) or not .1 <= args.lifetime_seconds <= 60:
        raise RuntimeError("Offline child paths or lifetime are outside test scope")
    flags = ["AGENTFORGE_REAL_CALLS_ENABLED", "AGENTFORGE_SINGLE_USE_PERMITS_ENABLED",
        "AGENTFORGE_REAL_WORKER_MODE", "AGENTFORGE_REAL_DAILY_BUDGET_USD",
        "AGENTFORGE_REAL_TEST_BUDGET_USD", "AGENTFORGE_EXTERNAL_MODELS_BLOCKED", "AGENTFORGE_REAL_MAX_RETRIES"]
    record = {"pid": os.getpid(), "created": creation_ticks(), "instance_id": args.instance_id,
        "role": args.role, "coder_credential_present": "AGENTFORGE_MODEL_CODER_KEY" in os.environ,
        "issuer_name_present": "AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN" in os.environ,
        "policy": {name: os.environ.get(name) for name in flags}, "service_starts": 0,
        "database_calls": 0, "external_model_calls": 0}
    ready.parent.mkdir(parents=True, exist_ok=True)
    ready.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    stopping = False
    def stop(signum, frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    deadline = time.monotonic() + args.lifetime_seconds
    while not stopping and time.monotonic() < deadline:
        time.sleep(.03)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("OFFLINE_LIFECYCLE_CHILD_FAILED", file=sys.stderr)
        raise SystemExit(1) from None
