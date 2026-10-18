import asyncio
import logging
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy import select, text, func
from langgraph.types import Command
from langsmith import tracing_context
from app.domain.tasks import AgentTask, Outbox, ModelOperation, TaskApproval
from app.services.tasks import now, event, locked_task, TERMINAL
from app.services.orchestration.runtime import Runtime
from app.services.orchestration.checkpoints import PostgresTaskSaver
from app.services.orchestration.graph import build_graph
from app.core.errors import AppError
from app.services.usage import tenant_usage
from app.domain.sandbox import SandboxExecution
from app.services.sandbox import EXECUTION_TERMINAL, settle_budget
from app.services.permit_authority import require_permit_task
from app.services.sandbox_maintenance import (admission_available, require_open, MAINTENANCE_ERRORS)
from app.sandbox.history import task_replay_allowed

STREAM = "agentforge:p2:tasks"
GROUP = "agentforge-p2-workers"
LEASE_SECONDS = 15
logger = logging.getLogger("agentforge")


class Worker:
    def __init__(self, connections, settings, owner=None):
        self.connections, self.settings = connections, settings
        self.owner = owner or str(uuid4())
        self.active: dict[str, asyncio.Task] = {}
        self.last_sweep = 0.0
        self.permit_identity = None
        self.permit_schema_available = None

    async def initialize(self):
        if self.permit_schema_available is None:
            async with self.connections.engine.connect() as connection:
                self.permit_schema_available = bool(await connection.scalar(text("SELECT to_regclass('public.execution_permits')")))
        if self.settings.real_worker_mode == 'permit_only' and self.permit_identity is None:
            from app.services.execution_permits import PermitService
            self.permit_identity = await PermitService(self.connections, self.settings).register_worker(self.owner)
        from redis.exceptions import ResponseError
        try:
            await self.connections.redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if not str(exc).startswith("BUSYGROUP"):
                raise

    async def publish(self):
        async with self.connections.sessions() as session, session.begin():
            rows = (await session.scalars(select(Outbox).where(Outbox.published_at.is_(None)).order_by(Outbox.created_at).limit(30).with_for_update(skip_locked=True))).all()
            for row in rows:
                task = await session.get(AgentTask, row.task_id)
                if task and task.options.get('workflow') == 'sandbox' and not await admission_available(session):
                    continue  # Preserve outbox; Redis never grants admission.
                if task and not await task_replay_allowed(session, task):
                    continue  # Preserve historical intent/outbox/UNKNOWN without replay.
                await self.connections.redis.xadd(STREAM, {"task_id":str(row.task_id),"outbox_id":str(row.id)})
                row.published_at = now()

    async def sweep(self):
        from app.services.execution_permits import PermitService
        if self.permit_schema_available:
            await PermitService(self.connections, self.settings).recover()
        async with self.connections.sessions() as session, session.begin():
            rows = (await session.scalars(select(AgentTask).where(AgentTask.status.not_in(TERMINAL)).with_for_update(skip_locked=True))).all()
            for task in rows:
                if not task.is_mock and task.options.get('workflow') == 'permit_test':
                    continue  # Permit recovery owns all unknown-outcome and reservation decisions.
                if not await task_replay_allowed(session, task):
                    continue  # Do not rewrite, settle or recover quarantined history.
                expired = task.deadline <= now()
                stopped = task.status == "cancel_requested"
                lease_expired = task.owner and task.lease_until and task.lease_until <= now()
                if not task.is_mock and task.options.get("workflow") == "sandbox":
                    if not await admission_available(session):
                        continue  # Running/cancel/UNKNOWN stay intact; Runner cleanup remains authorized.
                    execution=(await session.scalars(select(SandboxExecution).where(SandboxExecution.task_id==task.id).with_for_update())).one()
                    if execution.status in EXECUTION_TERMINAL:
                        task.status = "failed" if execution.status in {"rejected","output_limit"} else execution.status
                        task.error_code=execution.failure_reason
                        task.result={"is_mock":False,"summary":"[DOCKER] Execution "+execution.status,"execution_id":str(execution.id)}
                        task.owner,task.lease_until=None,None
                        event(session,task,"status",{"status":task.status,"cleanup_status":execution.cleanup_status})
                        continue
                    if expired or stopped:
                        if execution.launch_claimed_at is None:
                            execution.status=task.status="timed_out" if expired else "cancelled"
                            execution.failure_reason=task.error_code="TASK_TIMEOUT" if expired else "TASK_CANCELLED"
                            approval=await session.get(TaskApproval,execution.approval_reference)
                            if approval.status=="pending": approval.status="expired" if expired else "cancelled"
                            await settle_budget(session,execution)
                            task.owner,task.lease_until=None,None
                            event(session,task,"status",{"status":task.status,"cleanup_status":execution.cleanup_status})
                        else:
                            task.status="cancel_requested"  # Runner must confirm whole-container cleanup first.
                        continue
                    if lease_expired:
                        task.owner,task.lease_until=None,None
                        if task.status!="waiting_approval":
                            task.status="queued"
                            session.add(Outbox(id=uuid4(),task_id=task.id))
                            event(session,task,"recovered",{"status":"queued","execution_id":str(execution.id)})
                    continue
                if expired or stopped:
                    task.status = "timed_out" if expired else "cancelled"
                    task.error_code = "TASK_TIMEOUT" if expired else "TASK_CANCELLED"
                    await self.release_reservations(session, task, await self.reserved(session, task.id))
                    task.owner, task.lease_until = None, None
                    approval = (await session.scalars(select(TaskApproval).where(TaskApproval.task_id == task.id,TaskApproval.status == "pending"))).one_or_none()
                    if approval:
                        approval.status = "expired" if expired else "cancelled"
                    event(session, task, "status", {"status":task.status})
                elif task.status == 'waiting_tools' and not task.owner:
                    from app.services.agent_tools import tools_ready
                    if await tools_ready(self.connections, task):
                        task.status = 'queued'
                        session.add(Outbox(id=uuid4(), task_id=task.id))
                elif task.status == 'pause_requested' and (not task.owner or lease_expired):
                    task.status, task.owner, task.lease_until = 'paused', None, None
                elif lease_expired:
                    task.owner, task.lease_until = None, None
                    if task.status in {"waiting_approval", "waiting_tools", "paused"}:
                        continue
                    task.status = "queued"
                    if task.attempts >= 3:
                        task.status, task.error_code = "failed", "RECOVERY_LIMIT"
                        await self.release_reservations(session, task, await self.reserved(session, task.id))
                    else:
                        session.add(Outbox(id=uuid4(), task_id=task.id))
                    event(session, task, "recovered", {"status":task.status})
            # Published messages may be lost when Redis is restarted without its data.
            # Re-enqueue idle queued tasks from the PostgreSQL truth source.
            for task in rows:
                if task.options.get('workflow') == 'sandbox' and not await admission_available(session):
                    continue
                if not await task_replay_allowed(session, task):
                    continue
                if task.status == "queued" and not task.owner:
                    latest = await session.scalar(select(func.max(Outbox.created_at)).where(Outbox.task_id == task.id))
                    if latest is None or latest < now()-timedelta(seconds=5):
                        session.add(Outbox(id=uuid4(), task_id=task.id))

    @staticmethod
    async def reserved(session, task_id):
        return (await session.scalars(select(ModelOperation).where(ModelOperation.task_id == task_id, ModelOperation.state == "reserved"))).all()

    @staticmethod
    async def release_reservations(session, task, operations):
        for op in operations:
            if not op.is_mock:
                continue  # Real dispatch reservations survive cancellation/unknown outcomes.
            quota = await tenant_usage(session,task.tenant_id,op.reservation_day)
            # Mock only: no supplier charge. Preserve explicit simulated input accounting.
            op.state, op.finished_at = "cancelled", now()
            op.cost = Decimal(op.input_tokens) * Decimal("0.000001")
            task.tokens_reserved -= op.reserved_tokens
            task.cost_reserved -= op.reserved_cost
            task.tokens_used += op.input_tokens
            task.cost_used += op.cost
            quota.tokens_reserved -= op.reserved_tokens
            quota.cost_reserved -= op.reserved_cost
            quota.tokens_used += op.input_tokens
            quota.cost_used += op.cost

    async def claim(self, task_id):
        async with self.connections.sessions() as session, session.begin():
            # Project-scoped advisory lock serializes global capacity decisions.
            await session.execute(text("SELECT pg_advisory_xact_lock(472902)"))
            task = await locked_task(session, task_id)
            if task.options.get('workflow') == 'sandbox' and not await admission_available(session):
                return None
            if not await task_replay_allowed(session, task):
                return None
            if not task.is_mock and task.options.get('workflow') != 'sandbox':
                require_permit_task(task)
                if task.options.get('workflow') == 'permit_test':
                    from app.domain.permits import ExecutionPermit
                    p = await session.get(ExecutionPermit, UUID(task.options['permit_id']))
                    if (not self.permit_identity or not p or p.status != 'ISSUED'
                            or p.authorized_worker_identity != self.permit_identity.identity):
                        return None
            if not task.is_mock and task.options.get("workflow") not in {"sandbox", "agents", "chat", "permit_test"}:
                task.status, task.error_code = "failed", "REAL_MODE_UNAVAILABLE"
                event(session, task, "status", {"status":task.status,"error_code":task.error_code})
                return None
            if task.status != "queued" or task.deadline <= now() or (task.owner and task.lease_until and task.lease_until > now()):
                return None
            if task.attempts >= 3 and task.is_mock:
                task.status, task.error_code = "failed", "RECOVERY_LIMIT"
                await self.release_reservations(session, task, await self.reserved(session, task.id))
                event(session, task, "status", {"status":task.status})
                return None
            running = (await session.scalars(select(AgentTask).where(AgentTask.owner.is_not(None), AgentTask.lease_until > now()))).all()
            if len(running) >= 4 or sum(t.tenant_id == task.tenant_id for t in running) >= 2:
                return None
            task.owner, task.fence = self.owner, task.fence + 1
            task.lease_until = now()+timedelta(seconds=LEASE_SECONDS)
            task.status, task.attempts = "running", task.attempts + 1
            event(session, task, "status", {"status":"running","attempt":task.attempts})
            return str(task.tenant_id), task.fence

    async def heartbeat(self):
        if self.permit_identity is not None:
            from app.services.execution_permits import PermitService
            await PermitService(self.connections, self.settings).heartbeat(self.permit_identity)
        await self.connections.redis.set(f"agentforge:p2:worker:{self.owner}", "up", ex=20)
        async with self.connections.sessions() as session, session.begin():
            rows = (await session.scalars(select(AgentTask).where(AgentTask.owner == self.owner, AgentTask.status.in_(["running","waiting_approval"])).with_for_update())).all()
            for task in rows:
                if not await task_replay_allowed(session, task):
                    continue
                task.lease_until = now()+timedelta(seconds=LEASE_SECONDS)

    async def finish(self, task_id, fence, result=None, error=None, *, stopping=False):
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, task_id)
            if task.owner != self.owner or task.fence != fence:
                return
            if not await task_replay_allowed(session, task):
                return  # A late callback must not rewrite/release unknown history.
            if not task.is_mock and task.options.get("workflow")=="sandbox":
                execution=(await session.scalars(select(SandboxExecution).where(SandboxExecution.task_id==task.id).with_for_update())).one()
                if execution.status in EXECUTION_TERMINAL:
                    task.status="failed" if execution.status in {"rejected","output_limit"} else execution.status
                    task.error_code=execution.failure_reason
                    task.result={"is_mock":False,"summary":"[DOCKER] Execution "+execution.status,"execution_id":str(execution.id)}
                elif task.status=="waiting_approval": pass
                elif (task.deadline<=now() or task.status=="cancel_requested") and execution.launch_claimed_at:
                    task.status="cancel_requested"
                elif error and execution.launch_claimed_at is None:
                    execution.status=task.status="failed"
                    execution.failure_reason=task.error_code=error
                    await settle_budget(session,execution)
                else:
                    task.status="queued"
                    session.add(Outbox(id=uuid4(),task_id=task.id))
                task.owner,task.lease_until=None,None
                event(session,task,"status",{"status":task.status,"cleanup_status":execution.cleanup_status})
                return
            if task.deadline <= now():
                task.status, task.error_code = "timed_out", "TASK_TIMEOUT"
            elif task.status == "cancel_requested":
                task.status, task.error_code = "cancelled", "TASK_CANCELLED"
            elif task.status in {"waiting_approval", "waiting_tools", "paused"}:
                pass
            elif task.status == "pause_requested":
                task.status = "paused"
            elif stopping:
                task.status = "queued"
                session.add(Outbox(id=uuid4(), task_id=task.id))
            elif error:
                task.status = "limit_exceeded" if error == "TASK_LIMIT" else ("needs_reconciliation" if error == "MODEL_OUTCOME_UNKNOWN" else "failed")
                task.error_code = error
            elif not task.is_mock:
                task.status = 'succeeded'
                final_id = result.get('chat') or result.get('review')
                final = await session.get(ModelOperation, (task.id, final_id)) if final_id else None
                task.result = {'is_mock': False, 'summary': (final.result or {}).get('summary', '') if final else '',
                    'coder': result.get('coder'), 'researcher': result.get('researcher'), 'reviewer': result.get('review'),
                    'evidence_status': 'provider_output_not_external_verification'}
            else:
                task.status = "succeeded"
                task.result = {"is_mock":True,"summary":"[MOCK] Workflow completed; no real model, tool or code execution",
                               "coder":result.get("coder"),"researcher":result.get("researcher"),"reviewer":result.get("review")}
            if task.status in TERMINAL:
                await self.release_reservations(session, task, await self.reserved(session, task_id))
                approval = (await session.scalars(select(TaskApproval).where(TaskApproval.task_id == task.id,TaskApproval.status == "pending"))).one_or_none()
                if approval:
                    approval.status = "expired" if task.status == "timed_out" else "cancelled"
            task.owner, task.lease_until = None, None
            event(session, task, "status", {"status":task.status,"error_code":task.error_code})

    async def execute(self, task_id, tenant_id, fence, message_id):
        try:
            saver = PostgresTaskSaver(self.connections, tenant_id, task_id, self.owner, fence)
            async with self.connections.sessions() as session:
                task=await session.get(AgentTask,task_id)
                if not await task_replay_allowed(session, task):
                    return  # Redis delivery or a stale in-flight callback is not authority.
                sandbox=not task.is_mock and task.options.get("workflow")=="sandbox"
            if not task.is_mock and task.options.get('workflow') == 'permit_test':
                from app.services.execution_permits import PermitService
                await PermitService(self.connections, self.settings).execute(UUID(task.options['permit_id']), self.permit_identity, fence)
                return
            if sandbox:
                from app.services.orchestration.sandbox_graph import build_sandbox_graph
                graph=build_sandbox_graph(self.connections,self.settings,task_id,tenant_id,self.owner,fence,saver)
            else:
                from app.services.orchestration.real_runtime import RealRuntime
                runtime = (Runtime if task.is_mock else RealRuntime)(self.connections, self.settings, task_id, tenant_id, self.owner, fence)
                if task.options.get('workflow') == 'chat':
                    from app.services.orchestration.chat_graph import build_chat_graph
                    graph = build_chat_graph(runtime, saver)
                else:
                    graph = build_graph(runtime, saver, priorities={role: cfg.get('priority', 50) for role, cfg in task.model_snapshot.items()})
            config = {"configurable":{"thread_id":str(task_id)},"recursion_limit":100,"callbacks":[]}
            saved = await saver.aget_tuple(config)
            resume = None
            if saved:
                state = await graph.aget_state(config)
                resume = Command(resume=True) if state.tasks and any(getattr(t,"interrupts",()) for t in state.tasks) else None
            value = resume if saved else {"task_id":str(task_id),"round":0}
            with tracing_context(enabled=False):
                result = await graph.ainvoke(value, config)
            await self.finish(task_id, fence, result=result)
        except asyncio.CancelledError:
            await self.finish(task_id, fence, stopping=True)
            raise
        except AppError as exc:
            if exc.code in MAINTENANCE_ERRORS:
                # Defer only an unlaunched task claimed by this exact fence.
                # Never finish/release UNKNOWN reservations as a frozen failure.
                async with self.connections.sessions() as session, session.begin():
                    task = await locked_task(session, task_id)
                    execution = (await session.scalars(select(SandboxExecution).where(SandboxExecution.task_id == task_id))).one_or_none()
                    if (execution and execution.launch_claimed_at is None and task.owner == self.owner
                            and task.fence == fence and task.status == 'running'):
                        task.status, task.owner, task.lease_until = 'queued', None, None
                        event(session, task, 'sandbox_maintenance_deferred', {'execution_id': str(execution.id)})
            else:
                await self.finish(task_id, fence, error=exc.code)
        except Exception as exc:
            logger.error("request_failed", extra={"error_type":type(exc).__name__})
            # A failed infrastructure operation is retried from durable state, bounded by attempts.
            from sqlalchemy.exc import SQLAlchemyError
            from redis.exceptions import RedisError
            if isinstance(exc, (SQLAlchemyError, RedisError, OSError)):
                await self.finish(task_id, fence, stopping=True)
            else:
                await self.finish(task_id, fence, error="WORKFLOW_FAILED")
        finally:
            try:
                await self.connections.redis.xack(STREAM, GROUP, message_id)
            except Exception:
                pass  # PostgreSQL task/outbox remains the recovery source.

    async def tick(self):
        for task_id, future in list(self.active.items()):
            if future.done():
                if not future.cancelled() and future.exception():
                    logger.error("request_failed", extra={"error_type":type(future.exception()).__name__})
                self.active.pop(task_id)
        await self.sweep()
        await self.heartbeat()
        await self.publish()
        if len(self.active) >= 2:
            return
        reclaimed = await self.connections.redis.xautoclaim(STREAM, GROUP, self.owner, min_idle_time=1000, count=5)
        messages = reclaimed[1]
        if not messages:
            batches = await self.connections.redis.xreadgroup(GROUP, self.owner, {STREAM:">"}, count=2, block=100)
            messages = batches[0][1] if batches else []
        for message_id, body in messages:
            if len(self.active) >= 2:
                break
            try:
                task_id = UUID(body["task_id"])
                claim = None if str(task_id) in self.active else await self.claim(task_id)
                if claim and len(self.active) < 2:
                    tenant_id, fence = claim
                    self.active[str(task_id)] = asyncio.create_task(self.execute(task_id, tenant_id, fence, message_id))
                else:
                    await self.connections.redis.xack(STREAM, GROUP, message_id)
            except AppError:
                await self.connections.redis.xack(STREAM, GROUP, message_id)

    async def close(self):
        futures = list(self.active.values())
        for future in futures:
            future.cancel()
        await asyncio.gather(*futures, return_exceptions=True)
        await self.connections.redis.delete(f"agentforge:p2:worker:{self.owner}")
        if self.permit_identity is not None:
            from app.services.execution_permits import PermitService
            try: await PermitService(self.connections, self.settings).heartbeat(self.permit_identity, revoke=True)
            except AppError: pass

    async def run(self):
        try:
            while True:
                try:
                    await self.initialize()  # Idempotent; recover a missing group after Redis data loss.
                    await self.tick()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("dependency_failed", extra={"dependency":"worker","error_type":type(exc).__name__})
                await asyncio.sleep(0.25)
        finally:
            await self.close()
