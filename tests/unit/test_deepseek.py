"""DeepSeek protocol fixtures only: no vendor traffic, no real credentials."""
import importlib.util
import json
from pathlib import Path
from decimal import Decimal
import httpx
import pytest
from pydantic import ValidationError
from app.core.errors import AppError
from app.providers.base import ProviderFailure
from app.providers.deepseek import DeepSeek
from app.providers.router import ModelRouter, PricePolicy
from app.schemas.models import ModelConfig, ModelRole

ROOT = Path(__file__).resolve().parents[2]


def cfg(**changes):
    return {**ModelConfig(provider='deepseek', base_url='https://api.deepseek.com', model='deepseek-flash').model_dump(),
            'max_tokens': 64, 'timeout': 1, **changes}


@pytest.mark.parametrize('model', ['deepseek-flash', 'deepseek-v4-pro'])
@pytest.mark.parametrize('mode', ['disabled', 'enabled'])
@pytest.mark.parametrize('effort', ['low', 'high', 'max'])
def test_explicit_mode_and_supported_parameters(model, mode, effort):
    body = DeepSeek().request_body(cfg(model=model, thinking_mode=mode, reasoning_effort=effort), [])
    assert body['thinking'] == {'type': mode} and body['max_tokens'] == 64
    assert 'max_completion_tokens' not in body and 'tools' not in body and body['stream_options']['include_usage']
    if mode == 'enabled':
        assert body['reasoning_effort'] == effort and 'temperature' not in body
    else:
        assert 'reasoning_effort' not in body and body['temperature'] == .2


@pytest.mark.parametrize('change', [
    {'base_url': 'https://api.deepseek.com.evil.example'}, {'base_url': 'https://deepseek.com'},
    {'base_url': 'https://api.deepseek.com/anthropic'}, {'base_url': 'https://api.deepseek.com/beta'},
    {'base_url': 'https://api.deepseek.com:444'}, {'model': 'deepseek-chat'},
    {'model': 'deepseek-v4-flash'}, {'thinking_mode': 'auto'}, {'reasoning_effort': 'unbounded'},
    {'base_url': 'https://user:secret@api.deepseek.com'}, {'base_url': 'https://api.deepseek.com?key=secret'}])
def test_unknown_models_endpoints_and_options_fail_closed(change):
    with pytest.raises(ValidationError): ModelConfig.model_validate(cfg(**change))


def test_openai_compatible_deepseek_alias_still_requires_audience(settings):
    config = cfg(provider='openai_compatible', enabled=True, credential_reference='env:AGENTFORGE_MODEL_TEST')
    settings = settings.model_copy(update={'real_calls_enabled': True})
    with pytest.raises(AppError) as error: ModelRouter(settings).resolve(config)
    assert error.value.code == 'CREDENTIAL_ENDPOINT_FORBIDDEN'


def test_audience_and_price_are_checked_without_using_local_credentials(settings, monkeypatch):
    config = cfg(enabled=True, credential_reference='env:AGENTFORGE_MODEL_TEST')
    settings = settings.model_copy(update={'real_calls_enabled': True})
    with pytest.raises(AppError) as error: ModelRouter(settings).resolve(config)
    assert error.value.code == 'CREDENTIAL_ENDPOINT_FORBIDDEN'
    monkeypatch.setenv('AGENTFORGE_MODEL_TEST', 'explicit-unit-only-credential')
    settings = settings.model_copy(update={'model_credential_hosts': {'AGENTFORGE_MODEL_TEST': ['api.deepseek.com']},
        'model_prices': {'deepseek/deepseek-flash': {'input_per_million': '.3', 'output_per_million': '1.2',
            'input_upper_bound': 8192, 'output_upper_bound': 64, 'version': 'test'}}})
    with pytest.raises(AppError) as error: ModelRouter(settings).resolve(config)
    assert error.value.code == 'MODEL_CAPABILITY_INVALID'  # max_completion_tokens is not accepted.
    settings.model_prices['deepseek/deepseek-flash']['token_parameter'] = 'max_tokens'
    adapter, secret, price = ModelRouter(settings).resolve(config)
    assert isinstance(adapter, DeepSeek) and secret == 'explicit-unit-only-credential'


