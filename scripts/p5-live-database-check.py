"""Project-specific backup/restore rehearsal and additive migration verification."""

from maintenance_policy import cli_gate, maintenance_action, authorize_maintenance_command
cli_gate(__file__, __name__)

import argparse
import asyncio
import hashlib
import importlib.util
from io import StringIO
import json
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone
from sqlalchemy import text, select
from app.core.config import Settings, runtime_env_file
from app.repositories.connections import Connections

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'work/p5-live-preflight'
CONTAINER = 'agentforge-p1-postgres'


def command(*args, input=None):
    authorize_maintenance_command("database", args)
    if input is not None:
        from lifecycle_manager import LifecycleError
        raise LifecycleError("MAINTENANCE_COMMAND_FORBIDDEN")
    result = subprocess.run(list(args), cwd=ROOT, input=input, text=True, capture_output=True)
    if result.returncode: raise RuntimeError('Project database command failed: ' + args[0])
    return result.stdout.strip()


@maintenance_action("database.owner")
def owner_check():
    project = command('docker', 'inspect', '--format', '{{index .Config.Labels "com.docker.compose.project"}}', CONTAINER)
    directory = command('docker', 'inspect', '--format', '{{index .Config.Labels "com.docker.compose.project.working_dir"}}', CONTAINER)
    assert project == 'agentforge-p1' and Path(directory).resolve() == ROOT.resolve()
    from urllib.parse import urlsplit
    port = urlsplit(Settings().database_url.get_secret_value()).port
    assert command('docker', 'port', CONTAINER, '5432/tcp') == '127.0.0.1:' + str(port)
    assert command('docker', 'exec', CONTAINER, 'psql', '-U', 'postgres', '-d', 'agentforge', '-Atc', 'SELECT current_database()') == 'agentforge'


def fingerprint_sql(table, columns):
    assert all(re.fullmatch('[a-z_][a-z0-9_]*', item) for item in [table, *columns])
    selected = ','.join('"' + col + '"' for col in columns)
    return f'''SELECT count(*)::text || ':' || md5(COALESCE(string_agg(md5(row_to_json(t)::text),'' ORDER BY md5(row_to_json(t)::text)),'')) FROM (SELECT {selected} FROM "{table}") t'''


async def inventory():
    settings = Settings()
    assert runtime_env_file().parent == DIRECTORY and not settings.real_calls_enabled
    c = Connections(settings)
    try:
        async with c.engine.connect() as conn:
            assert await conn.scalar(text('SELECT current_database()')) == 'agentforge'
            rows = (await conn.execute(text("SELECT table_name, array_agg(column_name ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='public' GROUP BY table_name ORDER BY table_name"))).all()
            schemas = {name: list(columns) for name, columns in rows}
            hashes = {table: await conn.scalar(text(fingerprint_sql(table, columns))) for table, columns in schemas.items()}
            revision = await conn.scalar(text('SELECT version_num FROM alembic_version'))
        return {'revision': revision, 'columns': schemas, 'fingerprints': hashes}
    finally: await c.close()


def clone_hashes(database, before):
    assert re.fullmatch('agentforge_p5_restore_[0-9]+', database)
    return {table: command('docker', 'exec', CONTAINER, 'psql', '-U', 'postgres', '-d', database, '-Atc', fingerprint_sql(table, columns))
            for table, columns in before['columns'].items()}


