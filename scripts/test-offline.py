"""Run unit/HTTP regressions without inherited credentials, project dotenv or sockets."""
import os
from pathlib import Path
import subprocess
import sys
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--frontend', action='store_true', help='Build/typecheck without server dotenv or inherited credentials')
parser.add_argument('--browser', action='store_true', help='Use a static app and fully mocked HTTP, never the real backend')
args = parser.parse_args()

root = Path(__file__).resolve().parents[1]
safe_names = ('SystemRoot', 'WINDIR', 'PATH', 'PATHEXT', 'COMSPEC', 'TEMP', 'TMP',
              'APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH')
# Read only named OS runtime variables, never enumerate/copy credential values.
environment = {name: os.environ[name] for name in safe_names if name in os.environ}
environment.update(PYTHONPATH=os.pathsep.join((str(root / 'backend'), str(root / 'tests/fixtures'))),
                   PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONIOENCODING='utf-8')
(root / 'work').mkdir(exist_ok=True)
if args.browser:
    result = subprocess.run(['node', 'node_modules/@playwright/test/cli.js', 'test', '--config=playwright.offline.config.ts'],
                            cwd=root / 'frontend', env=environment)
    raise SystemExit(result.returncode)
if args.frontend:
    directory = root / 'frontend'
    checks = [['node', 'node_modules/typescript/bin/tsc', '--noEmit'],
              ['node', 'node_modules/vite/bin/vite.js', 'build']]
    for check in checks:
        result = subprocess.run(check, cwd=directory, env=environment)
        if result.returncode: raise SystemExit(result.returncode)
    raise SystemExit(0)
command = [sys.executable, '-m', 'pytest', '-p', 'offline_guards', '-p', 'pytest_asyncio.plugin',
           '-c', 'backend/pyproject.toml', 'tests/unit', 'tests/http', '-q',
           '--junitxml=work/p5-live-offline.xml']
result = subprocess.run(command, cwd=root, env=environment)
raise SystemExit(result.returncode)
