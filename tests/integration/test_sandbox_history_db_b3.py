"""Actual attested PG/Redis; the Runner/Docker boundary remains a Stub."""
import asyncio
from datetime import timedelta
from uuid import UUID,uuid4
import pytest
from sqlalchemy import func,select
from app.core.errors import AppError
from app.domain.tasks import AgentTask,Outbox,TaskEvent
from app.domain.sandbox import SandboxExecution
from app.domain.sandbox_ownership import SandboxOwnership
from app.sandbox.engine import SandboxRunner
from app.sandbox.history import review_metadata
from app.schemas.sandbox import RunnerDispatch
from app.schemas.tasks import ApprovalDecision
from app.services.sandbox_maintenance import freeze,issue_thaw,thaw
from app.services.tasks import now
from app.workers.engine import Worker,STREAM
from test_sandbox_maintenance_db import ctx,open_gate,queued

pytestmark=pytest.mark.integration


async def legacy(ctx,status,cid=None):
    row=await queued(ctx)
    async with ctx.c.sessions() as session,session.begin():
        execution=await session.get(SandboxExecution,UUID(row['execution_id']))
        execution.launch_claimed_at=now()-timedelta(days=1)
        execution.status=status;execution.container_id=cid
        execution.cleanup_status='removed' if cid else 'not_created'
        execution.runner_owner='legacy-unverified-owner'
        task=await session.get(AgentTask,execution.task_id)
        task.deadline=now()-timedelta(seconds=2)  # Sweep must not rewrite history.
    return row


async def facts(ctx,rows):
    async with ctx.c.sessions() as session:
        output=[]
        for item in rows:
            row=await session.get(SandboxExecution,UUID(item['execution_id']))
            task=await session.get(AgentTask,row.task_id)
            output.append((review_metadata(row),str(row.reserved_cpu_seconds),task.status,task.owner,task.fence,
                await session.scalar(select(func.count()).select_from(TaskEvent).where(TaskEvent.task_id==task.id)),
                await session.scalar(select(func.count()).select_from(Outbox).where(Outbox.task_id==task.id,Outbox.published_at.is_(None)))))
        return output


async def test_fourteen_plus_one_stay_immutable_through_publish_duplicate_messages_and_recovery(ctx):
    await open_gate(ctx)
    rows=[await legacy(ctx,'needs_reconciliation',str(i+1).zfill(64)) for i in range(14)]
    rows.append(await legacy(ctx,'failed'))
    before=await facts(ctx,rows)
    worker=Worker(ctx.c,ctx.settings);await worker.initialize()
    try:
        size=await ctx.c.redis.xlen(STREAM)
        await worker.publish();assert await ctx.c.redis.xlen(STREAM)==size
        for _ in range(2):
            for row in rows:await ctx.c.redis.xadd(STREAM,{'task_id':row['task_id'],'outbox_id':str(uuid4())})
        results=await asyncio.gather(*(worker.claim(UUID(row['task_id'])) for row in rows for _ in range(2)))
        assert all(r is None for r in results)
        await worker.sweep();await worker.tick()
        for row in rows:
            await worker.execute(UUID(row['task_id']),ctx.settings.tenant_id,1,'0-0')
        assert await facts(ctx,rows)==before
        async with ctx.c.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(SandboxOwnership))==0
    finally:await worker.close()


