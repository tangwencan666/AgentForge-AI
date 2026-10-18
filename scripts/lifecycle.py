"""Fixed project CLI: no arbitrary command, root, state-dir or force override."""
import argparse
import json
from pathlib import Path
import sys
# Isolated Python (-I) intentionally omits the script directory. Only the fixed
# sibling directory is trusted here; never import from cwd or PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lifecycle_manager import LifecycleError, LifecycleManager


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop", "restart-worker", "status", "manual-stop", "maintenance-run"))
    parser.add_argument("--mode", choices=("mock", "coder"), default="mock")
    parser.add_argument("--models-only", action="store_true")
    parser.add_argument("--worker-only", action="store_true")
    parser.add_argument("--restart-models", action="store_true")
    parser.add_argument("--phase", choices=("p2", "p3", "p4", "p5"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manager = LifecycleManager(root)
    try:
        if args.action == "start":
            result = manager.start(args.mode, args.models_only, args.restart_models)
        elif args.action == "stop":
            result = manager.stop(args.models_only, args.worker_only)
        elif args.action == "restart-worker":
            result = manager.restart_worker()
        elif args.action == "status":
            result = manager.status()
        elif args.action == "manual-stop":
            result = manager.manual_stop(models_only=args.models_only)
        else:
            if args.phase is None:
                raise LifecycleError("SCOPE_INVALID")
            with manager.maintenance_session():
                from lifecycle_regression import run_phase
                return run_phase(root, args.phase)
        # Only non-secret manager metadata is serialized.
        print(json.dumps(result, sort_keys=True))
        return 0
    except LifecycleError as exc:
        print(json.dumps({"status": "refused", "code": exc.code}))
        return 2
    except Exception:
        print(json.dumps({"status": "refused", "code": "LIFECYCLE_UNAVAILABLE"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
