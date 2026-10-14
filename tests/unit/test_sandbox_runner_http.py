"""Internal authorization tests use an explicit runner double, never real execution."""
from types import SimpleNamespace
from uuid import uuid4
from fastapi.testclient import TestClient
from pydantic import SecretStr
from app.sandbox.main import create_app


class RunnerDouble:
    def __init__(self):
        self.calls = []

    async def start(self):
        pass

    async def close(self):
        pass

    async def dispatch(self, request):
        self.calls.append(request)
        return {"execution_id": str(request.execution_id), "status": "starting"}


def client(settings):
    settings = settings.model_copy(update={"sandbox_runner_token": SecretStr("unit-only-" + "a" * 32)})
    runner = RunnerDouble()
    app = create_app(settings, connections=SimpleNamespace(), runner=runner)
    return TestClient(app), runner, settings.sandbox_runner_token.get_secret_value()


def payload(execution_id):
    return {"task_id": str(uuid4()), "execution_id": str(execution_id), "owner": "worker-test", "fence": 1}


def test_internal_endpoint_denies_missing_and_wrong_credentials(settings):
    web, runner, token = client(settings)
    execution_id = uuid4()
    with web:
        for headers in [{}, {"X-AgentForge-Runner-Token": "wrong"}]:
            response = web.post(f"/internal/executions/{execution_id}/dispatch", json=payload(execution_id), headers=headers)
            assert response.status_code == 403
            assert token not in response.text
    assert runner.calls == []


def test_internal_schema_cannot_override_docker_security(settings):
    web, runner, token = client(settings)
    execution_id = uuid4()
    with web:
        response = web.post(f"/internal/executions/{execution_id}/dispatch",
            json={**payload(execution_id), "privileged": True, "image": "unapproved", "code": "private-secret"},
            headers={"X-AgentForge-Runner-Token": token})
        assert response.status_code == 422
        assert "private-secret" not in response.text and "unapproved" not in response.text
    assert runner.calls == []


def test_internal_execution_mismatch_never_dispatches(settings):
    web, runner, token = client(settings)
    execution_id = uuid4()
    with web:
        response = web.post(f"/internal/executions/{execution_id}/dispatch", json=payload(uuid4()),
            headers={"X-AgentForge-Runner-Token": token})
        assert response.status_code == 409 and response.json()["code"] == "EXECUTION_MISMATCH"
        assert web.get("/docs").status_code == 404
    assert runner.calls == []
