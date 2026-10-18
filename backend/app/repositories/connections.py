import asyncio
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from redis.asyncio import Redis
from app.core.config import Settings

logger = logging.getLogger("agentforge")
MIGRATION_REVISION = "0008_execution_permits"
OWNERSHIP_REVISION = '0009_sandbox_ownership'
MAINTENANCE_REVISION = '0010_sandbox_maintenance'


class Connections:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = create_async_engine(
            settings.database_url.get_secret_value(), echo=False, hide_parameters=True,
            pool_pre_ping=True, pool_size=5, max_overflow=0,
            connect_args={"timeout": settings.dependency_timeout},
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.redis = Redis.from_url(
            settings.redis_url.get_secret_value(), socket_connect_timeout=settings.dependency_timeout,
            socket_timeout=settings.dependency_timeout, decode_responses=True,
        )

    async def _postgres_status(self) -> str:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            if await conn.scalar(text("SELECT to_regclass('public.alembic_version')")) is None:
                return "migration_required"
            revision = await conn.scalar(text("SELECT version_num FROM alembic_version"))
            legacy_closed = revision == '0007_deepseek' and not self.settings.single_use_permits_enabled and self.settings.real_worker_mode == 'deny'
            if revision not in {MIGRATION_REVISION, OWNERSHIP_REVISION, MAINTENANCE_REVISION} and not legacy_closed:
                return "migration_required"
            if revision in {MIGRATION_REVISION, OWNERSHIP_REVISION, MAINTENANCE_REVISION}:
                await conn.execute(text('SELECT permit_id FROM execution_permits LIMIT 1'))
            if revision in {OWNERSHIP_REVISION, MAINTENANCE_REVISION}:
                await conn.execute(text('SELECT execution_id FROM sandbox_ownership LIMIT 1'))
                await conn.execute(text('SELECT runner_instance_id FROM sandbox_runner_identities LIMIT 1'))
            if revision == MAINTENANCE_REVISION:
                await conn.execute(text('SELECT id FROM sandbox_maintenance LIMIT 1'))
            # Verify core table exists too, not only a forged revision string.
            await conn.execute(text("SELECT role FROM model_slots LIMIT 1"))
            await conn.execute(text("SELECT id FROM agent_tasks LIMIT 1"))
            await conn.execute(text("SELECT id FROM tool_calls LIMIT 1"))
            await conn.execute(text("SELECT skill_id FROM skill_versions LIMIT 1"))
            return "up"

    async def _redis_status(self) -> str:
        return "up" if await self.redis.ping() else "down"

    async def _check(self, name: str, operation) -> str:
        try:
            return await asyncio.wait_for(operation(), timeout=self.settings.dependency_timeout)
        except Exception as exc:
            logger.warning("dependency_failed", extra={"dependency": name, "error_type": type(exc).__name__})
            return "down"

    async def readiness(self) -> dict[str, str]:
        pg, redis = await asyncio.gather(
            self._check("postgresql", self._postgres_status), self._check("redis", self._redis_status),
        )
        return {"postgresql": pg, "redis": redis}

    async def close(self):
        await self.redis.aclose()
        await self.engine.dispose()
