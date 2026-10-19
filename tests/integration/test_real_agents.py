"""Real PG/Redis/LangGraph and explicit provider Stub: NOT external API acceptance."""
import asyncio
import json
import os
from datetime import timedelta
from uuid import UUID, uuid4
from decimal import Decimal
import pytest
from sqlalchemy import delete, select
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.entities import ModelSlot
from app.domain.tasks import AgentTask, ModelOperation, TaskEvent
from app.domain.real import AgentToolOperation, RealDailyUsage
from app.domain.tools import ToolPermission, ToolCall, CapabilityApproval, CapabilityAudit, ManagedNote, ToolDailyUsage
from app.providers.base import ModelReply, ProviderFailure
from app.providers.router import ModelRouter
from app.repositories.connections import Connections
from app.schemas.tasks import TaskCreate, ApprovalDecision
from app.schemas.tools import CapabilityDecision, PermissionUpdate
from app.services.tasks import TaskService, TERMINAL, now
from app.services.tool_gateway import ToolGateway
from app.workers.engine import Worker

pytestmark = pytest.mark.integration


class ProviderStub:
    calls = []
    failure = None
    fail_count = 0
    usage_missing = False
    delay = .04
    revision_rounds = 0
    proposed_tool = None
    dependency = 'independent'
    malformed = False
    fail_role = None

    async def complete(self, config, messages, credential, delta):
        assert credential == 'explicit-provider-stub-only-value'
        role = config['model'].removeprefix('stub-')
        context = json.loads(messages[-1]['content'])
        self.calls.append((role, now(), context))
        await asyncio.sleep(self.delay)
        if self.failure and self.fail_count > 0 and (self.fail_role is None or self.fail_role == role):
            type(self).fail_count -= 1
            raise ProviderFailure(self.failure, self.failure in {'MODEL_RATE_LIMIT', 'MODEL_TIMEOUT', 'MODEL_SERVER_ERROR'}, 429)
        if role == 'planner':
            data = {'nodes': [{'id': 'coder', 'role': 'coder', 'instruction': 'analyze task', 'depends_on': ['researcher'] if self.dependency == 'research_first' else []},
                              {'id': 'researcher', 'role': 'researcher', 'instruction': 'analyze evidence', 'depends_on': ['coder'] if self.dependency == 'code_first' else []}]}
        elif role == 'reviewer':
            data = {'summary': 'Explicit Stub review, no external provider was contacted', 'needs_revision': context['round'] < self.revision_rounds, 'conflicts': []}
        else:
            data = {'summary': 'Explicit provider Stub ' + role, 'tools': [self.proposed_tool] if role == 'coder' and self.proposed_tool else []}
        text = json.dumps(data) if 'schema:' in messages[0]['content'] else 'Explicit provider Stub chat\ncomplete'
        if self.malformed: text = 'invalid structured output'
        await delta(text[:8]); await delta(text[8:])
        return ModelReply(text, None if self.usage_missing else 100, None if self.usage_missing else 30,
                          None if self.usage_missing else 130, 10, 40)