class Chunks(httpx.AsyncByteStream):
    def __init__(self, data): self.data = data
    async def __aiter__(self):
        for i in range(0, len(self.data), 3): yield self.data[i:i + 3]


def wire(items, done=True):
    data = ': keep-alive\r\n\r\n' + ''.join('data: ' + json.dumps(v, ensure_ascii=False) + '\r\n\r\n' for v in items)
    return (data + ('data: [DONE]\r\n\r\n' if done else '')).encode()


def final_usage():
    return {'prompt_tokens': 10, 'completion_tokens': 8, 'total_tokens': 18,
            'prompt_cache_hit_tokens': 4, 'prompt_cache_miss_tokens': 6,
            'prompt_tokens_details': {'cached_tokens': 4}, 'completion_tokens_details': {'reasoning_tokens': 5}}


def frame(content=None, reason=None, **delta):
    return {'choices': [{'index': 0, 'delta': {'content': content, **delta}, 'finish_reason': reason}]}


def install(monkeypatch, handler):
    from transport_permit_stub import authorize_mock_transport
    authorize_mock_transport(monkeypatch)
    original = httpx.AsyncClient
    async def address(host):
        assert host == 'api.deepseek.com'
        return '93.184.216.34'
    monkeypatch.setattr('app.providers.openai_compatible.public_address', address)
    def client(**kwargs):
        kwargs.pop('transport', None)
        return original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(httpx, 'AsyncClient', client)


@pytest.mark.parametrize('model', ['deepseek-flash', 'deepseek-v4-pro'])
@pytest.mark.parametrize('known', [True, False])
@pytest.mark.parametrize('mode', ['disabled', 'enabled'])
async def test_fragmented_sse_final_choice_usage_and_private_reasoning(monkeypatch, model, known, mode):
    items = [frame(reasoning_content='PRIVATE_THINKING_NOT_AN_ANSWER'), frame('连通'), frame('connected')]
    last = frame('', 'stop')
    if known: last['usage'] = final_usage()
    items.append(last)
    def handler(request):
        assert request.url.host == '93.184.216.34' and request.headers['host'] == 'api.deepseek.com'
        assert request.extensions['sni_hostname'] == 'api.deepseek.com'
        body = json.loads(request.content)
        assert body['thinking'] == {'type': mode} and body['max_tokens'] == 64
        assert ('reasoning_effort' in body) == (mode == 'enabled')
        assert ('temperature' in body) == (mode == 'disabled')
        return httpx.Response(200, headers={'content-type': 'text/event-stream; charset=utf-8'}, stream=Chunks(wire(items)))
    install(monkeypatch, handler)
    deltas = []
    async def delta(text): deltas.append(text)
    result = await DeepSeek().complete(cfg(model=model, thinking_mode=mode), [], 'explicit-fake-key', delta)
    assert result.text == '连通connected' and ''.join(deltas) == result.text
    assert result.total_tokens == (18 if known else None) and result.output_tokens == (8 if known else None)
    assert 'PRIVATE_' not in repr(result) and result.first_token_ms is not None


@pytest.mark.parametrize('change', [{'total_tokens': 17}, {'prompt_cache_hit_tokens': 3},
    {'prompt_cache_miss_tokens': None}, {'prompt_tokens_details': {'cached_tokens': 5}},
    {'completion_tokens_details': {'reasoning_tokens': 9}}, {'completion_tokens_details': {'reasoning_tokens': True}}])
def test_usage_details_are_consistent_and_reasoning_is_not_double_counted(change):
    with pytest.raises(ProviderFailure, match='MODEL_USAGE_INVALID'): DeepSeek().parse_usage({**final_usage(), **change})
    assert DeepSeek().parse_usage(final_usage()) == [10, 8, 18]


