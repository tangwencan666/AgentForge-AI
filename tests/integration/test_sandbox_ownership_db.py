"""S3A: real isolated PostgreSQL transactions, Docker API entirely in memory.

No real Runner process or Docker SDK client is created by this module. The S1
resource proof/lease is required before migrations or business writes occur.
"""
import asyncio
from copy import deepcopy
from datetime import timedelta
import os
from types import SimpleNamespace
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from docker.errors import NotFound
import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from app.core.config import Settings
from app.domain.sandbox import SandboxExecution
from app.domain.tasks import AgentTask, TaskApproval
from app.domain.sandbox_ownership import SandboxOwnership, SandboxOwnershipAudit, SandboxRunnerIdentity
from app.repositories.connections import Connections
from app.sandbox.driver import DockerDriver
from app.sandbox.engine import SandboxRunner
from app.sandbox.ownership import (OwnershipCoordinator, ThreadAuthority, PREFIX, provision_identity,
                                   labels, Scope)
from app.sandbox.policy import PolicyViolation, create_options
from app.schemas.sandbox import SandboxCreate, ResourceLimits, POLICY_VERSION
from app.services.sandbox import SandboxService
from app.services.tasks import now
from sandbox_database import fresh_database, migrate
from app.services.sandbox_maintenance import provision_maintenance, issue_thaw, thaw

pytestmark = pytest.mark.integration
IMAGE = 'sha256:' + 'a' * 64
DAEMON = 'S3A_IN_MEMORY_DAEMON_ONLY'


@pytest.fixture(scope='module')
async def owned_database():
    if os.environ.get('AGENTFORGE_RUN_INTEGRATION') != '1':
        pytest.skip('Requires attested disposable PostgreSQL/Redis, not the main database')
    # Isolated new stack only: exercise empty additive upgrade/downgrade before
    # any identity/history exists. Never run this fixture against main settings.
    await asyncio.to_thread(command.upgrade, Config('backend/alembic.ini'), '0008_execution_permits')
    connections = Connections(Settings())
    async with connections.engine.connect() as conn:
        before = (await conn.execute(text('SELECT role, enabled, version FROM model_slots ORDER BY role'))).all()
    await asyncio.to_thread(command.upgrade, Config('backend/alembic.ini'), '0009_sandbox_ownership')
    await asyncio.to_thread(command.downgrade, Config('backend/alembic.ini'), '0008_execution_permits')
    async with connections.engine.connect() as conn:
        assert (await conn.execute(text('SELECT role, enabled, version FROM model_slots ORDER BY role'))).all() == before
    await asyncio.to_thread(command.upgrade, Config('backend/alembic.ini'), '0009_sandbox_ownership')
    await connections.close()
    yield


@pytest.fixture
async def context(owned_database, request):
    settings = Settings().model_copy(update={'sandbox_image_id': IMAGE, 'tenant_id': str(uuid4())})
    c = await fresh_database(request, settings)
    async with c.sessions() as session, session.begin():
        identity, proof = await provision_identity(session, DAEMON)
        # Explicit TEST-ONLY stand-in for independently reviewed deployment
        # clearance. No production issuance endpoint or config flag exists.
        identity.compatibility_evidence_id, identity.compatibility_cleared_at = uuid4(), now()
        identity_id = identity.runner_instance_id
        _, (operator, approver) = await provision_maintenance(session, DAEMON)
    settings = settings.model_copy(update={'sandbox_identity_id': identity_id,
        'sandbox_identity_generation': 1, 'sandbox_identity_proof': proof})
    owner = 'runner-' + uuid4().hex
    coordinator = OwnershipCoordinator(c, settings, owner)
    grant = await issue_thaw(c, approver, operator.identity, identity_id, 1)
    await thaw(c, operator, grant)
    await coordinator.claim()
    value = SimpleNamespace(c=c, settings=settings, co=coordinator, owner=owner)
    try:
        yield value
    finally:
        # Only our generated test tenant: no real containers or code ever ran.
        # Stop synthetic leases from occupying subsequent Worker capacity. Keep
        # ALL ownership/unknown/budget/audit records; this is not a production
        # recovery rule and must never be copied to real-execution cleanup.
        async with c.sessions() as session, session.begin():
            tasks = list((await session.scalars(select(AgentTask).where(
                AgentTask.tenant_id == UUID(settings.tenant_id)))).all())
            for task in tasks:
                task.owner, task.lease_until = None, None
                if task.status not in {'failed', 'cancelled', 'succeeded', 'needs_reconciliation'}:
                    task.status, task.error_code = 'failed', 'S3A_STUB_TEST_FINISHED'
        await c.close()