@pytest.fixture
async def setup(monkeypatch):
    # Legacy multi-role graph/budget regression uses explicit authorization AND provider doubles.
    # No real adapter has a DispatchLease here; the production HTTP permit guard remains intact.
    from app.services.orchestration.real_runtime import RealRuntime
    monkeypatch.setattr(TaskService, 'require_real_permit', lambda self: None)
    monkeypatch.setattr(RealRuntime, 'require_real_permit', lambda self: None)
    monkeypatch.setattr('app.workers.engine.require_permit_task', lambda task: None)
    if os.environ.get('AGENTFORGE_RUN_INTEGRATION') != '1': pytest.skip('Real project PostgreSQL/Redis opt-in required')
    monkeypatch.setenv('AGENTFORGE_MODEL_P5_STUB_KEY', 'explicit-provider-stub-only-value')
    monkeypatch.setattr(ModelRouter, 'adapters', {'openai_compatible': ProviderStub})
    for key, value in {'calls': [], 'failure': None, 'fail_count': 0, 'usage_missing': False, 'delay': .04,
                       'revision_rounds': 0, 'proposed_tool': None, 'dependency': 'independent', 'malformed': False, 'fail_role': None}.items():
        setattr(ProviderStub, key, value)
    price = {'input_per_million': '1', 'output_per_million': '2', 'input_upper_bound': 8192, 'output_upper_bound': 1024, 'version': 'explicit-stub-price-v1'}
    settings = Settings().model_copy(update={'tenant_id': str(uuid4()), 'real_calls_enabled': True,
        'real_max_retries': 2,
        'allowed_model_hosts': 'api.openai.com',  # Explicit Stub policy, independent of the operator's live host list.
        'real_daily_budget_usd': Decimal('1'), 'real_daily_token_limit': 100000,
        'model_credential_hosts': {'AGENTFORGE_MODEL_P5_STUB_KEY': ['api.openai.com']},
        'model_prices': {'openai_compatible/stub-' + role: price for role in ('planner','coder','researcher','reviewer')}})
    connections = Connections(settings)
    async with connections.sessions() as session, session.begin():
        for role in ('planner','coder','researcher','reviewer'):
            session.add(ModelSlot(tenant_id=UUID(settings.tenant_id), role=role, provider='openai_compatible', base_url='https://api.openai.com/v1',
                model='stub-' + role, credential_reference='env:AGENTFORGE_MODEL_P5_STUB_KEY', temperature=.2, max_tokens=1024, timeout=2, enabled=True, version=1))
    worker = Worker(connections, settings)
    await worker.initialize()
    service = TaskService(connections, settings)
    try: yield settings, connections, worker, service
    finally:
        await worker.close()
        async with connections.sessions() as session, session.begin():
            for model in (AgentTask, ModelSlot, RealDailyUsage, ToolCall, ToolPermission, CapabilityApproval, CapabilityAudit, ManagedNote, ToolDailyUsage):
                await session.execute(delete(model).where(model.tenant_id == UUID(settings.tenant_id)))
        await connections.close()


async def create(setup, **changes):
    settings, _, _, service = setup
    return await service.create(settings.tenant_id, uuid4(), TaskCreate(**({'goal': 'P5 explicit provider Stub integration',
        'execution_mode': 'real', 'require_approval': False} | changes)))


async def drive(setup, task_id, wanted=TERMINAL, timeout=15):
    settings, _, worker, service = setup
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        await worker.tick(); await asyncio.sleep(.03)
        row = await service.get(UUID(task_id), settings.tenant_id)
        if row['status'] in wanted: return row
    raise AssertionError('P5 workflow failed to reach a bounded state')


async def test_four_independent_slots_real_ledger_and_actual_parallel_graph_with_explicit_stub(setup):
    task = await create(setup)
    row = await drive(setup, task['task_id'])
    assert row['status'] == 'succeeded', row['error_code']
    assert {r['role'] for r in row['calls']} == {'planner','coder','researcher','reviewer'}
    assert all(not r['is_mock'] and r['usage_status'] == 'reported_estimate' for r in row['calls'])
    assert row['usage']['input_output_tokens'] == 520 and Decimal(row['usage']['real_cost_usd']) > 0
    calls = {r['role']: r for r in row['calls']}
    assert calls['coder']['started_at'] < calls['researcher']['finished_at']
    assert calls['researcher']['started_at'] < calls['coder']['finished_at']
    review = next(context for role, _, context in ProviderStub.calls if role == 'reviewer')
    assert {e['role'] for e in review['evidence']} >= {'coder', 'researcher'}


@pytest.mark.parametrize('mode', ['research_first', 'code_first'])
async def test_model_plan_controls_validated_dependency_order(setup, mode):
    ProviderStub.dependency = mode
    row = await drive(setup, (await create(setup))['task_id'])
    assert row['status'] == 'succeeded', row['error_code']
    calls = {r['role']: r for r in row['calls']}
    first, second = ('researcher', 'coder') if mode == 'research_first' else ('coder', 'researcher')
    assert calls[first]['finished_at'] <= calls[second]['started_at']


