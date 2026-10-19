import json
import secrets
import pytest
import httpx
from pydantic import ValidationError
from app.providers.base import ProviderFailure
from app.providers.openai_compatible import OpenAICompatible, public_address
from app.providers.router import ModelRouter, PricePolicy, resolve_credential
from app.schemas.agents import AgentPlan, ToolProposal


@pytest.mark.parametrize('nodes', [[], [{'id': 'coder', 'role': 'coder', 'depends_on': [], 'instruction': 'x'}],
    [{'id': 'coder', 'role': 'coder', 'depends_on': ['researcher'], 'instruction': 'x'}, {'id': 'researcher', 'role': 'researcher', 'depends_on': ['coder'], 'instruction': 'x'}]])
def test_structured_plan_rejects_invalid_dags(nodes):
    with pytest.raises(ValidationError): AgentPlan.model_validate({'nodes': nodes})


@pytest.mark.parametrize('extra', [{'approved': True}, {'endpoint': 'http://localhost'}, {'requester': 'reviewer'}])
def test_tool_proposals_cannot_grant_authority(extra):
    with pytest.raises(ValidationError): ToolProposal.model_validate({'tool': 'notes.read', 'arguments': {'resource': 'test'}, **extra})


def test_router_is_fail_closed_and_does_not_use_admin_as_model_key(settings, monkeypatch):
    with pytest.raises(Exception, match='REAL_CALLS_DISABLED'): ModelRouter(settings).resolve({})
    monkeypatch.setenv('AGENTFORGE_MODEL_UNIT_KEY', settings.admin_token.get_secret_value())
    with pytest.raises(Exception, match='CREDENTIAL_UNAVAILABLE'): resolve_credential('env:AGENTFORGE_MODEL_UNIT_KEY', settings)


def test_credential_audience_is_checked_before_network(settings, monkeypatch):
    monkeypatch.setenv('AGENTFORGE_MODEL_UNIT_KEY', 'explicit-unit-credential-value')
    settings = settings.model_copy(update={'real_calls_enabled': True})
    cfg = {**config(), 'enabled': True, 'provider': 'openai_compatible', 'credential_reference': 'env:AGENTFORGE_MODEL_UNIT_KEY'}
    with pytest.raises(Exception, match='CREDENTIAL_ENDPOINT_FORBIDDEN'): ModelRouter(settings).resolve(cfg)


@pytest.mark.parametrize('address', ['127.0.0.1', '169.254.169.254', '10.0.0.1', '::1'])
async def test_dns_private_and_metadata_addresses_are_rejected(monkeypatch, address):
    monkeypatch.setattr('socket.getaddrinfo', lambda *a, **k: [(None, None, None, '', (address, 443))])
    with pytest.raises(ProviderFailure, match='MODEL_ENDPOINT_BLOCKED'): await public_address('approved.example')


def test_price_uses_decimal_and_requires_reviewed_bounds():
    price = PricePolicy(input_per_million='.1', output_per_million='.2', input_upper_bound=8192, output_upper_bound=1024, version='unit')
    assert str(price.cost(1000, 1000)) == '0.00030000'
    with pytest.raises(ValidationError): PricePolicy(input_per_million='NaN', output_per_million=0, input_upper_bound=1, output_upper_bound=1, version='x')


def test_priority_orders_ready_roles_without_changing_their_routes():
    from app.services.orchestration.graph import dispatch_order
    assert dispatch_order({'coder': 80, 'researcher': 5}) == ['researcher_parallel', 'coder_parallel']
    assert dispatch_order({'coder': 1, 'researcher': 90}) == ['coder_parallel', 'researcher_parallel']


def setup_transport(monkeypatch, handler):
    from transport_permit_stub import authorize_mock_transport
    authorize_mock_transport(monkeypatch)
    original = httpx.AsyncClient
    monkeypatch.setattr('app.providers.openai_compatible.public_address', async_ip)
    def client(**kw):
        kw.pop('transport', None)
        return original(transport=httpx.MockTransport(handler), **kw)
    monkeypatch.setattr(httpx, 'AsyncClient', client)


async def async_ip(host): return '93.184.216.34'


def config(): return {'base_url': 'https://api.openai.com/v1', 'model': 'unit', 'temperature': .2, 'max_tokens': 64, 'timeout': 1}


