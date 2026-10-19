import secrets
import os
from pathlib import Path
import sys
import pytest
from app.core.config import Settings


def _s1_context():
    """Validate the disposable stack before any integration fixture can write."""
    root = Path(__file__).resolve().parents[1]
    if os.environ.get("AGENTFORGE_RUN_SANDBOX") == "1":
        raise pytest.UsageError("S1_RUNNER_ISOLATION_BLOCKED")
    locator = os.environ.get("AGENTFORGE_S1_MANIFEST")
    if not locator:
        raise pytest.UsageError("S1_ISOLATION_MANIFEST_REQUIRED")
    forbidden = {"AGENTFORGE_DATABASE_URL", "AGENTFORGE_REDIS_URL", "AGENTFORGE_ADMIN_TOKEN",
                 "AGENTFORGE_MODEL_PERMIT_ISSUER_TOKEN", "AGENTFORGE_SANDBOX_RUNNER_URL"}
    forbidden.update("AGENTFORGE_MODEL_" + role + "_KEY" for role in ("CODER", "PLANNER", "RESEARCHER", "REVIEWER"))
    if any(name in os.environ for name in forbidden):
        raise pytest.UsageError("S1_SETTINGS_OVERRIDE_FORBIDDEN")
    sys.path.insert(0, str(root / "scripts"))
    try:
        from s1_isolation import validate_isolation
        verified = validate_isolation(root, Path(locator))
    except Exception:
        raise pytest.UsageError("S1_ISOLATION_UNVERIFIED") from None
    selected = os.environ.get("AGENTFORGE_SETTINGS_FILE")
    if not selected or Path(selected).resolve() != Path(verified["settings_path"]).resolve():
        raise pytest.UsageError("S1_SETTINGS_REFERENCE_MISMATCH")
    return verified


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if (os.environ.get("AGENTFORGE_RUN_INTEGRATION") == "1"
            or os.environ.get("AGENTFORGE_RUN_SANDBOX") == "1"):
        verified = _s1_context()
        # A short validation is insufficient: cleanup/reconfiguration must stay
        # excluded until pytest has released every fixture and finalizer.
        from s1_isolation import isolation_lease
        lease = isolation_lease(Path(__file__).resolve().parents[1], Path(verified["manifest_path"]))
        try:
            held = lease.__enter__()
        except Exception:
            raise pytest.UsageError("S1_ISOLATION_UNVERIFIED") from None
        config.add_cleanup(lambda: lease.__exit__(None, None, None))
        if held != verified:
            raise pytest.UsageError("S1_ISOLATION_CHANGED")
        config._agentforge_s1_context = held
        sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
        from preflight_guards import install_verified_guard
        install_verified_guard(held)


@pytest.fixture(autouse=True)
def require_isolated_integration(request):
    """An environment flag requests integration; it never supplies authority."""
    if request.node.get_closest_marker("integration") is None:
        return
    if os.environ.get("AGENTFORGE_RUN_INTEGRATION") != "1":
        return  # Existing explicit offline skips remain truthful.
    verified = getattr(request.config, "_agentforge_s1_context", None)
    if verified is None:
        pytest.fail("S1_ISOLATION_UNVERIFIED", pytrace=False)
    if request.node.get_closest_marker("sandbox") is not None:
        pytest.skip("S1_RUNNER_ISOLATION_BLOCKED: real Runner deployment is separately authorized")
    selected = os.environ.get("AGENTFORGE_SETTINGS_FILE")
    if (not selected or Path(selected).resolve() != Path(verified["settings_path"]).resolve()
            or any(name in os.environ for name in ("AGENTFORGE_DATABASE_URL", "AGENTFORGE_REDIS_URL"))):
        pytest.fail("S1_SETTINGS_REFERENCE_MISMATCH", pytrace=False)


@pytest.fixture
def settings():
    return Settings(_env_file=None, environment="test",
                    database_url="postgresql+asyncpg://agentforge:test-only@127.0.0.1:65501/agentforge",
                    redis_url="redis://:test-only@127.0.0.1:65502/0",
                    admin_token=secrets.token_hex(32), dependency_timeout=0.3)


class StubConnections:
    """Explicit HTTP unit-test double, never evidence of real DB/Redis connectivity."""
    def __init__(self, status=None):
        self.status = status or {"postgresql": "down", "redis": "down"}
        self.closed = False

    async def readiness(self):
        return self.status

    async def close(self):
        self.closed = True