@pytest.mark.parametrize('items,done,code', [
    ([frame('draft', 'length')], True, 'MODEL_OUTPUT_INCOMPLETE'),
    ([frame('draft')], False, 'MODEL_STREAM_INCOMPLETE'),
    ([frame(reasoning_content='only thinking'), frame('', 'stop')], True, 'MODEL_STREAM_INCOMPLETE'),
    ([frame(tool_calls=[{'function': {'name': 'host.shell'}}])], True, 'MODEL_NATIVE_TOOL_CALL_REJECTED'),
    ([frame(function_call={'name': 'host.shell'})], True, 'MODEL_NATIVE_TOOL_CALL_REJECTED'),
    ([{'error': {'message': 'PROVIDER_SECRET'}}], True, 'MODEL_STREAM_ERROR'),
    ([{'choices': False}], True, 'MODEL_PROTOCOL_INVALID'),
    ([frame(False)], True, 'MODEL_PROTOCOL_INVALID'),
    ([frame('done', 'stop'), frame('unexpected')], True, 'MODEL_PROTOCOL_INVALID'),
    ([[]], True, 'MODEL_PROTOCOL_INVALID')])
async def test_bad_streams_cannot_be_success_or_execute_tools(monkeypatch, items, done, code):
    install(monkeypatch, lambda req: httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Chunks(wire(items, done))))
    async def delta(text): pass
    with pytest.raises(ProviderFailure) as error: await DeepSeek().complete(cfg(), [], 'FAKE_SECRET', delta)
    assert error.value.code == code and 'PROVIDER_SECRET' not in str(error.value) and 'FAKE_SECRET' not in str(error.value)


@pytest.mark.parametrize('status,code,retry', [(401,'MODEL_AUTH_INVALID',False), (402,'MODEL_PAYMENT_REQUIRED',False),
    (422,'MODEL_REQUEST_INVALID',False), (429,'MODEL_RATE_LIMIT',True), (500,'MODEL_SERVER_ERROR',True),
    (503,'MODEL_SERVER_ERROR',True), (307,'MODEL_REQUEST_REJECTED',False)])
async def test_provider_errors_are_safe_and_bounded_by_runtime(monkeypatch, status, code, retry):
    install(monkeypatch, lambda req: httpx.Response(status, text='NEVER_ECHO_PROVIDER_BODY'))
    async def delta(text): pass
    with pytest.raises(ProviderFailure) as error: await DeepSeek().complete(cfg(), [], 'FAKE_SECRET', delta)
    assert (error.value.code, error.value.retryable) == (code, retry)
    assert 'NEVER_ECHO' not in str(error.value)


async def test_network_timeout_is_safe(monkeypatch):
    def handler(request): raise httpx.ReadTimeout('NEVER_ECHO_NETWORK_DETAILS')
    install(monkeypatch, handler)
    async def delta(text): pass
    with pytest.raises(ProviderFailure) as error: await DeepSeek().complete(cfg(), [], 'FAKE_SECRET', delta)
    assert error.value.code == 'MODEL_TIMEOUT' and error.value.retryable


def test_disabled_four_role_template_and_usd_peak_budget():
    template = json.loads((ROOT / 'config/deepseek-preparation.json').read_text(encoding='utf-8'))
    policy = template['server_policy']
    assert not policy['real_calls_enabled'] and Decimal(policy['real_daily_budget_usd']) == 0
    assert Decimal(policy['real_test_budget_usd']) == 0
    assert set(template['slots']) == {r.value for r in ModelRole}
    for role, raw in template['slots'].items():
        slot = ModelConfig.model_validate(raw)
        assert not slot.enabled and slot.thinking_mode == 'disabled'
        assert slot.credential_reference == f'env:AGENTFORGE_MODEL_{role.upper()}_KEY'
        assert policy['model_credential_hosts'][slot.credential_reference[4:]] == ['api.deepseek.com']
    flash = PricePolicy.model_validate(policy['model_prices']['deepseek/deepseek-flash'])
    pro = PricePolicy.model_validate(policy['model_prices']['deepseek/deepseek-v4-pro'])
    assert flash.cost(8192, 64) == Decimal('0.00253440')
    assert pro.cost(8192, 64) == Decimal('0.01106688')
    with pytest.raises(ValidationError): PricePolicy.model_validate({**flash.model_dump(), 'currency': 'CNY'})


def test_legacy_usd_snapshot_is_compatible_but_price_changes_are_blocked():
    from app.providers.router import price_matches_snapshot
    old = {'input_per_million': '.3', 'output_per_million': '1.2', 'input_upper_bound': 8192,
           'output_upper_bound': 64, 'version': 'test', 'token_parameter': 'max_tokens'}
    price = PricePolicy.model_validate(old)
    assert price_matches_snapshot(price, old)
    assert not price_matches_snapshot(price, {**old, 'output_per_million': '1.3'})
    assert not price_matches_snapshot(price, {**old, 'currency': 'CNY'})


