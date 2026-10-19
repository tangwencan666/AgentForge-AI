from types import SimpleNamespace
from uuid import uuid4
import pytest
from pydantic import SecretStr, ValidationError
from app.core.errors import AppError
from app.providers.base import ProviderFailure
from app.providers.deepseek import DeepSeek
from app.providers.openai_compatible import OpenAICompatible
from app.services.permit_authority import DispatchLease, require_dispatch, verify_issuer, require_issuer
from app.services.orchestration.real_runtime import RealRuntime
from app.services.context import redact


@pytest.mark.parametrize('adapter', [OpenAICompatible, DeepSeek])
@pytest.mark.parametrize('capability', [None, 'permit-id', SimpleNamespace(commit=lambda: None),
    DispatchLease(None, uuid4(), None, 1, object())])
async def test_physical_adapter_requires_sealed_permit_before_dns_or_http(adapter, capability, monkeypatch):
    async def forbidden(*args): raise AssertionError('Must not reach DNS')
    monkeypatch.setattr('app.providers.openai_compatible.public_address', forbidden)
    async def delta(_): raise AssertionError('Must not stream')
    with pytest.raises(ProviderFailure, match='MODEL_PERMIT_REQUIRED'):
        await adapter().complete({'timeout': 30}, [], 'explicit-fake', delta, dispatch=capability)


@pytest.mark.parametrize('entry', ['operation', '_real_attempt'])
async def test_legacy_background_runtime_is_closed(settings, entry):
    runtime = RealRuntime(None, settings, uuid4(), settings.tenant_id, 'untrusted', 1)
    with pytest.raises(AppError, match='MODEL_PERMIT_REQUIRED'):
        await getattr(runtime, entry)('coder', 0, {}) if entry == 'operation' else await runtime._real_attempt('coder', 'coder:0:0', 0)


def test_issuer_is_distinct_and_redacted(settings):
    token = 'distinct-test-issuer-protected-0001'
    s = settings.model_copy(update={'model_permit_issuer_token': SecretStr(token)})
    assert token not in repr(s) and token not in redact('value ' + token, s)
    with pytest.raises(AppError): verify_issuer(settings.admin_token.get_secret_value(), s)
    with pytest.raises(AppError): require_issuer(SimpleNamespace(tenant_id=s.tenant_id), s)
    with pytest.raises(ValidationError):
        type(settings).model_validate(settings.model_dump() | {'model_permit_issuer_token': settings.admin_token})


def test_worker_bootstrap_discards_issuer_authority_but_keeps_model_key_name(settings, monkeypatch):
    from app.workers import main as bootstrap
    monkeypatch.setenv('AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN', 'explicit-issuer-test-not-for-worker')
    monkeypatch.setenv('AGENTFORGE_MODEL_CODER_KEY', 'explicit-coder-test-only')
    monkeypatch.setattr(bootstrap, 'Settings', lambda **values: settings.model_copy(update=values))
    import os
    result = bootstrap.load_worker_settings()
    assert result.model_permit_issuer_token is None
    assert 'AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN' not in os.environ
    assert 'AGENTFORGE_MODEL_CODER_KEY' in os.environ