def migration_sql(action):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = ROOT / 'backend/migrations/versions/0007_deepseek.py'
    spec = importlib.util.spec_from_file_location('deepseek_ddl', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    buffer = StringIO()
    module.op = Operations(MigrationContext.configure(dialect_name='postgresql', opts={'as_sql': True, 'output_buffer': buffer}))
    getattr(module, action)()
    return buffer.getvalue()


@maintenance_action("database.rehearsal")
def backup():
    owner_check()
    before = asyncio.run(inventory())
    assert before['revision'] == '0006_real_models', 'Unexpected baseline migration; no backup/migration assumptions made'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    remote = '/tmp/agentforge-p5-' + stamp + '.dump'
    local = DIRECTORY / ('agentforge-before-0007-' + stamp + '.dump')
    clone = 'agentforge_p5_restore_' + stamp
    command('docker', 'exec', CONTAINER, 'pg_dump', '-U', 'postgres', '-d', 'agentforge', '-Fc', '-f', remote)
    command('docker', 'cp', CONTAINER + ':' + remote, str(local))
    assert local.stat().st_size > 0
    command('docker', 'exec', CONTAINER, 'pg_restore', '--list', remote)
    command('docker', 'exec', CONTAINER, 'createdb', '-U', 'postgres', '--owner=agentforge', clone)
    try:
        command('docker', 'exec', CONTAINER, 'pg_restore', '-U', 'postgres', '--no-owner', '--exit-on-error', '-d', clone, remote)
        assert clone_hashes(clone, before) == before['fingerprints'], 'Restored data mismatch'
        forward, reverse = migration_sql('upgrade'), migration_sql('downgrade')
        command('docker', 'exec', CONTAINER, 'psql', '-U', 'postgres', '-d', clone, '-v', 'ON_ERROR_STOP=1', '-1c', forward)
        assert clone_hashes(clone, before) == before['fingerprints'], 'Upgrade changed pre-existing data'
        defaults = command('docker', 'exec', CONTAINER, 'psql', '-U', 'postgres', '-d', clone, '-Atc', "SELECT count(*) FROM model_slots WHERE thinking_mode<>'disabled' OR reasoning_effort<>'high'")
        assert defaults == '0'
        command('docker', 'exec', CONTAINER, 'psql', '-U', 'postgres', '-d', clone, '-v', 'ON_ERROR_STOP=1', '-1c', reverse)
        assert clone_hashes(clone, before) == before['fingerprints'], 'Downgrade changed pre-existing data'
    finally:
        owner_check()
        assert command('docker', 'exec', CONTAINER, 'psql', '-U', 'postgres', '-d', clone, '-Atc', 'SELECT current_database()') == clone
        command('docker', 'exec', CONTAINER, 'dropdb', '-U', 'postgres', clone)
    before.update(backup_path=str(local), backup_sha256=hashlib.sha256(local.read_bytes()).hexdigest(),
                  backup_bytes=local.stat().st_size, restore_verified=True, upgrade_downgrade_rehearsal=True, clone_removed=True)
    (DIRECTORY / 'backup.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    print(json.dumps({key: before[key] for key in ('revision','backup_path','backup_sha256','backup_bytes','restore_verified','upgrade_downgrade_rehearsal','clone_removed')}))


@maintenance_action("database.verify")
async def verify():
    owner_check()
    before = json.loads((DIRECTORY / 'backup.json').read_text())
    settings = Settings()
    c = Connections(settings)
    try:
        async with c.engine.connect() as conn:
            revision = await conn.scalar(text('SELECT version_num FROM alembic_version'))
            assert revision == '0007_deepseek'
            unchanged = []
            for table, columns in before['columns'].items():
                if table == 'alembic_version': continue
                assert await conn.scalar(text(fingerprint_sql(table, columns))) == before['fingerprints'][table], table + ' data changed'
                unchanged.append(table)
        result = {'revision': revision, 'pre_existing_tables_unchanged': unchanged, 'backup_sha256': before['backup_sha256'], 'actual_external_model_calls': 0}
        (DIRECTORY / 'migration.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
    finally: await c.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['backup', 'verify', 'owner'])
    args = parser.parse_args()
    try:
        if args.action == 'backup': backup()
        elif args.action == 'verify': asyncio.run(verify())
        else:
            owner_check()
            print('PASS: AgentForge project labels, workspace directory, database name and published connection port match')
    except Exception as exc:
        print('Database preflight failed: ' + type(exc).__name__)
        raise SystemExit(1) from None
