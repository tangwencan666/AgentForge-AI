import os
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
from app.core.config import validate_model_endpoint, is_model_credential_name
from app.core.errors import AppError
from app.providers.openai_compatible import OpenAICompatible


class PricePolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    input_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    output_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    input_upper_bound: int = Field(ge=128, le=100000)
    output_upper_bound: int = Field(ge=1, le=131072)
    version: str = Field(min_length=1, max_length=32)
    token_parameter: str = Field(default='max_completion_tokens', pattern='^(max_completion_tokens|max_tokens)$')

    def cost(self, input_tokens, output_tokens):
        return ((Decimal(input_tokens) * self.input_per_million + Decimal(output_tokens) * self.output_per_million) / Decimal(1000000)).quantize(Decimal('0.00000001'), rounding='ROUND_CEILING')


def resolve_credential(reference, settings):
    name = (reference or '').removeprefix('env:')
    if not reference or not reference.startswith('env:') or not is_model_credential_name(name):
        raise AppError('CREDENTIAL_UNAVAILABLE', 'Protected model credential is unavailable', 409)
    # Project .env is read on the server; never load secrets into a public DTO/snapshot.
    from dotenv import dotenv_values
    from app.core.config import ROOT
    value = os.environ.get(name) or dotenv_values(ROOT / '.env').get(name)
    protected = [v.get_secret_value() for v in (settings.admin_token, settings.sandbox_runner_token,
        settings.sandbox_approver_token, settings.mcp_server_token, settings.capability_approver_token) if v]
    if not value or len(value) < 16 or any(c.isspace() for c in value) or value in protected:
        raise AppError('CREDENTIAL_UNAVAILABLE', 'Protected model credential is unavailable', 409)
    return value


def price_for(config, settings):
    try:
        return PricePolicy.model_validate(settings.model_prices[config['provider'] + '/' + config['model']])
    except Exception:
        raise AppError('MODEL_PRICE_UNAVAILABLE', 'Register a reviewed model price and conservative token bounds', 409) from None


class ModelRouter:
    adapters = {'openai_compatible': OpenAICompatible}

    def __init__(self, settings):
        self.settings = settings

    def resolve(self, config):
        if not self.settings.real_calls_enabled:
            raise AppError('REAL_CALLS_DISABLED', 'Real model calls are disabled by server policy', 409)
        if not config['enabled'] or config['provider'] not in self.adapters:
            raise AppError('MODEL_ADAPTER_UNAVAILABLE', 'Model slot is disabled or protocol adapter is unavailable', 409)
        try:
            validate_model_endpoint(config['base_url'], self.settings.model_hosts)
        except (ValueError, TypeError):
            raise AppError('MODEL_ENDPOINT_BLOCKED', 'Model endpoint is not approved', 409) from None
        from urllib.parse import urlsplit
        name = (config.get('credential_reference') or '').removeprefix('env:')
        permitted = self.settings.model_credential_hosts.get(name, [])
        if not isinstance(permitted, list) or urlsplit(config['base_url']).hostname not in permitted:
            raise AppError('CREDENTIAL_ENDPOINT_FORBIDDEN', 'Credential is not approved for this endpoint audience', 409)
        secret = resolve_credential(config['credential_reference'], self.settings)
        price = price_for(config, self.settings)
        if config['max_tokens'] > price.output_upper_bound:
            raise AppError('MODEL_CAPABILITY_INVALID', 'Configured output exceeds registered model capability', 409)
        return self.adapters[config['provider']](), secret, price
