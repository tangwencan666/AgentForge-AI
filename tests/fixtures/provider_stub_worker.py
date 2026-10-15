"""Test-only OS Worker. The production adapter registry cannot select this Stub."""
import asyncio
from decimal import Decimal
from pathlib import Path
import runpy
import sys
from app.core.config import Settings
from app.providers.router import ModelRouter
from app.repositories.connections import Connections
from app.workers.engine import Worker

root = Path(__file__).resolve().parents[2]
ProviderStub = runpy.run_path(str(root / 'tests/integration/test_real_agents.py'))['ProviderStub']
ModelRouter.adapters = {'openai_compatible': ProviderStub}
price = {'input_per_million': '1', 'output_per_million': '2', 'input_upper_bound': 8192, 'output_upper_bound': 1024, 'version': 'explicit-stub-price-v1'}
settings = Settings().model_copy(update={'tenant_id': sys.argv[1], 'real_calls_enabled': True,
    'real_daily_budget_usd': Decimal('1'), 'real_daily_token_limit': 100000,
    'model_credential_hosts': {'AGENTFORGE_MODEL_P5_STUB_KEY': ['api.openai.com']},
    'model_prices': {'openai_compatible/stub-' + role: price for role in ('planner','coder','researcher','reviewer')}})


class TestTenantWorker(Worker):
    async def claim(self, task_id):
        from app.domain.tasks import AgentTask
        async with self.connections.sessions() as session:
            row = await session.get(AgentTask, task_id)
            if row is None or str(row.tenant_id) != settings.tenant_id: return None
        return await super().claim(task_id)


async def main():
    connections = Connections(settings)
    try: await TestTenantWorker(connections, settings).run()
    finally: await connections.close()

asyncio.run(main())
