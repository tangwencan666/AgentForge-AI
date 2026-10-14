import secrets
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from conftest import StubConnections


def test_liveness_does_not_claim_dependencies_up(settings):
    connections = StubConnections()
    with TestClient(create_app(settings, connections)) as client:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json()["data"] == {"status": "alive", "phase": "P3"}
        assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert connections.closed


@pytest.mark.parametrize("state,expected", [
    ({"postgresql": "up", "redis": "up"}, 200),
    ({"postgresql": "up", "redis": "down"}, 503),
    ({"postgresql": "migration_required", "redis": "up"}, 503),
])
def test_readiness_http_contract_with_explicit_unit_double(settings, state, expected):
    with TestClient(create_app(settings, StubConnections(state))) as client:
        response = client.get("/health/ready")
        assert response.status_code == expected
        assert response.json()["data"]["dependencies"] == state
        assert response.json()["success"] == (expected == 200)


def test_request_id_validation(settings):
    with TestClient(create_app(settings, StubConnections())) as client:
        valid = str(uuid4())
        assert client.get('/health/live', headers={"X-Request-ID": valid}).headers['X-Request-ID'] == valid
        unsafe = "not-a-uuid-sensitive-value"
        response = client.get('/health/live', headers={"X-Request-ID": unsafe})
        assert unsafe not in response.text


def test_config_requires_authentication(settings):
    with TestClient(create_app(settings, StubConnections())) as client:
        assert client.get('/api/v1/model-slots').status_code == 401
        assert client.post('/api/v1/model-slots/validate', json={}).status_code == 401


def test_validation_does_not_echo_api_key_or_body(settings, capsys):
    secret = secrets.token_hex(32)
    with TestClient(create_app(settings, StubConnections())) as client:
        response = client.post('/api/v1/model-slots/validate', json={"api_key": secret, secret: secret},
                               headers={"Authorization": f"Bearer {settings.admin_token.get_secret_value()}"})
        assert response.status_code == 422
        assert secret not in response.text
        assert settings.admin_token.get_secret_value() not in response.text
        assert secret not in capsys.readouterr().err


def test_no_model_success_is_fabricated(settings):
    with TestClient(create_app(settings, StubConnections())) as client:
        body = client.get('/api/v1/system').json()
        assert body['data']['model_calls'] == 'mock_only'
        assert client.post('/api/v1/chat', json={"message": "test"}).status_code == 404
        validated = client.post('/api/v1/model-slots/validate', json={"provider": "mock", "model": "mock-test", "enabled": True},
                                headers={"Authorization": f"Bearer {settings.admin_token.get_secret_value()}"})
        assert validated.json()['data'] == {"valid": True, "is_mock": True, "call_status": "not_implemented"}


def test_openapi_and_uniform_not_found(settings):
    with TestClient(create_app(settings, StubConnections())) as client:
        schema = client.get('/openapi.json').json()
        assert '/health/live' in schema['paths']
        assert '/api/v1/model-slots/{role}' in schema['paths']
        assert schema['paths']['/api/v1/model-slots/validate']['post']['responses']['422']['content']['application/json']['schema']['$ref'].endswith('/ApiResponse')
        response = client.get('/nonexistent')
        assert response.status_code == 404
        assert response.json()['error']['code'] == 'HTTP_ERROR'


def test_unexpected_error_has_no_exception_value(settings):
    app = create_app(settings, StubConnections())
    secret = secrets.token_hex(32)
    @app.get('/test-error')
    async def error_route():
        raise RuntimeError(secret)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/test-error')
        assert response.status_code == 500
        assert secret not in response.text
        assert response.headers['X-Request-ID'] == response.json()['request_id']
