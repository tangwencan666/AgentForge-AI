"""S2 maintenance boundaries: isolated child, fake backend, no real services.

No parent credential values are copied or saved. All lifecycle state used by this
suite lives in a fresh work/seal-fixes subtree, never the project's live manifest.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/seal_s2_probe.py"
SYSTEM_NAMES = ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP",
    "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
IMAGE = "sha256:" + "a" * 64
ENTRY_CASES = [
    ("bootstrap_local.py", []),
    ("bootstrap-sandbox.py", ["--image-id", IMAGE]),
    ("bootstrap-sandbox.py", ["--image-id", IMAGE, "--replace-approved-image"]),
    ("bootstrap-p4.py", []),
    ("migrate.py", ["upgrade"]), ("migrate.py", ["check"]), ("migrate.py", ["current"]),
    ("configure-deepseek-coder.py", []), ("p5-live-preflight.py", ["prepare"]),
    ("p5-live-state-check.py", []), ("p5-live-state-check.py", ["--stop"]),
    ("prepare-permit-tests.py", []),
    ("deploy-permit-database.py", ["backup"]), ("deploy-permit-database.py", ["migrate"]),
    ("deploy-permit-database.py", ["verify"]), ("verify-permit-deployment.py", []),
    ("verify-permit-migration.py", []), ("verify-permit-restoration.py", []),
    ("p5-live-database-check.py", ["backup"]), ("p5-live-database-check.py", ["verify"]),
    ("p5-live-database-check.py", ["owner"]),
    ("permit-test-runner-isolation.py", ["pause"]), ("permit-test-runner-isolation.py", ["restore"]),
    ("p2-compose-probe.py", []), ("test-real-models.py", []),
    ("freeze-lock.py", []),
]
DIRECT_CASES = [
    ("bootstrap_local.py", "main", [], {}), ("bootstrap-sandbox.py", "main", [], {}),
    ("bootstrap-p4.py", "main", [], {}), ("migrate.py", "main", [], {}),
    ("configure-deepseek-coder.py", "main", [], {}), ("p5-live-preflight.py", "prepare", [], {}),
    ("p5-live-state-check.py", "main", [], {"stop": True}),
    ("p5-live-state-check.py", "main", [], {"stop": False}),
    ("prepare-permit-tests.py", "main", [], {}),
    ("deploy-permit-database.py", "backup", [], {}), ("deploy-permit-database.py", "main", ["migrate"], {}),
    ("deploy-permit-database.py", "verify", [], {}),
    ("verify-permit-deployment.py", "main", [False], {}),
    ("verify-permit-migration.py", "main", [], {}), ("verify-permit-restoration.py", "main", [], {}),
    ("p5-live-database-check.py", "backup", [], {}), ("p5-live-database-check.py", "verify", [], {}),
    ("p5-live-database-check.py", "owner_check", [], {}),
    ("permit-test-runner-isolation.py", "main", ["pause"], {}),
    ("permit-test-runner-isolation.py", "main", ["restore"], {}),
    ("p2-compose-probe.py", "main", [], {}), ("test-real-models.py", "run", [], {}),
    ("lifecycle_regression.py", "run_phase", ["__FIXTURE_ROOT__", "p5"], {}),
    ("freeze-lock.py", "main", [], {}),
    ("prepare-permit-tests.py", "command", ["docker", "stop", "agentforge-p3-runner"], {}),
    ("deploy-permit-database.py", "command", ["docker", "stop", "agentforge-p3-runner"], {}),
    ("p5-live-database-check.py", "command", ["docker", "stop", "agentforge-p1-postgres"], {}),
    ("permit-test-runner-isolation.py", "command", ["docker", "stop", "agentforge-p3-runner"], {}),
]
HELPER_SCOPE_CASES = [
    ("prepare-permit-tests.py", "permit.verify", ["docker", "stop", "agentforge-p3-runner"], {}),
    ("deploy-permit-database.py", "permit.verify", ["docker", "stop", "agentforge-p3-runner"], {}),
    ("p5-live-database-check.py", "database.owner", ["docker", "stop", "agentforge-p1-postgres"], {}),
    ("p5-live-database-check.py", "database.verify", ["docker", "stop", "agentforge-p1-postgres"], {}),
    ("permit-test-runner-isolation.py", "permit.verify", ["docker", "stop", "agentforge-p3-runner"], {}),
    ("permit-test-runner-isolation.py", "runner.pause", ["docker", "stop", "other-project-runner"], {}),
    ("permit-test-runner-isolation.py", "runner.pause", ["docker", "start", "agentforge-p3-runner"], {}),
    ("p5-live-database-check.py", "database.owner", ["docker", "port", "agentforge-p1-postgres", "5432/tcp"],
        {"input": "explicit-offline-input-forbidden"}),
]
HELPER_ALLOWED_CASES = [
    ("deploy-permit-database.py", "permit.verify", ["docker", "ps", "-aq", "--filter", "label=agentforge.sandbox.execution"]),
    ("prepare-permit-tests.py", "permit.restoration", ["docker", "ps", "-aq", "--filter", "label=agentforge.sandbox.execution"]),
    ("prepare-permit-tests.py", "permit.verify", ["docker", "inspect", "--format",
        '{{index .Config.Labels "com.docker.compose.project"}}', "agentforge-p1-postgres"]),
    ("p5-live-database-check.py", "database.owner", ["docker", "exec", "agentforge-p1-postgres", "psql",
        "-U", "postgres", "-d", "agentforge", "-Atc", "SELECT current_database()"]),
    ("permit-test-runner-isolation.py", "runner.pause", ["docker", "stop", "agentforge-p3-runner"]),
    ("permit-test-runner-isolation.py", "runner.restore", ["docker", "start", "agentforge-p3-runner"]),
]
OPERATIONS = ["bootstrap.local", "bootstrap.sandbox", "bootstrap.p4", "preflight.prepare",
    "configure.coder", "state.inspect", "state.hold", "migrate.check", "migrate.current",
    "migrate.upgrade", "runner.pause", "runner.restore", "probe.mock", "model.observe",
    "permit.verify", "permit.restoration", "bootstrap.sandbox.rotate", "database.verify", "database.owner",
    "dependency.freeze", "regression.run", "permit.prepare", "permit.backup", "permit.migrate",
    "permit.rehearsal", "database.rehearsal"]
SCENARIOS = ["clean_allowed", "unknown_record", "concurrent_lock", "finally_cannot_restore",
    "async_action_holds_lock", "unknown_operation", "risky_requires_confirmation", "root_mismatch",
    "credential_environment_refused", "risky_confirmation_is_one_use", "confirmation_revalidates_state",
    "confirmation_expires", "body_error_releases_lock", "cli_lease_lasts_until_exit",
    "different_async_tasks_cannot_reenter", "synchronous_cli_hands_off_to_async_without_reapproval",
    "synchronous_cli_handoff_still_excludes_other_tasks"]


def expected_entry_operation(script, arguments):
    fixed = {"bootstrap_local.py": "bootstrap.local", "bootstrap-p4.py": "bootstrap.p4",
        "configure-deepseek-coder.py": "configure.coder", "p5-live-preflight.py": "preflight.prepare",
        "prepare-permit-tests.py": "permit.prepare", "verify-permit-deployment.py": "permit.verify",
        "verify-permit-migration.py": "permit.rehearsal", "verify-permit-restoration.py": "permit.restoration",
        "p2-compose-probe.py": "probe.mock", "test-real-models.py": "model.observe", "freeze-lock.py": "dependency.freeze"}
    if script in fixed:
        return fixed[script]
    if script == "bootstrap-sandbox.py":
        return "bootstrap.sandbox.rotate" if "--replace-approved-image" in arguments else "bootstrap.sandbox"
    if script == "p5-live-state-check.py":
        return "state.hold" if "--stop" in arguments else "state.inspect"
    operation = arguments[0] if arguments else "upgrade"
    return {"migrate.py": {"upgrade": "migrate.upgrade", "check": "migrate.check", "current": "migrate.current"},
        "deploy-permit-database.py": {"backup": "permit.backup", "migrate": "permit.migrate", "verify": "permit.verify"},
        "p5-live-database-check.py": {"backup": "database.rehearsal", "verify": "database.verify", "owner": "database.owner"},
        "permit-test-runner-isolation.py": {"pause": "runner.pause", "restore": "runner.restore"}}[script][operation]


def probe(mode, payload):
    directory = ROOT / "work/seal-fixes" / uuid4().hex
    directory.mkdir(parents=True)
    environment = {name: os.environ[name] for name in SYSTEM_NAMES if name in os.environ}
    environment.update(PYTHONDONTWRITEBYTECODE="1", TEMP=str(directory), TMP=str(directory))
    command = [sys.executable, "-B", "-I", str(FIXTURE), "--mode", mode,
        "--directory", str(directory), "--payload", json.dumps(payload, separators=(",", ":"))]
    result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, "Isolated S2 probe failed; raw child output is intentionally withheld"
    evidence = json.loads(result.stdout)
    assert evidence["passed"] is True
    assert evidence["real_services_started"] == evidence["database_calls"] == evidence["external_model_calls"] == 0


@pytest.mark.parametrize("script,arguments", ENTRY_CASES)
def test_cli_refuses_before_business_access_or_side_effects(script, arguments):
    probe("entry", {"script": script, "arguments": arguments,
        "expected_operation": expected_entry_operation(script, arguments)})


@pytest.mark.parametrize("script,function,arguments,keywords", DIRECT_CASES)
def test_imported_side_effect_function_cannot_bypass_maintenance(script, function, arguments, keywords):
    probe("direct", {"script": script, "function": function, "arguments": arguments, "keywords": keywords,
        "expect_existing_context_required": function == "command"})


@pytest.mark.parametrize("script,operation,arguments,keywords", HELPER_SCOPE_CASES)
def test_helper_cannot_expand_an_existing_scope(script, operation, arguments, keywords):
    probe("helper-scope", {"script": script, "operation": operation, "arguments": arguments, "keywords": keywords})


@pytest.mark.parametrize("script,operation,arguments", HELPER_ALLOWED_CASES)
def test_fixed_helper_command_reaches_only_the_explicit_subprocess_stub(script, operation, arguments):
    probe("helper-scope", {"script": script, "operation": operation, "arguments": arguments,
        "keywords": {}, "explicit_stub_allowed": True})


@pytest.mark.parametrize("operation", OPERATIONS)
def test_fixed_maintenance_operation_refuses_protected_state(operation):
    probe("operation", {"operation": operation})


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_maintenance_policy_state_and_lock_boundaries(scenario):
    probe("scenario", {"scenario": scenario})
