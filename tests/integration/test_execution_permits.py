"""Real PostgreSQL/Redis permit races; ONLY local virtual model transport."""
import asyncio
from datetime import timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4
import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select, delete, func, text
from sqlalchemy.exc import IntegrityError, DBAPIError
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.entities import ModelSlot
from app.domain.tasks import AgentTask, ModelOperation
from app.domain.real import RealDailyUsage
from app.domain.permits import ExecutionPermit, PermitAudit, TrustedModelWorker
from app.providers.base import ProviderFailure
from app.providers.deepseek import DeepSeek
from app.providers.openai_compatible import OpenAICompatible
from app.repositories.connections import Connections
from app.schemas.models import ModelConfig
from app.schemas.tasks import TaskCreate
from app.services.context import content_hash
from app.services.execution_permits import PermitService, PROMPT, request_body, operation_id
from app.services.permit_authority import verify_issuer, WorkerIdentity
from app.services.tasks import TaskService, now
from app.workers.engine import Worker

pytestmark = pytest.mark.integration


async def test_concurrent_issuers_create_one_fixed_permit(permit_setup):
    f = permit_setup
    results = await asyncio.gather(f.service.issue(f.authority), f.service.issue(f.authority), return_exceptions=True)
    assert sum(isinstance(value, dict) for value in results) == 1
    assert sum(isinstance(value, AppError) for value in results) == 1
    async with f.c.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ExecutionPermit).where(
            ExecutionPermit.tenant_id == UUID(f.settings.tenant_id))) == 1
    assert f.wire.requests == []


@pytest.mark.parametrize('committed,expected', [(False,'ABORTED'), (True,'UNKNOWN')])
async def test_commit_boundary_failure_keeps_conservative_outcome(permit_setup, monkeypatch, committed, expected):
    f = permit_setup
    original = f.service.commit_dispatch
    async def lost_ack(lease, config, body):
        if committed: await original(lease, config, body)
        raise TimeoutError('Explicit local transaction boundary failure')
    monkeypatch.setattr(f.service, 'commit_dispatch', lost_ack)
    p = await run_permit(f)
    assert p['status'] == expected and p['dispatch_attempts'] == int(committed)
    assert f.wire.requests == []
    async with f.c.sessions() as session:
        quota = await session.get(RealDailyUsage, (UUID(f.settings.tenant_id), now().date()))
        assert quota.test_calls == 1 and bool(quota.cost_reserved) == committed


async def test_migration_downgrade_cannot_erase_issued_or_unknown_history(permit_setup):
    from alembic import command
    from alembic.config import Config
    f = permit_setup
    p = await issued(f)
    with pytest.raises(DBAPIError):
        await asyncio.to_thread(command.downgrade, Config('backend/alembic.ini'), '0007_deepseek')
    assert (await f.service.get(p['permit_id']))['status'] == 'ISSUED'
    assert f.wire.requests == []


class Wire:
    def __init__(self):
        self.requests = []
        self.mode = 'ok'
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.release.set()

    async def handle(self, request):
        body = json.loads(request.content)
        assert body['model'] == 'deepseek-flash' and body['max_tokens'] == 64
        assert body['messages'] == [{'role': 'user', 'content': PROMPT}]
        assert body['thinking'] == {'type': 'disabled'} and 'reasoning_effort' not in body and 'tools' not in body
        self.requests.append({'model': body['model'], 'thinking': body['thinking'], 'max_tokens': body['max_tokens']})
        self.started.set()
        await self.release.wait()
        if self.mode == 'timeout': raise httpx.ReadTimeout('explicit virtual transport timeout', request=request)
        if self.mode == '429': return httpx.Response(429, text='explicit virtual rate limit')
        content = 'other answer' if self.mode == 'wrong_answer' else 'connected'
        frames = [{'choices': [{'index': 0, 'delta': {'content': content}, 'finish_reason': None}]},
                  {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}]
        if self.mode != 'usage_missing':
            frames[-1]['usage'] = {'prompt_tokens': 7, 'completion_tokens': 2, 'total_tokens': 9,
                'prompt_cache_hit_tokens': 5, 'prompt_cache_miss_tokens': 2,
                'prompt_tokens_details': {'cached_tokens': 5}, 'completion_tokens_details': {'reasoning_tokens': 0}}
        raw = ''.join('data: ' + json.dumps(item) + '\n\n' for item in frames)
        if self.mode != 'stream_broken': raw += 'data: [DONE]\n\n'
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=raw)