@pytest.mark.parametrize('status,cid',[('needs_reconciliation','a'*64),('failed',None)])
async def test_dispatch_and_ownership_refuse_legacy_even_with_new_approval(ctx,status,cid):
    await open_gate(ctx);row=await legacy(ctx,status,cid);before=await facts(ctx,[row])
    runner=SandboxRunner(ctx.c,ctx.settings,driver=object())  # Any SDK call would fail.
    with pytest.raises(AppError,match='SANDBOX_HISTORY_QUARANTINED'):
        await runner.dispatch(RunnerDispatch(task_id=UUID(row['task_id']),execution_id=UUID(row['execution_id']),owner='fake',fence=1))
    async with ctx.c.sessions() as session,session.begin():
        execution=await session.get(SandboxExecution,UUID(row['execution_id']))
        with pytest.raises(AppError,match='SANDBOX_HISTORY_QUARANTINED'):await ctx.co.issue(session,execution)
    with pytest.raises(AppError,match='SANDBOX_HISTORY_QUARANTINED'):
        await ctx.service.decide(UUID(row['execution_id']),ctx.settings.tenant_id,ApprovalDecision(decision='approved',operation_hash=row['operation_hash']))
    assert await facts(ctx,[row])==before


async def test_missing_container_id_intent_alone_blocks_thaw_without_rewriting_failure(ctx):
    await open_gate(ctx);row=await legacy(ctx,'failed');before=await facts(ctx,[row])
    await freeze(ctx.c,ctx.op)
    grant=await issue_thaw(ctx.c,ctx.approver,ctx.op.identity,ctx.rid,1)
    with pytest.raises(AppError,match='SANDBOX_HISTORY_UNRESOLVED'):await thaw(ctx.c,ctx.op,grant)
    assert await facts(ctx,[row])==before


async def test_worker_cannot_reclaim_new_unknown_boundary(ctx):
    await open_gate(ctx);row=await queued(ctx)
    async with ctx.c.sessions() as session,session.begin():
        task=await session.get(AgentTask,UUID(row['task_id']));task.owner='stub-owner';task.fence=1
        execution=await session.get(SandboxExecution,UUID(row['execution_id']))
        await ctx.co.issue(session,execution)
        owned=await session.get(SandboxOwnership,execution.id);owned.state='UNKNOWN'
        execution.launch_claimed_at=now();task.owner=None
    worker=Worker(ctx.c,ctx.settings);await worker.initialize()
    try:
        assert await worker.claim(UUID(row['task_id'])) is None
        async with ctx.c.sessions() as session:assert (await session.get(SandboxOwnership,UUID(row['execution_id']))).state=='UNKNOWN'
    finally:await worker.close()


async def test_fresh_launch_commits_ownership_and_launch_intent_together(ctx,monkeypatch):
    await open_gate(ctx);row=await queued(ctx)
    async with ctx.c.sessions() as session,session.begin():
        task=await session.get(AgentTask,UUID(row['task_id']))
        task.owner='b3-worker';task.fence=1;task.status='running';task.lease_until=now()+timedelta(seconds=30)
    runner=SandboxRunner(ctx.c,ctx.settings,driver=object())
    runner.owner=ctx.owner;runner.ownership=ctx.co;runner.blocked=False
    observed=[]
    async def fake_run(request,inputs,stop):
        async with ctx.c.sessions() as session:
            execution=await session.get(SandboxExecution,request.execution_id)
            owned=await session.get(SandboxOwnership,request.execution_id)
            observed.append(bool(execution.launch_claimed_at and owned and owned.state=='INTENT'))
    monkeypatch.setattr(runner,'_run',fake_run)
    await runner.dispatch(RunnerDispatch(task_id=UUID(row['task_id']),execution_id=UUID(row['execution_id']),owner='b3-worker',fence=1))
    await asyncio.gather(*list(runner.active.values()))
    assert observed==[True]


async def test_late_finish_and_heartbeat_cannot_rewrite_unowned_history(ctx):
    await open_gate(ctx);row=await legacy(ctx,'failed')
    worker=Worker(ctx.c,ctx.settings);await worker.initialize()
    try:
        async with ctx.c.sessions() as session,session.begin():
            task=await session.get(AgentTask,UUID(row['task_id']));task.owner=worker.owner;task.fence=1;task.status='running'
        before=await facts(ctx,[row])
        await worker.heartbeat();await worker.finish(UUID(row['task_id']),1,error='FORGED_RETRY_RESULT')
        assert await facts(ctx,[row])==before
    finally:await worker.close()
