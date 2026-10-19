import pytest
from app.providers.base import ProviderFailure
from app.core.errors import AppError
from app.services.orchestration.real_runtime import RealRuntime


@pytest.mark.parametrize('code', ['MODEL_RATE_LIMIT', 'MODEL_TIMEOUT', 'MODEL_SERVER_ERROR', 'MODEL_OUTPUT_INVALID'])
async def test_real_connectivity_test_never_retries_even_a_retryable_failure(code):
    runtime = object.__new__(RealRuntime)
    runtime.require_real_permit = lambda: None  # Retry algorithm under an explicit authorization double.
    calls = []
    async def options(): return {'model_test': True}
    async def attempt(*args):
        calls.append(args)
        raise ProviderFailure(code, True)
    runtime.options = options
    runtime._real_attempt = attempt
    with pytest.raises(AppError) as error: await runtime.operation('coder', 0, {})
    assert error.value.code == code and len(calls) == 1


async def test_maintenance_egress_gate_stops_before_dns_or_credential_use(monkeypatch):
    from transport_permit_stub import authorize_mock_transport
    authorize_mock_transport(monkeypatch)
    from app.providers.deepseek import DeepSeek
    monkeypatch.setenv('AGENTFORGE_EXTERNAL_MODELS_BLOCKED', '1')
    async def forbidden(host): raise AssertionError('DNS must not execute')
    monkeypatch.setattr('app.providers.openai_compatible.public_address', forbidden)
    async def delta(text): raise AssertionError('No response can be published')
    with pytest.raises(ProviderFailure) as error:
        await DeepSeek().complete({}, [], 'explicit-fake-key-only', delta)
    assert error.value.code == 'MODEL_EGRESS_BLOCKED' and not error.value.retryable
