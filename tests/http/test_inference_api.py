from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from conftest import StubConnections


@pytest.mark.parametrize('path', ['/models/policy', '/models/metrics', '/models/runtime-status', '/chat/history'])
def test_inference_configuration_and_history_are_protected(settings, path):
    with TestClient(create_app(settings, StubConnections())) as client:
        assert client.get('/api/v1' + path).status_code == 401


def test_real_model_test_is_blocked_before_database_or_network_without_quota(settings):
    headers = {'Authorization': 'Bearer ' + settings.admin_token.get_secret_value(), 'Idempotency-Key': str(uuid4())}
    with TestClient(create_app(settings, StubConnections())) as client:
        policy = client.get('/api/v1/models/policy', headers=headers).json()['data']
        assert policy['paid_test_status'] == 'BLOCKED'
        result = client.post('/api/v1/model-slots/planner/test', headers=headers)
        assert result.status_code == 409 and result.json()['error']['code'] == 'MODEL_TEST_BUDGET_BLOCKED'
        assert settings.admin_token.get_secret_value() not in result.text
