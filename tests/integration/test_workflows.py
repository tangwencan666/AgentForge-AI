import asyncio
import os
from uuid import UUID, uuid4
from datetime import timedelta
from sqlalchemy import select, func
import pytest
from app.core.config import Settings
from app.core.errors import AppError
from app.repositories.connections import Connections
from app.schemas.tasks import TaskCreate, ApprovalDecision
from app.services.tasks import TaskService, TERMINAL, now, locked_task
from app.domain.tasks import AgentTask, ModelOperation, TaskEvent, GraphCheckpoint, Outbox
from app.workers.engine import Worker, STREAM

pytestmark = pytest.mark.integration


@pytest.fixture
async def setup():
    if os.environ.get('AGENTFORGE_RUN_INTEGRATION') != '1':
        pytest.skip('Real PostgreSQL/Redis integration opt-in required')
    settings = Settings()
    assert '127.0.0.1' in settings.database_url.get_secret_value()
    connections = Connections(settings)
    worker = Worker(connections,settings)
    await worker.initialize()
    service = TaskService(connections,settings)
    try:
        yield settings,connections,worker,service
    finally:
        await worker.close()
        await connections.close()


async def drive(worker, service, tenant, task_id, wanted=TERMINAL, timeout=10):
    deadline = asyncio.get_running_loop().time()+timeout
    while asyncio.get_running_loop().time() < deadline:
        await worker.tick()
        await asyncio.sleep(0.04)
        task = await service.get(UUID(task_id),tenant)
        if task['status'] in wanted:
            return task
    raise AssertionError('Workflow did not reach requested state within bounded time')


async def make(setup, **changes):
    settings,connections,worker,service = setup
    request = TaskCreate(**({'goal':'P2 integration test','execution_mode':'mock','require_approval':False,'mock_options':{'latency_ms':50}} | changes))
    task = await service.create(settings.tenant_id,uuid4(),request)
    return task


async def test_four_mock_roles_and_real_persistence(setup):
    settings,connections,worker,service = setup
    created = await make(setup)
    task = await drive(worker,service,settings.tenant_id,created['task_id'])
    assert task['status'] == 'succeeded', task['error_code']
    assert {call['role'] for call in task['calls']} == {'planner','coder','researcher','reviewer'}
    assert all(call['is_mock'] and call['provider']=='mock' for call in task['calls'])
    assert all(call['model']==task['model_snapshot'][call['role']]['model'] for call in task['calls'])
    assert task['usage']['real_cost_usd'] == '0.00000000'
    assert task['usage']['input_output_tokens'] > 0
    async with connections.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(GraphCheckpoint).where(GraphCheckpoint.task_id == UUID(task['task_id']))) > 0


@pytest.mark.parametrize('mode', ['independent','research_first','code_first'])
async def test_worker_dependency_and_concurrency(setup,mode):
    settings,connections,worker,service = setup
    task = await make(setup,worker_dependency=mode,mock_options={'latency_ms':300})
    task = await drive(worker,service,settings.tenant_id,task['task_id'])
    assert task['status'] == 'succeeded'
    async with connections.sessions() as session:
        rows = (await session.scalars(select(ModelOperation).where(ModelOperation.task_id == UUID(task['task_id'])))).all()
    roles = {row.role:row for row in rows}
    if mode == 'independent':
        assert roles['coder'].started_at < roles['researcher'].finished_at
        assert roles['researcher'].started_at < roles['coder'].finished_at
    elif mode == 'research_first':
        assert roles['researcher'].finished_at <= roles['coder'].started_at
    else:
        assert roles['coder'].finished_at <= roles['researcher'].started_at


async def test_plan_approval_restarts_from_checkpoint_without_replaying_planner(setup):
    settings,connections,worker,service = setup
    created = await make(setup,require_approval=True)
    task = await drive(worker,service,settings.tenant_id,created['task_id'],{'waiting_approval'})
    # Await the save/release boundary before approval (no arbitrary graph resume API).
    for _ in range(30):
        await worker.tick(); await asyncio.sleep(0.03)
        async with connections.sessions() as session:
            record = await session.get(AgentTask,UUID(task['task_id']))
            if record.owner is None: break
    item = next(a for a in await service.approvals(settings.tenant_id) if a['task_id']==task['task_id'])
    with pytest.raises(AppError):
        await service.decide(UUID(item['approval_id']),settings.tenant_id,ApprovalDecision(decision='approved',operation_hash='0'*64))
    await worker.close()
    worker2 = Worker(connections,settings)
    await worker2.initialize()
    try:
        await service.decide(UUID(item['approval_id']),settings.tenant_id,ApprovalDecision(decision='approved',operation_hash=item['operation_hash']))
        task = await drive(worker2,service,settings.tenant_id,task['task_id'])
        assert task['status']=='succeeded', task['error_code']
        assert sum(call['role']=='planner' for call in task['calls'])==1
    finally:
        await worker2.close()


