"""Real services only; no SQLite, fakeredis or mocked successful DB assertions."""
import os
from uuid import UUID
import pytest
from sqlalchemy import text, select
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app
from app.repositories.connections import Connections
from app.domain.entities import ModelSlot

pytestmark = pytest.mark.integration


@pytest.fixture
def real_settings():
    if os.environ.get('AGENTFORGE_RUN_INTEGRATION') != '1':
        pytest.skip('Explicit real integration opt-in required; not a connectivity pass')
    settings = Settings()
    from urllib.parse import urlsplit
    pg, redis = urlsplit(settings.database_url.get_secret_value()), urlsplit(settings.redis_url.get_secret_value())
    assert pg.hostname == '127.0.0.1' and pg.username == 'agentforge' and pg.path == '/agentforge'
    assert redis.hostname == '127.0.0.1' and redis.path == '/0'
    return settings


async def test_real_postgresql_redis_and_migration(real_settings):
    connections = Connections(real_settings)
    try:
        assert await connections.readiness() == {'postgresql': 'up', 'redis': 'up'}
        async with connections.engine.connect() as conn:
            assert await conn.scalar(text('SELECT version_num FROM alembic_version')) == '0001_model_slots'
            role = (await conn.execute(text('SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user'))).one()
            assert role == (False, False, False)
        async with connections.sessions() as session:
            slots = (await session.scalars(select(ModelSlot).where(ModelSlot.tenant_id == UUID(real_settings.tenant_id)))).all()
            assert {slot.role for slot in slots} == {'planner', 'coder', 'researcher', 'reviewer'}
    finally:
        await connections.close()


def test_real_http_configuration_persistence_and_version_conflict(real_settings):
    headers = {'Authorization': f'Bearer {real_settings.admin_token.get_secret_value()}'}
    with TestClient(create_app(real_settings)) as client:
        assert client.get('/health/ready').status_code == 200
        before = client.get('/api/v1/model-slots', headers=headers)
        assert before.status_code == 200
        planner = next(slot for slot in before.json()['data'] if slot['role'] == 'planner')
        payload = {key: value for key, value in planner.items() if key in {
            'provider','base_url','model','credential_reference','temperature','timeout','max_tokens','enabled'
        }}
        payload['expected_version'] = planner['version']
        payload['timeout'] = 61 if planner['timeout'] != 61 else 60
        changed = client.put('/api/v1/model-slots/planner', headers=headers, json=payload)
        assert changed.status_code == 200
        assert client.put('/api/v1/model-slots/planner', headers=headers, json=payload).status_code == 409
        actual = next(slot for slot in client.get('/api/v1/model-slots', headers=headers).json()['data'] if slot['role'] == 'planner')
        assert actual['timeout'] == payload['timeout']
        assert actual['version'] == planner['version'] + 1
        # Restore original configuration, without deleting data or resetting Redis.
        payload['timeout'] = planner['timeout']
        payload['expected_version'] = actual['version']
        assert client.put('/api/v1/model-slots/planner', headers=headers, json=payload).status_code == 200


async def test_real_failure_is_not_reported_as_ready(real_settings):
    data = real_settings.model_dump()
    data['database_url'] = 'postgresql+asyncpg://agentforge:test-only@127.0.0.1:65501/agentforge'
    data['redis_url'] = 'redis://:test-only@127.0.0.1:65502/0'
    data['dependency_timeout'] = 0.3
    connections = Connections(Settings(_env_file=None, **data))
    try:
        assert await connections.readiness() == {'postgresql': 'down', 'redis': 'down'}
    finally:
        await connections.close()