@pytest.fixture
def permit_process_maintenance(request):
    """Hold only this disposable stack before Settings, DB or fake keys exist."""
    name = getattr(request.node, 'originalname', request.node.name)
    if name != 'test_actual_os_worker_crash_and_restart_never_redispatches' or os.environ.get('AGENTFORGE_RUN_INTEGRATION') != '1':
        yield
        return
    from lifecycle_permit_child import isolated_context
    from s1_isolation import isolation_lease
    root = Path(__file__).resolve().parents[2]
    verified = isolated_context(root)
    with isolation_lease(root, Path(verified['manifest_path'])):
        yield verified


@pytest.fixture
async def permit_setup(monkeypatch, request, permit_process_maintenance):
    if os.environ.get('AGENTFORGE_RUN_INTEGRATION') != '1': pytest.skip('Explicit project PostgreSQL/Redis required')
    ttl = getattr(request, 'param', 60)
    issuer_token = 'explicit-permit-issuer-test-only-credential-0001'
    settings = Settings().model_copy(update={'tenant_id': str(uuid4()), 'single_use_permits_enabled': True,
        'real_worker_mode': 'permit_only', 'real_calls_enabled': True, 'real_max_retries': 0,
        'real_daily_token_limit': 8256, 'real_test_max_calls': 1, 'real_daily_budget_usd': Decimal('.005'),
        'real_test_budget_usd': Decimal('.005'), 'model_credentials_env_only': True, 'permit_ttl_seconds': ttl,
        'model_permit_issuer_token': SecretStr(issuer_token), 'allowed_model_hosts': 'api.deepseek.com',
        'model_credential_hosts': {'AGENTFORGE_MODEL_CODER_KEY': ['api.deepseek.com']},
        'model_prices': {'openai_compatible/deepseek-flash': {'currency': 'USD', 'input_per_million': '.30',
            'output_per_million': '1.20', 'input_upper_bound': 8192, 'output_upper_bound': 4096,
            'version': 'explicit-virtual-peak-v1', 'token_parameter': 'max_tokens'}}})
    monkeypatch.setenv('AGENTFORGE_MODEL_CODER_KEY', 'explicit-virtual-provider-credential-only')
    c = Connections(settings)
    wire = Wire()
    async def public_ip(host):
        assert host == 'api.deepseek.com'
        return '93.184.216.34'
    monkeypatch.setattr('app.providers.openai_compatible.public_address', public_ip)
    monkeypatch.setattr('app.providers.openai_compatible.assert_model_egress', lambda: None)
    monkeypatch.setattr(OpenAICompatible, 'http_client', lambda self, timeout: httpx.AsyncClient(
        transport=httpx.MockTransport(wire.handle), trust_env=False, follow_redirects=False))
    async with c.sessions() as session, session.begin():
        for role in ('coder','planner','researcher','reviewer'):
            data = ModelConfig(provider='openai_compatible', base_url='https://api.deepseek.com', model='deepseek-flash',
                credential_reference='env:AGENTFORGE_MODEL_CODER_KEY', max_tokens=64, timeout=30, enabled=True).model_dump() if role == 'coder' else ModelConfig().model_dump()
            session.add(ModelSlot(tenant_id=UUID(settings.tenant_id), role=role, version=1, **data))
    service = PermitService(c, settings)
    worker = Worker(c, settings)
    await worker.initialize()
    authority = verify_issuer(issuer_token, settings)
    fixture = SimpleNamespace(settings=settings, c=c, service=service, worker=worker, workers=[worker], wire=wire, authority=authority)
    try:
        yield fixture
    finally:
        wire.release.set()
        for owned in fixture.workers: await owned.close()
        async with c.sessions() as session, session.begin():
            ids = select(ExecutionPermit.permit_id).where(ExecutionPermit.tenant_id == UUID(settings.tenant_id))
            await session.execute(delete(PermitAudit).where(PermitAudit.permit_id.in_(ids)))
            tasks = select(ExecutionPermit.task_id).where(ExecutionPermit.tenant_id == UUID(settings.tenant_id))
            await session.execute(delete(ModelOperation).where(ModelOperation.task_id.in_(tasks)))
            await session.execute(delete(ExecutionPermit).where(ExecutionPermit.tenant_id == UUID(settings.tenant_id)))
            for model in (AgentTask, ModelSlot, RealDailyUsage, TrustedModelWorker):
                await session.execute(delete(model).where(model.tenant_id == UUID(settings.tenant_id)))
        await c.close()


