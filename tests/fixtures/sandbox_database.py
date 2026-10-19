"""Real schemas on an attested disposable PG only; retain every test history."""
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.repositories.connections import Connections

ROOT = Path(__file__).resolve().parents[2]


async def migrate(connections, revision, *, downgrade=False):
    async with connections.engine.begin() as connection:
        def apply(sync):
            config = Config(str(ROOT / 'backend/alembic.ini'))
            config.attributes['connection'] = sync
            (command.downgrade if downgrade else command.upgrade)(config, revision)
        await connection.run_sync(apply)


async def fresh_database(request, settings, *, revision='0010_sandbox_maintenance'):
    verified = getattr(request.config, '_agentforge_s1_context', None)
    if not verified:
        raise RuntimeError('ATTESTED_DISPOSABLE_DATABASE_REQUIRED')
    uri = urlsplit(settings.database_url.get_secret_value())
    if not (settings.environment == 'test' and uri.hostname == '127.0.0.1'
            and uri.port == verified['ports']['postgres'] and uri.port >= 30000 and uri.path == '/agentforge'):
        raise RuntimeError('ATTESTED_DISPOSABLE_DATABASE_REQUIRED')
    # Each case has real migrations/state/UNKNOWN/audit, never erased to thaw.
    schema = 'b1_' + uuid4().hex
    root = Connections(settings)
    try:
        async with root.engine.begin() as connection:
            await connection.execute(text('CREATE SCHEMA ' + schema))
    finally:
        await root.close()
    scoped = Connections(settings)
    await scoped.engine.dispose()
    scoped.engine = create_async_engine(settings.database_url.get_secret_value(), echo=False,
        hide_parameters=True, pool_pre_ping=True, pool_size=10, max_overflow=0,
        connect_args={'timeout': 5, 'server_settings': {'search_path': schema}})
    scoped.sessions = async_sessionmaker(scoped.engine, expire_on_commit=False)
    scoped.test_schema = schema
    try:
        await migrate(scoped, revision)
    except BaseException:
        await scoped.close()
        raise
    return scoped
