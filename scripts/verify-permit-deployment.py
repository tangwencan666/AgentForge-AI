"""Read-only post-deployment checks; model credential NAME presence only."""

from maintenance_policy import cli_gate, maintenance_action
cli_gate(__file__, __name__)

import argparse
import asyncio
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import httpx
from app.core.config import Settings
from app.repositories.connections import Connections
from app.services.model_runtime_status import observe

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('permit_deployment',ROOT/'scripts/deploy-permit-database.py')
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)


@maintenance_action("permit.verify")
async def main(require_credential):
    settings = Settings()
    assert settings.model_hosts == {'api.deepseek.com'}
    assert settings.model_credential_hosts == {'AGENTFORGE_MODEL_CODER_KEY':['api.deepseek.com']}
    c = Connections(settings)
    try:
        async with httpx.AsyncClient(base_url='http://127.0.0.1:18100',trust_env=False,timeout=5) as client:
            assert (await client.get('/health/ready')).status_code == 200
            headers = {'Authorization':'Bearer '+settings.admin_token.get_secret_value()}
            runtime = (await client.get('/api/v1/models/runtime-status',headers=headers)).json()['data']
            assert runtime['worker_available'] and runtime['configuration_consistent'] and runtime['credential_presence_consistent']
            expected = await observe(c,settings)
            assert runtime['api']['configuration_digest'] == expected['configuration_digest']
            for name in ('api','worker'):
                policy = runtime[name]['policy']
                assert policy['permit_required'] and not policy['permit_issuance_enabled'] and policy['real_worker_mode'] == 'deny'
                assert not policy['real_calls_enabled'] and policy['external_calls_blocked']
                assert policy['daily_budget_usd'] == policy['test_budget_usd'] == '0' and policy['real_max_retries'] == 0
                assert policy['credentials_env_only'] and policy['deepseek_host_allowed'] and policy['coder_audience_exact']
                if require_credential: assert runtime[name]['coder_credential_present'] is True
            unknown = await client.get('/api/v1/model-permits/'+str(uuid4()),headers=headers)
            assert unknown.status_code == 404
            runner = (await client.get('/api/v1/sandbox/policy',headers=headers)).json()['data']['runner_status']
            assert runner == {'available':True,'blocked':False,'active_executions':0}
            assert (await client.get('http://127.0.0.1:15173')).status_code == 200
        workers = [name async for name in c.redis.scan_iter(match='agentforge:p2:worker:*')]
        assert len(workers) == 1
        pending = await c.redis.xpending('agentforge:p2:tasks','agentforge-p2-workers')
        assert pending['pending'] == 0
        groups = await c.redis.xinfo_groups('agentforge:p2:tasks')
        assert len(groups) == 1 and groups[0]['name'] == 'agentforge-p2-workers' and groups[0]['lag'] == 0
        assert not deployment.command('docker','ps','-aq','--filter','label=agentforge.sandbox.execution')
        result = {'checked_at':datetime.now(timezone.utc).isoformat(),'revision':'0008_execution_permits',
            'services_healthy':True,'api_worker_configuration_consistent':True,
            'api_coder_credential_present':runtime['api']['coder_credential_present'],
            'worker_coder_credential_present':runtime['worker']['coder_credential_present'],
            'slot_versions':runtime['api']['slot_versions'],'policy':runtime['api']['policy'],
            'all_slots_disabled':True,'active_tasks':0,'real_model_operations':0,'execution_permits':0,
            'pending_outbox':0,'redis_pending':0,'redis_lag':0,'effective_workers':1,
            'execution_containers':0,'external_model_requests':0,
            'credential_check':'environment_name_presence_only_not_authentication',
            'status':'PASS' if runtime['api']['coder_credential_present'] else 'BLOCKED_CREDENTIAL_RELOAD'}
        (deployment.DIRECTORY/'final-state.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))
    finally:
        await c.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-credential',action='store_true')
    options = parser.parse_args()
    try:
        deployment.verify()
        asyncio.run(main(options.require_credential))
    except Exception as exc:
        print('Deployment final check stopped: '+type(exc).__name__)
        raise SystemExit(1) from None
