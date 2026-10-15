"""Agent entry to P4 Gateway; stable proposals, lease checks and P3 handoff."""
from uuid import UUID, uuid5
from sqlalchemy import select
from langgraph.types import interrupt
from app.core.errors import AppError
from app.domain.real import AgentToolOperation
from app.domain.tasks import AgentTask, ModelOperation
from app.domain.tools import ToolPermission
from app.schemas.tools import ToolRequest
from app.schemas.sandbox import SandboxCreate
from app.services.context import content_hash
from app.services.tasks import check_lease, event, locked_task, now, TERMINAL
from app.services.capabilities import tenant_lock
from app.services.tool_gateway import ToolGateway
from app.services.sandbox import SandboxService, EXECUTION_TERMINAL


async def authorize_parent(session, tenant, context, active=False, sandbox=False):
    task = await session.get(AgentTask, UUID(context['task_id']), with_for_update=True)
    binding = await session.get(AgentToolOperation, (UUID(context['task_id']), context['operation_id']))
    if not task or task.tenant_id != tenant or not binding or binding.tenant_id != tenant or task.deadline <= now():
        raise AppError('AGENT_TOOL_FORBIDDEN', 'Agent task binding is invalid', 403)
    if task.status not in {'running', 'waiting_tools'}:
        raise AppError('AGENT_TOOL_FORBIDDEN', 'Agent task is not active', 403)
    if active:
        check_lease(task, binding.owner, binding.fence)
    if sandbox:
        grant = await session.get(ToolPermission, (tenant, 'sandbox.execute', 'python'))
        if not grant or not grant.allowed or grant.generation != binding.permission_generation:
            raise AppError('TOOL_FORBIDDEN', 'Current sandbox resource permission is required', 403)
    return binding