@pytest.mark.parametrize('change', [{'max_calls': 1}, {'max_tokens': 100}, {'max_budget_usd': '0.00000001'}, {'max_iterations': 1}])
async def test_real_budget_and_iteration_caps_cannot_be_bypassed(setup, change):
    if 'max_iterations' in change: ProviderStub.revision_rounds = 9
    row = await drive(setup, (await create(setup, **change))['task_id'])
    assert row['status'] == 'limit_exceeded', row['error_code']
    if 'max_tokens' in change or 'max_budget_usd' in change: assert not ProviderStub.calls


@pytest.mark.parametrize('failure,retry', [('MODEL_AUTH_INVALID', False), ('MODEL_RATE_LIMIT', True), ('MODEL_SERVER_ERROR', True), ('MODEL_TIMEOUT', True)])
async def test_provider_errors_bounded_retry_and_pending_costs(setup, failure, retry):
    ProviderStub.failure, ProviderStub.fail_count = failure, 1
    row = await drive(setup, (await create(setup))['task_id'])
    assert row['status'] == ('succeeded' if retry else 'failed'), row['error_code']
    assert sum(role == 'planner' for role, _, _ in ProviderStub.calls) == (2 if retry else 1)
    assert Decimal(row['usage']['reserved_real_cost_usd']) > 0


async def test_usage_missing_is_unknown_with_reservation_preserved(setup):
    ProviderStub.usage_missing = True
    row = await drive(setup, (await create(setup))['task_id'])
    assert row['status'] == 'succeeded' and row['usage']['cost_status'] == 'estimated_with_pending'
    assert all(r['input_tokens'] is None and r['estimated_cost_usd'] is None and r['usage_status'] == 'unknown' for r in row['calls'])
    assert Decimal(row['usage']['reserved_real_cost_usd']) > 0


async def test_format_error_fails_after_at_most_one_repair_and_never_runs_workers(setup):
    ProviderStub.malformed = True
    row = await drive(setup, (await create(setup))['task_id'])
    assert row['status'] == 'failed' and row['error_code'] == 'MODEL_OUTPUT_INVALID'
    assert len(ProviderStub.calls) == 2 and {role for role, _, _ in ProviderStub.calls} == {'planner'}


async def test_explicit_chat_sse_history_and_tenant_isolation(setup):
    settings, _, _, service = setup
    first = await create(setup, workflow='chat', chat_role='researcher')
    row = await drive(setup, first['task_id'])
    assert row['status'] == 'succeeded' and len(row['calls']) == 1
    events, _ = await service.events(UUID(row['task_id']), settings.tenant_id, 0)
    assert any(r['kind'] == 'model_delta' for r in events)
    second = await create(setup, workflow='chat', chat_role='researcher', conversation_id=row['options']['conversation_id'])
    result = await drive(setup, second['task_id'])
    assert result['status'] == 'succeeded'
    assert ProviderStub.calls[-1][2]['history'][0]['assistant']
    with pytest.raises(AppError, match='TASK_NOT_FOUND'): await service.get(UUID(first['task_id']), str(uuid4()))


async def test_cancel_deadline_and_pause_resume_are_persistent(setup):
    settings, _, _, service = setup
    ProviderStub.delay = .4
    task = await create(setup)
    await service.pause(UUID(task['task_id']), settings.tenant_id)
    assert (await service.get(UUID(task['task_id']), settings.tenant_id))['status'] == 'paused'
    await service.pause(UUID(task['task_id']), settings.tenant_id, resume=True)
    row = await drive(setup, task['task_id'], {'running'})
    await service.cancel(UUID(task['task_id']), settings.tenant_id)
    assert (await drive(setup, task['task_id']))['status'] == 'cancelled'
    timed = await create(setup, timeout_seconds=1)
    assert (await drive(setup, timed['task_id']))['status'] == 'timed_out'


