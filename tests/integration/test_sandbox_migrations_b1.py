"""Populate/backup/actually restore disposable data, never read a main backup."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from datetime import timedelta
from uuid import uuid4
import pytest
from pydantic import SecretStr
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import Settings
from app.domain.tasks import AgentTask, TaskApproval
from app.domain.sandbox import SandboxExecution
from app.repositories.connections import Connections
from app.sandbox.ownership import provision_identity
from app.services.sandbox_maintenance import provision_maintenance
from app.services.tasks import now
from sandbox_database import fresh_database, migrate, ROOT

pytestmark = pytest.mark.integration


def _pg_command(request, arguments, *, data=None):
    """Finite backup/restore operations, bound to already leased data resource."""
    import s1_isolation as isolation
    verified = request.config._agentforge_s1_context
    path = Path(verified['manifest_path'])
    assert isolation.has_active_lease(path)
    document, _ = isolation._read_document(ROOT, path)
    isolation.attest_container(ROOT, document, 'postgres')
    cid = document['resources']['postgres']['id']
    assert document['ports']['postgres'] >= 30000 and cid != '7ea24834b4835bbb151257910a42d1891d7209c117eebc4e384fb7ce3e6c2d5d'
    assert arguments[0] in {'pg_dump', 'pg_restore', 'createdb'}
    result = subprocess.run(['docker', 'exec', '-i', cid, *arguments], input=data,
        capture_output=True, timeout=40, env=isolation.runtime_environment())
    if result.returncode:
        raise AssertionError('B1_DISPOSABLE_BACKUP_TOOL_FAILED')
    return result.stdout


async def fingerprints(c):
    result = {}
    async with c.engine.connect() as connection:
        names = await connection.run_sync(lambda sync: inspect(sync).get_table_names(schema=c.test_schema))
        for name in names:
            if name == 'alembic_version': continue
            assert re.fullmatch('[a-z_]+', name)
            rows = (await connection.execute(text('SELECT to_jsonb(t)::text FROM '+name+' t ORDER BY to_jsonb(t)::text'))).scalars().all()
            columns = await connection.run_sync(lambda sync: inspect(sync).get_columns(name, schema=c.test_schema))
            result[name] = {'rows': len(rows), 'sha256': hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
                'columns': [(col['name'], str(col['type']), col['nullable']) for col in columns]}
    return result


async def test_populated_backup_restore_0009_consistency_and_guarded_downgrades(request):
    settings = Settings()
    source = await fresh_database(request, settings, revision='0008_execution_permits')
    clone = None
    try:
        # Explicit synthetic LEGACY records, including UNKNOWN and missing CID.
        async with source.sessions() as session, session.begin():
            for status, cid in [('needs_reconciliation', 'a'*64), ('failed', None), ('succeeded', 'b'*64)]:
                tid, eid, aid, tenant = uuid4(), uuid4(), uuid4(), uuid4()
                session.add(AgentTask(id=tid, tenant_id=tenant, idempotency_key=uuid4(), request_hash='a'*64,
                    goal='B1 synthetic migration fixture', options={'workflow':'sandbox'}, model_snapshot={},
                    status=status, is_mock=False, deadline=now()+timedelta(seconds=60),
                    token_limit=1, call_limit=1, iteration_limit=1, budget_limit=0))
                await session.flush()
                session.add(TaskApproval(id=aid, task_id=tid, tenant_id=tenant, operation_hash='b'*64,
                    policy_version='p3-python-v2', expires_at=now(), status='approved', decided_by='sandbox-reviewer'))
                await session.flush()
                session.add(SandboxExecution(id=eid, task_id=tid, tenant_id=tenant, language='python',
                    code='print("not executed: migration fixture")', code_hash='c'*64, operation_hash='b'*64,
                    timeout_seconds=1, resource_limits={'cpu':.5,'memory_mb':128,'pids':16},
                    policy_version='p3-python-v2', approval_reference=aid, status=status,
                    launch_claimed_at=now(), cleanup_status='removed' if cid else 'not_created', container_id=cid,
                    budget_day=now().date(), reserved_cpu_seconds=0))
        before = await fingerprints(source)
        archive = _pg_command(request, ['pg_dump','-U','postgres','-d','agentforge','-Fc','--schema='+source.test_schema])
        assert archive.startswith(b'PGDMP') and len(archive)>1024
        toc = _pg_command(request, ['pg_restore','--list'], data=archive)
        assert source.test_schema.encode() in toc and b'sandbox_executions' in toc
        # Every rehearsal owns a new evidence directory. Never overwrite a
        # previous stage's archive/report when the complete suite is rerun.
        out = Path(request.config._agentforge_s1_context['run_directory'])/'reports'/('migration-'+uuid4().hex)
        out.mkdir(parents=True,exist_ok=False)
        (out/'synthetic-0008.dump').write_bytes(archive)
        db = 'b1_restore_'+uuid4().hex
        _pg_command(request, ['createdb','-U','postgres','--owner=agentforge',db])
        _pg_command(request, ['pg_restore','-U','postgres','--role=agentforge','--no-owner','--no-acl','--exit-on-error','-d',db], data=archive)
        clone = Connections(settings)
        await clone.engine.dispose()
        uri = make_url(settings.database_url.get_secret_value()).set(database=db)
        clone.engine = create_async_engine(uri, echo=False, hide_parameters=True,
            connect_args={'timeout':5,'server_settings':{'search_path':source.test_schema}})
        clone.sessions = async_sessionmaker(clone.engine, expire_on_commit=False)
        clone.test_schema = source.test_schema
        assert await fingerprints(clone) == before
        await migrate(clone, '0009_sandbox_ownership')
        upgraded = await fingerprints(clone)
        assert all(upgraded[name] == value for name,value in before.items())
        assert set(upgraded)-set(before) == {'sandbox_ownership','sandbox_runner_identities','sandbox_ownership_audit'}
        async with clone.engine.connect() as connection:
            constraints = await connection.run_sync(lambda sync: inspect(sync).get_check_constraints('sandbox_ownership', schema=clone.test_schema))
            assert {'ck_ownership_protocol','ck_ownership_state'} <= {item['name'] for item in constraints}
            foreign_keys = await connection.run_sync(lambda sync: inspect(sync).get_foreign_keys('sandbox_ownership', schema=clone.test_schema))
            unique = await connection.run_sync(lambda sync: inspect(sync).get_unique_constraints('sandbox_ownership', schema=clone.test_schema))
            assert {item['referred_table'] for item in foreign_keys} == {'sandbox_executions','agent_tasks','sandbox_runner_identities'}
            assert ['container_id'] in [item['column_names'] for item in unique]
        await migrate(clone, '0008_execution_permits', downgrade=True)
        assert await fingerprints(clone) == before
        await migrate(clone, '0009_sandbox_ownership')
        async with clone.sessions() as session, session.begin(): await provision_identity(session, 'B1_STUB_DAEMON')
        with pytest.raises(DBAPIError): await migrate(clone, '0008_execution_permits', downgrade=True)
        await migrate(clone, '0010_sandbox_maintenance')
        async with clone.sessions() as session, session.begin(): await provision_maintenance(session, 'B1_STUB_DAEMON')
        with pytest.raises(DBAPIError): await migrate(clone, '0009_sandbox_ownership', downgrade=True)
        final = await fingerprints(clone)
        assert all(final[name] == value for name,value in before.items())
        async with clone.engine.connect() as connection:
            assert await connection.scalar(text('SELECT version_num FROM alembic_version')) == '0010_sandbox_maintenance'
            assert await connection.scalar(text("SELECT count(*) FROM sandbox_executions WHERE status='needs_reconciliation'")) == 1
        (out/'migration-restore.json').write_text(json.dumps({'status':'PASS','source':'SYNTHETIC_DISPOSABLE_DATA_ONLY',
            'main_database_touched':False,'archive_bytes':len(archive),'sha256':hashlib.sha256(archive).hexdigest(),
            'business_tables':len(before),'original_data_preserved':True,'actual_restore':True,
            'empty_0009_downgrade_passed':True,'nonempty_0009_0010_downgrades_refused':True,
            'source_schema':source.test_schema,'restored_database':db},indent=2),encoding='utf-8')
    finally:
        await source.close()
        if clone: await clone.close()
        # Explicitly retain schemas/database/archive. No Docker rm/volume rm/drop.
