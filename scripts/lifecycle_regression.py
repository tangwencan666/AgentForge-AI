"""Fixed maintenance regressions; called only inside the shared lifecycle lease.

No main API/Worker stop, start or automatic restoration. Existing images only.
"""
import os
from pathlib import Path
from maintenance_policy import maintenance_action, PROJECT_ROOT


@maintenance_action("regression.run")
def run_phase(root, phase):
    from lifecycle_manager import SAFE_ENV, LifecycleError
    if phase not in {"p2", "p3", "p4", "p5"}:
        raise LifecycleError("SCOPE_INVALID")
    root = Path(root).resolve()
    if root != PROJECT_ROOT:
        raise LifecycleError("MAINTENANCE_PROJECT_MISMATCH")
    if phase == "p3":
        raise LifecycleError("S1_RUNNER_ISOLATION_BLOCKED")
    # The old shared maintenance lease is retained. It is not evidence that a
    # database, queue or Compose project is a disposable test instance.
    locator = os.environ.get("AGENTFORGE_S1_MANIFEST")
    if not locator:
        raise LifecycleError("S1_ISOLATION_MANIFEST_REQUIRED")
    from s1_isolation import validate_isolation
    try:
        verified = validate_isolation(root, Path(locator))
    except Exception:
        raise LifecycleError("S1_ISOLATION_UNVERIFIED") from None
    selected = os.environ.get("AGENTFORGE_SETTINGS_FILE")
    if (not selected or Path(selected).resolve() != Path(verified["settings_path"]).resolve()
            or any(name in os.environ for name in ("AGENTFORGE_DATABASE_URL", "AGENTFORGE_REDIS_URL"))):
        raise LifecycleError("S1_SETTINGS_REFERENCE_MISMATCH")
    for name, value in SAFE_ENV.items():
        os.environ[name] = value
    os.environ["AGENTFORGE_RUN_INTEGRATION"] = "1"
    os.environ["AGENTFORGE_RUN_SANDBOX"] = "0"
    # Only non-secret module/search metadata; model keys are never copied.
    import sys
    for directory in (root / "backend", root / "tests/fixtures"):
        sys.path.insert(0, str(directory))
    suites = {
        "p2": ["test_dependencies.py", "test_workflows.py"],
        "p3": ["test_sandbox.py", "test_sandbox_failures.py"],
        "p4": ["test_capabilities.py"],
        "p5": ["test_dependencies.py", "test_real_agents.py", "test_model_runtime_status.py", "test_execution_permits.py"],
    }
    import pytest
    paths = [root / "tests/unit", root / "tests/http"] + [root / "tests/integration" / name for name in suites[phase]]
    arguments = ["-p", "preflight_guards", "-c", str(root / "backend/pyproject.toml"),
                 *map(str, paths), "-q", "--tb=short",
                 "--junitxml=" + str(Path(verified["run_directory"]) / ("lifecycle-" + phase + ".xml"))]
    # No finally block may restore main services or remove shared containers.
    return int(pytest.main(arguments))