async def issued(f):
    return await f.service.issue(f.authority)


async def claim_task(f, permit):
    claim = await f.worker.claim(permit['task_id'])
    assert claim is not None
    return claim[1]


async def run_permit(f):
    p = await issued(f)
    fence = await claim_task(f, p)
    return await f.service.execute(p['permit_id'], f.worker.permit_identity, fence)


async def test_one_permit_success_usage_http_audit_and_no_reuse(permit_setup):
    f = permit_setup
    p = await run_permit(f)
    assert p['status'] == 'SUCCEEDED' and p['claim_count'] == p['dispatch_attempts'] == 1
    assert p['http_status'] == 200 and p['sse_complete'] is True
    assert p['result']['summary'] == 'connected' and p['usage']['total_tokens'] == 9
    assert p['usage_details'] == {'cache_hit_tokens': 5, 'cache_miss_tokens': 2, 'cached_tokens': 5, 'reasoning_tokens': 0}
    assert p['reserved_cost'] == Decimal('.00253440') and p['settled_cost'] == Decimal('.00000450')
    assert len(f.wire.requests) == 1
    with pytest.raises(AppError, match='PERMIT_CONSUMED'):
        await f.service.execute(p['permit_id'], f.worker.permit_identity, 1)
    assert len(f.wire.requests) == 1
    previous = '0' * 64
    for row in p['audit']:
        assert row['previous_hash'] == previous
        data = {'permit_id': str(p['permit_id']), 'execution_id': str(p['execution_id']),
            **{name: row[name] for name in ('sequence','previous_status','status','event','details','previous_hash')}}
        assert row['event_hash'] == content_hash(data)
        previous = row['event_hash']
    async with f.c.sessions() as session:
        quota = await session.get(RealDailyUsage, (UUID(f.settings.tenant_id), now().date()))
        assert quota.test_calls == 1 and quota.cost_reserved == 0 and quota.cost_used == p['settled_cost']


@pytest.mark.parametrize('stage,expected', [('claimed','ABORTED'), ('dispatched','UNKNOWN')])
async def test_actual_os_worker_crash_and_restart_never_redispatches(permit_setup, stage, expected):
    from lifecycle_permit_child import PermitProcessChild, isolated_context
    f = permit_setup
    await f.worker.close()  # The child alone holds the trusted proof for the new permit.
    root = Path(__file__).resolve().parents[2]
    verified = isolated_context(root)
    directory = Path(verified['run_directory']) / 'permit-process-tests' / f.settings.tenant_id
    directory.mkdir(parents=True)
    def spawn(mode):
        return PermitProcessChild(root, f.settings.tenant_id, mode)
    async def record(name, timeout=15):
        async with asyncio.timeout(timeout):
            while not (directory / (name + '.json')).is_file():
                assert not (directory / 'failure.json').is_file(), 'Crash probe child failed safely'
                await asyncio.sleep(.05)
        return json.loads((directory / (name + '.json')).read_text())
    async def stop(process):
        # Guard ownership is thread-local; cleanup stays on the owning test thread.
        process.stop()
    process = spawn(stage)
    replacement = None
    try:
        ready = await record('ready')
        process.bind(ready['pid'])
        p = await issued(f)
        assert str(p['authorized_worker_identity']) == ready['identity']
        (directory / 'request.json').write_text(json.dumps({'permit_id': str(p['permit_id']), 'task_id': str(p['task_id'])}))
        boundary = await record('boundary')
        await stop(process)  # Abrupt OS termination, no Python finally/settlement path.
        # Wait for the real persisted worker lease to expire; no simulated timestamp edit.
        async with asyncio.timeout(24):
            while True:
                async with f.c.sessions() as session:
                    expired = await session.scalar(select(TrustedModelWorker.expires_at <= func.clock_timestamp()).where(
                        TrustedModelWorker.identity == UUID(ready['identity'])))
                if expired: break
                await asyncio.sleep(.2)
        replacement = spawn('recover')
        recovered = await record('recovery')
        await asyncio.to_thread(replacement.wait, 10)
        assert replacement.returncode == 0 and recovered['pid'] != ready['pid']
        assert recovered['status'] == expected and recovered['claim'] is None
        assert recovered['dispatch_attempts'] == (stage == 'dispatched')
        async with f.c.sessions() as session:
            quota = await session.get(RealDailyUsage, (UUID(f.settings.tenant_id), now().date()))
            assert quota.test_calls == 1
            assert quota.cost_reserved == (Decimal('.00253440') if expected == 'UNKNOWN' else 0)
        (directory / 'evidence.json').write_text(json.dumps({'before': boundary, 'after': recovered,
            'actual_external_model_requests': 0,
            'owned_launcher_identity': process.launcher_facts,
            'owned_crashed_child_identity': process.child_facts,
            'replacement_launcher_identity': replacement.launcher_facts,
            'replacement_child_identity': replacement.child_facts}, indent=2))
    finally:
        await stop(process)
        if replacement: await stop(replacement)