async def test_idempotency_and_cross_tenant_auth(setup):
    settings,connections,worker,service = setup
    key=uuid4(); body=TaskCreate(goal='P2 idempotency',execution_mode='mock',require_approval=False)
    one=await service.create(settings.tenant_id,key,body); two=await service.create(settings.tenant_id,key,body)
    assert one['task_id']==two['task_id']
    with pytest.raises(AppError) as conflict:
        await service.create(settings.tenant_id,key,TaskCreate(goal='changed',execution_mode='mock'))
    assert conflict.value.code=='IDEMPOTENCY_CONFLICT'
    with pytest.raises(AppError):
        await service.get(UUID(one['task_id']),str(uuid4()))
    await service.cancel(UUID(one['task_id']),settings.tenant_id)


@pytest.mark.parametrize('changes,status', [({'max_calls':1},'limit_exceeded'),({'max_tokens':100},'limit_exceeded'),
    ({'max_budget_usd':'0.00000001'},'limit_exceeded'),({'max_iterations':1,'mock_options':{'review_rounds':1,'latency_ms':10}},'limit_exceeded'),
    ({'mock_options':{'fail_role':'reviewer','latency_ms':10}},'failed')])
async def test_limits_and_single_model_failure(setup,changes,status):
    settings,connections,worker,service = setup
    task=await make(setup,**changes)
    task=await drive(worker,service,settings.tenant_id,task['task_id'])
    assert task['status']==status, task['error_code']
    assert task['usage']['reserved_tokens']==0


async def test_cancel_and_timeout_are_persistent(setup):
    settings,connections,worker,service=setup
    task=await make(setup,mock_options={'latency_ms':2000})
    await worker.tick(); await asyncio.sleep(0.15)
    await service.cancel(UUID(task['task_id']),settings.tenant_id)
    task=await drive(worker,service,settings.tenant_id,task['task_id'])
    assert task['status']=='cancelled'
    assert task['usage']['reserved_tokens']==0
    timed=await make(setup,timeout_seconds=1,mock_options={'latency_ms':2000})
    timed=await drive(worker,service,settings.tenant_id,timed['task_id'])
    assert timed['status']=='timed_out'


async def test_stale_fence_and_duplicate_delivery_do_not_repeat_results(setup):
    settings,connections,worker,service=setup
    task=await make(setup)
    task=await drive(worker,service,settings.tenant_id,task['task_id'])
    before=task['usage']['model_attempts']
    await connections.redis.xadd(STREAM,{'task_id':task['task_id'],'outbox_id':str(uuid4())})
    for _ in range(5): await worker.tick()
    assert (await service.get(UUID(task['task_id']),settings.tenant_id))['usage']['model_attempts']==before
    queued=await make(setup)
    claim=await worker.claim(UUID(queued['task_id']))
    from app.services.orchestration.runtime import Runtime
    tenant,fence=claim
    async with connections.sessions() as session,session.begin():
        record=await locked_task(session,UUID(queued['task_id']))
        record.fence += 1
    with pytest.raises(AppError) as error:
        await Runtime(connections,settings,UUID(queued['task_id']),tenant,worker.owner,fence).assert_active()
    assert error.value.code=='STALE_LEASE'
    await service.cancel(UUID(queued['task_id']),settings.tenant_id)
    await worker.sweep()


