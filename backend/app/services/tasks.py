import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError
from app.core.errors import AppError
from app.domain.tasks import AgentTask, TaskEvent, Outbox, TaskApproval, ModelOperation
from app.schemas.tasks import TaskCreate, ApprovalDecision
from app.services.context import content_hash, redact

TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed_out", "limit_exceeded", "needs_reconciliation"})
MOCK_RATE = Decimal("0.000001")


def now():
    return datetime.now(timezone.utc)


def event(session, task: AgentTask, kind: str, payload: dict):
    task.event_seq += 1
    task.version += 1
    session.add(TaskEvent(task_id=task.id, seq=task.event_seq, kind=kind, payload={**payload, "is_mock": task.is_mock}))


async def locked_task(session, task_id: UUID, tenant_id: str | None = None):
    stmt = select(AgentTask).where(AgentTask.id == task_id).with_for_update()
    if tenant_id:
        stmt = stmt.where(AgentTask.tenant_id == UUID(tenant_id))
    task = (await session.scalars(stmt)).one_or_none()
    if task is None:
        raise AppError("TASK_NOT_FOUND", "Task not found", 404)
    return task


def check_lease(task: AgentTask, owner: str, fence: int, *, allow_waiting=False, allow_cancel=False, allow_pausing=False):
    if task.owner != owner or task.fence != fence or not task.lease_until or task.lease_until <= now():
        raise AppError("STALE_LEASE", "Worker lease is no longer valid", 409)
    if task.deadline <= now():
        raise AppError("TASK_TIMEOUT", "Task deadline reached", 408)
    allowed = {"running"} | ({"waiting_approval", "waiting_tools"} if allow_waiting else set()) | ({"cancel_requested"} if allow_cancel else set()) | ({"pause_requested"} if allow_pausing else set())
    if task.status not in allowed:
        raise AppError("TASK_STOPPED", "Task execution has stopped", 409)


def task_dto(task: AgentTask):
    return {"task_id": str(task.id), "goal": task.goal, "status": task.status, "is_mock": task.is_mock,
            "execution_mode": "mock" if task.is_mock else ("sandbox" if task.options.get('workflow') == 'sandbox' else 'real'), "created_at": task.created_at.isoformat(), "deadline": task.deadline.isoformat(),
            "version": task.version, "iterations": task.iterations, "error_code": task.error_code,
            "options": task.options, "model_snapshot": task.model_snapshot, "plan_hash": task.plan_hash,
            "result": task.result, "usage": {"input_output_tokens": task.tokens_used, "reserved_tokens": task.tokens_reserved,
                "model_attempts": task.calls_used, "mock_cost_usd": str(task.cost_used) if task.is_mock else '0',
                "real_cost_usd": str(task.cost_used) if not task.is_mock else '0.00000000',
                "reserved_mock_cost_usd": str(task.cost_reserved) if task.is_mock else '0',
                "reserved_real_cost_usd": str(task.cost_reserved) if not task.is_mock else '0',
                "cost_status": 'estimated_with_pending' if not task.is_mock and task.cost_reserved else ('estimated' if not task.is_mock else 'mock'),
                "price_version": "mock-usd-v1" if task.is_mock else 'per_call', "is_mock": task.is_mock}}


