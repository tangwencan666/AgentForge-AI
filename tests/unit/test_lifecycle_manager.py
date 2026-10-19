"""Offline acceptance: isolated fake credentials, never real app/DB/vendor calls.

The parent test process never reads any model credential value, even to save it
for monkeypatch restoration. Each case gets an explicit environment whitelist.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "lifecycle_acceptance.py"
SYSTEM_NAMES = ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP",
    "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
CASES = [
    "fake_coder_protected_start", "keyless_maintenance_rejected", "keyless_test_stop_rejected",
    "finally_cannot_replace_protected", "concurrent_start_cannot_overwrite", "reused_pid_is_never_terminated",
    "exited_identity_is_safely_cleared", "mock_without_protected_starts", "refusal_has_no_business_side_effects",
    "credentials_do_not_enter_evidence", "closed_permit_budget_and_egress_preserved", "p3_p4_safety_files_unchanged",
]


@pytest.mark.parametrize("scenario", CASES)
def test_lifecycle_offline_acceptance(scenario):
    directory = ROOT / "work" / "lifecycle-tests" / uuid4().hex
    directory.mkdir(parents=True)
    child_env = {name: os.environ[name] for name in SYSTEM_NAMES if name in os.environ}
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    child_env["TEMP"] = child_env["TMP"] = str(directory)
    command = [sys.executable, str(FIXTURE), "--scenario", scenario, "--directory", str(directory)]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(command, cwd=ROOT, env=child_env, capture_output=True, text=True,
        timeout=360, creationflags=flags)
    assert result.returncode == 0, "Isolated lifecycle acceptance failed; raw child output is intentionally withheld"
    record = json.loads(result.stdout)
    assert record["scenario"] == scenario and record["passed"] is True
    assert record["real_services_started"] == record["database_calls"] == record["external_model_calls"] == 0
