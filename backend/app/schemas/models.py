from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from urllib.parse import urlsplit
from typing import Literal


class ModelRole(StrEnum):
    PLANNER = "planner"
    CODER = "coder"
    RESEARCHER = "researcher"
    REVIEWER = "reviewer"


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)
    provider: str | None = None
    base_url: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9._:/-]+$")
    credential_reference: str | None = Field(default=None, pattern=r"^env:AGENTFORGE_MODEL_[A-Z0-9_]{1,64}$")
    temperature: float = Field(default=0.2, ge=0, le=2, allow_inf_nan=False)
    max_tokens: int = Field(default=4096, ge=1, le=131072)
    timeout: int = Field(default=60, ge=1, le=300)
    enabled: bool = False
    priority: int = Field(default=50, ge=0, le=100)
    thinking_mode: Literal['disabled', 'enabled'] = 'disabled'
    reasoning_effort: Literal['low', 'high', 'max'] = 'high'

    @field_validator('credential_reference')
    @classmethod
    def credential_is_not_policy(cls, value):
        from app.core.config import is_model_credential_name
        if value is not None and not is_model_credential_name(value.removeprefix('env:')):
            raise ValueError('model policy variables cannot be credential references')
        return value

    @field_validator("provider")
    @classmethod
    def provider_registered(cls, value):
        if value is not None and value not in {"deepseek", "openai_compatible", "anthropic", "google", "azure_openai", "mock"}:
            raise ValueError("provider is not registered for configuration")
        return value

    @field_validator("base_url")
    @classmethod
    def endpoint_has_no_secrets(cls, value):
        if value is not None:
            try:
                url = urlsplit(value)
                if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise ValueError
                if url.port not in {None, 443}:
                    raise ValueError
            except ValueError:
                raise ValueError("invalid model endpoint") from None
        return value

    @model_validator(mode="after")
    def enabled_requires_configuration(self):
        if self.enabled:
            if not self.provider or not self.model:
                raise ValueError("enabled slot requires provider and model")
            if self.provider != "mock" and (not self.base_url or not self.credential_reference):
                raise ValueError("enabled real slot requires endpoint and credential reference")
        if self.provider == "mock" and (self.credential_reference or self.base_url):
            raise ValueError("mock configuration must not contain real credentials or endpoints")
        from app.providers.deepseek import validate_profile, uses_deepseek_profile
        if uses_deepseek_profile(self.model_dump()):
            from app.core.errors import AppError
            try:
                validate_profile(self.model_dump())
            except (AppError, ValueError):
                raise ValueError('invalid DeepSeek model or endpoint') from None
        elif self.thinking_mode != 'disabled' or self.reasoning_effort != 'high':
            raise ValueError('thinking controls require the reviewed DeepSeek adapter')
        return self


class ModelUpdate(ModelConfig):
    expected_version: int = Field(ge=1)
