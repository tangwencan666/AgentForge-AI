"""Real PG lock failure/transaction recovery, exclusively new attested schemas."""
from pathlib import Path
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.core.config import Settings
from app.domain.entities import ModelSlot
from sandbox_database import fresh_database,migrate,ROOT
from test_sandbox_migrations_b1 import fingerprints

pytestmark=pytest.mark.integration


async def test_failed_0009_ddl_rolls_back_then_recovery_keeps_old_data(request):
    c=await fresh_database(request,Settings(),revision='0008_execution_permits')
    try:
        async with c.sessions() as session,session.begin():session.add(ModelSlot(tenant_id=uuid4(),role='coder',enabled=False))
        before=await fingerprints(c)
        async with c.engine.connect() as blocker:
            transaction=await blocker.begin()
            await blocker.execute(text('LOCK TABLE sandbox_executions IN ACCESS EXCLUSIVE MODE'))
            try:
                with pytest.raises(DBAPIError):
                    async with c.engine.begin() as connection:
                        await connection.execute(text("SET LOCAL lock_timeout='150ms'"))
                        def upgrade(sync):
                            config=Config(str(ROOT/'backend/alembic.ini'));config.attributes['connection']=sync
                            command.upgrade(config,'0009_sandbox_ownership')
                        await connection.run_sync(upgrade)
            finally:await transaction.rollback()
        assert await fingerprints(c)==before
        async with c.engine.connect() as connection:
            assert await connection.scalar(text('SELECT version_num FROM alembic_version'))=='0008_execution_permits'
        await migrate(c,'0009_sandbox_ownership');await migrate(c,'0010_sandbox_maintenance')
        after=await fingerprints(c)
        assert all(after[n]==value for n,value in before.items())
        assert len(set(after)-set(before))==7
    finally:await c.close()  # No row/schema/container/network deleted.
