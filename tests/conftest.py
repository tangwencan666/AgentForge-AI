import secrets
import pytest
from app.core.config import Settings


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
