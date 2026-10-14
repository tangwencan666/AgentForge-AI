import pytest
from pydantic import ValidationError
from app.core.config import Settings, validate_model_endpoint
from app.schemas.models import ModelConfig, ModelRole
from app.services.models import validate_configuration
from app.core.errors import AppError


def test_four_role_slots_are_fixed():
    assert [role.value for role in ModelRole] == ["planner", "coder", "researcher", "reviewer"]
    assert ModelConfig().enabled is False


@pytest.mark.parametrize("changes", [
    {"timeout": 0}, {"max_tokens": -1}, {"temperature": 2.5}, {"temperature": float('inf')},
    {"provider": "unregistered"}, {"enabled": True}, {"api_key": "forbidden"},
    {"credential_reference": "raw-key"}, {"enabled": "true"},
    {"base_url": "https://user:password@api.openai.com/v1"},
    {"base_url": "https://api.openai.com/v1?api_key=forbidden"},
])
def test_reject_invalid_model_configuration(changes):
    with pytest.raises(ValidationError):
        ModelConfig(**changes)


@pytest.mark.parametrize("url", ["https://127.0.0.1/v1", "https://169.254.169.254/", "https://localhost/v1", "https://unapproved.example/v1"])
def test_endpoint_allowlist_rejects_private_and_unregistered(url, settings):
    with pytest.raises(ValueError):
        validate_model_endpoint(url, settings.model_hosts)


def test_enabled_slot_uses_protected_reference(settings, monkeypatch):
    config = ModelConfig(provider="openai_compatible", model="test-model", base_url="https://api.openai.com/v1",
                         credential_reference="env:AGENTFORGE_MODEL_TEST", enabled=True)
    monkeypatch.delenv("AGENTFORGE_MODEL_TEST", raising=False)
    with pytest.raises(AppError) as error:
        validate_configuration(config, settings)
    assert error.value.code == "CREDENTIAL_UNAVAILABLE"
    monkeypatch.setenv("AGENTFORGE_MODEL_TEST", "unit-test-only")
    validate_configuration(config, settings)


def test_mock_is_explicit_and_has_no_real_credential():
    assert ModelConfig(provider="mock", model="mock-test", enabled=True).provider == "mock"
    with pytest.raises(ValidationError):
        ModelConfig(provider="mock", credential_reference="env:AGENTFORGE_MODEL_TEST")


@pytest.mark.parametrize("url", ["sqlite:///agentforge", "postgresql+asyncpg://u:p@localhost:5432/other_project", "postgresql+asyncpg://u:p@localhost:5432/agentforge?debug=secret"])
def test_environment_rejects_wrong_database(url, settings):
    data = settings.model_dump()
    data["database_url"] = url
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **data)


def test_settings_do_not_expose_secret_values(settings):
    values = [settings.admin_token.get_secret_value(), settings.database_url.get_secret_value(), settings.redis_url.get_secret_value()]
    for value in values:
        assert value not in repr(settings)
        assert value not in settings.model_dump_json()


def test_secret_cannot_be_stored_in_a_public_model_field(settings,monkeypatch):
    import secrets
    secret=secrets.token_hex(32)
    monkeypatch.setenv('AGENTFORGE_MODEL_TEST',secret)
    config=ModelConfig(provider='openai_compatible',model=secret)
    with pytest.raises(AppError) as error:
        validate_configuration(config,settings)
    assert error.value.code=='CONFIGURATION_CONTAINS_SECRET'


def test_missing_required_environment_is_error(monkeypatch):
    for key in ["AGENTFORGE_DATABASE_URL", "AGENTFORGE_REDIS_URL", "AGENTFORGE_ADMIN_TOKEN"]:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
