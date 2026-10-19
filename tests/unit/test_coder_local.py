"""Explicit fake values and local doubles only; no vendor authentication."""
import json
import importlib.util
import os
from pathlib import Path
import subprocess
from time import time
from types import SimpleNamespace
from decimal import Decimal
import pytest
from pydantic import ValidationError
from app.core.config import is_model_credential_name
from app.core.errors import AppError
from app.providers.base import ProviderFailure
from app.providers.deepseek import DeepSeek
from app.providers.router import ModelRouter, resolve_credential
from app.schemas.models import ModelConfig
from app.services.models import credential_configured
from app.services.orchestration.real_runtime import RealRuntime
from app.services import model_runtime_status as status


def configuration(**changes):
    return ModelConfig(provider='openai_compatible', model='deepseek-flash', base_url='https://api.deepseek.com',
        credential_reference='env:AGENTFORGE_MODEL_CODER_KEY', max_tokens=64, **changes).model_dump()


def test_alias_selects_reviewed_adapter_and_explicit_disabled_thinking(settings, monkeypatch):
    monkeypatch.setenv('AGENTFORGE_MODEL_CODER_KEY', 'explicit-test-fake-credential-only')
    template = json.loads((Path(__file__).resolve().parents[2] / 'config/deepseek-coder-local.json').read_text())
    config = ModelConfig.model_validate(template['slot']).model_dump()
    price_key = config['provider'] + '/' + config['model']
    assert price_key == 'openai_compatible/deepseek-flash' and not config['enabled']
    reviewed = settings.model_copy(update={'real_calls_enabled': True,
        'model_credential_hosts': {'AGENTFORGE_MODEL_CODER_KEY': ['api.deepseek.com']},
        'model_prices': {price_key: template['price']}})
    adapter, _, price = ModelRouter(reviewed).resolve(config | {'enabled': True})
    assert isinstance(adapter, DeepSeek)
    body = adapter.request_body(config, [])
    assert body['thinking'] == {'type': 'disabled'} and body['max_tokens'] == 64
    assert 'max_completion_tokens' not in body and 'reasoning_effort' not in body
    assert price.cost(8192, 64) == Decimal('.00253440')
    assert price.output_upper_bound == 4096
    assert price.cost(8192, price.output_upper_bound) == Decimal('.00737280') > Decimal('.005')


@pytest.mark.parametrize('price_changes,error_code', [({}, None),
    ({'output_upper_bound': 63}, 'PERMIT_PRICE_INVALID'),
    ({'input_upper_bound': 8193}, 'PERMIT_PRICE_INVALID'),
    ({'output_per_million': '40'}, 'PERMIT_PRICE_INVALID')])
async def test_actual_coder_price_bounds_are_checked_by_permit_profile(settings, price_changes, error_code):
    from app.services.execution_permits import PermitService
    template = json.loads((Path(__file__).resolve().parents[2] / 'config/deepseek-coder-local.json').read_text())
    rows = [SimpleNamespace(role=role, version=7, **template['slot'])
        for role in ('planner', 'coder', 'researcher', 'reviewer')]
    next(row for row in rows if row.role == 'coder').enabled = True  # In-memory slot double only.

    class Session:
        async def scalars(self, statement): return SimpleNamespace(all=lambda: rows)

    reviewed = settings.model_copy(update={'model_prices': {
        'openai_compatible/deepseek-flash': template['price'] | price_changes}})
    service = PermitService(None, reviewed)
    if error_code:
        with pytest.raises(AppError) as error: await service._profile(Session())
        assert error.value.code == error_code
    else:
        config, price = await service._profile(Session())
        assert config['config_version'] == 7 and config['max_tokens'] == 64
        assert price.input_upper_bound + config['max_tokens'] == 8256
        assert price.cost(price.input_upper_bound, config['max_tokens']) == Decimal('.00253440')
        assert price.cost(price.input_upper_bound, config['max_tokens']) <= Decimal('.005')


@pytest.mark.parametrize('changes', [{'base_url': 'https://api.deepseek.com/beta'}, {'model': 'deepseek-chat'},
    {'thinking_mode': 'auto'}, {'base_url': 'https://api.deepseek.com/anthropic'}])
def test_alias_cannot_bypass_deepseek_profile_validation(changes):
    values = configuration()
    with pytest.raises(ValidationError): ModelConfig.model_validate(values | changes)


def test_environment_only_missing_key_never_reads_dotenv(settings, monkeypatch):
    assert settings.real_max_retries == 0 and settings.model_credentials_env_only
    monkeypatch.delenv('AGENTFORGE_MODEL_CODER_KEY', raising=False)
    monkeypatch.delenv('AGENTFORGE_MODEL_CREDENTIALS_ENV_ONLY', raising=False)
    def forbidden(*args, **kwargs): raise AssertionError('No dotenv fallback allowed')
    monkeypatch.setattr('dotenv.dotenv_values', forbidden)
    assert credential_configured('env:AGENTFORGE_MODEL_CODER_KEY') is False
    with pytest.raises(AppError) as error:
        resolve_credential('env:AGENTFORGE_MODEL_CODER_KEY', settings)
    assert error.value.code == 'CREDENTIAL_UNAVAILABLE'


