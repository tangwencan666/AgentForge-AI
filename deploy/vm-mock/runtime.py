"""Independent VM entrypoint; no reuse or relaxation of hosted-CI guards."""
import asyncio
import json
import os
from pathlib import Path
import sys
from time import time

from vm_mock_policy import (
    BASE_SOURCE, IDENTITY_KEY, MODES, POLICY, Refusal, configuration, require,
    validate_database_identity, validate_slots,
)


def settings_from_environment():
    values = configuration(dict(os.environ))
    os.environ.update(POLICY)
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGSMITH_TRACING"] = "false"
    from app.core.config import Settings, get_settings
    # Dedicated process only: keep every existing Settings validator, remove
    # dotenv as an input source for both explicit and transitive Settings calls.
    Settings.model_config = {**Settings.model_config, "env_file": None}
    for key, value in values.items():
        os.environ["AGENTFORGE_" + key.upper()] = (
            json.dumps(value) if isinstance(value, (dict, bool)) else str(value))
    get_settings.cache_clear()
    settings = Settings(_env_file=None, **values)
    require(settings.sandbox_image_id is None and settings.sandbox_runner_token is None
            and settings.sandbox_approver_token is None and settings.model_permit_issuer_token is None
            and settings.mcp_server_token is None and settings.capability_approver_token is None,
            "VM_EXECUTION_AUTHORITY_FORBIDDEN")
    return settings


async def connect_verified(settings, migration=False):
    import asyncpg
    from redis.asyncio import Redis
    database = await asyncpg.connect(
        settings.database_url.get_secret_value().replace("postgresql+asyncpg:", "postgresql:"),
        timeout=3)
    cache = Redis.from_url(settings.redis_url.get_secret_value(),
                           decode_responses=True, socket_timeout=3, socket_connect_timeout=3)
    try:
        require(await database.fetchval("SELECT current_database()") == "agentforge",
                "VM_DATABASE_NAME_MISMATCH")
        require(await database.fetchval("SELECT current_user") == "agentforge_demo"
                and not await database.fetchval("SELECT rolsuper FROM pg_roles WHERE rolname=current_user"),
                "VM_DATABASE_ROLE_MISMATCH")
        rows = await database.fetch("SELECT instance,purpose,base_source FROM vm_demo_guard.identity")
        require(len(rows) == 1, "VM_DATABASE_IDENTITY_MISMATCH")
        validate_database_identity(rows[0], settings.tenant_id)
        if migration:
            require(await database.fetchval(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'") == 0,
                "VM_MIGRATION_REQUIRES_EMPTY_DATABASE")
        identity = json.dumps({"instance": settings.tenant_id, "base_source": BASE_SOURCE}, sort_keys=True)
        existing = await cache.get(IDENTITY_KEY)
        if migration and existing is None:
            require(await cache.dbsize() == 0, "VM_FRESH_REDIS_REQUIRED")
            require(await cache.set(IDENTITY_KEY, identity, nx=True), "VM_REDIS_INITIALIZATION_RACE")
            existing = identity
        require(existing == identity, "VM_REDIS_IDENTITY_MISMATCH")
        if not migration:
            require(await database.fetchval("SELECT version_num FROM alembic_version")
                    == "0010_sandbox_maintenance", "VM_SCHEMA_VERSION_MISMATCH")
            slots = await database.fetch(
                "SELECT tenant_id,role,provider,enabled,base_url,credential_reference "
                "FROM model_slots WHERE tenant_id=$1", __import__("uuid").UUID(settings.tenant_id))
            validate_slots(slots, settings.tenant_id)
        return database, cache
    except BaseException:
        await database.close()
        await cache.aclose()
        raise


async def verify_services(settings, migration=False):
    database, cache = await connect_verified(settings, migration=migration)
    await database.close()
    await cache.aclose()


def migrate(settings):
    # Only an explicit one-shot migration mode can create the Redis marker and
    # migrate. API/Worker startup never upgrades a database automatically.
    asyncio.run(verify_services(settings, migration=True))
    async def upgrade_new_database():
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        from alembic.config import Config
        from alembic import command
        from uuid import UUID
        engine = create_async_engine(settings.database_url.get_secret_value(),
                                     echo=False, hide_parameters=True)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("SELECT pg_advisory_xact_lock(472903)"))
                # Recheck inside the SAME transaction used by Alembic, so another
                # migration cannot race the fresh-database condition.
                row = (await connection.execute(text(
                    "SELECT instance,purpose,base_source FROM vm_demo_guard.identity"))).mappings().all()
                require(len(row) == 1, "VM_DATABASE_IDENTITY_MISMATCH")
                validate_database_identity(row[0], settings.tenant_id)
                require(await connection.scalar(text("SELECT current_user")) == "agentforge_demo"
                        and not await connection.scalar(text(
                            "SELECT rolsuper FROM pg_roles WHERE rolname=current_user")),
                        "VM_DATABASE_ROLE_MISMATCH")
                require(await connection.scalar(text(
                    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")) == 0,
                    "VM_MIGRATION_REQUIRES_EMPTY_DATABASE")
                def upgrade(sync_connection):
                    config = Config(str(Path(__file__).with_name("alembic.ini")))
                    config.attributes["connection"] = sync_connection
                    command.upgrade(config, "head")
                await connection.run_sync(upgrade)
                parameters = {"tenant": UUID(settings.tenant_id)}
                count = await connection.scalar(text(
                    "SELECT count(*) FROM model_slots WHERE tenant_id=:tenant"), parameters)
                require(count == 4, "VM_FOUR_MOCK_SLOTS_REQUIRED")
                await connection.execute(text(
                    "UPDATE model_slots SET provider='mock', model='vm-demo-mock', enabled=true, "
                    "base_url=NULL, credential_reference=NULL, version=version+1 WHERE tenant_id=:tenant"),
                    parameters)
        finally:
            await engine.dispose()
        await verify_services(settings)
    asyncio.run(upgrade_new_database())


async def serve(settings, mode):
    await verify_services(settings)
    if mode == "api":
        import uvicorn
        from app.main import create_app
        await uvicorn.Server(uvicorn.Config(create_app(settings), host="0.0.0.0", port=8000,
                                           access_log=False)).serve()
    elif mode == "worker":
        # Original publisher, fencing, leases, approvals and safety checks.
        from app.workers.main import main
        await main()
    else:
        database, cache = await connect_verified(settings)
        try:
            value = await cache.get("agentforge:p5:model-runtime:" + settings.tenant_id)
            state = json.loads(value or "{}")
            policy = state.get("policy", {})
            require(0 <= time() - state.get("observed_at", 0) <= 12
                    and policy.get("external_calls_blocked") is True
                    and policy.get("real_calls_enabled") is False
                    and not state.get("coder_credential_present", True), "VM_WORKER_NOT_READY")
        finally:
            await database.close()
            await cache.aclose()


def main():
    require(sys.platform == "linux" and Path("/.dockerenv").is_file(), "VM_CONTAINER_REQUIRED")
    require(len(sys.argv) == 2 and sys.argv[1] in MODES, "VM_MODE_REQUIRED")
    settings = settings_from_environment()
    if sys.argv[1] == "migrate":
        migrate(settings)
    else:
        asyncio.run(serve(settings, sys.argv[1]))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("VM Mock refused/failed: " + (str(exc) if isinstance(exc, Refusal)
                                          else type(exc).__name__), flush=True)
        raise SystemExit(1) from None
