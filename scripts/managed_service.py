"""Trusted single-process bootstrap; never a generic command runner."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_manager import SAFE_ENV, LifecycleError, LifecycleManager, check_environment, process_facts, _atomic_json, _local_path
from lifecycle_windows import process_identity, same_identity
from lifecycle_channel import ControlServer
from lifecycle_v2 import configuration_digest, controller_peer, same_owner
import lifecycle_runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--role", choices=("backend", "worker"), required=True)
    parser.add_argument("--mode", choices=("mock", "coder"), required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--settings-path", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--generation", type=int, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    state = _local_path(args.state_dir)
    if state != root / "work/lifecycle":
        raise LifecycleError("STATE_DIRECTORY_FORBIDDEN")
    check_environment(args.mode)
    manifest = LifecycleManager(root)._load()
    intent = manifest["entries"][args.role]
    if (intent["status"] != "starting" or intent["instance_id"] != args.instance_id or intent["mode"] != args.mode
            or intent["settings_path"] != str(_local_path(args.settings_path)) or intent["role"] != args.role):
        raise LifecycleError("BOOTSTRAP_NOT_AUTHORIZED")
    if intent.get("policy") != SAFE_ENV or intent["ports"].get(args.role, 0) != args.port:
        raise LifecycleError("BOOTSTRAP_NOT_AUTHORIZED")
    manager = process_identity(intent["manager_pid"])
    own = process_identity(os.getpid())
    if (not manager or not same_identity(manager, intent["creator"]) or not same_owner(manager, own)
            or intent["generation"] != args.generation):
        raise LifecycleError("BOOTSTRAP_NOT_AUTHORIZED")
    # One use only: an identical direct command cannot run the same intent twice.
    # The claim is deliberately never recycled, including after startup failure.
    claim_path = _local_path(state / "ready" / (args.instance_id + ".claim"))
    with claim_path.open("x", encoding="ascii") as claim:
        claim.write(args.instance_id + "\n")
        claim.flush()
        os.fsync(claim.fileno())
    for name, value in SAFE_ENV.items():
        os.environ[name] = value
    os.environ["AGENTFORGE_SETTINGS_FILE"] = args.settings_path
    sys.path.insert(0, str(root / "backend"))
    binding = {"instance_id": args.instance_id, "generation": args.generation,
        "role": args.role, "mode": args.mode, "protected": args.mode == "coder",
        "config_digest": configuration_digest(intent), "state": "STARTING"}
    with ControlServer(root, binding, lambda peer: controller_peer(root, manager, peer)) as control:
        lifecycle_runtime.install(args.role, control.set_ready)
        facts = {**own, "instance_id": args.instance_id, "role": args.role, "control": control.snapshot}
        # This file is a locator only. The parent must authenticate the live pipe
        # and its kernel peer before treating this process as managed or ready.
        _atomic_json(state / "ready" / (args.instance_id + ".json"), facts)
        if args.role == "backend":
            import uvicorn
            uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=args.port, access_log=False, workers=1, reload=False)
        elif args.role == "worker":
            runpy.run_module("app.workers.main", run_name="__main__")


if __name__ == "__main__":
    try:
        main()
    except LifecycleError as exc:
        print(json.dumps({"status": "refused", "code": exc.code}))
        raise SystemExit(2)
    except Exception:
        print(json.dumps({"status": "refused", "code": "BOOTSTRAP_UNAVAILABLE"}))
        raise SystemExit(2)
