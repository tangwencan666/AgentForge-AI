"""Only local services, database and key-name presence. Never resolves a model key."""
import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
import httpx
from sqlalchemy import select, func, text
from app.core.config import Settings
from app.domain.entities import ModelSlot
from app.domain.permits import ExecutionPermit
from app.domain.tasks import AgentTask, ModelOperation
from app.providers.router import PricePolicy
from app.repositories.connections import Connections
from app.services.context import content_hash
from app.services.tasks import TERMINAL

REVISION = '0008_execution_permits'
ROOT = Path(__file__).resolve().parents[1]


def managed_status():
    """Fixed read-only lifecycle CLI observer; never inherit model credentials."""
    public = ('SystemRoot', 'WINDIR', 'PATH', 'PATHEXT', 'COMSPEC', 'TEMP', 'TMP',
              'APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH')
    environment = {name: os.environ[name] for name in public if name in os.environ}
    try:
        result = subprocess.run([str(ROOT / '.venv/Scripts/python.exe'), '-B',
            str(ROOT / 'scripts/lifecycle.py'), 'status'], cwd=ROOT, env=environment,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding='utf-8',
            timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode != 0 or result.stderr:
            raise ValueError
        state = json.loads(result.stdout)
        if not isinstance(state, dict) or state.get('version') != 2 or not isinstance(state.get('entries'), dict):
            raise ValueError
        return state
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, TypeError):
        raise RuntimeError('Lifecycle status unavailable or unverified') from None


def validate_local_policy(settings):
    if sys.flags.optimize:
        raise RuntimeError("Optimized Python is not supported for safety validation")
    assert not settings.real_calls_enabled and settings.real_daily_budget_usd == settings.real_test_budget_usd == 0
    assert not settings.single_use_permits_enabled and settings.real_worker_mode == 'deny'
    assert settings.model_permit_issuer_token is None
    assert settings.real_max_retries == 0 and settings.model_credentials_env_only
    assert settings.real_daily_token_limit == 8256 and settings.real_test_max_calls == 1
    assert settings.model_hosts == frozenset({'api.deepseek.com'})
    assert settings.model_credential_hosts.get('AGENTFORGE_MODEL_CODER_KEY') == ['api.deepseek.com']
    assert os.environ.get('AGENTFORGE_EXTERNAL_MODELS_BLOCKED') == '1'


def runtime_ready(state):
    return (state.get('worker_available') is True and state.get('configuration_consistent') is True
        and state.get('credential_presence_consistent') is True
        and all(state.get(role) and state[role].get('coder_credential_present') is True for role in ('api', 'worker')))


def validate_runtime_state(state, expected_price_digest):
    # Equality alone accepts False/False; successful inheritance requires two explicit True booleans.
    assert runtime_ready(state)
    for role in ('api', 'worker'):
        policy = state[role]['policy']
        assert not policy['real_calls_enabled'] and policy['external_calls_blocked']
        assert policy['daily_budget_usd'] == policy['test_budget_usd'] == '0'
        assert policy['real_max_retries'] == 0 and policy['credentials_env_only']
        assert policy['daily_token_limit'] == 8256 and policy['test_max_calls'] == 1
        assert policy['permit_required'] and not policy['permit_issuance_enabled'] and policy['real_worker_mode'] == 'deny'
        assert policy['deepseek_host_allowed'] and policy['coder_audience_exact']
        assert policy['flash_price_digest'] == expected_price_digest


