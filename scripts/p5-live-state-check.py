"""Stop persisted real model jobs and report public configuration / audit counters."""

from maintenance_policy import cli_gate, maintenance_action
cli_gate(__file__, __name__)

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import UUID
from sqlalchemy import select, text
from app.core.config import Settings, validate_model_endpoint
from app.core.errors import AppError
from app.domain.entities import ModelSlot
from app.domain.tasks import AgentTask, ModelOperation
from app.repositories.connections import Connections
from app.services.tasks import TERMINAL, event
from app.providers.deepseek import validate_profile, uses_deepseek_profile
from app.providers.router import price_for

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'work/p5-live-preflight'


async def model_ledger(session):
    rows = (await session.execute(select(ModelOperation.task_id, ModelOperation.operation_id, ModelOperation.state,
        ModelOperation.input_tokens, ModelOperation.output_tokens, ModelOperation.cost, ModelOperation.reserved_cost)
        .where(ModelOperation.is_mock.is_(False)).order_by(ModelOperation.task_id, ModelOperation.operation_id))).all()
    return [[str(item) for item in row] for row in rows]


@maintenance_action(lambda a, k: "state.hold" if k.get("stop", a[0] if a else False) else "state.inspect")
async def main(stop=False):
    settings = Settings()
    assert not settings.real_calls_enabled and settings.real_daily_budget_usd == settings.real_test_budget_usd == 0
    assert os.environ.get('AGENTFORGE_EXTERNAL_MODELS_BLOCKED') == '1'
    c = Connections(settings)
    try:
        async with c.sessions() as session, session.begin():
            tasks = (await session.scalars(select(AgentTask).where(AgentTask.tenant_id == UUID(settings.tenant_id), AgentTask.is_mock.is_(False),
                AgentTask.options['workflow'].astext.is_distinct_from('sandbox'), AgentTask.status.not_in(TERMINAL)).with_for_update())).all()
            stopped = []
            if stop:
                for task in tasks:
                    task.status, task.owner, task.lease_until = 'paused', None, None
                    task.fence += 1
                    event(session, task, 'maintenance_hold', {'reason': 'P5_LIVE_ZERO_EXTERNAL_CALLS'})
                    stopped.append(str(task.id))
            ledger = await model_ledger(session)
            active = [str(task.id) for task in tasks if task.status != 'paused']
            assert not active
        if stop:
            (DIRECTORY / 'ledger-before.json').write_text(json.dumps(ledger, indent=2), encoding='utf-8')
        else:
            assert ledger == json.loads((DIRECTORY / 'ledger-before.json').read_text()), 'Persisted real model attempts changed'
        async with c.sessions() as session:
            slots = (await session.scalars(select(ModelSlot).where(ModelSlot.tenant_id == settings.tenant_id).order_by(ModelSlot.role))).all()
            configs = []
            for slot in slots:
                data = {name: getattr(slot, name) for name in ('role','provider','base_url','model','credential_reference','enabled','thinking_mode','reasoning_effort','max_tokens','timeout','priority')}
                try:
                    if not uses_deepseek_profile(data): raise AppError('DEEPSEEK_SLOT_NOT_CONFIGURED', 'not configured', 409)
                    validate_profile(data)
                    validate_model_endpoint(slot.base_url, settings.model_hosts)
                    price = price_for(data, settings)
                    assert price.token_parameter == 'max_tokens'
                    data['deepseek_configuration_status'] = 'validated_without_authentication'
                except (AppError, ValueError, AssertionError) as exc:
                    data['deepseek_configuration_status'] = exc.code if isinstance(exc, AppError) else 'MODEL_CONFIGURATION_INVALID'
                configs.append(data)
            revision = await session.scalar(text('SELECT version_num FROM alembic_version'))
        result = {'migration': revision, 'real_calls_enabled': False, 'external_model_transport_blocked': True,
                  'test_budget_usd': '0', 'daily_budget_usd': '0', 'test_max_calls': settings.real_test_max_calls,
                  'daily_token_limit': settings.real_daily_token_limit, 'test_retry_policy': 'none',
                  'held_task_ids': stopped, 'active_real_model_tasks': len(active),
                  'persisted_real_model_operations': len(ledger), 'existing_real_model_ledger_unchanged': not stop,
                  'deepseek_global_host_allowed': 'api.deepseek.com' in settings.model_hosts,
                  'deepseek_credential_audiences': {key: settings.model_credential_hosts.get(key, []) for key in
                      ('AGENTFORGE_MODEL_CODER_KEY', 'AGENTFORGE_MODEL_PLANNER_KEY', 'AGENTFORGE_MODEL_RESEARCHER_KEY', 'AGENTFORGE_MODEL_REVIEWER_KEY')},
                  'deepseek_flash_price_registered': 'deepseek/deepseek-flash' in settings.model_prices,
                  'deepseek_pro_price_registered': 'deepseek/deepseek-v4-pro' in settings.model_prices,
                  'slots': configs}
        (DIRECTORY / ('state-before.json' if stop else 'state-after.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
    finally: await c.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    try: asyncio.run(main(args.stop))
    except Exception as exc:
        print('State verification failed: ' + type(exc).__name__)
        raise SystemExit(1) from None
