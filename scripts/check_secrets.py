"""Read-only scan of working files (including untracked), bundles and logs."""
from pathlib import Path
import base64
import subprocess
import sys
import argparse
import re
from urllib.parse import quote
from dotenv import dotenv_values
from app.core.config import is_model_credential_name, runtime_env_file

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--no-local-secrets', action='store_true', help='Never read dotenv; check credential formats instead of known secret values')
args = parser.parse_args()
local = {} if args.no_local_secrets else dotenv_values(runtime_env_file())
values = [value for key, value in local.items() if value and (
    'PASSWORD' in key or key.endswith('_TOKEN') or is_model_credential_name(key) or key.endswith('_URL')
)]
patterns = set()
for value in values:
    patterns.update([value.encode(), quote(value, safe='').encode(), base64.b64encode(value.encode())])
files = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root).decode().split('\0')
failures = []
def exposed(data):
    return any(pattern in data for pattern in patterns) or bool(re.search(rb'\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}\b', data))

for name in filter(None, files):
    path = root / name
    if not path.is_file():
        continue
    if not path.resolve().is_relative_to(root.resolve()):
        failures.append(name)
        continue
    data = path.read_bytes()
    if exposed(data):
        failures.append(name)
# Preserve index scanning too: a staged secret can differ from the working copy.
staged = subprocess.check_output(['git', 'diff', '--cached', '--name-only', '-z'], cwd=root).decode().split('\0')
for name in filter(None, staged):
    entry = subprocess.run(['git', 'show', ':' + name], cwd=root, capture_output=True)
    if entry.returncode == 0 and exposed(entry.stdout):
        failures.append('index:' + name)
for file in (root / 'frontend' / 'dist').rglob('*'):
    if file.is_file() and exposed(file.read_bytes()):
        failures.append(str(file.relative_to(root)))
reports = list((root / 'work').glob('*.log')) + list((root / 'work').glob('*.xml')) + list((root / 'work').glob('*e2e*.json')) + list((root / 'work').glob('*real-api*.json')) + list((root / 'work').glob('*worker-restart*.json'))
if args.no_local_secrets:
    reports += list((root / 'work').glob('p5-live-*.xml')) + list((root / 'work').glob('p5-live-*.json'))
for file in reports:
    if exposed(file.read_bytes()):
        failures.append(str(file.relative_to(root)))
for name in failures:
    print('Secret exposure detected in file: ' + name, file=sys.stderr)
if failures:
    raise SystemExit(1)
if args.no_local_secrets:
    print(f'PASS: credential-format scan of {len(list(filter(None, files)))} working files, index, bundle and P5-LIVE reports; no dotenv or known-key values read; not a known-secret comparison')
else:
    print(f'PASS: {len(list(filter(None, files)))} tracked/untracked working files, frontend bundle, project logs and test reports contain no known local secret values or common encodings')
