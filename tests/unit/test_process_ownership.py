from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows local lifecycle ownership checks')
def test_local_lifecycle_ownership_guards():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(['powershell', '-NoProfile', '-File', str(root / 'scripts/test-process-ownership.ps1')],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0
