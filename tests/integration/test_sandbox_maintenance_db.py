"""Real attested PG/Redis concurrency; HTTP/Docker are strictly local Stubs."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.tasks import AgentTask, Outbox, TaskApproval
from app.domain.sandbox import SandboxExecution
from app.domain.sandbox_maintenance import (SandboxMaintenance, SandboxMaintenanceAudit,
    SandboxMaintenanceAuthority, SandboxThawGrant)
from app.domain.sandbox_ownership import SandboxRunnerIdentity
from app.sandbox.ownership import provision_identity, OwnershipCoordinator
from app.sandbox.engine import SandboxRunner
from app.schemas.sandbox import SandboxCreate, RunnerDispatch
from app.schemas.tasks import ApprovalDecision
from app.services.sandbox import SandboxService
from app.services.sandbox_maintenance import (provision_maintenance, freeze, seal_freeze,
    require_open, dispatch_window, issue_thaw, thaw, MaintenancePrincipal, public_state)
from app.services.tasks import now
from app.workers.engine import Worker, STREAM, GROUP
from sandbox_database import fresh_database

pytestmark = pytest.mark.integration
DAEMON = 'B1_DOCKER_STUB_ONLY'


@pytest.fixture
async def ctx(request):
    settings = Settings().model_copy(update={'tenant_id': str(uuid4()), 'sandbox_image_id': 'sha256:'+'a'*64})
    c = await fresh_database(request, settings)
    async with c.sessions() as session, session.begin():
        _, (operator, approver) = await provision_maintenance(session, DAEMON)
        runner, proof = await provision_identity(session, DAEMON)
        runner.compatibility_evidence_id, runner.compatibility_cleared_at = uuid4(), now()
        rid = runner.runner_instance_id
    settings = settings.model_copy(update={'sandbox_identity_id': rid,
        'sandbox_identity_generation':1, 'sandbox_identity_proof':proof})
    owner = 'b1-stub-runner-'+uuid4().hex
    coordinator = OwnershipCoordinator(c, settings, owner)
    await coordinator.claim()
    value = SimpleNamespace(c=c, settings=settings, op=operator, approver=approver, rid=rid,
        service=SandboxService(c, settings), co=coordinator, owner=owner)
    try: yield value
    finally: await c.close()  # Schemas/history retained; no rm/drop/delete.


async def open_gate(ctx):
    grant = await issue_thaw(ctx.c, ctx.approver, ctx.op.identity, ctx.rid, 1)
    return await thaw(ctx.c, ctx.op, grant)


async def queued(ctx):
    row = await ctx.service.create(ctx.settings.tenant_id, uuid4(), SandboxCreate(code='print("stub only")'))
    async with ctx.c.sessions() as session, session.begin():
        task = await session.get(AgentTask, UUID(row['task_id']))
        execution = await session.get(SandboxExecution, UUID(row['execution_id']))
        approval = await session.get(TaskApproval, execution.approval_reference)
        task.status, execution.status = 'queued', 'queued'
        approval.status, approval.decided_by = 'approved', 'sandbox-reviewer'
    return row


async def test_install_defaults_closed_and_survives_connections(ctx):
    with pytest.raises(AppError, match='SANDBOX_FROZEN'):
        await ctx.service.create(ctx.settings.tenant_id, uuid4(), SandboxCreate(code='print(1)'))
    assert (await public_state(ctx.c))['state'] == 'FROZEN'
    async with ctx.c.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AgentTask)) == 0
        assert await session.scalar(select(func.count()).select_from(SandboxMaintenanceAudit)) == 1


async def test_authorized_thaw_single_use_and_two_concurrent_operators(ctx):
    grant = await issue_thaw(ctx.c, ctx.approver, ctx.op.identity, ctx.rid, 1)
    results = await asyncio.gather(thaw(ctx.c, ctx.op, grant), thaw(ctx.c, ctx.op, grant), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, AppError) for result in results) == 1
    async with ctx.c.sessions() as session:
        assert (await session.get(SandboxThawGrant, grant)).status == 'USED'
    assert (await public_state(ctx.c))['admission_open'] is True


@pytest.mark.parametrize('fault', ['forged', 'wrong_role', 'expired', 'new_epoch', 'generation', 'daemon', 'evidence', 'revoked_approver', 'wrong_operator'])
async def test_thaw_invalid_authority_and_stale_grants_refused(ctx, fault):
    grant = await issue_thaw(ctx.c, ctx.approver, ctx.op.identity, ctx.rid, 1)
    operator = ctx.op
    if fault == 'forged': operator = MaintenancePrincipal(ctx.op.identity, SecretStr('fake'))
    if fault == 'wrong_role': operator = ctx.approver
    if fault == 'wrong_operator': operator = MaintenancePrincipal(uuid4(), SecretStr('fake'))
    if fault == 'new_epoch': await freeze(ctx.c, ctx.op)
    async with ctx.c.sessions() as session, session.begin():
        if fault == 'expired': (await session.get(SandboxThawGrant, grant)).expires_at = now()-timedelta(seconds=1)
        if fault == 'generation': (await session.get(SandboxRunnerIdentity, ctx.rid)).runner_generation += 1
        if fault == 'daemon': (await session.get(SandboxRunnerIdentity, ctx.rid)).daemon_id = 'wrong'
        if fault == 'evidence': (await session.get(SandboxRunnerIdentity, ctx.rid)).compatibility_evidence_id = uuid4()
        if fault == 'revoked_approver': (await session.get(SandboxMaintenanceAuthority, ctx.approver.identity)).revoked = True
    with pytest.raises(AppError): await thaw(ctx.c, operator, grant)
    assert (await public_state(ctx.c))['admission_open'] is False


async def test_dispatch_freeze_real_pg_competition_is_draining_then_sealed(ctx):
    await open_gate(ctx)
    entered, release = asyncio.Event(), asyncio.Event()
    async def dispatch():
        async with dispatch_window(ctx.c):
            entered.set()
            await release.wait()
    task = asyncio.create_task(dispatch())
    await asyncio.wait_for(entered.wait(), 3)
    try:
        result = await freeze(ctx.c, ctx.op)
        assert result['state'] == 'DRAINING' and not result['dispatch_windows_drained']
        with pytest.raises(AppError, match='SANDBOX_FROZEN'):
            async with dispatch_window(ctx.c): pytest.fail('No new IO window during draining')
    finally:
        release.set(); await task
    result = await seal_freeze(ctx.c, ctx.op)
    assert result['state'] == 'FROZEN' and result['dispatch_windows_drained']
    assert not result['runner_quiescence_proven']


async def test_admission_transaction_and_freeze_compete_on_real_row_lock(ctx):
    await open_gate(ctx)
    admitted, release = asyncio.Event(), asyncio.Event()
    async def submit():
        async with ctx.c.sessions() as session, session.begin():
            await require_open(session)
            admitted.set(); await release.wait()
    first = asyncio.create_task(submit()); await asyncio.wait_for(admitted.wait(), 3)
    freezing = asyncio.create_task(freeze(ctx.c, ctx.op))
    await asyncio.sleep(.1)
    assert not freezing.done()
    release.set(); await first
    assert (await freezing)['state'] == 'FROZEN'


async def test_redis_duplicates_publishing_claim_and_recovery_cannot_bypass(ctx):
    await open_gate(ctx); row = await queued(ctx)
    worker = Worker(ctx.c, ctx.settings); await worker.initialize()
    await freeze(ctx.c, ctx.op)
    for _ in range(2): await ctx.c.redis.xadd(STREAM, {'task_id': row['task_id'], 'outbox_id': str(uuid4())})
    await worker.tick()
    assert not worker.active and await worker.claim(UUID(row['task_id'])) is None
    async with ctx.c.sessions() as session:
        task = await session.get(AgentTask, UUID(row['task_id']))
        assert task.owner is None and task.status == 'queued' and task.attempts == 0
        assert await session.scalar(select(func.count()).select_from(Outbox).where(Outbox.published_at.is_(None))) == 1
    await worker.close()


@pytest.mark.parametrize('status', ['running', 'cancel_requested', 'needs_reconciliation'])
async def test_existing_unknown_cancel_running_and_budgets_untouched(ctx, status):
    await open_gate(ctx); row = await queued(ctx)
    async with ctx.c.sessions() as session, session.begin():
        execution = await session.get(SandboxExecution, UUID(row['execution_id']))
        task = await session.get(AgentTask, UUID(row['task_id']))
        execution.status, execution.cleanup_status, execution.launch_claimed_at = status, 'unconfirmed', now()
        execution.container_id = 'b'*64
        task.status = status
        before = (execution.status, execution.cleanup_status, execution.reserved_cpu_seconds, task.cost_reserved)
    await freeze(ctx.c, ctx.op)
    worker = Worker(ctx.c, ctx.settings); await worker.sweep()
    async with ctx.c.sessions() as session:
        execution = await session.get(SandboxExecution, UUID(row['execution_id'])); task = await session.get(AgentTask, UUID(row['task_id']))
        assert (execution.status, execution.cleanup_status, execution.reserved_cpu_seconds, task.cost_reserved) == before
    grant = await issue_thaw(ctx.c, ctx.approver, ctx.op.identity, ctx.rid, 1)
    with pytest.raises(AppError, match='SANDBOX_HISTORY_UNRESOLVED'): await thaw(ctx.c, ctx.op, grant)


async def test_runner_dispatch_and_api_approval_closed_but_cancel_allowed(ctx):
    await open_gate(ctx); row = await queued(ctx)
    await freeze(ctx.c, ctx.op)
    runner = SandboxRunner(ctx.c, ctx.settings)
    with pytest.raises(AppError, match='SANDBOX_FROZEN'):
        await runner.dispatch(RunnerDispatch(execution_id=row['execution_id'], task_id=row['task_id'], owner='fake', fence=1))
    with pytest.raises(AppError, match='SANDBOX_FROZEN'):
        await ctx.service.decide(UUID(row['execution_id']), ctx.settings.tenant_id,
            ApprovalDecision(decision='approved', operation_hash=row['operation_hash']))
    result = await ctx.service.cancel(UUID(row['execution_id']), ctx.settings.tenant_id)
    assert result['status'] == 'cancelled'


async def test_audit_contains_no_proofs_or_model_issuer(ctx):
    await open_gate(ctx); await freeze(ctx.c, ctx.op)
    async with ctx.c.sessions() as session:
        rows = (await session.scalars(select(SandboxMaintenanceAudit))).all()
        values = str([{name: getattr(row, name) for name in ('id','action','epoch','actor_id','grant_id')} for row in rows])
    assert len(rows) >= 5
    assert all(principal.proof.get_secret_value() not in values for principal in (ctx.op, ctx.approver))
    assert 'Authorization' not in values and 'Issuer' not in values


async def test_missing_schema_control_and_transport_db_failure_are_closed(ctx):
    async with ctx.c.sessions() as session, session.begin():
        await session.execute(text('ALTER TABLE sandbox_maintenance RENAME TO b1_unavailable_state'))
    assert (await public_state(ctx.c))['admission_open'] is False
    with pytest.raises(AppError, match='SANDBOX_MAINTENANCE_UNAVAILABLE'):
        await ctx.service.create(ctx.settings.tenant_id, uuid4(), SandboxCreate(code='print(1)'))


async def test_freeze_competes_with_concurrent_real_submissions(ctx):
    await open_gate(ctx)
    start = asyncio.Event()
    async def submit():
        await start.wait()
        try: return await ctx.service.create(ctx.settings.tenant_id, uuid4(), SandboxCreate(code='print(1)'))
        except AppError as error: return error.code
    tasks = [asyncio.create_task(submit()) for _ in range(8)]
    start.set()
    result = await freeze(ctx.c, ctx.op)
    rows = await asyncio.gather(*tasks)
    assert result['state'] == 'FROZEN'
    assert all(isinstance(row, dict) or row == 'SANDBOX_FROZEN' for row in rows)
    async with ctx.c.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(SandboxExecution)) == sum(isinstance(row,dict) for row in rows)
    with pytest.raises(AppError, match='SANDBOX_FROZEN'):
        await ctx.service.create(ctx.settings.tenant_id, uuid4(), SandboxCreate(code='print(1)'))


@pytest.mark.parametrize('action', ['create','start','inject'])
async def test_actual_dispatch_window_blocks_docker_stub_io_but_owned_cleanup_works(ctx, action):
    from test_sandbox_ownership_db import DockerStub, driver_for, seed
    from app.sandbox.policy import PolicyViolation
    await open_gate(ctx)
    wire = DockerStub(); wire.info = lambda: {'ID': DAEMON}
    eid, container = await seed(ctx, wire)
    await freeze(ctx.c, ctx.op)
    async with ctx.c.sessions() as session:
        operation = (await session.get(SandboxExecution, eid)).operation_hash
    with pytest.raises(AppError, match='SANDBOX_FROZEN'):
        await ctx.co.action(action, eid, container.attrs, operation_hash=operation)
    driver = driver_for(ctx, wire)
    def attempt():
        with driver.dispatch_window():
            pytest.fail('Frozen create/start/inject must not reach Docker IO')
    with pytest.raises(PolicyViolation, match='SANDBOX_MAINTENANCE_BOUNDARY_REFUSED'):
        await asyncio.to_thread(attempt)
    assert wire.mutations == []
    assert await asyncio.to_thread(driver.remove, container) is True
    assert wire.mutations == [('kill', container.id), ('remove', container.id)]


async def test_normal_api_and_model_cannot_access_private_thaw_controls(ctx):
    import httpx
    from app.main import create_app
    app = create_app(ctx.settings, ctx.c);app.state.connections = ctx.c
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        admin = {'Authorization':'Bearer '+ctx.settings.admin_token.get_secret_value()}
        response = await client.post('/api/v1/sandbox/executions', headers={**admin,'Idempotency-Key':str(uuid4())}, json={'code':'print(1)'})
        assert response.status_code == 503 and response.json()['error']['code'] == 'SANDBOX_FROZEN'
        for path in ('/api/v1/sandbox/maintenance/thaw','/api/v1/sandbox/maintenance/issue','/internal/maintenance/thaw'):
            assert (await client.post(path, headers=admin, json={'force':True,'frozen':False})).status_code == 404


async def test_redis_boolean_and_duplicate_recovery_do_not_supply_authority(ctx):
    await ctx.c.redis.set('agentforge:maintenance:state', 'OPEN')
    with pytest.raises(AppError, match='SANDBOX_FROZEN'):
        async with dispatch_window(ctx.c): pytest.fail('Redis is not maintenance authority')


async def test_frozen_sandbox_graph_http_node_never_calls_runner(ctx, monkeypatch):
    import app.services.orchestration.sandbox_graph as module
    await open_gate(ctx);row = await queued(ctx)
    worker = Worker(ctx.c, ctx.settings)
    claim = await worker.claim(UUID(row['task_id']));assert claim is not None
    await freeze(ctx.c, ctx.op)
    class CaptureGraph:
        def __init__(self, *_): self.nodes = {}
        def add_node(self, name, node): self.nodes[name] = node
        def add_edge(self, *_): pass
        def compile(self, **_): return self.nodes
    monkeypatch.setattr(module, 'StateGraph', CaptureGraph)
    async def never_post(*_args, **_kwargs): pytest.fail('No HTTP dispatch is allowed')
    monkeypatch.setattr(module.httpx.AsyncClient, 'post', never_post)
    nodes = module.build_sandbox_graph(ctx.c, ctx.settings, UUID(row['task_id']), ctx.settings.tenant_id, worker.owner, claim[1], None)
    with pytest.raises(AppError, match='SANDBOX_FROZEN'):
        await nodes['sandbox']({'execution_id':row['execution_id']})


async def test_claimed_task_freeze_before_graph_defers_without_losing_reservation(ctx):
    await open_gate(ctx);row = await queued(ctx)
    worker = Worker(ctx.c, ctx.settings)
    claim = await worker.claim(UUID(row['task_id']));assert claim
    await freeze(ctx.c, ctx.op)
    await worker.execute(UUID(row['task_id']), claim[0], claim[1], '0-0')
    async with ctx.c.sessions() as session:
        task = await session.get(AgentTask, UUID(row['task_id']))
        execution = await session.get(SandboxExecution, UUID(row['execution_id']))
        assert task.status == 'queued' and task.owner is None and execution.launch_claimed_at is None
        assert execution.reserved_cpu_seconds > 0


async def test_agent_gateway_cannot_create_sandbox_child_while_frozen(ctx):
    from app.domain.tools import ToolPermission
    from app.services.agent_tools import AgentToolGateway
    await open_gate(ctx);row = await queued(ctx)
    worker = Worker(ctx.c, ctx.settings)
    claim = await worker.claim(UUID(row['task_id']));assert claim
    async with ctx.c.sessions() as session, session.begin():
        session.add(ToolPermission(tenant_id=UUID(ctx.settings.tenant_id), tool='sandbox.execute', resource='python', allowed=True))
    await freeze(ctx.c, ctx.op)
    runtime = SimpleNamespace(task_id=UUID(row['task_id']), tenant_id=ctx.settings.tenant_id, owner=worker.owner, fence=claim[1])
    with pytest.raises(AppError, match='SANDBOX_FROZEN'):
        await AgentToolGateway(ctx.c, ctx.settings).one(runtime, 'coder:0:tool:0',
            {'tool':'sandbox.execute','arguments':{'code':'print(1)','language':'python'}})
    async with ctx.c.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(SandboxExecution)) == 1


async def test_unauthorized_freeze_does_not_change_open_gate_and_is_audited(ctx):
    await open_gate(ctx)
    with pytest.raises(AppError): await freeze(ctx.c, ctx.approver)
    assert (await public_state(ctx.c))['admission_open']
    async with ctx.c.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(SandboxMaintenanceAudit).where(SandboxMaintenanceAudit.action=='FREEZE_REFUSED')) == 1


@pytest.mark.parametrize('fault', ['trigger_disabled','constraint_missing','unreviewed_revision'])
async def test_additive_revision_does_not_bypass_permit_schema_safety(ctx, fault):
    from app.services.execution_permits import PermitService
    service = PermitService(ctx.c, ctx.settings)
    await service.require_schema()  # Real migrated 0010 retains all 0008 guards.
    async with ctx.c.sessions() as session, session.begin():
        if fault == 'trigger_disabled': await session.execute(text('ALTER TABLE execution_permits DISABLE TRIGGER execution_permit_guard'))
        if fault == 'constraint_missing': await session.execute(text('ALTER TABLE execution_permits DROP CONSTRAINT ck_permit_counts'))
        if fault == 'unreviewed_revision': await session.execute(text("UPDATE alembic_version SET version_num='unreviewed_b1_fixture'"))
    with pytest.raises(AppError, match='PERMIT_MIGRATION_REQUIRED'): await service.require_schema()
    async with ctx.c.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(SandboxMaintenanceAudit)) == 1
