from functools import lru_cache
from pathlib import Path
from decimal import Decimal
from urllib.parse import urlsplit
import ipaddress

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTFORGE_", env_file=ROOT / ".env", extra="ignore",
        hide_input_in_errors=True,
    )
    environment: str = "development"
    database_url: SecretStr = Field(repr=False)
    redis_url: SecretStr = Field(repr=False)
    admin_token: SecretStr = Field(repr=False, min_length=32)
    tenant_id: str = "00000000-0000-4000-8000-000000000001"
    dependency_timeout: float = Field(default=2, gt=0, le=10)
    daily_mock_token_limit: int = Field(default=1000000, ge=1)
    daily_mock_budget_usd: Decimal = Field(default=Decimal("10"), gt=0, allow_inf_nan=False)
    allowed_model_hosts: str = "api.openai.com,api.anthropic.com,generativelanguage.googleapis.com"
    sandbox_runner_token: SecretStr | None = Field(default=None, repr=False)
    sandbox_approver_token: SecretStr | None = Field(default=None, repr=False)
    sandbox_image_id: str | None = None
    sandbox_runner_url: str = "http://127.0.0.1:18120"
    sandbox_daily_cpu_seconds: Decimal = Field(default=Decimal("3600"), gt=0, le=86400)
    sandbox_max_concurrency: int = Field(default=4, ge=1, le=4)
    sandbox_tenant_concurrency: int = Field(default=2, ge=1, le=2)
    sandbox_prewarm_enabled: bool = False

    @field_validator("sandbox_image_id")
    @classmethod
    def immutable_image(cls, value):
        import re
        if value is not None and not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
            raise ValueError("sandbox image must be a fixed immutable image ID")
        return value

    @field_validator("sandbox_runner_url")
    @classmethod
    def local_runner(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "runner"} or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("sandbox Runner endpoint must be the project control plane")
        return value.rstrip("/")

    @field_validator("environment")
    @classmethod
    def valid_environment(cls, value: str) -> str:
        if value not in {"development", "test", "production"}:
            raise ValueError("unsupported environment")
        return value

    @field_validator("tenant_id")
    @classmethod
    def valid_tenant(cls, value: str) -> str:
        from uuid import UUID
        return str(UUID(value))

    @field_validator("database_url", "redis_url")
    @classmethod
    def valid_connection_url(cls, value: SecretStr, info) -> SecretStr:
        try:
            parsed = urlsplit(value.get_secret_value())
            allowed = {"postgresql+asyncpg"} if info.field_name == "database_url" else {"redis", "rediss"}
            if parsed.scheme not in allowed or not parsed.hostname or not parsed.port or parsed.query or parsed.fragment:
                raise ValueError
            if info.field_name == "database_url" and parsed.path != "/agentforge":
                raise ValueError
            if info.field_name == "redis_url" and parsed.path != "/0":
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("invalid project connection URL") from None
        return value

    @model_validator(mode="after")
    def enforce_production_transport(self):
        configured = [self.admin_token, self.sandbox_runner_token, self.sandbox_approver_token]
        values = [v.get_secret_value() for v in configured if v is not None]
        if any(len(v) < 32 for v in values) or len(values) != len(set(values)):
            raise ValueError("server roles require distinct protected credentials")
        if self.sandbox_prewarm_enabled:
            raise ValueError("prewarm is disabled until isolation and lifecycle validation is approved")
        if self.environment == "production":
            if not self.redis_url.get_secret_value().startswith("rediss://"):
                raise ValueError("production Redis requires TLS")
            raise ValueError("Only development/test deployment is supported; production is not released")
        return self

    @property
    def model_hosts(self) -> frozenset[str]:
        return frozenset(host.strip().lower() for host in self.allowed_model_hosts.split(",") if host.strip())


def validate_model_endpoint(value: str, allowed_hosts: frozenset[str]) -> str:
    try:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError
        if url.port not in {None, 443} or url.hostname.lower() not in allowed_hosts:
            raise ValueError
        try:
            address = ipaddress.ip_address(url.hostname)
        except ValueError:
            address = None
        if url.hostname.lower() == "localhost" or (address and not address.is_global):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("model endpoint is not approved") from None
    return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