async def test_dns_failure_is_a_safe_network_error(monkeypatch):
    from transport_permit_stub import authorize_mock_transport
    authorize_mock_transport(monkeypatch)
    async def failure(host): raise OSError('NEVER_ECHO_DNS_DETAILS')
    monkeypatch.setattr('app.providers.openai_compatible.public_address', failure)
    async def delta(text): pass
    with pytest.raises(ProviderFailure) as error: await DeepSeek().complete(cfg(), [], 'FAKE_SECRET', delta)
    assert error.value.code == 'MODEL_NETWORK_ERROR' and error.value.retryable


def test_migration_is_additive_offline(monkeypatch):
    spec = importlib.util.spec_from_file_location('deepseek_migration', ROOT / 'backend/migrations/versions/0007_deepseek.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    added, constraints = [], []
    monkeypatch.setattr(module.op, 'add_column', lambda table, col: added.append((table, col)))
    monkeypatch.setattr(module.op, 'create_check_constraint', lambda *args: constraints.append(args))
    module.upgrade()
    assert module.down_revision == '0006_real_models' and len(added) == 2 and len(constraints) == 2
    assert all(table == 'model_slots' and not col.nullable for table, col in added)
    assert {col.server_default.arg for _, col in added} == {'disabled', 'high'}


def test_postgresql_upgrade_sql_can_be_generated_without_a_connection(monkeypatch):
    from io import StringIO
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location('deepseek_sql', ROOT / 'backend/migrations/versions/0007_deepseek.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    buffer = StringIO()
    context = MigrationContext.configure(dialect_name='postgresql', opts={'as_sql': True, 'output_buffer': buffer})
    monkeypatch.setattr(module, 'op', Operations(context))
    module.upgrade()
    sql = buffer.getvalue()
    assert 'ADD COLUMN thinking_mode' in sql and "DEFAULT 'disabled' NOT NULL" in sql
    assert 'ck_model_effort' in sql and 'DROP ' not in sql and 'api_key' not in sql


def test_four_role_thinking_settings_survive_database_roundtrip_without_secrets():
    from uuid import uuid4
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from sqlalchemy.exc import IntegrityError
    from app.domain.entities import ModelSlot
    from app.services.models import slot_dto
    engine = create_engine('sqlite:///:memory:')
    ModelSlot.__table__.create(engine)
    tenant = uuid4()
    with Session(engine) as session:
        for index, role in enumerate(ModelRole):
            session.add(ModelSlot(tenant_id=tenant, role=role.value,
                **cfg(thinking_mode='enabled' if index % 2 else 'disabled', reasoning_effort='low',
                      credential_reference=f'env:AGENTFORGE_MODEL_{role.value.upper()}_KEY')))
        session.commit()
    with Session(engine) as session:
        rows = session.scalars(select(ModelSlot).order_by(ModelSlot.role)).all()
        assert {row.role for row in rows} == {r.value for r in ModelRole}
        for row in rows:
            dto = slot_dto(row)
            assert dto['thinking_mode'] == row.thinking_mode and dto['reasoning_effort'] == 'low'
            assert not dto['credential_configured'] and 'api_key' not in dto
            body = DeepSeek().request_body(dto, [])
            assert ('temperature' in body) == (row.thinking_mode == 'disabled')
        rows[0].thinking_mode = 'unsafe'
        with pytest.raises(IntegrityError): session.commit()
    engine.dispose()


def test_offline_guards_block_secret_file_and_external_network():
    import socket
    # The guard is intentionally opt-in through scripts/test-offline.py.
    import sys
    if not {'offline_guards', 'preflight_guards'} & sys.modules.keys():
        pytest.skip('Requires the dedicated no-secret offline runner')
    with pytest.raises(RuntimeError, match='OFFLINE_PROJECT_ENV_READ_FORBIDDEN'):
        (ROOT / '.env').read_text()
    with pytest.raises(RuntimeError, match='OFFLINE_NETWORK_FORBIDDEN'):
        socket.getaddrinfo('api.deepseek.com', 443)