class Container:
    def __init__(self, attrs, client):
        self.attrs, self.client = attrs, client
        self.id, self.name = attrs['Id'], attrs['Name'].lstrip('/')
        self.removed = False

    @property
    def labels(self):
        return self.attrs['Config']['Labels']

    def reload(self):
        if self.removed:
            raise NotFound('Stub: immutable container absent')

    def kill(self):
        self.client.mutations.append(('kill', self.id))
        self.attrs['State']['Running'] = False

    def remove(self, **kwargs):
        if self.client.fail_remove:
            raise OSError('synthetic diagnostic must never escape')
        self.client.mutations.append(('remove', self.id))
        self.removed = True


class DockerStub:
    def __init__(self):
        self.items, self.mutations, self.queries = [], [], []
        self.containers = self
        self.fail_remove = self.unavailable = False

    def info(self):
        if self.unavailable:
            raise OSError('Stub: daemon unavailable')
        return {'ID': DAEMON}

    def list(self, *, all, filters):
        self.queries.append(filters)
        return [c for c in self.items if not c.removed and all_labels(c, filters['label'])]

    def get(self, cid):
        for container in self.items:
            if container.id == cid and not container.removed:
                return container
        raise NotFound('Stub: immutable container absent')


def all_labels(container, wanted):
    return all(container.labels.get(key) == value for key, value in (item.split('=', 1) for item in wanted))


def driver_for(ctx, stub):
    driver = DockerDriver(IMAGE, client=stub, authority=ThreadAuthority(ctx.co, asyncio.get_running_loop()))
    driver.health = lambda: True  # Explicitly isolate ownership from image/platform diagnostics.
    return driver


async def seed(ctx, stub):
    row = await SandboxService(ctx.c, ctx.settings).create(ctx.settings.tenant_id, uuid4(), SandboxCreate(code='print(1)'))
    eid = UUID(row['execution_id'])
    async with ctx.c.sessions() as session, session.begin():
        execution = await session.get(SandboxExecution, eid)
        task = await session.get(AgentTask, execution.task_id)
        task.owner, task.fence = 's3a-worker-' + uuid4().hex, 1
        task.status, task.lease_until = 'running', now() + timedelta(seconds=60)
        approval = await session.get(TaskApproval, execution.approval_reference)
        approval.status, approval.decided_by = 'approved', 'sandbox-reviewer'
        await ctx.co.issue(session, execution)
        execution.status, execution.launch_claimed_at = 'starting', now()
        execution.runner_owner, execution.runner_lease_until = ctx.owner, now() + timedelta(seconds=30)
    ownership = await ctx.co.action('create', eid, operation_hash=row['operation_hash'])
    opts = create_options(IMAGE, eid, ResourceLimits().model_dump())
    opts['labels'].update(ownership)
    attrs = {'Id': uuid4().hex + uuid4().hex, 'Name': '/' + opts['name'], 'Image': IMAGE, 'Mounts': [],
        'Config': {'User': opts['user'], 'Cmd': opts['command'], 'Entrypoint': [], 'Labels': opts['labels']},
        'State': {'Running': True}, 'HostConfig': {'NetworkMode': 'none', 'Privileged': False,
        'ReadonlyRootfs': True, 'CapDrop': ['ALL'], 'CapAdd': [], 'SecurityOpt': opts['security_opt'],
        'NanoCpus': opts['nano_cpus'], 'Memory': opts['mem_limit'], 'MemorySwap': opts['memswap_limit'],
        'PidsLimit': opts['pids_limit'], 'Binds': [], 'Mounts': [], 'Devices': [], 'IpcMode': 'private',
        'LogConfig': opts['log_config'], 'Tmpfs': opts['tmpfs']}}
    await ctx.co.action('bind', eid, attrs)
    async with ctx.c.sessions() as session, session.begin():
        execution = await session.get(SandboxExecution, eid)
        execution.container_id = attrs['Id']
    container = Container(attrs, stub)
    stub.items.append(container)
    return eid, container


