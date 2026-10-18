"""Project-owned isolated test stack and read-only original database backup."""

from maintenance_policy import cli_gate, maintenance_action, authorize_maintenance_command
cli_gate(__file__, __name__)

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit, urlunsplit
from dotenv import dotenv_values
from sqlalchemy import text
from app.core.config import Settings, runtime_env_file, is_model_credential_name
from app.repositories.connections import Connections

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'work/p5-live-preflight/permit-test'
PROJECT = 'agentforge-permit-tests'


def command(*args):
    authorize_maintenance_command("permit", args)
    result = subprocess.run(list(args), cwd=ROOT, capture_output=True, text=True)
    if result.returncode: raise RuntimeError('Project test setup command failed: ' + args[0])
    return result.stdout.strip()


def fingerprint_sql(table, columns):
    assert all(re.fullmatch('[a-z_][a-z0-9_]*', item) for item in [table, *columns])
    fields = ','.join('"' + col + '"' for col in columns)
    return f'''SELECT count(*)::text || ':' || md5(COALESCE(string_agg(md5(row_to_json(t)::text),'' ORDER BY md5(row_to_json(t)::text)),'')) FROM (SELECT {fields} FROM "{table}") t'''


async def snapshot():
    c = Connections(Settings())
    try:
        async with c.engine.connect() as conn:
            await conn.execute(text('SET TRANSACTION READ ONLY'))
            assert await conn.scalar(text('SELECT current_database()')) == 'agentforge'
            revision = await conn.scalar(text('SELECT version_num FROM alembic_version'))
            assert revision == '0007_deepseek'
            rows = (await conn.execute(text("SELECT table_name,array_agg(column_name ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='public' GROUP BY table_name ORDER BY table_name"))).all()
            columns = {name: list(fields) for name, fields in rows}
            hashes = {name: await conn.scalar(text(fingerprint_sql(name, fields))) for name, fields in columns.items()}
        return {'revision': revision, 'columns': columns, 'fingerprints': hashes}
    finally: await c.close()


