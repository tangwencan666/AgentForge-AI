"""Scoped 0008 deployment: stopped dispatch, verified backup, additive migration.

Uses only the prepared service-only environment. Never resolves model credentials.
The restore rehearsal creates/removes only its uniquely named project backup clone.
"""

from maintenance_policy import cli_gate, maintenance_action
cli_gate(__file__, __name__)

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.util
from io import StringIO
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from alembic import command as alembic
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from app.core.config import Settings, runtime_env_file
from app.repositories.connections import Connections

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'work/p5-live-preflight/permit-deployment'
CONTAINER = 'agentforge-p1-postgres'
spec = importlib.util.spec_from_file_location('permit_backup_helpers', ROOT/'scripts/prepare-permit-tests.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
command = helper.command


def owner_check():
    if not __debug__: raise RuntimeError('Optimized Python disables safety assertions; deployment refused')
    settings = Settings()
    assert runtime_env_file() == ROOT/'work/p5-live-preflight/.env'
    url = urlsplit(settings.database_url.get_secret_value())
    assert (url.hostname, url.port, url.path) == ('127.0.0.1', 15432, '/agentforge')
    assert not settings.real_calls_enabled and not settings.single_use_permits_enabled
    assert settings.real_worker_mode == 'deny' and settings.real_max_retries == 0
    assert settings.real_daily_budget_usd == settings.real_test_budget_usd == 0
    assert settings.model_permit_issuer_token is None and settings.model_credentials_env_only
    assert os.environ.get('AGENTFORGE_EXTERNAL_MODELS_BLOCKED') == '1'
    assert command('docker','inspect','--format','{{index .Config.Labels "com.docker.compose.project"}}',CONTAINER) == 'agentforge-p1'
    assert Path(command('docker','inspect','--format','{{index .Config.Labels "com.docker.compose.project.working_dir"}}',CONTAINER)).resolve() == ROOT
    assert command('docker','port',CONTAINER,'5432/tcp') == '127.0.0.1:15432'


async def snapshot(expected):
    c = Connections(Settings())
    try:
        async with c.engine.connect() as conn:
            await conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            assert (await conn.execute(text('SELECT current_database(), current_user'))).one() == ('agentforge','agentforge')
            revision = await conn.scalar(text('SELECT version_num FROM alembic_version'))
            assert revision == expected
            assert await conn.scalar(text("SELECT count(*) FROM agent_tasks WHERE status NOT IN ('succeeded','failed','cancelled','timed_out','limit_exceeded','needs_reconciliation')")) == 0
            assert await conn.scalar(text('SELECT count(*) FROM model_operations WHERE NOT is_mock')) == 0
            assert await conn.scalar(text('SELECT count(*) FROM model_slots WHERE enabled')) == 0
            assert await conn.scalar(text('SELECT count(*) FROM model_slots')) == 4
            assert await conn.scalar(text('SELECT count(*) FROM task_outbox WHERE published_at IS NULL')) == 0
            rows = (await conn.execute(text("SELECT table_name,array_agg(column_name ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='public' GROUP BY table_name ORDER BY table_name"))).all()
            columns = {name:list(fields) for name,fields in rows}
            hashes = {name:await conn.scalar(text(helper.fingerprint_sql(name,fields))) for name,fields in columns.items()}
            if expected == '0008_execution_permits':
                assert all(hashes[name].startswith('0:') for name in ('execution_permits','permit_audit','trusted_model_workers'))
                checks = set((await conn.execute(text("SELECT conname FROM pg_constraint WHERE conrelid='execution_permits'::regclass AND contype='c'"))).scalars())
                assert checks == {'ck_permit_credential','ck_permit_profile','ck_permit_status','ck_permit_counts','ck_permit_limits'}
                assert await conn.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgrelid='execution_permits'::regclass AND tgname='execution_permit_guard' AND tgenabled='O'")) == 1
                assert await conn.scalar(text("SELECT indisunique AND indpred IS NOT NULL FROM pg_index WHERE indexrelid='uq_permit_active_tenant'::regclass"))
                assert await conn.scalar(text("SELECT indisunique FROM pg_index WHERE indexrelid='uq_permit_audit_sequence'::regclass"))
        assert await c.redis.ping()
        return {'revision':revision,'columns':columns,'fingerprints':hashes}
    finally:
        await c.close()


def dispatch_stopped():
    # API/Worker recorded by the project launcher must be gone before DB changes.
    records = json.loads((ROOT/'work/dev-pids.json').read_text(encoding='utf-8-sig'))
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    for row in records:
        if row['name'] not in {'backend','worker'}: continue
        handle = kernel.OpenProcess(0x1000,False,row['pid'])
        if handle:
            kernel.CloseHandle(handle)
            raise RuntimeError('Project API/Worker has not stopped')
        assert ctypes.get_last_error() == 87  # ERROR_INVALID_PARAMETER: PID no longer exists.
    assert command('docker','inspect','--format','{{.State.Running}}','agentforge-p3-runner') == 'false'
    assert not command('docker','ps','-aq','--filter','label=agentforge.sandbox.execution')


def clone_hashes(clone,before):
    assert re.fullmatch('agentforge_permit_restore_[0-9]+',clone)
    return {name:command('docker','exec',CONTAINER,'psql','-U','postgres','-d',clone,'-Atc',helper.fingerprint_sql(name,fields)) for name,fields in before['columns'].items()}


def migration_sql(action):
    spec = importlib.util.spec_from_file_location('permit_ddl',ROOT/'backend/migrations/versions/0008_execution_permits.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    buffer = StringIO()
    module.op = Operations(MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':buffer}))
    getattr(module,action)()
    return buffer.getvalue()


@maintenance_action("permit.backup")
def backup():
    owner_check()
    dispatch_stopped()
    before = asyncio.run(snapshot('0007_deepseek'))
    DIRECTORY.mkdir(parents=True,exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    remote = '/tmp/agentforge-permit-deploy-'+stamp+'.dump'
    local = DIRECTORY/('before-0008-'+stamp+'.dump')
    clone = 'agentforge_permit_restore_'+stamp
    command('docker','exec',CONTAINER,'pg_dump','-U','postgres','-d','agentforge','-Fc','-f',remote)
    command('docker','exec',CONTAINER,'pg_restore','--list',remote)
    command('docker','cp',CONTAINER+':'+remote,str(local))
    assert local.stat().st_size > 0
    command('docker','exec',CONTAINER,'createdb','-U','postgres','--owner=agentforge',clone)
    command('docker','exec',CONTAINER,'pg_restore','-U','postgres','--role=agentforge','--no-owner','--exit-on-error','-d',clone,remote)
    assert clone_hashes(clone,before) == before['fingerprints']
    for action in ('upgrade','downgrade'):
        command('docker','exec',CONTAINER,'psql','-U','postgres','-d',clone,'-v','ON_ERROR_STOP=1','-1c',migration_sql(action))
        assert clone_hashes(clone,before) == before['fingerprints']
    assert command('docker','exec',CONTAINER,'psql','-U','postgres','-d',clone,'-Atc',"SELECT to_regclass('execution_permits') IS NULL AND to_regprocedure('guard_execution_permit()') IS NULL") == 't'
    owner_check()
    assert command('docker','exec',CONTAINER,'psql','-U','postgres','-d',clone,'-Atc','SELECT current_database()') == clone
    command('docker','exec',CONTAINER,'dropdb','-U','postgres',clone)
    assert asyncio.run(snapshot('0007_deepseek')) == before
    before.update(backup=str(local),sha256=hashlib.sha256(local.read_bytes()).hexdigest(),bytes=local.stat().st_size,
                  restore_verified=True,upgrade_downgrade_rehearsal=True,clone_removed=True,created_at=datetime.now(timezone.utc).isoformat())
    (DIRECTORY/'backup.json').write_text(json.dumps(before,indent=2),encoding='utf-8')
    print(json.dumps({key:before[key] for key in ('revision','backup','sha256','bytes','restore_verified','upgrade_downgrade_rehearsal','clone_removed')}))


@maintenance_action("permit.verify")
def verify():
    owner_check()
    before = json.loads((DIRECTORY/'backup.json').read_text())
    assert hashlib.sha256(Path(before['backup']).read_bytes()).hexdigest() == before['sha256']
    after = asyncio.run(snapshot('0008_execution_permits'))
    assert set(after['columns'])-set(before['columns']) == {'trusted_model_workers','execution_permits','permit_audit'}
    for name,fields in before['columns'].items():
        assert after['columns'][name] == fields
        if name != 'alembic_version': assert after['fingerprints'][name] == before['fingerprints'][name]
    alembic.check(Config(str(ROOT/'backend/alembic.ini')))
    result = {'revision':after['revision'],'old_business_tables_unchanged':len(before['columns'])-1,
        'new_tables':3,'permit_tables_empty':True,'constraints_indexes_trigger_verified':True,
        'metadata_check':'PASS','postgres_redis_healthy':True,'active_tasks':0,'persisted_real_model_operations':0,
        'pending_outbox':0,'all_slots_disabled':True,'backup_sha256':before['sha256'],
        'verified_at':datetime.now(timezone.utc).isoformat(),'external_model_calls':0}
    (DIRECTORY/'migration.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


@maintenance_action(lambda a, k: {"backup":"permit.backup","migrate":"permit.migrate","verify":"permit.verify"}.get(k.get("action", a[0] if a else ""), ""))
def main(action):
    if action == 'backup': return backup()
    if action == 'migrate':
        owner_check()
        dispatch_stopped()
        before = json.loads((DIRECTORY/'backup.json').read_text())
        assert before['restore_verified'] and before['upgrade_downgrade_rehearsal']
        assert hashlib.sha256(Path(before['backup']).read_bytes()).hexdigest() == before['sha256']
        current = asyncio.run(snapshot('0007_deepseek'))
        assert current['columns'] == before['columns'] and current['fingerprints'] == before['fingerprints']
        alembic.upgrade(Config(str(ROOT/'backend/alembic.ini')),'0008_execution_permits')
    verify()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=['backup','migrate','verify'])
    try: main(parser.parse_args().action)
    except Exception as exc:
        print('Scoped Permit deployment stopped: '+type(exc).__name__)
        raise SystemExit(1) from None