async def test_exact_owned_container_cleanup_and_audit(context):
    wire = DockerStub(); eid, container = await seed(context, wire)
    driver = driver_for(context, wire)
    assert await asyncio.to_thread(driver.owned) == [container]
    assert await asyncio.to_thread(driver.remove, container)
    async with context.c.sessions() as session:
        assert (await session.get(SandboxOwnership, eid)).state == 'REMOVED'
        actions = list((await session.scalars(select(SandboxOwnershipAudit.action).where(
            SandboxOwnershipAudit.execution_id == eid))).all())
        assert actions == ['INTENT_COMMITTED', 'CREATE', 'BIND', 'STOP', 'REMOVE', 'REMOVED']


@pytest.mark.parametrize('field', ['project_id', 'runner_instance_id', 'runner_generation',
    'sandbox_namespace', 'task_id', 'execution_id', 'ownership_protocol_version', 'created_at', 'policy_version'])
async def test_forged_labels_never_authorize_cleanup(context, field):
    wire = DockerStub(); _, container = await seed(context, wire)
    container.labels[PREFIX + field] = str(uuid4()) if field.endswith('_id') else 'forged'
    with pytest.raises((PolicyViolation, ValueError)):
        await asyncio.to_thread(driver_for(context, wire).remove, container)
    assert wire.mutations == [] and not container.removed


@pytest.mark.parametrize('fault', ['missing_record', 'missing_labels', 'wrong_id', 'execution_id_mismatch', 'generation', 'retired', 'expired'])
async def test_durable_mismatch_fails_closed(context, fault):
    wire = DockerStub(); eid, container = await seed(context, wire)
    async with context.c.sessions() as session, session.begin():
        if fault == 'missing_record':
            await session.execute(delete(SandboxOwnership).where(SandboxOwnership.execution_id == eid))
        elif fault == 'missing_labels':
            container.attrs['Config']['Labels'] = {}
        elif fault == 'wrong_id':
            container.id = container.attrs['Id'] = 'b' * 64
        elif fault == 'execution_id_mismatch':
            (await session.get(SandboxExecution, eid)).container_id = 'b' * 64
        else:
            identity = await session.get(SandboxRunnerIdentity, context.co.scope.runner_instance_id)
            if fault == 'generation': identity.runner_generation += 1
            if fault == 'retired': identity.retired = True
            if fault == 'expired': identity.lease_until = now() - timedelta(seconds=1)
    with pytest.raises((PolicyViolation, ValueError)):
        await asyncio.to_thread(driver_for(context, wire).remove, container)
    assert wire.mutations == []


async def test_concurrent_registration_claim_only_one_process(context):
    await context.co.release()
    contenders = [OwnershipCoordinator(context.c, context.settings, 'runner-' + uuid4().hex) for _ in range(2)]
    results = await asyncio.gather(*(candidate.claim() for candidate in contenders), return_exceptions=True)
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, PolicyViolation) for result in results) == 1


