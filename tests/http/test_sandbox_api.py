import secrets
from fastapi.testclient import TestClient
from app.main import create_app
from app.schemas.sandbox import SandboxCreate, SandboxExecutionRequest, ResourceLimits
from pydantic import ValidationError
from conftest import StubConnections
import pytest

@pytest.mark.parametrize("override",[{"image":"evil"},{"privileged":True},{"network":"host"},{"mounts":["C:/"]},{"resource_limits":{"memory_mb":513}},{"resource_limits":{"pids":65}},{"resource_limits":{"cpu":True}},{"timeout_seconds":121},{"language":"shell"}])
def test_policy_cannot_be_overridden(override):
    with pytest.raises(ValidationError): SandboxCreate(code="print(1)",**override)

def test_code_repr_is_protected():
    body=SandboxCreate(code="do not echo private source")
    assert "private source" not in repr(body)

def test_unauthorized_execution_never_reaches_storage(settings):
    with TestClient(create_app(settings,StubConnections())) as client:
        response=client.post("/api/v1/sandbox/executions",headers={"Idempotency-Key":"00000000-0000-4000-8000-000000000002"},json={"code":"print(1)"})
        assert response.status_code==401

def test_admin_cannot_approve_high_risk_code(settings):
    from pydantic import SecretStr
    settings.sandbox_approver_token=SecretStr(secrets.token_hex(32))
    with TestClient(create_app(settings,StubConnections())) as client:
        response=client.post("/api/v1/sandbox/executions/00000000-0000-4000-8000-000000000002/decision",
            headers={"Authorization":"Bearer "+settings.admin_token.get_secret_value()},json={"decision":"approved","operation_hash":"a"*64})
        assert response.status_code==403

def test_unconfigured_sandbox_fails_closed(settings):
    with TestClient(create_app(settings,StubConnections())) as client:
        response=client.post("/api/v1/sandbox/executions",headers={"Authorization":"Bearer "+settings.admin_token.get_secret_value(),"Idempotency-Key":"00000000-0000-4000-8000-000000000002"},json={"code":"print(1)"})
        assert response.status_code==503
        assert response.json()["error"]["code"]=="SANDBOX_UNAVAILABLE"