async def test_real_concurrent_sessions_consume_once_and_reserve_once(permit_setup):
    f = permit_setup
    p = await issued(f)
    fence = await claim_task(f, p)
    async with f.c.engine.connect() as blocker:
        transaction = await blocker.begin()
        await blocker.execute(select(ExecutionPermit).where(ExecutionPermit.permit_id == p['permit_id']).with_for_update())
        futures = [asyncio.create_task(f.service.claim(p['permit_id'], f.worker.permit_identity, fence)) for _ in range(2)]
        waiting = []
        for _ in range(100):
            async with f.c.engine.connect() as observer:
                waiting = (await observer.execute(text("SELECT pid FROM pg_stat_activity WHERE datname=current_database() AND usename=current_user AND wait_event_type='Lock' AND pid<>pg_backend_pid()"))).scalars().all()
            if len(waiting) >= 2: break
            await asyncio.sleep(.02)
        assert len(set(waiting)) >= 2, 'Must observe two distinct PostgreSQL backends waiting concurrently'
        await transaction.commit()
    results = await asyncio.gather(*futures, return_exceptions=True)
    assert sum(not isinstance(value, Exception) for value in results) == 1
    assert sum(isinstance(value, AppError) and value.code == 'PERMIT_CONSUMED' for value in results) == 1
    async with f.c.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ModelOperation).where(ModelOperation.task_id == p['task_id'],
            ModelOperation.operation_id == operation_id(SimpleNamespace(execution_id=p['execution_id'])))) == 1
        quota = await session.get(RealDailyUsage, (UUID(f.settings.tenant_id), now().date()))
        assert quota.test_calls == 1 and quota.cost_reserved == Decimal('.00253440') and quota.tokens_reserved == 8256
    Path('work/p5-live-permit-concurrency.json').write_text(json.dumps({'distinct_waiting_pg_backends': waiting,
        'successful_claims': 1, 'model_operations': 1, 'reserved_usd': '.00253440', 'external_api_calls': 0}), encoding='utf-8')


async def test_two_distinct_workers_race_only_bound_worker_can_win(permit_setup):
    f = permit_setup
    p = await issued(f)
    second = Worker(f.c, f.settings)
    await second.initialize()
    f.workers.append(second)
    fence = await claim_task(f, p)
    barrier = asyncio.Barrier(2)
    async def contender(identity):
        await barrier.wait()
        return await f.service.claim(p['permit_id'], identity, fence)
    values = await asyncio.gather(contender(f.worker.permit_identity), contender(second.permit_identity), return_exceptions=True)
    assert not isinstance(values[0], Exception)
    assert isinstance(values[1], AppError) and values[1].code == 'PERMIT_WORKER_FORBIDDEN'
    assert not f.wire.requests