async def test_restart_recovers_same_durable_identity_but_fences_old_owner(context):
    wire = DockerStub(); eid, container = await seed(context, wire)
    await context.co.release()
    recovered = OwnershipCoordinator(context.c, context.settings, 'runner-' + uuid4().hex)
    await recovered.claim()
    assert recovered.scope == context.co.scope
    with pytest.raises(PolicyViolation):
        await asyncio.to_thread(driver_for(context, wire).remove, container)
    replacement = SimpleNamespace(**{**vars(context), 'co': recovered})
    assert await asyncio.to_thread(driver_for(replacement, wire).remove, container)
    with pytest.raises(PolicyViolation):
        await recovered.action('create', eid)


async def test_two_runners_concurrent_reconcile_ignore_foreign_containers(context):
    wire = DockerStub(); eid_a, a = await seed(context, wire)
    async with context.c.sessions() as session, session.begin():
        identity, proof = await provision_identity(session, DAEMON, project_id=context.co.scope.project_id)
        identity.compatibility_evidence_id, identity.compatibility_cleared_at = uuid4(), now()
        settings = context.settings.model_copy(update={'sandbox_identity_id': identity.runner_instance_id, 'sandbox_identity_proof': proof})
    other = SimpleNamespace(c=context.c, settings=settings, owner='runner-' + uuid4().hex)
    other.co = OwnershipCoordinator(other.c, settings, other.owner)
    await other.co.claim()
    eid_b, b = await seed(other, wire)
    async with context.c.sessions() as session, session.begin():
        for eid in (eid_a, eid_b):
            (await session.get(SandboxExecution, eid)).runner_lease_until = now() - timedelta(seconds=1)
    runners = []
    for ctx in (context, other):
        runner = SandboxRunner(ctx.c, ctx.settings, driver=driver_for(ctx, wire))
        runner.owner, runner.ownership = ctx.owner, ctx.co
        runners.append(runner)
    await asyncio.gather(*(runner.reconcile() for runner in runners))
    assert a.removed and b.removed and not any(runner.blocked for runner in runners)
    assert sorted(wire.mutations) == sorted([('kill', a.id), ('remove', a.id), ('kill', b.id), ('remove', b.id)])
    assert len(wire.queries) == 2 and wire.queries[0] != wire.queries[1]


async def test_unregistered_or_uncleared_runner_never_discovers_docker(context):
    wire = DockerStub()
    for settings in (context.settings.model_copy(update={'sandbox_identity_id': None}), context.settings):
        if settings.sandbox_identity_id:
            async with context.c.sessions() as session, session.begin():
                identity = await session.get(SandboxRunnerIdentity, settings.sandbox_identity_id)
                identity.compatibility_cleared_at = None
        runner = SandboxRunner(context.c, settings, driver=driver_for(context, wire))
        await runner.start()
        assert runner.blocked
    assert wire.queries == wire.mutations == []


async def test_cleanup_error_and_daemon_unavailable_never_expand_scope(context):
    wire = DockerStub(); eid, container = await seed(context, wire)
    driver = driver_for(context, wire)
    wire.fail_remove = True
    with pytest.raises(OSError):
        await asyncio.to_thread(driver.remove, container)
    assert wire.mutations == [('kill', container.id)] and not wire.queries
    wire.unavailable = True
    with pytest.raises(OSError):
        await asyncio.to_thread(driver.absence, eid, container.id)
    assert wire.mutations == [('kill', container.id)]


async def test_unknown_create_never_resets_or_uses_name_lookup(context):
    wire = DockerStub(); eid, container = await seed(context, wire)
    await context.co.action('unknown', eid)
    with pytest.raises(PolicyViolation):
        await context.co.action('create', eid)
    assert await asyncio.to_thread(driver_for(context, wire).absence, eid, None) is False
    assert wire.mutations == wire.queries == []