async def test_model_test_requires_explicit_approved_quota_before_dispatch(setup):
    settings, _, _, service = setup
    with pytest.raises(AppError, match='MODEL_TEST_BUDGET_BLOCKED'):
        await service.create(settings.tenant_id, uuid4(), TaskCreate(goal='test', execution_mode='real', workflow='chat'), model_test=True)
    assert not ProviderStub.calls


async def test_agent_tool_permission_denial_cannot_be_overruled_by_reviewer(setup):
    ProviderStub.proposed_tool = {'tool': 'notes.write', 'arguments': {'resource': 'test', 'text': 'must not execute'}}
    row = await drive(setup, (await create(setup))['task_id'])
    assert row['status'] == 'failed' and row['error_code'] == 'TOOL_FORBIDDEN'
    assert not any(role == 'reviewer' for role, _, _ in ProviderStub.calls)


async def test_agent_mcp_approval_wait_resume_and_reviewer_sees_actual_receipt(setup):
    settings, connections, _, _ = setup
    gateway = ToolGateway(connections, settings)
    await gateway.permission(settings.tenant_id, PermissionUpdate(tool='notes.write', resource='test', allowed=True))
    ProviderStub.proposed_tool = {'tool': 'notes.write', 'arguments': {'resource': 'test', 'text': 'P5 actual MCP receipt'}}
    task = await create(setup)
    row = await drive(setup, task['task_id'], {'waiting_tools'})
    await asyncio.sleep(.15)
    call_id = UUID(row['tools'][0]['call_id'])
    call = await gateway.get(settings.tenant_id, call_id)
    review = await gateway.review(settings.tenant_id, UUID(call['approval_id']))
    await gateway.decide(settings.tenant_id, UUID(call['approval_id']), CapabilityDecision(decision='approved', operation_hash=review['operation_hash']))
    final = await drive(setup, task['task_id'])
    assert final['status'] == 'succeeded', final['error_code']
    assert final['tools'][0]['result']['result']['revision'] == 1
    context = next(c for role, _, c in ProviderStub.calls if role == 'reviewer')
    assert context['tool_results'][0]['result']['result']['text'] == 'P5 actual MCP receipt'


async def test_worker_restart_never_replays_an_uncertain_paid_dispatch(setup):
    settings, connections, worker, service = setup
    task = await create(setup)
    claim = await worker.claim(UUID(task['task_id']))
    async with connections.sessions() as session, session.begin():
        row = await session.get(AgentTask, UUID(task['task_id']))
        session.add(ModelOperation(task_id=row.id, operation_id='planner:0:0', role='planner', provider='openai_compatible', model='stub-planner',
            is_mock=False, state='reserved', input_tokens=0, reserved_tokens=9000, reserved_cost=Decimal('.01'), cost=0,
            request_hash='0' * 64, fence=claim[1], usage_status='pending', reservation_day=now().date()))
        row.owner, row.lease_until = None, None
        row.status = 'queued'
    final = await drive(setup, task['task_id'])
    assert final['status'] == 'needs_reconciliation'
    assert not ProviderStub.calls


async def test_completed_planner_survives_new_worker_without_rebilling(setup):
    settings, connections, worker, service = setup
    task = await create(setup, require_approval=True)
    waiting = await drive(setup, task['task_id'], {'waiting_approval'})
    await asyncio.sleep(.15)
    await worker.close()
    approval = next(r for r in await service.approvals(settings.tenant_id) if r['task_id'] == task['task_id'])
    await service.decide(UUID(approval['approval_id']), settings.tenant_id, ApprovalDecision(decision='approved', operation_hash=approval['operation_hash']))
    replacement = Worker(connections, settings)
    await replacement.initialize()
    try:
        final = await drive((settings, connections, replacement, service), task['task_id'])
        assert final['status'] == 'succeeded', final['error_code']
        assert sum(role == 'planner' for role, _, _ in ProviderStub.calls) == 1
    finally: await replacement.close()


