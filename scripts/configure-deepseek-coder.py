"""Apply non-secret Coder preparation only. Never resolves a model credential."""

from maintenance_policy import cli_gate, maintenance_action
cli_gate(__file__, __name__)

import asyncio
import json
import os
from pathlib import Path
import re
from uuid import UUID
from dotenv import dotenv_values
from sqlalchemy import select
from app.core.config import Settings, runtime_env_file, is_model_credential_name
from app.domain.entities import ModelSlot
from app.domain.tasks import AgentTask, ModelOperation
from app.providers.router import PricePolicy
from app.repositories.connections import Connections
from app.schemas.models import ModelConfig
from app.services.tasks import TERMINAL

ROOT = Path(__file__).resolve().parents[1]
ISSUER_NAME = 'AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN'
DECLARATION = re.compile(r"^\s*(?:export\s+)?(?:'([A-Za-z_][A-Za-z0-9_]*)'|([A-Za-z_][A-Za-z0-9_]*))(?=\s*(?:=|#|$))")


def credential_name(name):
    name = name.upper()
    # Issuer is deliberately excluded by the model-reference classifier. It is
    # still an independent secret and must never enter a service configuration.
    return name == ISSUER_NAME or is_model_credential_name(name)


def require_service_only_file(target):
    """Reject credential declarations before Settings/dotenv value parsing."""
    with target.open(encoding='utf-8-sig') as stream:
        for opaque_line in stream:
            match = DECLARATION.match(opaque_line)
            if match and credential_name(match.group(1) or match.group(2)):
                raise RuntimeError('SERVICE_FILE_CREDENTIAL_DECLARATION_FORBIDDEN')


@maintenance_action("configure.coder")
async def main():
    # Membership/names only: never resolve an inherited Issuer or model value.
    if any(credential_name(name) for name in os.environ):
        raise RuntimeError('CREDENTIAL_AUTHORITY_FORBIDDEN_IN_CONFIGURATION')
    target = runtime_env_file()
    if target != ROOT / 'work/p5-live-preflight/.env':
        raise RuntimeError('FIXED_SERVICE_FILE_REQUIRED')
    require_service_only_file(target)
    settings = Settings()
    assert not settings.real_calls_enabled and settings.real_daily_budget_usd == settings.real_test_budget_usd == 0
    template = json.loads((ROOT / 'config/deepseek-coder-local.json').read_text())
    config = ModelConfig.model_validate(template['slot'])
    assert not config.enabled and config.credential_reference == 'env:AGENTFORGE_MODEL_CODER_KEY'
    price = PricePolicy.model_validate(template['price'])
    assert str(price.input_per_million) == '0.30' and str(price.output_per_million) == '1.20' and price.currency == 'USD'
    require_service_only_file(target)
    values = dict(dotenv_values(target, interpolate=False))  # Existing service-only maintenance file.
    if any(credential_name(name) for name in values):
        raise RuntimeError('SERVICE_FILE_CREDENTIAL_DECLARATION_FORBIDDEN')
    hosts = ['api.deepseek.com']
    audiences = {**settings.model_credential_hosts, 'AGENTFORGE_MODEL_CODER_KEY': ['api.deepseek.com']}
    prices = {**settings.model_prices, 'openai_compatible/deepseek-flash': price.model_dump(mode='json')}
    values.update(AGENTFORGE_ALLOWED_MODEL_HOSTS=','.join(hosts), AGENTFORGE_MODEL_CREDENTIAL_HOSTS=json.dumps(audiences),
        AGENTFORGE_MODEL_PRICES=json.dumps(prices), AGENTFORGE_REAL_CALLS_ENABLED='false',
        AGENTFORGE_REAL_DAILY_BUDGET_USD='0', AGENTFORGE_REAL_TEST_BUDGET_USD='0',
        AGENTFORGE_REAL_TEST_MAX_CALLS='1', AGENTFORGE_REAL_DAILY_TOKEN_LIMIT='8256',
        AGENTFORGE_REAL_MAX_RETRIES='0', AGENTFORGE_MODEL_CREDENTIALS_ENV_ONLY='true')
    c = Connections(settings)
    try:
        async with c.sessions() as session, session.begin():
            active = (await session.scalars(select(AgentTask.id).where(AgentTask.status.not_in(TERMINAL | {'paused'})))).all()
            assert not active, 'Do not change configuration while tasks are active'
            rows = (await session.scalars(select(ModelSlot).where(ModelSlot.tenant_id == UUID(settings.tenant_id)).with_for_update())).all()
            assert {row.role for row in rows} == {'coder', 'planner', 'researcher', 'reviewer'}
            before = {row.role: {**{name: getattr(row, name) for name in ModelConfig.model_fields}, 'version': row.version} for row in rows}
            backup = ROOT / 'work/p5-live-preflight/coder-slots-before.json'
            if not backup.exists(): backup.write_text(json.dumps(before, indent=2), encoding='utf-8')
            for row in rows:
                updates = config.model_dump() if row.role == 'coder' else {'enabled': False}
                if any(getattr(row, name) != value for name, value in updates.items()):
                    for name, value in updates.items(): setattr(row, name, value)
                    row.version += 1
            # This file contains service credentials, but never a model credential.
            require_service_only_file(target)
            target.write_text(''.join(name + '=' + json.dumps(value) + '\n' for name, value in sorted(values.items())), encoding='utf-8')
            print(json.dumps({'coder': config.model_dump(), 'price': price.model_dump(mode='json'),
                'global_deepseek_host_allowed': True, 'coder_credential_audience': audiences['AGENTFORGE_MODEL_CODER_KEY'],
                'other_real_slots_disabled': True, 'model_credential_values_accessed': False}))
    finally:
        await c.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as exc:
        print('Coder configuration failed: ' + type(exc).__name__)
        raise SystemExit(1) from None