async def test_downgrade_refuses_to_erase_ownership_history(context):
    with pytest.raises(DBAPIError):
        await migrate(context.c, '0008_execution_permits', downgrade=True)
    async with context.c.engine.connect() as conn:
        assert await conn.scalar(text('SELECT version_num FROM alembic_version')) == '0010_sandbox_maintenance'


@pytest.mark.parametrize('fault', ['approval', 'worker_fence', 'cancelled', 'code_hash', 'image', 'budget'])
async def test_injection_revalidates_p3_approval_fence_and_limits(context, fault):
    from app.core.errors import AppError
    wire = DockerStub(); eid, container = await seed(context, wire)
    async with context.c.sessions() as session, session.begin():
        execution = await session.get(SandboxExecution, eid)
        if fault == 'approval': (await session.get(TaskApproval, execution.approval_reference)).status = 'rejected'
        if fault == 'worker_fence': (await session.get(AgentTask, execution.task_id)).fence += 1
        if fault == 'cancelled': (await session.get(AgentTask, execution.task_id)).status = 'cancelled'
        if fault == 'code_hash': execution.code_hash = '0' * 64
        if fault == 'image': execution.image_id = 'sha256:' + 'b' * 64
        if fault == 'budget': execution.reserved_cpu_seconds = 0
    with pytest.raises((PolicyViolation, AppError)):
        async with context.c.sessions() as session:
            op_hash = (await session.get(SandboxExecution, eid)).operation_hash
        await context.co.action('inject', eid, container.attrs, operation_hash=op_hash)
    assert wire.mutations == []
    async with context.c.sessions() as session:
        assert 'BOUNDARY_REFUSED' in list((await session.scalars(select(SandboxOwnershipAudit.action).where(
            SandboxOwnershipAudit.execution_id == eid))).all())


async def test_cancel_can_still_cleanup_exact_resource_without_new_execution(context):
    wire = DockerStub(); eid, container = await seed(context, wire)
    async with context.c.sessions() as session, session.begin():
        execution = await session.get(SandboxExecution, eid)
        (await session.get(AgentTask, execution.task_id)).status = 'cancelled'
        (await session.get(TaskApproval, execution.approval_reference)).status = 'rejected'
    assert await asyncio.to_thread(driver_for(context, wire).remove, container)


async def test_missing_discovered_record_blocks_without_removal(context):
    wire = DockerStub(); eid, container = await seed(context, wire)
    async with context.c.sessions() as session, session.begin():
        await session.execute(delete(SandboxOwnership).where(SandboxOwnership.execution_id == eid))
    runner = SandboxRunner(context.c, context.settings, driver=driver_for(context, wire))
    runner.owner, runner.ownership = context.owner, context.co
    await runner.reconcile()
    assert runner.blocked and wire.mutations == [] and not container.removed


async def test_new_generation_does_not_discover_old_resources(context):
    wire = DockerStub(); _, container = await seed(context, wire)
    await context.co.release()
    async with context.c.sessions() as session, session.begin():
        identity = await session.get(SandboxRunnerIdentity, context.co.scope.runner_instance_id)
        identity.runner_generation += 1
    other = OwnershipCoordinator(context.c, context.settings.model_copy(update={'sandbox_identity_generation': 2}), 'runner-' + uuid4().hex)
    await other.claim()
    replacement = SimpleNamespace(**{**vars(context), 'co': other})
    assert await asyncio.to_thread(driver_for(replacement, wire).owned) == []
    with pytest.raises(PolicyViolation):
        await asyncio.to_thread(driver_for(replacement, wire).remove, container)
    assert wire.mutations == []

    stale_restart = OwnershipCoordinator(context.c, context.settings, 'runner-' + uuid4().hex)
    with pytest.raises(PolicyViolation, match='GENERATION_CHANGED'):
        await stale_restart.claim()