class TaskService:
    def __init__(self, connections, settings):
        self.connections, self.settings = connections, settings

    def require_real_permit(self):
        from app.services.permit_authority import reject_unpermitted_real
        reject_unpermitted_real()

    async def create(self, tenant_id: str, key: UUID, request: TaskCreate, *, model_test=False):
        payload = request.model_dump(mode="json")
        if model_test:
            if request.execution_mode != 'real' or self.settings.real_test_budget_usd <= 0:
                raise AppError('MODEL_TEST_BUDGET_BLOCKED', 'Real API test requires approved server-side test quota', 409)
            payload['model_test'] = True
        if request.execution_mode == 'real':
            self.require_real_permit()  # Only PermitService may create the fixed real test task.
        digest = hmac.new(self.settings.admin_token.get_secret_value().encode(),json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode(),hashlib.sha256).hexdigest()
        payload["goal"] = redact(payload["goal"].strip(), self.settings)
        if not payload["goal"]:
            raise AppError("INVALID_GOAL", "Task goal is required", 422)
        async with self.connections.sessions() as session:
            async with session.begin():
                await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),{"key":tenant_id+":"+str(key)})
                previous = (await session.scalars(select(AgentTask).where(AgentTask.tenant_id == UUID(tenant_id), AgentTask.idempotency_key == key))).one_or_none()
                if previous:
                    if previous.request_hash != digest:
                        raise AppError("IDEMPOTENCY_CONFLICT", "Idempotency key already used with a different request", 409)
                    return task_dto(previous)
                snapshot = {role: {"provider":"mock", "base_url":None,"credential_reference":None,"temperature":0.2,
                    "model":f"mock-{role}-v1", "max_tokens":1024, "timeout":60, "enabled":True, "is_mock":True,
                    "priority":50,"config_version":"mock-v1"} for role in ('planner','coder','researcher','reviewer')}
                if request.execution_mode == 'real':
                    from app.services.models import list_slots
                    from app.providers.router import ModelRouter
                    slots = await list_slots(session, tenant_id)
                    needed = {request.chat_role} if request.workflow == 'chat' else set(snapshot)
                    snapshot = {}
                    for slot in slots:
                        if slot['role'] in needed:
                            _, _, price = ModelRouter(self.settings).resolve(slot)
                            snapshot[slot['role']] = {k: slot[k] for k in ('provider','base_url','model','credential_reference','temperature','max_tokens','timeout','enabled','priority','thinking_mode','reasoning_effort')}
                            snapshot[slot['role']].update(config_version=slot['version'], is_mock=False, price=price.model_dump(mode='json'))
                    if set(snapshot) != needed:
                        raise AppError('MODEL_SLOTS_NOT_INITIALIZED', 'Required model slots are unavailable', 409)
                if request.conversation_id:
                    parent = await session.scalar(select(AgentTask.id).where(AgentTask.tenant_id == UUID(tenant_id),
                        AgentTask.options['conversation_id'].astext == str(request.conversation_id)).limit(1))
                    if not parent:
                        raise AppError('CONVERSATION_NOT_FOUND', 'Conversation is outside the authorized scope', 404)
                elif request.workflow == 'chat':
                    payload['conversation_id'] = str(uuid4())
                # Explicit Mock never mutates the real Model Center.
                task = AgentTask(id=uuid4(), tenant_id=UUID(tenant_id), idempotency_key=key, request_hash=digest,
                    goal=payload.pop("goal"), options=payload, status="queued", is_mock=request.execution_mode == 'mock',
                    model_snapshot=snapshot,
                    deadline=now()+timedelta(seconds=request.timeout_seconds), token_limit=request.max_tokens,
                    call_limit=request.max_calls, iteration_limit=request.max_iterations, budget_limit=request.max_budget_usd,
                    created_at=now(), updated_at=now(), event_seq=0, version=1, fence=0, attempts=0, iterations=0,
                    tokens_used=0, tokens_reserved=0, calls_used=0, cost_used=Decimal(0), cost_reserved=Decimal(0))
                session.add(task)
                event(session, task, "status", {"status":"queued"})
                session.add(Outbox(id=uuid4(), task_id=task.id))
                try:
                    await session.flush()
                except IntegrityError:
                    # A concurrent same-key creator wins; caller can retry the same key safely.
                    raise AppError("IDEMPOTENCY_RACE", "Retry with the same idempotency key", 409) from None
                return task_dto(task)

    async def get(self, task_id: UUID, tenant_id: str):
        async with self.connections.sessions() as session:
            task = (await session.scalars(select(AgentTask).where(AgentTask.id == task_id, AgentTask.tenant_id == UUID(tenant_id)))).one_or_none()
            if not task:
                raise AppError("TASK_NOT_FOUND", "Task not found", 404)
            dto = task_dto(task)
            ops = (await session.scalars(select(ModelOperation).where(ModelOperation.task_id == task_id).order_by(ModelOperation.started_at))).all()
            dto["calls"] = [{"operation_id":o.operation_id,"role":o.role,"provider":o.provider,"model":o.model,"state":o.state,
                "input_tokens":o.input_tokens if o.is_mock or o.total_tokens is not None else None,
                "output_tokens":o.output_tokens if o.is_mock or o.total_tokens is not None else None,
                "total_tokens":o.total_tokens, "usage_status":o.usage_status, "first_token_ms":o.first_token_ms,
                "error_code":o.error_code, "mock_cost_usd":str(o.cost) if o.is_mock else '0',
                "estimated_cost_usd":str(o.cost) if not o.is_mock and o.total_tokens is not None else None,"is_mock":o.is_mock,
                "latency_ms":o.latency_ms,"started_at":o.started_at.isoformat(),"finished_at":o.finished_at.isoformat() if o.finished_at else None,
                "result":o.result} for o in ops]
            from app.domain.real import AgentToolOperation
            tools = (await session.scalars(select(AgentToolOperation).where(AgentToolOperation.task_id == task.id))).all()
            dto['tools'] = [{'operation_id': r.operation_id, 'tool': r.proposal['tool'], 'call_id': str(r.call_id) if r.call_id else None,
                'sandbox_execution_id': str(r.sandbox_execution_id) if r.sandbox_execution_id else None, 'result': r.result} for r in tools]
            return dto

    async def list(self, tenant_id: str):
        async with self.connections.sessions() as session:
            tasks = (await session.scalars(select(AgentTask).where(AgentTask.tenant_id == UUID(tenant_id),
                AgentTask.options['workflow'].astext.is_distinct_from('sandbox')).order_by(AgentTask.created_at.desc()).limit(100))).all()
            return [task_dto(task) for task in tasks]

    async def cancel(self, task_id: UUID, tenant_id: str):
        current = await self.get(task_id,tenant_id)
        if current["execution_mode"] == "sandbox":
            from app.services.sandbox import SandboxService
            await SandboxService(self.connections,self.settings).cancel(UUID(current["options"]["execution_id"]),tenant_id)
            return await self.get(task_id,tenant_id)
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, task_id, tenant_id)
            if task.status not in TERMINAL and task.status != "cancel_requested":
                task.status = "cancel_requested" if task.owner and task.lease_until and task.lease_until > now() else "cancelled"
                event(session, task, "status", {"status":task.status})
                approval = (await session.scalars(select(TaskApproval).where(TaskApproval.task_id == task_id))).one_or_none()
                if approval and approval.status == "pending":
                    approval.status = "cancelled"
            data = task_dto(task)
        if not data['is_mock']:
            from app.services.agent_tools import cancel_children
            await cancel_children(self.connections, self.settings, task_id, tenant_id)
        return data

    async def pause(self, task_id, tenant_id, resume=False):
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, task_id, tenant_id)
            if task.options.get('workflow') == 'sandbox':
                raise AppError('TASK_PAUSE_UNAVAILABLE', 'Sandbox uses cancel rather than pause', 409)
            if resume:
                if task.status != 'paused' or task.deadline <= now():
                    raise AppError('TASK_NOT_PAUSED', 'Task cannot be resumed', 409)
                task.status = 'queued'
                session.add(Outbox(id=uuid4(), task_id=task.id))
            elif task.status not in TERMINAL:
                task.status = 'pause_requested' if task.owner and task.lease_until and task.lease_until > now() else 'paused'
            event(session, task, 'status', {'status': task.status})
            return task_dto(task)

    async def events(self, task_id: UUID, tenant_id: str, after: int):
        async with self.connections.sessions() as session:
            task = (await session.scalars(select(AgentTask).where(AgentTask.id == task_id, AgentTask.tenant_id == UUID(tenant_id)))).one_or_none()
            if not task:
                raise AppError("TASK_NOT_FOUND", "Task not found", 404)
            if after > task.event_seq:
                raise AppError("INVALID_CURSOR", "Event cursor is ahead of task history", 409)
            rows = (await session.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id, TaskEvent.seq > after).order_by(TaskEvent.seq).limit(200))).all()
            return [{"id":r.seq,"kind":r.kind,"payload":r.payload,"created_at":r.created_at.isoformat()} for r in rows], task.status

    async def approvals(self, tenant_id: str):
        async with self.connections.sessions() as session:
            rows = (await session.scalars(select(TaskApproval).where(TaskApproval.tenant_id == UUID(tenant_id),TaskApproval.policy_version == "p2-plan-v1").order_by(TaskApproval.expires_at.desc()).limit(100))).all()
            return [{"approval_id":str(r.id),"task_id":str(r.task_id),"operation_hash":r.operation_hash,"policy_version":r.policy_version,
                "status":r.status,"expires_at":r.expires_at.isoformat(),"is_mock":True,"type":"plan_confirmation"} for r in rows]

    async def decide(self, approval_id: UUID, tenant_id: str, decision: ApprovalDecision):
        async with self.connections.sessions() as session, session.begin():
            # Lock order is always task then approval to avoid cancellation deadlocks.
            existing = (await session.scalars(select(TaskApproval).where(TaskApproval.id == approval_id, TaskApproval.tenant_id == UUID(tenant_id)))).one_or_none()
            if not existing:
                raise AppError("APPROVAL_NOT_FOUND", "Approval not found", 404)
            task = await locked_task(session, existing.task_id, tenant_id)
            approval = (await session.scalars(select(TaskApproval).where(TaskApproval.id == approval_id).with_for_update().execution_options(populate_existing=True))).one()
            if approval.operation_hash != decision.operation_hash or task.plan_hash != decision.operation_hash or approval.policy_version != "p2-plan-v1":
                raise AppError("APPROVAL_MISMATCH", "Approval operation changed", 409)
            if approval.status == decision.decision:
                return {"status":approval.status,"task_id":str(task.id)}
            if approval.status != "pending" or task.status != "waiting_approval" or approval.expires_at <= now() or task.deadline <= now():
                raise AppError("APPROVAL_INACTIVE", "Approval expired or task is no longer waiting", 409)
            # Wait until interrupted graph checkpoint is durable and worker lease released.
            if task.owner and task.lease_until and task.lease_until > now():
                raise AppError("APPROVAL_CHECKPOINT_PENDING", "Approval checkpoint is being saved; retry shortly", 409)
            approval.status = decision.decision
            approval.decided_by, approval.decided_at = "local-admin", now()
            task.status = "queued" if decision.decision == "approved" else "failed"
            task.error_code = None if decision.decision == "approved" else "PLAN_REJECTED"
            event(session, task, "approval_decided", {"status":approval.status})
            event(session, task, "status", {"status":task.status})
            if decision.decision == "approved":
                session.add(Outbox(id=uuid4(), task_id=task.id))
            return {"status":approval.status,"task_id":str(task.id)}
