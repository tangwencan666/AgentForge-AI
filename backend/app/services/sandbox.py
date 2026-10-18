"""Authorized bounded sandbox requests, approval and resource reservation."""
import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from app.core.errors import AppError
from app.domain.sandbox import SandboxExecution, SandboxDailyUsage
from app.domain.tasks import AgentTask, TaskApproval, Outbox
from app.schemas.sandbox import SandboxCreate, POLICY_VERSION
from app.schemas.tasks import ApprovalDecision
from app.services.context import redact
from app.services.tasks import now, locked_task, event, TERMINAL
from app.services.sandbox_maintenance import require_open
from app.sandbox.history import require_replayable

EXECUTION_TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed_out", "needs_reconciliation", "rejected", "output_limit"})

def execution_dto(row, approval=None):
    return {"execution_id":str(row.id), "task_id":str(row.task_id), "language":row.language,
        "code_hash":row.code_hash, "operation_hash":row.operation_hash, "policy_version":row.policy_version,
        "status":row.status, "approval_reference":str(row.approval_reference),
        "approval_status":approval.status if approval else None, "timeout_seconds":row.timeout_seconds,
        "resource_limits":row.resource_limits, "exit_code":row.exit_code, "stdout_summary":row.stdout_summary,
        "stderr_summary":row.stderr_summary, "duration_ms":row.duration_ms, "resource_usage":row.resource_usage,
        "container_id":row.container_id, "failure_reason":row.failure_reason, "cleanup_status":row.cleanup_status,
        "created_at":row.created_at.isoformat(), "is_mock":False}

