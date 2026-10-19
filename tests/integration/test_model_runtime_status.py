"""Local PostgreSQL/Redis observations only; no Agent task or model invocation."""
import asyncio
import os
import httpx
import pytest
from app.core.config import Settings
from app.main import create_app
from app.services.model_runtime_status import publish_worker_status, status_key

pytestmark = pytest.mark.integration


async def test_authenticated_runtime_observation_reports_boolean_presence_and_matching_versions(monkeypatch):
    if os.environ.get('AGENTFORGE_RUN_INTEGRATION') != '1': pytest.skip('Explicit project database opt-in required')
    settings = Settings()
    monkeypatch.setenv('AGENTFORGE_MODEL_CODER_KEY', 'explicit-local-status-test-fake-only')
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        connections = app.state.connections
        producer = asyncio.create_task(publish_worker_status(connections, settings))
        try:
            for _ in range(30):
                if await connections.redis.exists(status_key(settings)): break
                await asyncio.sleep(.05)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://local-test') as client:
                assert (await client.get('/api/v1/models/runtime-status')).status_code == 401
                headers = {'Authorization': 'Bearer ' + settings.admin_token.get_secret_value()}
                for _ in range(30):
                    response = await client.get('/api/v1/models/runtime-status', headers=headers)
                    data = response.json()['data']
                    if data['configuration_consistent'] and data['credential_presence_consistent']: break
                    await asyncio.sleep(.05)
                assert data['configuration_consistent'] and data['credential_presence_consistent']
                assert data['api']['coder_credential_present'] is True and data['worker']['coder_credential_present'] is True
                assert data['api']['slot_versions'] == data['worker']['slot_versions']
                assert 'explicit-local-status-test-fake-only' not in response.text
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)
            await connections.redis.delete(status_key(settings))