class AgentToolGateway(ToolGateway):
    async def progress(self, runtime, round_no):
        async with self.connections.sessions() as session:
            results = (await session.scalars(select(ModelOperation).where(ModelOperation.task_id == runtime.task_id,
                ModelOperation.state == 'completed', ModelOperation.role.in_(['coder', 'researcher'])))).all()
        waiting = False
        for result in results:
            if result.operation_id.split(':')[1] != str(round_no): continue
            for index, proposal in enumerate((result.result or {}).get('tools', [])):
                op_id = f'{result.role}:{round_no}:tool:{index}'
                waiting = (not await self.one(runtime, op_id, proposal)) or waiting
        if waiting:
            async with self.connections.sessions() as session, session.begin():
                task = await locked_task(session, runtime.task_id, runtime.tenant_id)
                check_lease(task, runtime.owner, runtime.fence)
                task.status = 'waiting_tools'
                event(session, task, 'tool_approval_required', {'round': round_no})
            interrupt({'type': 'agent_tools', 'round': round_no})
        return {}

    async def one(self, runtime, op_id, proposal):
        from app.schemas.agents import ToolProposal
        body = ToolProposal.model_validate(proposal)
        context = {'task_id': str(runtime.task_id), 'operation_id': op_id}
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, runtime.task_id, runtime.tenant_id)
            check_lease(task, runtime.owner, runtime.fence)
            row = await session.get(AgentToolOperation, (task.id, op_id))
            if row is None:
                row = AgentToolOperation(task_id=task.id, operation_id=op_id, tenant_id=task.tenant_id,
                    request_hash=content_hash(proposal), proposal=proposal, owner=runtime.owner, fence=runtime.fence)
                session.add(row)
            elif row.request_hash != content_hash(proposal):
                raise AppError('AGENT_TOOL_CHANGED', 'Tool proposal changed during recovery', 409)
            if row.result is not None: return True
            row.owner, row.fence = runtime.owner, runtime.fence
            call_id, execution_id = row.call_id, row.sandbox_execution_id
        key = uuid5(runtime.task_id, op_id)
        if body.tool == 'sandbox.execute':
            if body.skill is not None:
                raise AppError('SKILL_PERMISSION_DENIED', 'Current Skill schema does not authorize sandbox execution', 403)
            args = SandboxCreate.model_validate(body.arguments)
            async with self.connections.sessions() as session, session.begin():
                await tenant_lock(session, runtime.tenant_id)
                binding = await session.get(AgentToolOperation, (runtime.task_id, op_id))
                grant = await session.get(ToolPermission, (binding.tenant_id, 'sandbox.execute', 'python'))
                if not grant or not grant.allowed:
                    raise AppError('TOOL_FORBIDDEN', 'Explicit sandbox.execute / python permission is required', 403)
                if binding.permission_generation is None: binding.permission_generation = grant.generation
                if binding.permission_generation != grant.generation:
                    raise AppError('TOOL_FORBIDDEN', 'Sandbox authorization changed', 403)
                await authorize_parent(session, binding.tenant_id, context, active=True, sandbox=True)
            service = SandboxService(self.connections, self.settings)
            data = await service.get(execution_id, runtime.tenant_id) if execution_id else await service.create(runtime.tenant_id, key, args, parent_context=context)
            execution_id = UUID(data['execution_id'])
            finished = data['status'] in EXECUTION_TERMINAL
            if finished and data['status'] != 'succeeded':
                raise AppError('AGENT_SANDBOX_FAILED', 'Sandbox did not complete successfully; inspect the linked execution', 409)
        else:
            request = ToolRequest(tool=body.tool, arguments=body.arguments, skill=body.skill)
            data = await self.get(runtime.tenant_id, call_id) if call_id else await self._create(runtime.tenant_id, key, request, task_context=context)
            call_id = UUID(data['call_id'])
            # Save the linkage BEFORE dispatch; replay recovers the same stable key.
            async with self.connections.sessions() as session, session.begin():
                binding = await session.get(AgentToolOperation, (runtime.task_id, op_id))
                binding.call_id = call_id
            if data['status'] == 'ready':
                data = await self.execute(runtime.tenant_id, call_id)
            if data['status'] in {'needs_reconciliation', 'dispatched'}:
                raise AppError('MODEL_OUTCOME_UNKNOWN', 'Tool result needs reconciliation; never replay it', 409)
            if data['status'] == 'rejected':
                raise AppError('TOOL_APPROVAL_REJECTED', 'Tool approval was rejected', 403)
            finished = data['status'] == 'succeeded'
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, runtime.task_id, runtime.tenant_id)
            check_lease(task, runtime.owner, runtime.fence)
            binding = await session.get(AgentToolOperation, (runtime.task_id, op_id))
            binding.call_id, binding.sandbox_execution_id = call_id, execution_id
            if finished: binding.result = data
            event(session, task, 'tool_result' if finished else 'tool_waiting', {'operation_id': op_id, 'tool': body.tool,
                'call_id': str(call_id) if call_id else None, 'sandbox_execution_id': str(execution_id) if execution_id else None, 'status': data['status']})
        return finished


async def tools_ready(connections, task):
    from app.domain.tools import ToolCall
    from app.domain.sandbox import SandboxExecution
    async with connections.sessions() as session:
        rows = (await session.scalars(select(AgentToolOperation).where(AgentToolOperation.task_id == task.id))).all()
        for row in rows:
            if row.result is not None: continue
            if row.call_id:
                call = await session.get(ToolCall, row.call_id)
                if call.status == 'awaiting_approval': return False
            elif row.sandbox_execution_id:
                execution = await session.get(SandboxExecution, row.sandbox_execution_id)
                if execution.status not in EXECUTION_TERMINAL: return False
        return True


async def cancel_children(connections, settings, task_id, tenant):
    async with connections.sessions() as session:
        rows = (await session.scalars(select(AgentToolOperation).where(AgentToolOperation.task_id == task_id))).all()
    for row in rows:
        if row.sandbox_execution_id:
            await SandboxService(connections, settings).cancel(row.sandbox_execution_id, tenant)
