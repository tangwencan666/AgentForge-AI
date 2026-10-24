"""Pure VM-demo policy validation: no I/O, app import, dotenv or connection."""
import re
from uuid import UUID

BASE_SOURCE = "662eb38d72f2bed243594deae54008042adf7e45"
EXPECTED_ENGINE = "f270beef-fc00-4691-8d57-a6643ad6f7cd"
IDENTITY_KEY = "agentforge:vm-mock:identity"
MODES = frozenset({"api", "worker", "migrate", "health"})
POLICY = {
    "AGENTFORGE_REAL_CALLS_ENABLED": "false",
    "AGENTFORGE_EXTERNAL_MODELS_BLOCKED": "1",
    "AGENTFORGE_SINGLE_USE_PERMITS_ENABLED": "false",
    "AGENTFORGE_REAL_WORKER_MODE": "deny",
    "AGENTFORGE_REAL_DAILY_BUDGET_USD": "0",
    "AGENTFORGE_REAL_TEST_BUDGET_USD": "0",
}


class Refusal(RuntimeError):
    """Only fixed error codes; never include values supplied by the operator."""


def require(condition, code):
    if not condition:
        raise Refusal(code)


def configuration(environment):
    # Reject even an empty inherited credential or settings-file override BEFORE
    # importing Settings (its class definition resolves the dotenv locator).
    for key, value in environment.items():
        if key.startswith("AGENTFORGE_"):
            require(key in POLICY and value == POLICY[key], "VM_INHERITED_CONFIG")
        if key.startswith(("OPENAI_", "ANTHROPIC_", "DEEPSEEK_", "GOOGLE_API_",
                           "LANGSMITH_API_", "LANGCHAIN_API_")):
            raise Refusal("VM_MODEL_CREDENTIAL_ENV")
    try:
        instance = str(UUID(environment.get("VM_MOCK_INSTANCE_ID", "")))
    except (ValueError, TypeError, AttributeError):
        raise Refusal("VM_INSTANCE_REQUIRED") from None
    require(instance == environment.get("VM_MOCK_INSTANCE_ID"), "VM_CANONICAL_INSTANCE_REQUIRED")
    keys = ("VM_MOCK_APP_PASSWORD", "VM_MOCK_REDIS_PASSWORD", "VM_MOCK_ADMIN_TOKEN")
    values = [environment.get(key, "") for key in keys]
    require(all(re.fullmatch(r"[0-9a-f]{64}", value) for value in values), "VM_FRESH_HEX_SECRETS_REQUIRED")
    require(len(set(values)) == len(values), "VM_DISTINCT_SECRETS_REQUIRED")
    app_password, redis_password, token = values
    # Endpoints cannot be supplied by env/CLI: only new Compose service aliases.
    return {
        "environment": "development",
        "database_url": "postgresql+asyncpg://agentforge_demo:" + app_password + "@postgres:5432/agentforge",
        "redis_url": "redis://:" + redis_password + "@redis:6379/0",
        "admin_token": token,
        "tenant_id": instance,
        "daily_mock_token_limit": 1000000, "daily_mock_budget_usd": "10",
        "real_calls_enabled": False, "single_use_permits_enabled": False,
        "real_worker_mode": "deny",
        "real_daily_budget_usd": "0", "real_test_budget_usd": "0",
        "real_max_retries": 0, "model_credentials_env_only": True,
        "model_prices": {}, "model_credential_hosts": {},
        "allowed_model_hosts": "",
    }


def validate_database_identity(row, instance):
    require(row is not None and str(row["instance"]) == instance
            and row["purpose"] == "agentforge-vm-mock"
            and row["base_source"] == BASE_SOURCE, "VM_DATABASE_IDENTITY_MISMATCH")


def validate_slots(rows, instance):
    require(len(rows) == 4 and {row["role"] for row in rows}
            == {"planner", "coder", "researcher", "reviewer"}, "VM_FOUR_MOCK_SLOTS_REQUIRED")
    require(all(str(row["tenant_id"]) == instance and row["provider"] == "mock"
                and row["enabled"] and row["base_url"] is None
                and row["credential_reference"] is None for row in rows), "VM_NON_MOCK_SLOT")
