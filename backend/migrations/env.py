import asyncio
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import pool
from app.core.config import get_settings
from app.domain.entities import Base
import app.domain.tasks  # P2 metadata
import app.domain.sandbox  # P3 metadata

target_metadata = Base.metadata


def configure(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def migrate_online():
    settings = get_settings()
    engine = create_async_engine(settings.database_url.get_secret_value(), poolclass=pool.NullPool,
                                 echo=False, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(configure)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(dialect_name="postgresql", target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(migrate_online())
