"""No database/network: the public API cannot manufacture permit authority."""
from decimal import Decimal
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from app.main import create_app
from conftest import StubConnections


@pytest.fixture
def permitted_settings(settings):
    return settings.model_copy(update={'real_calls_enabled': True, 'single_use_permits_enabled': True,
        'real_daily_budget_usd': Decimal('.005'), 'real_test_budget_usd': Decimal('.005'),
        'model_permit_issuer_token': SecretStr('independent-test-issuer-only-00000001')})


@pytest.mark.parametrize('path', ['/chat', '/tasks', '/model-slots/coder/test',
    '/model-slots/planner/test', '/model-slots/researcher/test', '/model-slots/reviewer/test'])
def test_global_flags_and_admin_cannot_spend_test_authorization(permitted_settings, path):
    s = permitted_settings
    headers = {'Authorization': 'Bearer ' + s.admin_token.get_secret_value(), 'Idempotency-Key': str(uuid4())}
    body = {'goal': 'ordinary request', 'workflow': 'chat', 'execution_mode': 'real', 'chat_role': 'coder'}
    with TestClient(create_app(s, StubConnections())) as client:
        response = client.post('/api/v1' + path, headers=headers, json=body)
        assert response.status_code == 409 and response.json()['error']['code'] == 'MODEL_PERMIT_REQUIRED'


@pytest.mark.parametrize('action', ['', '/' + str(uuid4()) + '/revoke'])
def test_admin_is_not_independent_issuer(permitted_settings, action):
    s = permitted_settings
    with TestClient(create_app(s, StubConnections())) as client:
        response = client.post('/api/v1/model-permits' + action,
            headers={'Authorization': 'Bearer ' + s.admin_token.get_secret_value()}, json={})
        assert response.status_code == 403 and response.json()['error']['code'] == 'PERMIT_ISSUER_FORBIDDEN'
        assert s.admin_token.get_secret_value() not in response.text


@pytest.mark.parametrize('field', ['task_id', 'execution_id', 'worker_id', 'authorized_worker_identity',
    'role', 'model', 'slot_version', 'request_fingerprint', 'max_attempts', 'max_budget_usd', 'status', 'expiration'])
def test_issuer_cannot_supply_bindings_or_limits(permitted_settings, field):
    s = permitted_settings
    with TestClient(create_app(s, StubConnections())) as client:
        response = client.post('/api/v1/model-permits',
            headers={'Authorization': 'Bearer ' + s.model_permit_issuer_token.get_secret_value()}, json={field: 'caller-controlled'})
        assert response.status_code == 422
        assert 'caller-controlled' not in response.text


def test_client_cannot_attach_permit_to_chat(permitted_settings):
    s = permitted_settings
    with TestClient(create_app(s, StubConnections())) as client:
        response = client.post('/api/v1/chat', headers={'Authorization': 'Bearer ' + s.admin_token.get_secret_value(),
            'Idempotency-Key': str(uuid4())}, json={'goal': 'steal', 'workflow': 'chat', 'execution_mode': 'real', 'permit_id': str(uuid4())})
        assert response.status_code == 422