def test_legacy_file_credential_requires_explicit_opt_in(settings, monkeypatch):
    monkeypatch.delenv('AGENTFORGE_MODEL_CODER_KEY', raising=False)
    monkeypatch.setenv('AGENTFORGE_MODEL_CREDENTIALS_ENV_ONLY', 'false')
    fake = 'explicit-legacy-file-test-credential-only'
    monkeypatch.setattr('dotenv.dotenv_values', lambda *args: {'AGENTFORGE_MODEL_CODER_KEY': fake})
    assert credential_configured('env:AGENTFORGE_MODEL_CODER_KEY') is True
    legacy = settings.model_copy(update={'model_credentials_env_only': False})
    assert resolve_credential('env:AGENTFORGE_MODEL_CODER_KEY', legacy) == fake


def test_credential_status_checks_membership_without_reading_value(monkeypatch):
    import os
    monkeypatch.setenv('AGENTFORGE_MODEL_CODER_KEY', 'explicit-test-fake-credential-only')
    original = os.environ.get
    def protected_get(name, *args):
        if name == 'AGENTFORGE_MODEL_CODER_KEY': raise AssertionError('Credential values must not be read')
        return original(name, *args)
    monkeypatch.setattr(os.environ, 'get', protected_get)
    assert credential_configured('env:AGENTFORGE_MODEL_CODER_KEY') is True


def test_policy_flag_is_never_a_credential_reference():
    assert not is_model_credential_name('AGENTFORGE_MODEL_CREDENTIALS_ENV_ONLY')
    with pytest.raises(ValidationError): ModelConfig(credential_reference='env:AGENTFORGE_MODEL_CREDENTIALS_ENV_ONLY')


@pytest.mark.parametrize('code', ['MODEL_RATE_LIMIT', 'MODEL_TIMEOUT', 'MODEL_SERVER_ERROR'])
async def test_server_zero_retries_also_applies_to_ordinary_workflow(settings, code):
    runtime = object.__new__(RealRuntime)
    runtime.require_real_permit = lambda: None  # Explicit offline authorization double for the retry algorithm.
    runtime.settings = settings.model_copy(update={'real_max_retries': 0})
    calls = []
    async def options(): return {'workflow': 'chat'}
    async def attempt(*args):
        calls.append(args)
        raise ProviderFailure(code, True)
    runtime.options, runtime._real_attempt = options, attempt
    with pytest.raises(AppError) as error: await runtime.operation('coder', 0, {})
    assert error.value.code == code and len(calls) == 1


@pytest.mark.parametrize('stale,different', [(False, False), (False, True), (True, False)])
async def test_runtime_status_detects_settings_difference_and_stale_worker(settings, monkeypatch, stale, different):
    api = {'process_id': 1, 'coder_credential_present': False, 'configuration_digest': 'a' * 64,
        'slot_versions': {'coder': 2}, 'policy': {'real_calls_enabled': False}, 'observed_at': time()}
    worker = {**api, 'process_id': 2, 'configuration_digest': ('b' if different else 'a') * 64,
              'observed_at': time() - (30 if stale else 0)}
    async def observe(*args): return api
    async def get(*args): return json.dumps(worker)
    monkeypatch.setattr(status, 'observe', observe)
    result = await status.compare_runtime_status(SimpleNamespace(redis=SimpleNamespace(get=get)), settings)
    assert result['worker_available'] is not stale
    assert result['configuration_consistent'] == (not stale and not different)