async def test_partial_model_failure_cannot_be_reported_as_success(setup):
    ProviderStub.failure, ProviderStub.fail_count, ProviderStub.fail_role = 'MODEL_AUTH_INVALID', 1, 'reviewer'
    row = await drive(setup, (await create(setup))['task_id'])
    assert row['status'] == 'failed' and row['error_code'] == 'MODEL_AUTH_INVALID'
    assert {r['role'] for r in row['calls'] if r['state'] == 'completed'} == {'planner', 'coder', 'researcher'}
    assert row['result'] is None


async def test_revision_loop_is_bounded_and_conflicts_reach_reviewer(setup):
    ProviderStub.revision_rounds = 1
    row = await drive(setup, (await create(setup))['task_id'])
    assert row['status'] == 'succeeded' and row['iterations'] == 2
    assert sum(role == 'coder' for role, _, _ in ProviderStub.calls) == 2


async def test_agent_sandbox_permission_cannot_be_bypassed(setup):
    ProviderStub.proposed_tool = {'tool': 'sandbox.execute', 'arguments': {'language': 'python', 'code': "print('not authorized')"}}
    row = await drive(setup, (await create(setup))['task_id'])
    assert row['status'] == 'failed' and row['error_code'] == 'TOOL_FORBIDDEN'


async def test_active_pause_finishes_current_call_and_resumes_without_rebilling(setup):
    settings, _, _, service = setup
    ProviderStub.delay = .3
    task = await create(setup)
    await drive(setup, task['task_id'], {'running'})
    await service.pause(UUID(task['task_id']), settings.tenant_id)
    paused = await drive(setup, task['task_id'], {'paused'})
    await service.pause(UUID(task['task_id']), settings.tenant_id, resume=True)
    final = await drive(setup, task['task_id'])
    assert final['status'] == 'succeeded', final['error_code']
    assert sum(role == 'planner' for role, _, _ in ProviderStub.calls) == 1


async def test_streaming_and_persisted_output_never_echo_the_protected_key(setup, monkeypatch):
    settings, _, _, service = setup
    async def echo(self, config, messages, credential, delta):
        text = 'response: ' + credential + '\ncomplete'
        for part in [text[:15], text[15:29], text[29:]]: await delta(part)
        return ModelReply(text, 10, 10, 20, 1, 3)
    monkeypatch.setattr(ProviderStub, 'complete', echo)
    task = await create(setup, workflow='chat')
    final = await drive(setup, task['task_id'])
    events, _ = await service.events(UUID(task['task_id']), settings.tenant_id, 0)
    assert 'explicit-provider-stub-only-value' not in json.dumps(final)
    assert 'explicit-provider-stub-only-value' not in json.dumps(events)
    assert '[REDACTED]' in final['result']['summary']


async def test_unresolved_conflicts_force_bounded_revision_even_if_reviewer_claims_complete(setup, monkeypatch):
    original = ProviderStub.complete
    async def conflicting(self, config, messages, credential, delta):
        result = await original(self, config, messages, credential, delta)
        if config['model'] == 'stub-reviewer':
            value = json.loads(result.text)
            value['conflicts'] = ['Coder and Researcher conclusions disagree']
            value['needs_revision'] = False
            result.text = json.dumps(value)
        return result
    monkeypatch.setattr(ProviderStub, 'complete', conflicting)
    row = await drive(setup, (await create(setup, max_iterations=1))['task_id'])
    assert row['status'] == 'limit_exceeded'
    assert row['result'] is None


async def test_parallel_branches_cannot_oversell_the_real_token_reservation(setup):
    ProviderStub.delay = .2
    row = await drive(setup, (await create(setup, max_tokens=10000))['task_id'])
    assert row['status'] == 'limit_exceeded'
    assert row['usage']['model_attempts'] <= 2
    assert row['usage']['input_output_tokens'] + row['usage']['reserved_tokens'] <= 10000


