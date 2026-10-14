import asyncio
from decimal import Decimal
from time import monotonic
from uuid import UUID, uuid4
from sqlalchemy import select
from langchain_core.runnables import RunnableLambda
from langsmith import tracing_context
from app.core.errors import AppError
from app.domain.tasks import AgentTask, ModelOperation, TaskApproval
from app.services.context import build_context, content_hash, mock_tokens
from app.services.tasks import now, event, locked_task, check_lease, MOCK_RATE
from app.services.usage import tenant_usage


class Runtime:
    def __init__(self, connections, settings, task_id: UUID, tenant_id: str, owner: str, fence: int):
        self.connections, self.settings, self.task_id, self.tenant_id = connections, settings, task_id, tenant_id
        self.owner, self.fence = owner, fence

    async def assert_active(self):
        await self.connections.redis.ping()
        async with self.connections.sessions() as session:
            task = (await session.scalars(select(AgentTask).where(AgentTask.id == self.task_id, AgentTask.tenant_id == UUID(self.tenant_id)))).one()
            check_lease(task, self.owner, self.fence, allow_waiting=True)

    async def options(self):
        async with self.connections.sessions() as session:
            task = (await session.scalars(select(AgentTask).where(AgentTask.id == self.task_id, AgentTask.tenant_id == UUID(self.tenant_id)))).one()
            check_lease(task, self.owner, self.fence, allow_waiting=True)
            return task.options

    async def operation(self, role: str, round_no: int, payload: dict):
        """Only explicit Mock. Stable ledger key protects replay and atomic budget reservations."""
        for attempt in range(3):
            op_id = f"{role}:{round_no}:{attempt}"
            try:
                return await self._attempt(role, op_id, round_no, payload)
            except AppError as exc:
                if exc.code != "MOCK_MODEL_FAILED" or attempt == 2:
                    raise
                await asyncio.sleep(0.1 * (attempt + 1))

    async def _attempt(self, role, op_id, round_no, payload):
        await self.connections.redis.ping()  # No new calls while the scheduling dependency is unavailable.
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, self.task_id, self.tenant_id)
            check_lease(task, self.owner, self.fence)
            context = build_context(task.goal, role, self.settings)
            context["round"] = round_no
            digest, units = content_hash(context), mock_tokens(context)
            options = task.options["mock_options"]
            row = await session.get(ModelOperation, (self.task_id, op_id))
            if row:
                if row.request_hash != digest:
                    raise AppError("OPERATION_CONFLICT", "Operation input changed during recovery", 409)
                if row.state == "completed":
                    return row.result
                if row.state == "failed":
                    raise AppError("MOCK_MODEL_FAILED", "Explicit mock failure", 502)
                if row.state != "reserved":
                    raise AppError("OPERATION_STOPPED", "Operation stopped", 409)
                row.fence = self.fence  # Pure deterministic Mock can safely resume its existing reservation.
            else:
                reserve = units + task.model_snapshot[role]["max_tokens"]
                cost = Decimal(reserve) * MOCK_RATE
                quota = await tenant_usage(session,task.tenant_id,now().date())
                if task.calls_used >= task.call_limit or task.tokens_used + task.tokens_reserved + reserve > task.token_limit or task.cost_used + task.cost_reserved + cost > task.budget_limit:
                    raise AppError("TASK_LIMIT", "Task token, call or budget limit reached", 409)
                if quota.tokens_used + quota.tokens_reserved + reserve > self.settings.daily_mock_token_limit or quota.cost_used + quota.cost_reserved + cost > self.settings.daily_mock_budget_usd:
                    raise AppError("TASK_LIMIT", "Tenant daily mock quota reached", 409)
                quota.tokens_reserved += reserve
                quota.cost_reserved += cost
                row = ModelOperation(task_id=self.task_id, operation_id=op_id, role=role, provider="mock", model=task.model_snapshot[role]["model"],
                    input_tokens=units, reserved_tokens=reserve, reserved_cost=cost, request_hash=digest, fence=self.fence,
                    state="reserved", is_mock=True, output_tokens=0, cost=Decimal(0), started_at=now(), price_version="mock-usd-v1",reservation_day=now().date())
                session.add(row)
                task.calls_used += 1
                task.tokens_reserved += reserve
                task.cost_reserved += cost
                event(session, task, "node_started", {"role":role,"operation_id":op_id,"round":round_no,"input_tokens":units,
                    "context_source":context["source"],"context_hash":context["source_hash"],"context_truncated":context["truncated"]})
        start = monotonic()
        # Checks every 100ms ensure cancellation and stale fencing stop work quickly.
        remaining = options["latency_ms"] / 1000
        while remaining > 0:
            delay = min(0.1, remaining)
            await asyncio.sleep(delay)
            remaining -= delay
            await self.assert_active()
        await self.assert_active()
        failed = options.get("fail_role") == role
        with tracing_context(enabled=False):
            result = None if failed else await RunnableLambda(lambda _: {**payload,"is_mock":True,"role":role,"operation_id":op_id}).ainvoke(context, {"callbacks":[]})
        output = mock_tokens(result) if result else 0
        if output > 1024:
            raise AppError("MOCK_OUTPUT_LIMIT", "Mock output exceeded reservation", 409)
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, self.task_id, self.tenant_id)
            check_lease(task, self.owner, self.fence)
            row = await session.get(ModelOperation, (self.task_id, op_id))
            quota = await tenant_usage(session,task.tenant_id,row.reservation_day)
            row.output_tokens, row.cost = output, Decimal(row.input_tokens + output) * MOCK_RATE
            row.state, row.result, row.finished_at, row.latency_ms = "failed" if failed else "completed", result, now(), int((monotonic()-start)*1000)
            task.tokens_reserved -= row.reserved_tokens
            task.cost_reserved -= row.reserved_cost
            task.tokens_used += row.input_tokens + output
            task.cost_used += row.cost
            quota.tokens_reserved -= row.reserved_tokens
            quota.cost_reserved -= row.reserved_cost
            quota.tokens_used += row.input_tokens + output
            quota.cost_used += row.cost
            event(session, task, "node_failed" if failed else "node_completed", {"role":role,"operation_id":op_id,"round":round_no})
            event(session, task, "usage", {"operation_id":op_id,"input_tokens":row.input_tokens,"output_tokens":output,"mock_cost_usd":str(row.cost),"real_cost_usd":"0"})
        if failed:
            raise AppError("MOCK_MODEL_FAILED", "Explicit mock failure", 502)
        return result

    async def record_plan(self, plan: dict):
        digest = content_hash(plan)
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, self.task_id, self.tenant_id)
            check_lease(task, self.owner, self.fence)
            if task.plan_hash and task.plan_hash != digest:
                raise AppError("PLAN_CHANGED", "Plan changed during resume", 409)
            if not task.plan_hash:
                task.plan_hash = digest
                event(session, task, "plan", {"plan":plan,"plan_hash":digest})
        return digest

    async def approval_state(self, plan_hash: str):
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, self.task_id, self.tenant_id)
            check_lease(task, self.owner, self.fence, allow_waiting=True)
            if not task.options["require_approval"]:
                return "approved"
            approval = (await session.scalars(select(TaskApproval).where(TaskApproval.task_id == task.id))).one_or_none()
            if not approval:
                approval = TaskApproval(id=uuid4(), task_id=task.id, tenant_id=task.tenant_id,
                    operation_hash=plan_hash, policy_version="p2-plan-v1", expires_at=task.deadline, status="pending")
                session.add(approval)
            if approval.operation_hash != plan_hash or approval.policy_version != "p2-plan-v1" or approval.expires_at <= now():
                raise AppError("APPROVAL_INACTIVE", "Approval is no longer valid", 409)
            if approval.status == "approved":
                return "approved"
            if approval.status != "pending":
                raise AppError("PLAN_REJECTED", "Plan approval rejected", 403)
            if task.status != "waiting_approval":
                task.status = "waiting_approval"
                event(session, task, "approval_required", {"approval_id":str(approval.id),"plan_hash":plan_hash})
                event(session, task, "status", {"status":"waiting_approval"})
            return "pending"

    async def begin_round(self, round_no):
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, self.task_id, self.tenant_id)
            check_lease(task, self.owner, self.fence)
            if round_no >= task.iteration_limit:
                raise AppError("TASK_LIMIT", "Maximum agent iterations reached", 409)
            task.iterations = max(task.iterations, round_no + 1)