@pytest.fixture
def local_check():
    path = Path(__file__).resolve().parents[2] / 'scripts/check-coder-local.py'
    spec = importlib.util.spec_from_file_location('coder_local_check', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def closed_coder_settings(settings, monkeypatch):
    template = json.loads((Path(__file__).resolve().parents[2] / 'config/deepseek-coder-local.json').read_text())
    monkeypatch.setenv('AGENTFORGE_EXTERNAL_MODELS_BLOCKED', '1')
    return settings.model_copy(update={'real_calls_enabled': False, 'real_max_retries': 0,
        'single_use_permits_enabled': False, 'real_worker_mode': 'deny', 'model_permit_issuer_token': None,
        'real_daily_budget_usd': Decimal(0), 'real_test_budget_usd': Decimal(0),
        'real_daily_token_limit': 8256, 'real_test_max_calls': 1, 'model_credentials_env_only': True,
        'allowed_model_hosts': 'api.deepseek.com',
        'model_credential_hosts': {'AGENTFORGE_MODEL_CODER_KEY': ['api.deepseek.com']},
        'model_prices': {'openai_compatible/deepseek-flash': template['price']}})


def test_local_startup_policy_requires_closed_permits(local_check, closed_coder_settings):
    local_check.validate_local_policy(closed_coder_settings)
    for change in ({'single_use_permits_enabled': True}, {'real_worker_mode': 'permit_only'},
        {'model_permit_issuer_token': object()}, {'allowed_model_hosts': 'api.deepseek.com,api.openai.com'}):
        with pytest.raises(AssertionError): local_check.validate_local_policy(closed_coder_settings.model_copy(update=change))


@pytest.mark.parametrize('api_presence,worker_presence', [(False, False), (True, False), (False, True), ('true', 'true')])
def test_local_check_requires_true_presence_not_merely_agreement(local_check, api_presence, worker_presence):
    state = {'worker_available': True, 'configuration_consistent': True, 'credential_presence_consistent': True,
        'api': {'coder_credential_present': api_presence}, 'worker': {'coder_credential_present': worker_presence}}
    with pytest.raises(AssertionError): local_check.validate_runtime_state(state, 'unused')


def test_local_runtime_verifies_permit_and_budget_policy(local_check, closed_coder_settings):
    import copy
    policy = status.public_policy(closed_coder_settings)
    state = {'worker_available': True, 'configuration_consistent': True, 'credential_presence_consistent': True,
        'api': {'coder_credential_present': True, 'policy': policy},
        'worker': {'coder_credential_present': True, 'policy': dict(policy)}}
    local_check.validate_runtime_state(state, policy['flash_price_digest'])
    for name, value in [('permit_issuance_enabled', True), ('real_worker_mode', 'permit_only'),
        ('test_budget_usd', '.005'), ('real_max_retries', 1)]:
        changed = copy.deepcopy(state)
        changed['worker']['policy'][name] = value
        with pytest.raises(AssertionError): local_check.validate_runtime_state(changed, policy['flash_price_digest'])


@pytest.mark.parametrize('revision,active,permit_count,enabled,passes', [
    ('0008_execution_permits', 0, 0, False, True), ('0007_deepseek', 0, 0, False, False),
    ('0008_execution_permits', 1, 0, False, False), ('0008_execution_permits', 0, 1, False, False),
    ('0008_execution_permits', 0, 0, True, False)])
async def test_before_restart_uses_database_safety_without_old_process_key_requirement(
        local_check, closed_coder_settings, monkeypatch, revision, active, permit_count, enabled, passes):
    from contextlib import asynccontextmanager
    template = json.loads((Path(__file__).resolve().parents[2] / 'config/deepseek-coder-local.json').read_text())
    rows = [SimpleNamespace(role=role, **template['slot']) for role in ('planner', 'coder', 'researcher', 'reviewer')]
    rows[0].enabled = enabled
    values = iter([revision, active, 0, permit_count])
    class Session:
        async def scalar(self, statement):
            if 'agent_tasks.status' in str(statement):
                assert 'paused' not in str(statement.compile().params) # Paused/resumable tasks must also block.
            return next(values)
        async def scalars(self, statement): return SimpleNamespace(all=lambda: rows)
    class Connections:
        @asynccontextmanager
        async def sessions(self): yield Session()
        async def close(self): pass
    def forbidden(*args, **kwargs): raise AssertionError('Pre-restart must not inspect old API/Worker or credential values')
    monkeypatch.setattr(local_check, 'Settings', lambda: closed_coder_settings)
    monkeypatch.setattr(local_check, 'Connections', lambda settings: Connections())
    monkeypatch.setattr(local_check.httpx, 'AsyncClient', forbidden)
    original_get = os.environ.get
    def protected_get(name, *args):
        if name == 'AGENTFORGE_MODEL_CODER_KEY': return forbidden()
        return original_get(name, *args)
    monkeypatch.setattr(os.environ, 'get', protected_get)
    if passes: await local_check.main(before_restart=True)
    else:
        with pytest.raises(AssertionError): await local_check.main(before_restart=True)


@pytest.mark.parametrize('issuer_present', [False, True])
def test_native_startup_policy_only_never_starts_services(issuer_present):
    root = Path(__file__).resolve().parents[2]
    safe_names = ('SystemRoot', 'WINDIR', 'PATH', 'PATHEXT', 'COMSPEC', 'TEMP', 'TMP',
        'APPDATA', 'LOCALAPPDATA', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH')
    child_env = {name: os.environ[name] for name in safe_names if name in os.environ}
    command = ['powershell', '-NoProfile', '-NonInteractive', '-File',
        str(root / 'tests/fixtures/coder-startup-probe.ps1'), '-PolicyOnly']
    if issuer_present: command.append('-IssuerPresent')
    result = subprocess.run(command, cwd=root, env=child_env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, 'Offline startup policy probe failed'
    state = json.loads(result.stdout)
    assert state['service_start_attempts'] == state['external_model_calls'] == 0
    assert state.get('issuer_rejected') is True if issuer_present else state['policy_closed'] and state['coder_name_present']