async def test_ordinary_chat_and_other_roles_cannot_use_test_budget(permit_setup):
    f = permit_setup
    p = await issued(f)
    service = TaskService(f.c, f.settings)
    for role in ('coder','planner','researcher','reviewer'):
        with pytest.raises(AppError, match='MODEL_PERMIT_REQUIRED'):
            await service.create(f.settings.tenant_id, uuid4(), TaskCreate(goal='not authorized', execution_mode='real', workflow='chat', chat_role=role))
    assert (await f.service.get(p['permit_id']))['status'] == 'ISSUED'
    assert not f.wire.requests


@pytest.mark.parametrize('mode,status,usage', [('timeout','UNKNOWN','unknown'), ('stream_broken','UNKNOWN','unknown'),
    ('429','FAILED','unknown'), ('usage_missing','SUCCEEDED','unknown'), ('wrong_answer','FAILED','reported_estimate')])
async def test_failures_unknown_and_missing_usage_never_repeat_or_drop_reservation(permit_setup, mode, status, usage):
    f = permit_setup
    f.wire.mode = mode
    p = await run_permit(f)
    assert p['status'] == status and p['usage_status'] == usage and len(f.wire.requests) == 1
    assert p['claim_count'] == p['dispatch_attempts'] == 1
    async with f.c.sessions() as session:
        quota = await session.get(RealDailyUsage, (UUID(f.settings.tenant_id), now().date()))
        assert quota.test_calls == 1
        assert (quota.cost_reserved > 0) == (usage == 'unknown')
    with pytest.raises(AppError, match='PERMIT_CONSUMED'):
        await f.service.execute(p['permit_id'], f.worker.permit_identity, 1)
    assert len(f.wire.requests) == 1


async def test_no_database_row_lock_is_held_while_http_waits(permit_setup):
    f = permit_setup
    p = await issued(f)
    fence = await claim_task(f, p)
    f.wire.release.clear()
    pending = asyncio.create_task(f.service.execute(p['permit_id'], f.worker.permit_identity, fence))
    await asyncio.wait_for(f.wire.started.wait(), 3)
    try:
        async with f.c.sessions() as session, session.begin():
            row = await session.scalar(select(ExecutionPermit).where(ExecutionPermit.permit_id == p['permit_id']).with_for_update(nowait=True))
            assert row.status == 'DISPATCH_COMMITTED' and row.dispatch_attempts == 1
    finally:
        f.wire.release.set()
    assert (await pending)['status'] == 'SUCCEEDED'


@pytest.mark.parametrize('boundary', ['claimed','committed'])
async def test_recovery_before_and_after_dispatch_intent_never_replays(permit_setup, boundary):
    f = permit_setup
    p = await issued(f)
    fence = await claim_task(f, p)
    lease = await f.service.claim(p['permit_id'], f.worker.permit_identity, fence)
    if boundary == 'committed':
        async with f.c.sessions() as session:
            task = await session.get(AgentTask, p['task_id'])
            cfg = task.model_snapshot['coder'] | {'token_parameter': 'max_tokens'}
        await lease.commit(cfg, request_body(cfg))
    async with f.c.sessions() as session, session.begin():
        row = await session.get(TrustedModelWorker, f.worker.permit_identity.identity)
        row.expires_at = now() - timedelta(seconds=1)
    await f.service.recover()
    state = await f.service.get(p['permit_id'])
    assert state['status'] == ('ABORTED' if boundary == 'claimed' else 'UNKNOWN')
    assert state['dispatch_attempts'] == (0 if boundary == 'claimed' else 1)
    async with f.c.sessions() as session:
        quota = await session.get(RealDailyUsage, (UUID(f.settings.tenant_id), now().date()))
        assert quota.test_calls == 1 and (quota.cost_reserved > 0) == (boundary == 'committed')
    assert not f.wire.requests
    replacement = Worker(f.c, f.settings)
    await replacement.initialize()
    f.workers.append(replacement)
    assert await replacement.claim(p['task_id']) is None
    assert not f.wire.requests


@pytest.mark.parametrize('permit_setup', [1], indirect=True)
async def test_expired_permit_is_never_dispatchable(permit_setup):
    f = permit_setup
    p = await issued(f)
    await asyncio.sleep(1.1)
    await f.service.recover()
    assert (await f.service.get(p['permit_id']))['status'] == 'EXPIRED'
    assert await f.worker.claim(p['task_id']) is None
    assert not f.wire.requests


