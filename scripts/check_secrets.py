"""Read-only scan of working files (including untracked), bundles and logs."""
from pathlib import Path
import base64
import subprocess
import sys
from urllib.parse import quote
from dotenv import dotenv_values
from app.core.config import is_model_credential_name

root = Path(__file__).resolve().parents[1]
local = dotenv_values(root / '.env')
values = [value for key, value in local.items() if value and (
    'PASSWORD' in key or 'TOKEN' in key or is_model_credential_name(key) or key.endswith('_URL')
)]
patterns = set()
for value in values:
    patterns.update([value.encode(), quote(value, safe='').encode(), base64.b64encode(value.encode())])
files = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root).decode().split('\0')
failures = []
for name in filter(None, files):
    path = root / name
    if not path.is_file():
        continue
    if not path.resolve().is_relative_to(root.resolve()):
        failures.append(name)
        continue
    data = path.read_bytes()
    if any(pattern in data for pattern in patterns):
        failures.append(name)
# Preserve index scanning too: a staged secret can differ from the working copy.
staged = subprocess.check_output(['git', 'diff', '--cached', '--name-only', '-z'], cwd=root).decode().split('\0')
for name in filter(None, staged):
    entry = subprocess.run(['git', 'show', ':' + name], cwd=root, capture_output=True)
    if entry.returncode == 0 and any(pattern in entry.stdout for pattern in patterns):
        failures.append('index:' + name)
for file in (root / 'frontend' / 'dist').rglob('*'):
    if file.is_file() and any(pattern in file.read_bytes() for pattern in patterns):
        failures.append(str(file.relative_to(root)))
reports = list((root / 'work').glob('*.log')) + list((root / 'work').glob('*.xml')) + list((root / 'work').glob('*e2e*.json')) + list((root / 'work').glob('*real-api*.json')) + list((root / 'work').glob('*worker-restart*.json'))
for file in reports:
    if any(pattern in file.read_bytes() for pattern in patterns):
        failures.append(str(file.relative_to(root)))
for name in failures:
    print('Secret exposure detected in file: ' + name, file=sys.stderr)
if failures:
    raise SystemExit(1)
print(f'PASS: {len(list(filter(None, files)))} tracked/untracked working files, frontend bundle, project logs and test reports contain no known local secret values or common encodings')
