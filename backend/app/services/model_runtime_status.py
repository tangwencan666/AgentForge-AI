"""Authenticated, non-secret runtime observations; credential names only."""
import asyncio
import json
import os
from time import time
from sqlalchemy import select
from app.domain.entities import ModelSlot
from app.schemas.models import ModelConfig
from app.services.context import content_hash
from app.providers.router import PricePolicy

CODER_KEY = 'AGENTFORGE_MODEL_CODER_KEY'
TTL = 12


def status_key(settings):
    return 'agentforge:p5:model-runtime:' + settings.tenant_id


def public_policy(settings):
    try:
        price = PricePolicy.model_validate(settings.model_prices['openai_compatible/deepseek-flash'])
        price_digest = content_hash(price.model_dump(mode='json'))
    except (ValueError, KeyError, TypeError):
        price_digest = None
    return {'real_calls_enabled': settings.real_calls_enabled,
        'daily_budget_usd': str(settings.real_daily_budget_usd),
        'test_budget_usd': str(settings.real_test_budget_usd),
        'daily_token_limit': settings.real_daily_token_limit, 'test_max_calls': settings.real_test_max_calls,
        'real_max_retries': settings.real_max_retries, 'credentials_env_only': settings.model_credentials_env_only,
        'permit_required': True, 'permit_issuance_enabled': settings.single_use_permits_enabled, 'real_worker_mode': settings.real_worker_mode,
        'deepseek_host_allowed': 'api.deepseek.com' in settings.model_hosts,
        'coder_audience_exact': settings.model_credential_hosts.get(CODER_KEY) == ['api.deepseek.com'],
        'flash_price_digest': price_digest,
        'external_calls_blocked': os.environ.get('AGENTFORGE_EXTERNAL_MODELS_BLOCKED', '').lower() in {'1', 'true'}}


async def observe(connections, settings):
    async with connections.sessions() as session:
        rows = (await session.scalars(select(ModelSlot).where(ModelSlot.tenant_id == settings.tenant_id).order_by(ModelSlot.role))).all()
        slots = [{**{name: getattr(row, name) for name in ModelConfig.model_fields},
                  'role': row.role, 'version': row.version} for row in rows]
    policy = public_policy(settings)
    digest = content_hash({'slots': slots, 'policy': policy, 'hosts': sorted(settings.model_hosts),
        'credential_hosts': settings.model_credential_hosts, 'prices': settings.model_prices})
    return {'process_id': os.getpid(), 'coder_credential_present': CODER_KEY in os.environ,
        'configuration_digest': digest, 'slot_versions': {slot['role']: slot['version'] for slot in slots},
        'policy': policy, 'observed_at': time()}


async def publish_worker_status(connections, settings):
    while True:
        try:
            state = await observe(connections, settings)
            await connections.redis.set(status_key(settings), json.dumps(state), ex=TTL)
        except Exception:
            pass  # Expiry marks an unavailable observation; never log payloads or credentials.
        await asyncio.sleep(3)


async def compare_runtime_status(connections, settings):
    api = await observe(connections, settings)
    raw = await connections.redis.get(status_key(settings))
    worker = None
    try:
        value = json.loads(raw) if raw else None
        if isinstance(value, dict) and isinstance(value.get('observed_at'), (int, float)) and 0 <= time() - value['observed_at'] <= TTL:
            # Return only the fixed fields emitted by this module.
            worker = {key: value[key] for key in api}
    except (ValueError, TypeError, KeyError):
        pass
    return {'api': api, 'worker': worker, 'worker_available': worker is not None,
        'configuration_consistent': bool(worker and api['configuration_digest'] == worker['configuration_digest']),
        'credential_presence_consistent': bool(worker and api['coder_credential_present'] == worker['coder_credential_present']),
        'credential_check': 'environment_name_presence_only_not_authentication'}
