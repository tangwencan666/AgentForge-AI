from uuid import uuid4
import secrets
from pydantic import SecretStr
from fastapi.testclient import TestClient
import pytest
from app.main import create_app
from conftest import StubConnections


@pytest.mark.parametrize('path', ['/mcp/tools', '/mcp/permissions', '/mcp/calls', '/skills', '/capabilities/approvals', '/capabilities/audit'])
def test_p4_resources_require_authentication(settings, path):
    with TestClient(create_app(settings, StubConnections())) as client:
        assert client.get('/api/v1' + path).status_code == 401


def test_admin_cannot_approve_p4_and_p4_approver_cannot_administer(settings):
    settings = settings.model_copy(update={'capability_approver_token': SecretStr(secrets.token_hex(32))})
    admin = {'Authorization': 'Bearer ' + settings.admin_token.get_secret_value()}
    approver = {'Authorization': 'Bearer ' + settings.capability_approver_token.get_secret_value()}
    with TestClient(create_app(settings, StubConnections())) as client:
        path = '/api/v1/capabilities/approvals/' + str(uuid4())
        assert client.get(path + '/review', headers=admin).status_code == 403
        assert client.post(path + '/decision', json={'decision': 'approved', 'operation_hash': 'a' * 64}, headers=admin).status_code == 403
        assert client.put('/api/v1/mcp/permissions', json={}, headers=approver).status_code == 401
        assert client.get('/api/v1/skills', headers=approver).status_code == 401


def test_discovery_is_fixed_and_does_not_report_unavailable_server_as_configured(settings):
    with TestClient(create_app(settings, StubConnections())) as client:
        data = client.get('/api/v1/mcp/tools', headers={'Authorization': 'Bearer ' + settings.admin_token.get_secret_value()}).json()['data']
        assert data['configured'] is False
        assert {item['name'] for item in data['tools']} == {'notes.read', 'notes.write'}


@pytest.mark.parametrize('extra', [{'approved': True}, {'requester': 'capability-reviewer'}, {'endpoint': 'http://127.0.0.1'}, {'tenant_id': str(uuid4())}])
def test_http_cannot_supply_privileged_gateway_fields(settings, extra):
    with TestClient(create_app(settings, StubConnections())) as client:
        response = client.post('/api/v1/mcp/calls', headers={'Authorization': 'Bearer ' + settings.admin_token.get_secret_value(), 'Idempotency-Key': str(uuid4())},
                               json={'tool': 'notes.write', 'arguments': {'resource': 'test', 'text': 'data'}, **extra})
        assert response.status_code == 422
        assert settings.admin_token.get_secret_value() not in response.text