async def test_daemon_mismatch_rejects_before_resource_access(context):
    wire = DockerStub(); _, container = await seed(context, wire)
    wire.info = lambda: {'ID': 'FOREIGN_STUB_DAEMON'}
    with pytest.raises(PolicyViolation):
        await asyncio.to_thread(driver_for(context, wire).remove, container)
    assert wire.queries == wire.mutations == []


async def test_provisioning_defaults_blocked_and_wrong_proof_fails(context):
    from pydantic import SecretStr
    async with context.c.sessions() as session, session.begin():
        identity, proof = await provision_identity(session, DAEMON)
        settings = context.settings.model_copy(update={'sandbox_identity_id': identity.runner_instance_id, 'sandbox_identity_proof': proof})
        assert identity.compatibility_evidence_id is None and identity.compatibility_cleared_at is None
    with pytest.raises(PolicyViolation, match='COMPATIBILITY_BLOCKED'):
        await OwnershipCoordinator(context.c, settings, 'runner-stub').claim()
    with pytest.raises(PolicyViolation, match='IDENTITY_INVALID'):
        await OwnershipCoordinator(context.c, settings.model_copy(update={'sandbox_identity_proof': SecretStr('test-only-invalid-proof')}), 'runner-stub').claim()


async def test_refusal_audit_does_not_include_proof_or_docker_error(context):
    import json
    wire = DockerStub(); eid, container = await seed(context, wire)
    container.attrs['Config']['Labels'][PREFIX + 'project_id'] = str(uuid4())
    with pytest.raises(PolicyViolation):
        await asyncio.to_thread(driver_for(context, wire).remove, container)
    async with context.c.sessions() as session:
        resources = list((await session.scalars(select(SandboxOwnershipAudit.resource).where(
            SandboxOwnershipAudit.execution_id == eid))).all())
    serialized = json.dumps(resources)
    assert context.settings.sandbox_identity_proof.get_secret_value() not in serialized
    assert 'synthetic diagnostic' not in serialized


async def test_foreign_recovery_cannot_modify_business_state(context):
    wire = DockerStub(); eid, container = await seed(context, wire)
    async with context.c.sessions() as session, session.begin():
        identity, proof = await provision_identity(session, DAEMON)
        identity.compatibility_evidence_id, identity.compatibility_cleared_at = uuid4(), now()
        settings = context.settings.model_copy(update={'sandbox_identity_id': identity.runner_instance_id,
            'sandbox_identity_proof': proof})
    foreign = OwnershipCoordinator(context.c, settings, 'runner-' + uuid4().hex)
    await foreign.claim()
    runner = SandboxRunner(context.c, settings, driver=driver_for(context, wire))
    runner.ownership = foreign
    await runner._mark_uncertain(eid)
    async with context.c.sessions() as session:
        assert (await session.get(SandboxExecution, eid)).status == 'starting'
    assert runner.blocked and wire.mutations == [] and not container.removed


async def test_input_digest_cannot_substitute_unapproved_code(context):
    wire = DockerStub(); eid, container = await seed(context, wire)
    for action in ('create', 'start', 'inject'):
        with pytest.raises(PolicyViolation, match='INPUT_MISMATCH'):
            await context.co.action(action, eid, container.attrs, operation_hash='0' * 64)
    assert wire.mutations == []


async def test_old_unlaunched_execution_is_not_automatically_adopted(context):
    dto = await SandboxService(context.c, context.settings).create(
        context.settings.tenant_id, uuid4(), SandboxCreate(code='print(1)'))
    eid = UUID(dto['execution_id'])
    async with context.c.sessions() as session, session.begin():
        row = await session.get(SandboxExecution, eid)
        identity = await session.get(SandboxRunnerIdentity, context.co.scope.runner_instance_id)
        row.created_at = identity.created_at - timedelta(seconds=1)
        with pytest.raises(PolicyViolation, match='LEGACY_EXECUTION_NOT_ADOPTED'):
            await context.co.issue(session, row)
        assert await session.get(SandboxOwnership, eid) is None
