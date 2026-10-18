"""Restore/upgrade/downgrade rehearsal ONLY in the owned isolated test container."""

from maintenance_policy import cli_gate, maintenance_action
cli_gate(__file__, __name__)

import asyncio
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlsplit
from alembic import command as alembic
from alembic.config import Config
from sqlalchemy import text
from app.core.config import Settings
from app.repositories.connections import Connections

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'work/p5-live-preflight/permit-test'
spec = importlib.util.spec_from_file_location('test_stack_setup', ROOT/'scripts/prepare-permit-tests.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


async def check_hashes(before, expected):
    c = Connections(Settings())
    try:
        async with c.engine.connect() as conn:
            revision = await conn.scalar(text('SELECT version_num FROM alembic_version'))
            assert revision == expected
            for name, columns in before['columns'].items():
                if name == 'alembic_version' and expected != before['revision']: continue
                assert await conn.scalar(text(helper.fingerprint_sql(name, columns))) == before['fingerprints'][name], name
    finally: await c.close()


@maintenance_action("permit.rehearsal")
def main():
    before = json.loads((DIRECTORY/'backup.json').read_text())
    settings = Settings()
    assert urlsplit(settings.database_url.get_secret_value()).port == 25432
    container = 'agentforge-permit-tests-postgres'
    assert helper.command('docker','inspect','--format','{{index .Config.Labels "com.docker.compose.project"}}',container) == helper.PROJECT
    assert Path(helper.command('docker','inspect','--format','{{index .Config.Labels "com.docker.compose.project.working_dir"}}',container)).resolve() == DIRECTORY
    assert helper.command('docker','port',container,'5432/tcp') == '127.0.0.1:25432'
    fresh = helper.command('docker','exec',container,'psql','-U','agentforge','-d','agentforge','-Atc',"SELECT to_regclass('public.alembic_version') IS NULL") == 't'
    if fresh:
        helper.command('docker','cp',before['backup'],container+':/tmp/permit-backup.dump')
        helper.command('docker','exec',container,'pg_restore','-U','agentforge','--no-owner','--exit-on-error','-d','agentforge','/tmp/permit-backup.dump')
    asyncio.run(check_hashes(before,'0007_deepseek'))
    config = Config(str(ROOT/'backend/alembic.ini'))
    alembic.upgrade(config,'head')
    asyncio.run(check_hashes(before,'0008_execution_permits'))
    alembic.check(config)
    alembic.downgrade(config,'0007_deepseek')
    asyncio.run(check_hashes(before,'0007_deepseek'))
    assert helper.command('docker','exec',container,'psql','-U','agentforge','-d','agentforge','-Atc',"SELECT to_regclass('public.execution_permits') IS NULL AND to_regprocedure('guard_execution_permit()') IS NULL") == 't'
    alembic.upgrade(config,'head')
    asyncio.run(check_hashes(before,'0008_execution_permits'))
    alembic.check(config)
    result = {'backup_sha256':before['sha256'],'restore_verified':True,'upgrade_verified':True,'downgrade_verified':True,
        'old_business_tables_unchanged':len(before['columns'])-1,'test_revision':'0008_execution_permits',
        'original_database_migrated':False,'metadata_check':'passed'}
    (DIRECTORY/'migration-rehearsal.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print('Isolated migration rehearsal failed: '+type(exc).__name__)
        cause = getattr(getattr(exc, 'orig', None), '__cause__', None)
        if cause is not None:
            print('DDL diagnostic: '+str(getattr(cause, 'sqlstate', ''))+' '+str(getattr(cause, 'message', '')))
        raise SystemExit(1) from None