@pytest.mark.parametrize('claimed', [False, True])
async def test_revocation_cannot_reenable_or_dispatch(permit_setup, claimed):
    f = permit_setup
    p = await issued(f)
    if claimed:
        fence = await claim_task(f, p)
        await f.service.claim(p['permit_id'], f.worker.permit_identity, fence)
    result = await f.service.revoke(p['permit_id'], f.authority)
    assert result['status'] == ('ABORTED' if claimed else 'REVOKED')
    with pytest.raises(AppError, match='PERMIT_CONSUMED'):
        await f.service.claim(p['permit_id'], f.worker.permit_identity, 1)
    assert not f.wire.requests


async def test_version_change_and_wire_mutation_block_before_http(permit_setup):
    f = permit_setup
    p = await issued(f)
    fence = await claim_task(f, p)
    lease = await f.service.claim(p['permit_id'], f.worker.permit_identity, fence)
    async with f.c.sessions() as session:
        task = await session.get(AgentTask, p['task_id'])
        cfg = task.model_snapshot['coder'] | {'token_parameter': 'max_tokens'}
    with pytest.raises(AppError, match='PERMIT_REQUEST_CHANGED'):
        await lease.commit(cfg, request_body(cfg) | {'max_tokens': 65})
    async with f.c.sessions() as session, session.begin():
        slot = await session.get(ModelSlot, (UUID(f.settings.tenant_id), 'coder'))
        slot.version += 1
    with pytest.raises(AppError, match='PERMIT_CONFIGURATION_CHANGED'):
        await lease.commit(cfg, request_body(cfg))
    assert not f.wire.requests


async def test_database_trigger_rejects_binding_edit_and_terminal_reset(permit_setup):
    f = permit_setup
    p = await run_permit(f)
    for statement in ("UPDATE execution_permits SET status='ISSUED',claim_count=0,dispatch_attempts=0 WHERE permit_id=:id",
                      "UPDATE execution_permits SET role='researcher' WHERE permit_id=:id",
                      "UPDATE execution_permits SET max_output_tokens=65 WHERE permit_id=:id"):
        with pytest.raises(DBAPIError):
            async with f.c.engine.begin() as conn: await conn.execute(text(statement), {'id': p['permit_id']})
    assert (await f.service.get(p['permit_id']))['status'] == 'SUCCEEDED'
    assert len(f.wire.requests) == 1


async def test_duplicate_redis_messages_and_worker_tick_have_one_virtual_request(permit_setup):
    f = permit_setup
    p = await issued(f)
    from app.workers.engine import STREAM
    for _ in range(4): await f.c.redis.xadd(STREAM, {'task_id': str(p['task_id']), 'outbox_id': str(uuid4())})
    for _ in range(100):
        await f.worker.tick()
        await asyncio.sleep(.02)
        if (await f.service.get(p['permit_id']))['status'] == 'SUCCEEDED': break
    for _ in range(4): await f.worker.tick()
    result = await f.service.get(p['permit_id'])
    assert result['status'] == 'SUCCEEDED' and len(f.wire.requests) == 1


async def test_fake_worker_identifier_and_insufficient_budget_are_denied(permit_setup):
    f = permit_setup
    p = await issued(f)
    fence = await claim_task(f, p)
    for identity in (str(f.worker.permit_identity.identity), WorkerIdentity(f.worker.permit_identity.identity, f.worker.owner, 'not-a-proof', object())):
        with pytest.raises(AppError, match='PERMIT_WORKER_FORBIDDEN'):
            await f.service.claim(p['permit_id'], identity, fence)
    async with f.c.sessions() as session, session.begin():
        quota = await session.get(RealDailyUsage, (UUID(f.settings.tenant_id), now().date()))
        quota.cost_reserved = Decimal('.004')
    with pytest.raises(AppError, match='PERMIT_BUDGET_BLOCKED'):
        await f.service.claim(p['permit_id'], f.worker.permit_identity, fence)
    assert (await f.service.get(p['permit_id']))['claim_count'] == 0 and not f.wire.requests