@pytest.mark.parametrize('status,code,retry', [(401, 'MODEL_AUTH_INVALID', False), (403, 'MODEL_ACCESS_DENIED', False), (429, 'MODEL_RATE_LIMIT', True), (500, 'MODEL_SERVER_ERROR', True), (302, 'MODEL_REQUEST_REJECTED', False)])
async def test_errors_never_echo_provider_body_or_credentials(monkeypatch, status, code, retry):
    secret = secrets.token_hex(24)
    setup_transport(monkeypatch, lambda req: httpx.Response(status, text=secret, headers={'Location': 'https://other.example'}))
    with pytest.raises(ProviderFailure) as result: await OpenAICompatible().complete(config(), [], secret, noop)
    assert result.value.code == code and result.value.retryable == retry and secret not in str(result.value)


async def noop(text): pass


@pytest.mark.parametrize('usage', [True, False])
async def test_streamed_text_usage_ttft_host_sni_and_bounded_tokens(monkeypatch, usage):
    async def handler(req):
        assert req.url.host == '93.184.216.34' and req.headers['host'] == 'api.openai.com'
        assert req.extensions['sni_hostname'] == 'api.openai.com'
        assert json.loads(req.content)['max_completion_tokens'] == 64
        frames = [{'choices': [{'index': 0, 'delta': {'content': 'hello\n'}, 'finish_reason': None}]},
                  {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}]
        if usage: frames.append({'choices': [], 'usage': {'prompt_tokens': 7, 'completion_tokens': 3, 'total_tokens': 10}})
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=''.join('data: ' + json.dumps(f) + '\n\n' for f in frames) + 'data: [DONE]\n\n')
    setup_transport(monkeypatch, handler)
    result = await OpenAICompatible().complete(config(), [], 'unit-protected-value', noop)
    assert result.text == 'hello\n' and result.first_token_ms is not None
    assert result.total_tokens == (10 if usage else None)


@pytest.mark.parametrize('body', ['not SSE', 'data: invalid-json\n\n', 'data: [DONE]\n\n'])
async def test_malformed_or_incomplete_stream_is_not_a_success(monkeypatch, body):
    setup_transport(monkeypatch, lambda req: httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=body))
    with pytest.raises(ProviderFailure): await OpenAICompatible().complete(config(), [], 'unit-protected-value', noop)


def test_policy_defaults_do_not_corrupt_json_but_credentials_still_redact(settings, monkeypatch):
    # Exercise the explicit protected-dotenv fallback, independent of maintenance env-only policy.
    settings = settings.model_copy(update={'model_credentials_env_only': False})
    from app.services.context import redact
    import dotenv
    secret = secrets.token_hex(24)
    monkeypatch.setenv('AGENTFORGE_MODEL_PRICES', '{}')
    monkeypatch.setenv('AGENTFORGE_MODEL_CREDENTIAL_HOSTS', '{}')
    monkeypatch.setenv('AGENTFORGE_MODEL_TEST_KEY', secret)
    monkeypatch.setattr(dotenv, 'dotenv_values', lambda *args: {
        'AGENTFORGE_MODEL_PRICES': '{}', 'AGENTFORGE_MODEL_CREDENTIAL_HOSTS': '{}',
        'AGENTFORGE_MODEL_LOCAL_KEY': secret[::-1]})
    assert redact('{"arguments": {}}', settings) == '{"arguments": {}}'
    assert secret not in redact(secret, settings)
    assert secret[::-1] not in redact(secret[::-1], settings)


@pytest.mark.parametrize('name', ['AGENTFORGE_MODEL_PRICES', 'AGENTFORGE_MODEL_CREDENTIAL_HOSTS'])
def test_model_policy_cannot_be_used_as_credential(settings, monkeypatch, name):
    from app.providers.router import resolve_credential
    from app.schemas.models import ModelConfig
    from app.core.errors import AppError
    from pydantic import ValidationError
    monkeypatch.setenv(name, secrets.token_hex(24))
    with pytest.raises(ValidationError): ModelConfig(credential_reference='env:' + name)
    with pytest.raises(AppError) as error: resolve_credential('env:' + name, settings)
    assert error.value.code == 'CREDENTIAL_UNAVAILABLE'