class SandboxService:
    def __init__(self, connections, settings):
        self.connections, self.settings = connections, settings

    def configured(self):
        if not self.settings.sandbox_image_id or not self.settings.sandbox_runner_token or not self.settings.sandbox_approver_token:
            raise AppError("SANDBOX_UNAVAILABLE", "Sandbox control plane is not configured", 503)

    def policy(self):
        return {"policy_version":POLICY_VERSION,"language":"python",
            "limits":{"cpu":[0.25,0.5,1.0],"memory_mb":512,"pids":64,"timeout_seconds":120,"output_bytes":1048576},
            "max_concurrency":self.settings.sandbox_max_concurrency,"tenant_concurrency":self.settings.sandbox_tenant_concurrency,
            "prewarm_enabled":False,"configured":bool(self.settings.sandbox_image_id and self.settings.sandbox_runner_token),
            "network":"none","root_filesystem":"read_only","user":"10001:10001",
            "daily_cpu_seconds_limit":str(self.settings.sandbox_daily_cpu_seconds)}

    async def create(self, tenant, key, request: SandboxCreate, *, parent_context=None):
        self.configured()
        from app.sandbox.policy import operation_digest
        code = request.code.get_secret_value()
        if len(code.encode()) > 65536 or not code.strip():
            raise AppError("CODE_SIZE_INVALID", "Code must be within 64 KiB", 422)
        if redact(code, self.settings) != code:
            raise AppError("SENSITIVE_CODE_REJECTED", "Code contains a protected credential or secret pattern", 422)
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        limits = request.resource_limits.model_dump()
        op_hash = operation_digest(code_hash, request.language, request.timeout_seconds, limits, self.settings.sandbox_image_id)
        digest = hmac.new(self.settings.admin_token.get_secret_value().encode(), op_hash.encode(), hashlib.sha256).hexdigest()
        reservation = Decimal(str(limits["cpu"])) * request.timeout_seconds
        async with self.connections.sessions() as session, session.begin():
            await require_open(session)
            await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key":tenant+":"+str(key)})
            if parent_context:
                from app.services.agent_tools import authorize_parent
                await authorize_parent(session, UUID(tenant), parent_context, active=True, sandbox=True)
            old = (await session.scalars(select(AgentTask).where(AgentTask.tenant_id==UUID(tenant), AgentTask.idempotency_key==key))).one_or_none()
            if old:
                if old.request_hash != digest or old.options.get("workflow") != "sandbox":
                    raise AppError("IDEMPOTENCY_CONFLICT", "Idempotency key has another request", 409)
                row = (await session.scalars(select(SandboxExecution).where(SandboxExecution.task_id==old.id))).one()
                return execution_dto(row, await session.get(TaskApproval, row.approval_reference))
            day = now().date()
            await session.execute(insert(SandboxDailyUsage).values(tenant_id=UUID(tenant),day=day,cpu_seconds_reserved=0,cpu_seconds_used=0).on_conflict_do_nothing())
            quota = (await session.scalars(select(SandboxDailyUsage).where(SandboxDailyUsage.tenant_id==UUID(tenant),SandboxDailyUsage.day==day).with_for_update())).one()
            if quota.cpu_seconds_reserved + quota.cpu_seconds_used + reservation > self.settings.sandbox_daily_cpu_seconds:
                raise AppError("SANDBOX_BUDGET_EXCEEDED", "Daily sandbox resource budget exceeded", 409)
            quota.cpu_seconds_reserved += reservation
            task_id, execution_id, approval_id = uuid4(), uuid4(), uuid4()
            task = AgentTask(id=task_id,tenant_id=UUID(tenant),idempotency_key=key,request_hash=digest,
                goal="Python sandbox execution "+code_hash[:12],options={"workflow":"sandbox","execution_mode":"sandbox","execution_id":str(execution_id)},
                model_snapshot={},status="queued",is_mock=False,deadline=now()+timedelta(seconds=900),
                token_limit=1,call_limit=1,iteration_limit=1,budget_limit=Decimal(0),plan_hash=op_hash)
            session.add(task)
            if parent_context:
                parent = await session.get(AgentTask, UUID(parent_context['task_id']))
                task.deadline = min(task.deadline, parent.deadline)
            await session.flush()
            approval = TaskApproval(id=approval_id,task_id=task_id,tenant_id=UUID(tenant),operation_hash=op_hash,
                policy_version=POLICY_VERSION,expires_at=task.deadline,status="pending")
            session.add(approval)
            await session.flush()
            row = SandboxExecution(id=execution_id,task_id=task_id,tenant_id=UUID(tenant),language=request.language,
                code=code,code_hash=code_hash,operation_hash=op_hash,timeout_seconds=request.timeout_seconds,
                resource_limits=limits,policy_version=POLICY_VERSION,approval_reference=approval_id,
                requester="local-admin",status="awaiting_approval",image_id=self.settings.sandbox_image_id,
                parent_context=parent_context,
                budget_day=day,reserved_cpu_seconds=reservation)
            session.add(row)
            event(session,task,"sandbox_submitted",{"execution_id":str(execution_id),"code_hash":code_hash,"policy_version":POLICY_VERSION})
            session.add(Outbox(id=uuid4(),task_id=task_id))
            await session.flush()
            return execution_dto(row,approval)

    async def get(self, execution_id, tenant):
        async with self.connections.sessions() as session:
            row = (await session.scalars(select(SandboxExecution).where(SandboxExecution.id==execution_id,SandboxExecution.tenant_id==UUID(tenant)))).one_or_none()
            if row is None:
                raise AppError("EXECUTION_NOT_FOUND", "Execution not found", 404)
            return execution_dto(row,await session.get(TaskApproval,row.approval_reference))

    async def list(self, tenant):
        async with self.connections.sessions() as session:
            rows = (await session.scalars(select(SandboxExecution).where(SandboxExecution.tenant_id==UUID(tenant)).order_by(SandboxExecution.created_at.desc()).limit(100))).all()
            return [execution_dto(r,await session.get(TaskApproval,r.approval_reference)) for r in rows]

    async def decide(self, execution_id, tenant, decision: ApprovalDecision):
        async with self.connections.sessions() as session, session.begin():
            if decision.decision == 'approved':
                await require_open(session)
            row = (await session.scalars(select(SandboxExecution).where(SandboxExecution.id==execution_id,SandboxExecution.tenant_id==UUID(tenant)))).one_or_none()
            if not row:
                raise AppError("EXECUTION_NOT_FOUND", "Execution not found", 404)
            task = await locked_task(session,row.task_id,tenant)
            row = (await session.scalars(select(SandboxExecution).where(SandboxExecution.id==execution_id).with_for_update().execution_options(populate_existing=True))).one()
            if decision.decision == 'approved':
                await require_replayable(session, row)
            approval = (await session.scalars(select(TaskApproval).where(TaskApproval.id==row.approval_reference).with_for_update())).one()
            if decision.operation_hash != row.operation_hash or approval.operation_hash != row.operation_hash or approval.policy_version != POLICY_VERSION:
                raise AppError("APPROVAL_MISMATCH", "Approval parameters changed", 409)
            if approval.status == decision.decision:
                return execution_dto(row,approval)
            if approval.status != "pending" or task.status != "waiting_approval" or approval.expires_at<=now() or task.deadline<=now():
                raise AppError("APPROVAL_INACTIVE", "Approval is no longer active", 409)
            if task.owner and task.lease_until and task.lease_until>now():
                raise AppError("APPROVAL_CHECKPOINT_PENDING", "Approval checkpoint is being saved; retry shortly", 409)
            approval.status,approval.decided_by,approval.decided_at = decision.decision,"sandbox-reviewer",now()
            if decision.decision == "approved":
                row.status,task.status = "queued","queued"
                session.add(Outbox(id=uuid4(),task_id=task.id))
            else:
                row.status,row.failure_reason,task.status,task.error_code = "rejected","APPROVAL_REJECTED","failed","APPROVAL_REJECTED"
                await settle_budget(session,row)
            event(session,task,"sandbox_approval_decided",{"execution_id":str(row.id),"decision":decision.decision})
            return execution_dto(row,approval)

    async def cancel(self, execution_id, tenant):
        async with self.connections.sessions() as session, session.begin():
            row = (await session.scalars(select(SandboxExecution).where(SandboxExecution.id==execution_id,SandboxExecution.tenant_id==UUID(tenant)))).one_or_none()
            if not row:
                raise AppError("EXECUTION_NOT_FOUND", "Execution not found", 404)
            task = await locked_task(session,row.task_id,tenant)
            row = (await session.scalars(select(SandboxExecution).where(SandboxExecution.id==execution_id).with_for_update().execution_options(populate_existing=True))).one()
            if row.status not in EXECUTION_TERMINAL:
                task.status = "cancel_requested"
                if row.launch_claimed_at is None:
                    row.status,row.failure_reason,task.status = "cancelled","TASK_CANCELLED","cancelled"
                    await settle_budget(session,row)
                approval = await session.get(TaskApproval,row.approval_reference)
                if approval.status == "pending": approval.status="cancelled"
                event(session,task,"sandbox_cancel_requested",{"execution_id":str(row.id),"cleanup_status":row.cleanup_status})
            return execution_dto(row,await session.get(TaskApproval,row.approval_reference))

async def settle_budget(session, row):
    if row.reserved_cpu_seconds <= 0: return
    quota = (await session.scalars(select(SandboxDailyUsage).where(SandboxDailyUsage.tenant_id==row.tenant_id,SandboxDailyUsage.day==row.budget_day).with_for_update())).one()
    quota.cpu_seconds_reserved -= row.reserved_cpu_seconds
    # Charge reserved upper bound on unknown usage; never turn uncertain runs into free retries.
    quota.cpu_seconds_used += row.reserved_cpu_seconds if row.launch_claimed_at else Decimal(0)
    row.reserved_cpu_seconds = Decimal(0)
