"""Check staged files and frontend bundles against local secrets, without printing values."""
from pathlib import Path
import base64
import subprocess
import sys
from urllib.parse import quote
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
local = dotenv_values(root / '.env')
values = [value for key, value in local.items() if value and (
    'PASSWORD' in key or 'TOKEN' in key or key.startswith('AGENTFORGE_MODEL_') or key.endswith('_URL')
)]
patterns = set()
for value in values:
    patterns.update([value.encode(), quote(value, safe='').encode(), base64.b64encode(value.encode())])
staged = subprocess.check_output(['git', 'diff', '--cached', '--name-only', '-z'], cwd=root).decode().split('\0')
failures = []
for name in filter(None, staged):
    data = subprocess.check_output(['git', 'show', ':' + name], cwd=root)
    if any(pattern in data for pattern in patterns):
        failures.append(name)
for file in (root / 'frontend' / 'dist').rglob('*'):
    if file.is_file() and any(pattern in file.read_bytes() for pattern in patterns):
        failures.append(str(file.relative_to(root)))
for file in (root / 'work').glob('*.log'):
    if any(pattern in file.read_bytes() for pattern in patterns):
        failures.append(str(file.relative_to(root)))
for name in failures:
    print('Secret exposure detected in file: ' + name, file=sys.stderr)
if failures:
    raise SystemExit(1)
print('PASS: staged files, frontend bundle and project logs contain no known local secret values or common encodings')
