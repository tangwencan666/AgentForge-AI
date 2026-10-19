"""Actual Windows lifecycle/pipe acceptance with explicitly stubbed services."""
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
OS_NAMES = ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "TEMP", "TMP",
            "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")


@pytest.mark.skipif(os.name != "nt", reason="Requires actual Windows processes and named pipes")
@pytest.mark.parametrize("scenario", ["protected", "legacy", "race", "identity"])
def test_native_lifecycle_v2_isolated(scenario):
    directory = ROOT / "work/maint-s1" / ("native-" + scenario + "-" + uuid4().hex)
    environment = {name: os.environ[name] for name in OS_NAMES if name in os.environ}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    # Target the actual fixture PID, not the venv forwarding launcher. On an
    # outer timeout its own kill-on-close Job Object reaps only test descendants.
    result = subprocess.run([getattr(sys, "_base_executable", sys.executable), "-I", "-B", str(ROOT / "tests/fixtures/s1_lifecycle_native.py"),
        scenario, str(directory)], cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=360, creationflags=subprocess.CREATE_NO_WINDOW)
    # Only this fixture's fixed code and synthetic values are present. Persist
    # diagnostic output under its unique test directory, never the main logs.
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "stdout.txt").write_text(result.stdout, encoding="utf-8")
    (directory / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    assert result.returncode == 0, "Isolated native lifecycle scenario failed; inspect its dedicated evidence"
    report = json.loads(result.stdout)
    assert report["passed"] and report["cleanup_verified"]
    assert report["native_windows_processes"] and report["application_transport"] == "stdlib-stub"
    assert report["real_applications_started"] == report["database_calls"] == report["external_model_calls"] == 0