async def test_real_connectivity_test_quota_is_shared_and_cannot_be_reused(setup):
    settings, _, worker, service = setup
    approved = settings.model_copy(update={'real_test_budget_usd': Decimal('.1'), 'real_test_max_calls': 1})
    service.settings = worker.settings = approved
    request = TaskCreate(goal='explicit Stub connectivity quota test', workflow='chat', execution_mode='real', max_calls=1)
    first = await service.create(settings.tenant_id, uuid4(), request, model_test=True)
    assert (await drive(setup, first['task_id']))['status'] == 'succeeded'
    second = await service.create(settings.tenant_id, uuid4(), request, model_test=True)
    row = await drive(setup, second['task_id'])
    assert row['status'] == 'failed' and row['error_code'] == 'MODEL_TEST_BUDGET_BLOCKED'
    assert len(ProviderStub.calls) == 1


async def test_connectivity_failure_is_not_retried_and_limits_are_audited(setup):
    settings, connections, worker, service = setup
    approved = settings.model_copy(update={'real_test_budget_usd': Decimal('.1'), 'real_test_max_calls': 1})
    service.settings = worker.settings = approved
    ProviderStub.failure, ProviderStub.fail_count = 'MODEL_RATE_LIMIT', 3
    task = await service.create(settings.tenant_id, uuid4(), TaskCreate(goal='explicit Stub no-retry audit',
        workflow='chat', execution_mode='real', max_calls=1), model_test=True)
    row = await drive(setup, task['task_id'])
    assert row['status'] == 'failed' and row['error_code'] == 'MODEL_RATE_LIMIT'
    assert len(ProviderStub.calls) == row['usage']['model_attempts'] == 1
    assert Decimal(row['usage']['reserved_real_cost_usd']) > 0
    async with connections.sessions() as session:
        audit = (await session.scalars(select(TaskEvent).where(TaskEvent.task_id == UUID(task['task_id']), TaskEvent.kind == 'node_started'))).one()
        assert audit.payload['retry_policy'] == 'none' and audit.payload['call_limit'] == 1
        assert audit.payload['token_limit'] == 100000 and audit.payload['model_test']


@pytest.mark.sandbox
async def test_coder_proposal_uses_real_p3_approval_runner_then_actual_review_evidence(setup):
    if os.environ.get('AGENTFORGE_RUN_SANDBOX') != '1': pytest.skip('Real approved project Docker Runner opt-in required')
    settings, connections, worker, _ = setup
    gateway = ToolGateway(connections, settings)
    await gateway.permission(settings.tenant_id, PermissionUpdate(tool='sandbox.execute', resource='python', allowed=True))
    ProviderStub.proposed_tool = {'tool': 'sandbox.execute', 'arguments': {'language': 'python', 'code': "print('P5 actual Docker evidence')", 'timeout_seconds': 3}}
    task = await create(setup)
    waiting = await drive(setup, task['task_id'], {'waiting_tools'})
    execution_id = UUID(waiting['tools'][0]['sandbox_execution_id'])
    from app.services.sandbox import SandboxService
    sandbox = SandboxService(connections, settings)
    for _ in range(80):
        await worker.tick(); await asyncio.sleep(.05)
        execution = await sandbox.get(execution_id, settings.tenant_id)
        if execution['status'] == 'waiting_approval': break
    await asyncio.sleep(.15)
    await sandbox.decide(execution_id, settings.tenant_id, ApprovalDecision(decision='approved', operation_hash=execution['operation_hash']))
    final = await drive(setup, task['task_id'], timeout=25)
    assert final['status'] == 'succeeded', final['error_code']
    result = final['tools'][0]['result']
    assert result['is_mock'] is False and result['cleanup_status'] == 'removed'
    assert 'P5 actual Docker evidence' in result['stdout_summary']
    reviewer = next(c for role, _, c in ProviderStub.calls if role == 'reviewer')
    assert 'P5 actual Docker evidence' in reviewer['tool_results'][0]['result']['stdout_summary']