async def main(*, before_restart=False):
    settings = Settings()
    validate_local_policy(settings)
    template_file = json.loads(Path('config/deepseek-coder-local.json').read_text())
    expected_price_digest = content_hash(PricePolicy.model_validate(template_file['price']).model_dump(mode='json'))
    assert content_hash(PricePolicy.model_validate(settings.model_prices['openai_compatible/deepseek-flash']).model_dump(mode='json')) == expected_price_digest
    c = Connections(settings)
    try:
        async with c.sessions() as session:
            revision = await session.scalar(text('SELECT version_num FROM alembic_version'))
            assert revision == REVISION
            active = await session.scalar(select(func.count()).select_from(AgentTask).where(AgentTask.status.not_in(TERMINAL)))
            real_ops = await session.scalar(select(func.count()).select_from(ModelOperation).where(ModelOperation.is_mock.is_(False)))
            active_permits = await session.scalar(select(func.count()).select_from(ExecutionPermit).where(
                ExecutionPermit.status.in_({'ISSUED', 'CLAIMED', 'DISPATCH_COMMITTED'})))
            assert active == 0 and real_ops == 0 and active_permits == 0
            rows = (await session.scalars(select(ModelSlot).where(ModelSlot.tenant_id == settings.tenant_id))).all()
            assert {row.role for row in rows} == {'planner', 'coder', 'researcher', 'reviewer'}
            assert all(not row.enabled for row in rows)
            coder_row = next(row for row in rows if row.role == 'coder')
            assert all(getattr(coder_row, name) == value for name, value in template_file['slot'].items())
        if before_restart:
            # Do not require old API/Worker processes to possess the user's new environment.
            print('PASS: migration 0008; no active tasks/permits; real-model operations = 0; four slots disabled; zero-fee policy enforced')
            return
        from app.core.config import runtime_env_file
        from dotenv import dotenv_values
        ports = dotenv_values(runtime_env_file(), interpolate=False)  # Service-only file, no model credentials.
        address = 'http://127.0.0.1:' + ports.get('BACKEND_PORT', '18100')
        headers = {'Authorization': 'Bearer ' + settings.admin_token.get_secret_value()}
        managed_before = managed_status()
        expected_pids = {role: managed_before['entries'].get(entry_role, {}).get('pid')
                         for role, entry_role in (('api', 'backend'), ('worker', 'worker'))}
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            response = await client.get(address + '/health/ready')
            assert response.status_code == 200
            for _ in range(15):
                response = await client.get(address + '/api/v1/models/runtime-status', headers=headers)
                assert response.status_code == 200
                state = response.json()['data']
                if (runtime_ready(state) and all(state[role]['process_id'] == expected_pids[role]
                                                for role in ('api', 'worker'))):
                    break
                await asyncio.sleep(1)
            validate_runtime_state(state, expected_price_digest)
            # Bind observations to the exact managed launch, not stale Redis
            # presence or a different process that happens to use the same port.
            managed = managed_status()
            for role, entry_role in (('api', 'backend'), ('worker', 'worker')):
                entry = managed['entries'].get(entry_role)
                if (not entry or entry['status'] != 'running' or not entry['protected']
                        or entry['mode'] != 'coder' or entry['pid'] != state[role]['process_id']):
                    raise RuntimeError('Runtime does not match the managed Coder launch')
                prior = managed_before['entries'].get(entry_role, {})
                if any(entry.get(key) != prior.get(key) for key in
                       ('instance_id', 'generation', 'pid', 'created', 'user_sid', 'logon_sid', 'session_id')):
                    raise RuntimeError('Managed Coder identity changed during verification')
            response = await client.get(address + '/api/v1/model-slots', headers=headers)
            assert response.status_code == 200
            slots = response.json()['data']
            template = template_file['slot']
            coder = next(slot for slot in slots if slot['role'] == 'coder')
            assert all(coder[name] == value for name, value in template.items())
            assert {slot['role'] for slot in slots} == {'planner', 'coder', 'researcher', 'reviewer'}
            assert all(not slot['enabled'] for slot in slots)
            assert state['api']['slot_versions'] == state['worker']['slot_versions'] == {slot['role']: slot['version'] for slot in slots}
            result = {'migration_revision': revision,
                'coder': {name: coder[name] for name in template} | {'version': coder['version']},
                'api_coder_credential_present': state['api']['coder_credential_present'],
                'worker_coder_credential_present': state['worker']['coder_credential_present'],
                'configuration_consistent': True, 'slot_versions': state['api']['slot_versions'],
                'policy': state['api']['policy'], 'credential_check': state['credential_check'],
                'active_tasks': active, 'active_permits': active_permits, 'persisted_real_model_operations': real_ops}
            Path('work/p5-live-preflight/coder-state.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result))
    finally:
        await c.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--before-restart', action='store_true')
    args = parser.parse_args()
    try:
        asyncio.run(main(before_restart=args.before_restart))
    except Exception as exc:
        print('Local Coder check failed: ' + type(exc).__name__)
        raise SystemExit(1) from None
