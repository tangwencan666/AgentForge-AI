"""OS crash probe only: real authority/DB, fake credential and virtual HTTP transport."""
import asyncio
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from uuid import UUID
import httpx
from pydantic import SecretStr
from sqlalchemy import select
from app.core.config import Settings
from app.domain.tasks import AgentTask
from app.domain.permits import ExecutionPermit
from app.providers.openai_compatible import OpenAICompatible
from app.repositories.connections import Connections
from app.services.execution_permits import PermitService
from app.workers.engine import Worker
from preflight_guards import install_verified_guard
from lifecycle_permit_child import isolated_context

root = Path(__file__).resolve().parents[2]
# Parent owns the resource lease until the exact child process exits. The child
# independently attests resources without claiming or waiting for that lock.
verified = isolated_context(root)
install_verified_guard(verified)
tenant, stage, directory = sys.argv[1], sys.argv[2], Path(sys.argv[3]).resolve()
if (str(UUID(tenant)) != tenant or stage not in {'claimed', 'dispatched', 'recover'}
        or directory != Path(verified['run_directory']) / 'permit-process-tests' / tenant):
    raise RuntimeError('S1_FIXTURE_SCOPE_INVALID')
os.environ['AGENTFORGE_MODEL_CODER_KEY'] = 'explicit-virtual-process-test-credential'
settings = Settings().model_copy(update={'tenant_id': tenant, 'single_use_permits_enabled': True,
    'real_worker_mode': 'permit_only', 'real_calls_enabled': True, 'real_max_retries': 0,
    'real_daily_token_limit': 8256, 'real_test_max_calls': 1, 'real_daily_budget_usd': Decimal('.005'),
    'real_test_budget_usd': Decimal('.005'), 'model_credentials_env_only': True,
    'model_permit_issuer_token': None, 'allowed_model_hosts': 'api.deepseek.com',
    'model_credential_hosts': {'AGENTFORGE_MODEL_CODER_KEY': ['api.deepseek.com']},
    'model_prices': {'openai_compatible/deepseek-flash': {'currency': 'USD', 'input_per_million': '.30',
        'output_per_million': '1.20', 'input_upper_bound': 8192, 'output_upper_bound': 4096,
        'version': 'explicit-virtual-peak-v1', 'token_parameter': 'max_tokens'}}})


def save(name, data):
    temporary = directory / (name + '.tmp')
    temporary.write_text(json.dumps(data), encoding='utf-8')
    temporary.replace(directory / (name + '.json'))


async def freeze(boundary):
    save('boundary', {'boundary': boundary, 'pid': os.getpid()})
    await asyncio.Event().wait()


async def public_ip(host):
    if stage == 'claimed': await freeze('CLAIMED_BEFORE_DISPATCH')
    return '93.184.216.34'


async def virtual_http(request):
    assert stage == 'dispatched'
    await freeze('DISPATCH_COMMITTED_VIRTUAL_HTTP_ENTERED')


import app.providers.openai_compatible as wire
wire.public_address = public_ip
wire.assert_model_egress = lambda: None  # MockTransport below; no sockets or DNS possible.
OpenAICompatible.http_client = lambda self, timeout: httpx.AsyncClient(transport=httpx.MockTransport(virtual_http), trust_env=False)


async def main():
    c = Connections(settings)
    worker, service = Worker(c, settings), PermitService(c, settings)
    pulse = None
    try:
        await worker.initialize()
        if stage == 'recover':
            await service.recover()
            p = json.loads((directory / 'request.json').read_text())
            claim = await worker.claim(UUID(p['task_id']))
            result = await service.get(UUID(p['permit_id']))
            save('recovery', {'pid': os.getpid(), 'status': result['status'], 'claim': claim,
                'dispatch_attempts': result['dispatch_attempts'], 'usage_status': result['usage_status'],
                'reserved_cost': str(result['reserved_cost']), 'external_requests': 0})
            return
        async def heartbeat():
            while True:
                await worker.heartbeat()
                await asyncio.sleep(1)
        pulse = asyncio.create_task(heartbeat())
        save('ready', {'pid': os.getpid(), 'identity': str(worker.permit_identity.identity)})
        while not (directory / 'request.json').is_file(): await asyncio.sleep(.05)
        p = json.loads((directory / 'request.json').read_text())
        claim = await worker.claim(UUID(p['task_id']))
        assert claim is not None
        await service.execute(UUID(p['permit_id']), worker.permit_identity, claim[1])
        raise AssertionError('Crash boundary must not return')
    finally:
        if pulse:
            pulse.cancel()
            await asyncio.gather(pulse, return_exceptions=True)
        await worker.close()
        await c.close()


try: asyncio.run(main())
except Exception as exc:
    save('failure', {'error_type': type(exc).__name__})
    raise SystemExit(1) from None