@maintenance_action("permit.prepare")
def main():
    assert runtime_env_file() == ROOT / 'work/p5-live-preflight/.env'
    settings = Settings()
    assert not settings.real_calls_enabled and settings.real_daily_budget_usd == settings.real_test_budget_usd == 0
    assert command('docker','inspect','--format','{{index .Config.Labels "com.docker.compose.project"}}','agentforge-p1-postgres') == 'agentforge-p1'
    assert Path(command('docker','inspect','--format','{{index .Config.Labels "com.docker.compose.project.working_dir"}}','agentforge-p1-postgres')).resolve() == ROOT
    assert command('docker','port','agentforge-p1-postgres','5432/tcp') == '127.0.0.1:' + str(urlsplit(settings.database_url.get_secret_value()).port)
    values = dict(dotenv_values(runtime_env_file(), interpolate=False))
    assert not any(is_model_credential_name(name) for name in values)
    DIRECTORY.mkdir(exist_ok=True)
    before = asyncio.run(snapshot())
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    dump = DIRECTORY / ('before-0008-' + stamp + '.dump')
    remote = '/tmp/agentforge-permits-' + stamp + '.dump'
    command('docker','exec','agentforge-p1-postgres','pg_dump','-U','postgres','-d','agentforge','-Fc','-f',remote)
    command('docker','exec','agentforge-p1-postgres','pg_restore','--list',remote)
    command('docker','cp','agentforge-p1-postgres:' + remote,str(dump))
    before.update(backup=str(dump), sha256=hashlib.sha256(dump.read_bytes()).hexdigest(), bytes=dump.stat().st_size)
    (DIRECTORY / 'backup.json').write_text(json.dumps(before, indent=2), encoding='utf-8')
    def new_port(value, port):
        url = urlsplit(value)
        return urlunsplit((url.scheme, url.netloc.rsplit(':',1)[0] + ':' + str(port), url.path, '', ''))
    values.update(COMPOSE_PROJECT_NAME=PROJECT, POSTGRES_PORT='25432', REDIS_PORT='26379', BACKEND_PORT='28100',
        FRONTEND_PORT='25173', SANDBOX_RUNNER_PORT='28120',
        AGENTFORGE_DATABASE_URL=new_port(values['AGENTFORGE_DATABASE_URL'],25432),
        AGENTFORGE_REDIS_URL=new_port(values['AGENTFORGE_REDIS_URL'],26379),
        AGENTFORGE_SANDBOX_RUNNER_URL='http://127.0.0.1:28120', AGENTFORGE_SINGLE_USE_PERMITS_ENABLED='false',
        AGENTFORGE_REAL_WORKER_MODE='deny', AGENTFORGE_REAL_CALLS_ENABLED='false',
        AGENTFORGE_REAL_DAILY_BUDGET_USD='0', AGENTFORGE_REAL_TEST_BUDGET_USD='0', AGENTFORGE_REAL_MAX_RETRIES='0')
    (DIRECTORY / '.env').write_text(''.join(key+'='+json.dumps(value)+'\n' for key,value in sorted(values.items())), encoding='utf-8')
    postgres_image = command('docker','inspect','--format','{{.Config.Image}}','agentforge-p1-postgres')
    redis_image = command('docker','inspect','--format','{{.Config.Image}}','agentforge-p1-redis')
    runtime_environment = {
        'AGENTFORGE_DATABASE_URL': 'postgresql+asyncpg://agentforge:${APP_DB_PASSWORD}@postgres:5432/agentforge',
        'AGENTFORGE_REDIS_URL': 'redis://:${REDIS_PASSWORD}@redis:6379/0',
        'AGENTFORGE_ADMIN_TOKEN':'${AGENTFORGE_ADMIN_TOKEN}', 'AGENTFORGE_TENANT_ID':'${AGENTFORGE_TENANT_ID}',
        'AGENTFORGE_SANDBOX_IMAGE_ID':'${AGENTFORGE_SANDBOX_IMAGE_ID}',
        'AGENTFORGE_SANDBOX_RUNNER_TOKEN':'${AGENTFORGE_SANDBOX_RUNNER_TOKEN}',
        'AGENTFORGE_SANDBOX_APPROVER_TOKEN':'${AGENTFORGE_SANDBOX_APPROVER_TOKEN}',
        'DOCKER_HOST':'unix:///var/run/docker.sock'}
    runner = {'image':PROJECT+'-runner:local', 'build':str(ROOT/'backend'), 'container_name':PROJECT+'-runner',
        'command':['python','-m','uvicorn','app.sandbox.main:create_app','--factory','--host','0.0.0.0','--port','8000','--no-access-log'],
        'user':'0:0','read_only':True,'tmpfs':['/tmp:rw,nosuid,nodev,size=16777216'],'cap_drop':['ALL'],
        'security_opt':['no-new-privileges:true'],'mem_limit':'384m','cpus':1,'pids_limit':128,
        'environment':runtime_environment, 'volumes':['/var/run/docker.sock:/var/run/docker.sock'], 'ports':['127.0.0.1:28120:8000']}
    unavailable = {**runner, 'container_name':PROJECT+'-unavailable-runner', 'profiles':['sandbox-test'],
        'environment':{**runtime_environment,'DOCKER_HOST':'unix:///nonexistent/agentforge-test.sock'},
        'volumes':[], 'ports':['127.0.0.1:28121:8000']}
    unavailable.pop('build')
    compose = {'name':PROJECT,'services':{
        'postgres':{'image':postgres_image,'container_name':PROJECT+'-postgres',
            'environment':{'POSTGRES_USER':'postgres','POSTGRES_DB':'agentforge','POSTGRES_PASSWORD':'${POSTGRES_PASSWORD}','APP_DB_PASSWORD':'${APP_DB_PASSWORD}'},
            'ports':['127.0.0.1:25432:5432'], 'volumes':['postgres_data:/var/lib/postgresql/data',str(ROOT/'deploy/init-app-role.sql')+':/docker-entrypoint-initdb.d/10-app-role.sql:ro'],
            'healthcheck':{'test':['CMD-SHELL','pg_isready -U postgres -d agentforge'],'interval':'3s','timeout':'3s','retries':15}},
        'redis':{'image':redis_image,'container_name':PROJECT+'-redis','command':['redis-server','/usr/local/etc/redis/redis.conf'],
            'environment':{'REDISCLI_AUTH':'${REDIS_PASSWORD}'}, 'ports':['127.0.0.1:26379:6379'],
            'volumes':['redis_data:/data',str(ROOT/'work/redis.conf')+':/usr/local/etc/redis/redis.conf:ro'],
            'healthcheck':{'test':['CMD','redis-cli','ping'],'interval':'3s','timeout':'3s','retries':15}},
        'runner':runner,'runner-unavailable':unavailable},
        'volumes':{'postgres_data':{'name':PROJECT+'-postgres-data'},'redis_data':{'name':PROJECT+'-redis-data'}}}
    (DIRECTORY/'compose.yaml').write_text(json.dumps(compose, indent=2),encoding='utf-8')
    print(json.dumps({key:before[key] for key in ('revision','backup','sha256','bytes')}))
    print('Prepared isolated project test stack, no model credentials copied; original database remains 0007')


if __name__ == '__main__':
    try: main()
    except Exception as exc:
        print('Permit test preparation failed: '+type(exc).__name__)
        raise SystemExit(1) from None