async def test_inflight_worker_takeover_reuses_ledger_and_checkpoints(setup):
    settings,connections,worker,service=setup
    created=await make(setup,mock_options={'latency_ms':300})
    deadline=asyncio.get_running_loop().time()+5
    while asyncio.get_running_loop().time()<deadline:
        await worker.tick(); await asyncio.sleep(0.03)
        task=await service.get(UUID(created['task_id']),settings.tenant_id)
        if any(call['role']=='reviewer' and call['state']=='reserved' for call in task['calls']): break
    assert any(call['role']=='reviewer' for call in task['calls'])
    async with connections.sessions() as session,session.begin():
        record=await locked_task(session,UUID(created['task_id']))
        record.lease_until=now()-timedelta(seconds=1)
    replacement=Worker(connections,settings)
    await replacement.initialize()
    try:
        await replacement.sweep()
        result=await drive(replacement,service,settings.tenant_id,created['task_id'])
        assert result['status']=='succeeded', result['error_code']
        assert len(result['calls'])==4  # No duplicate simulated model charge on replay.
        assert result['usage']['reserved_tokens']==0
    finally:
        await replacement.close()


async def test_parallel_budget_reservations_are_atomic(setup):
    settings,connections,worker,service=setup
    created=await make(setup,max_tokens=2000)
    tenant,fence=await worker.claim(UUID(created['task_id']))
    from app.services.orchestration.runtime import Runtime
    runtime=Runtime(connections,settings,UUID(created['task_id']),tenant,worker.owner,fence)
    results=await asyncio.gather(runtime.operation('coder',0,{'summary':'[MOCK] test'}),runtime.operation('researcher',0,{'summary':'[MOCK] test'}),return_exceptions=True)
    assert sum(isinstance(value,AppError) and value.code=='TASK_LIMIT' for value in results)==1
    task=await service.get(UUID(created['task_id']),tenant)
    assert task['usage']['model_attempts']==1 and task['usage']['reserved_tokens']==0
    await service.cancel(UUID(created['task_id']),tenant); await worker.sweep()


async def test_shared_tenant_daily_quota_is_atomic_across_tasks(setup):
    settings,connections,worker,service=setup
    data=settings.model_dump(); data['tenant_id']=str(uuid4()); data['daily_mock_token_limit']=2000
    limited=Settings(_env_file=None,**data)
    limited_service=TaskService(connections,limited)
    tasks=[await limited_service.create(limited.tenant_id,uuid4(),TaskCreate(goal='P2 shared quota',execution_mode='mock',require_approval=False)) for _ in range(2)]
    from app.services.orchestration.runtime import Runtime
    runtimes=[]
    for task in tasks:
        tenant,fence=await worker.claim(UUID(task['task_id']))
        runtimes.append(Runtime(connections,limited,UUID(task['task_id']),tenant,worker.owner,fence))
    results=await asyncio.gather(*(runtime.operation('coder',0,{'summary':'[MOCK] test'}) for runtime in runtimes),return_exceptions=True)
    assert sum(isinstance(value,AppError) and value.code=='TASK_LIMIT' for value in results)==1
    for task in tasks: await limited_service.cancel(UUID(task['task_id']),limited.tenant_id)
    await worker.sweep()


async def test_sse_replay_authentication_and_secret_redaction(setup):
    settings,connections,worker,service=setup
    task=await make(setup,goal='P2 key '+settings.admin_token.get_secret_value()+' api_key=do-not-return')
    task=await drive(worker,service,settings.tenant_id,task['task_id'])
    assert task['status']=='succeeded'
    from fastapi.testclient import TestClient
    from app.main import create_app
    headers={'Authorization':'Bearer '+settings.admin_token.get_secret_value()}
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/v1/tasks/'+task['task_id']+'/events').status_code==401
        replay=client.get('/api/v1/tasks/'+task['task_id']+'/events',headers=headers)
        assert replay.status_code==200 and 'event: completed' in replay.text
        assert settings.admin_token.get_secret_value() not in replay.text
        assert 'do-not-return' not in client.get('/api/v1/tasks/'+task['task_id'],headers=headers).text
        import re
        ids=[int(value) for value in re.findall(r'^id: (\d+)$',replay.text,re.M)]
        assert ids==sorted(set(ids))
        later=client.get('/api/v1/tasks/'+task['task_id']+'/events',headers=headers | {'Last-Event-ID':str(ids[3])})
        assert all(int(value)>ids[3] for value in re.findall(r'^id: (\d+)$',later.text,re.M))
        assert client.get('/api/v1/tasks/'+task['task_id']+'/events',headers=headers | {'Last-Event-ID':'999999'}).status_code==409
