"""Read-only final checks on the original 0007 database and closed local services."""

from maintenance_policy import cli_gate, maintenance_action
cli_gate(__file__, __name__)

import asyncio
import importlib.util
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
import httpx
from sqlalchemy import select, text, func
from app.core.config import Settings, runtime_env_file
from app.domain.entities import ModelSlot
from app.domain.tasks import AgentTask, ModelOperation
from app.repositories.connections import Connections
from app.services.tasks import TERMINAL

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('permit_test_setup', ROOT/'scripts/prepare-permit-tests.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


@maintenance_action("permit.restoration")
async def main():
    settings = Settings()
    assert runtime_env_file() == ROOT/'work/p5-live-preflight/.env'
    assert urlsplit(settings.database_url.get_secret_value()).port == 15432
    assert not settings.real_calls_enabled and not settings.single_use_permits_enabled and settings.real_worker_mode == 'deny'
    assert settings.real_daily_budget_usd == settings.real_test_budget_usd == 0 and settings.real_max_retries == 0
    assert settings.model_permit_issuer_token is None and settings.model_credentials_env_only
    assert os.environ.get('AGENTFORGE_EXTERNAL_MODELS_BLOCKED') == '1'
    before = json.loads((ROOT/'work/p5-live-preflight/permit-test/backup.json').read_text())
    after = await helper.snapshot()
    assert after['columns'] == before['columns'] and after['fingerprints'] == before['fingerprints']
    c = Connections(settings)
    try:
        async with c.sessions() as session:
            slots = (await session.scalars(select(ModelSlot).where(ModelSlot.tenant_id == settings.tenant_id))).all()
            assert len(slots) == 4 and not any(row.enabled for row in slots)
            active = await session.scalar(select(func.count()).select_from(AgentTask).where(
                AgentTask.is_mock.is_(False), AgentTask.options['workflow'].astext.is_distinct_from('sandbox'), AgentTask.status.not_in(TERMINAL)))
            operations = await session.scalar(select(func.count()).select_from(ModelOperation).where(ModelOperation.is_mock.is_(False)))
            assert active == operations == 0
        async with httpx.AsyncClient(base_url='http://127.0.0.1:18100', trust_env=False, timeout=5) as client:
            assert (await client.get('/health/ready')).status_code == 200
            headers = {'Authorization': 'Bearer ' + settings.admin_token.get_secret_value()}
            runtime = (await client.get('/api/v1/models/runtime-status', headers=headers)).json()['data']
            assert runtime['worker_available'] and runtime['configuration_consistent'] and runtime['credential_presence_consistent']
            assert not runtime['api']['coder_credential_present'] and not runtime['worker']['coder_credential_present']
            unavailable = await client.get('/api/v1/model-permits/' + str(uuid4()), headers=headers)
            assert unavailable.status_code == 503 and unavailable.json()['error']['code'] == 'PERMIT_MIGRATION_REQUIRED'
            runner = (await client.get('/api/v1/sandbox/policy', headers=headers)).json()['data']['runner_status']
            assert runner == {'available':True,'blocked':False,'active_executions':0}
            assert (await client.get('http://127.0.0.1:15173')).status_code == 200
        workers = [name async for name in c.redis.scan_iter(match='agentforge:p2:worker:*')]
        assert len(workers) == 1
        assert not helper.command('docker','ps','-aq','--filter','label=agentforge.sandbox.execution')
        result = {'status':'PASS', 'original_revision':after['revision'], 'original_business_data_unchanged':True,
            'tables_checked':len(after['columns']), 'permit_migration_deployed_to_original':False,
            'original_services_ready':True, 'api_worker_configuration_consistent':True,
            'api_coder_credential_present':False, 'worker_coder_credential_present':False,
            'all_slots_disabled':True, 'real_calls_enabled':False, 'permit_issuance_enabled':False,
            'independent_issuer_credential_configured':False, 'real_worker_mode':'deny',
            'daily_and_test_budget_usd':'0', 'real_retries':0, 'model_egress_blocked':True,
            'active_real_tasks':active, 'persisted_real_model_operations':operations,
            'leftover_execution_containers':0, 'original_runner_ready':True,
            'effective_worker_heartbeats':len(workers), 'actual_external_model_requests_this_stage':0}
        (ROOT/'work/p5-live-permit-restoration.json').write_text(json.dumps(result,indent=2), encoding='utf-8')
        print(json.dumps(result))
    finally: await c.close()


if __name__ == "__main__":
    try: asyncio.run(main())
    except Exception as exc:
        print('Permit restoration verification failed: '+type(exc).__name__)
        raise SystemExit(1) from None
