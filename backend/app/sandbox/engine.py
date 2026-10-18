"""Durable trusted runner: one launch intent, no automatic replay of uncertain code."""
import asyncio
from datetime import timedelta
from decimal import Decimal
from queue import Queue, Empty
from threading import Event
from uuid import UUID, uuid4
from sqlalchemy import select, func, text
from app.domain.tasks import AgentTask, TaskApproval
from app.domain.sandbox import SandboxExecution, SandboxDailyUsage
from app.services.tasks import now, event, check_lease, locked_task
from app.services.context import redact
from app.core.errors import AppError
from app.sandbox.driver import DockerDriver
from app.sandbox.policy import (TERMINAL, OWNER_LABEL, EXECUTION_LABEL, SUMMARY_LIMIT, PolicyViolation, validate_execution, assert_runner_lease)
from app.schemas.sandbox import POLICY_VERSION
from app.domain.sandbox_ownership import SandboxOwnership
from app.sandbox.ownership import OwnershipCoordinator, ThreadAuthority, labels as ownership_labels
from app.services.sandbox_maintenance import require_open
from app.sandbox.history import require_replayable


class SandboxRunner:
    def __init__(self, connections, settings, driver=None):
        self.connections, self.settings = connections, settings
        self.driver = driver or DockerDriver(settings.sandbox_image_id)
        self.owner = "runner-" + uuid4().hex
        self.active = {}
        self.controls = {}
        self.blocked = True
        self.closing = False
        self.reconciler = None
        self.ownership = OwnershipCoordinator(connections, settings, self.owner)

    async def start(self):
        try:
            await self.ownership.claim()
            self.driver.authority = ThreadAuthority(self.ownership, asyncio.get_running_loop())
        except Exception:
            self.blocked = True
            return  # No registration/clearance: no Docker discovery or mutation.
        await self.reconcile()
        self.reconciler = asyncio.create_task(self._reconcile_loop())

    async def close(self):
        self.closing = True
        for stop in self.controls.values():
            stop.set()
        if self.reconciler:
            self.reconciler.cancel()
            await asyncio.gather(self.reconciler, return_exceptions=True)
        if self.active:
            await asyncio.gather(*list(self.active.values()), return_exceptions=True)
        if self.ownership.scope is not None:
            try:
                await self.ownership.release()
            except Exception:
                self.blocked = True

    async def _reconcile_loop(self):
        while not self.closing:
            await asyncio.sleep(5)
            await self.reconcile()

    async def reconcile(self):
        """Discover by scope, authorize against durable exact ownership before IO."""
        try:
            await self.ownership.refresh()
            await asyncio.to_thread(self.driver.health)
            containers = await asyncio.to_thread(self.driver.owned)
            clean = True
            for container in containers:
                labels = container.labels or {}
                try:
                    execution_id = UUID(labels.get(EXECUTION_LABEL, ""))
                except (ValueError, TypeError):
                    clean = False
                    await self.ownership.refuse_resource(None, container.id)
                    continue
                if container.name != "agentforge-p3-exec-" + execution_id.hex or labels.get(OWNER_LABEL) != POLICY_VERSION:
                    clean = False  # Do not delete containers failing ownership checks.
                    await self.ownership.refuse_resource(execution_id, container.id)
                    continue
                if execution_id in self.active:
                    continue
                async with self.connections.sessions() as session:
                    row = await session.get(SandboxExecution, execution_id)
                    record = await session.get(SandboxOwnership, execution_id)
                    live = row and row.runner_lease_until and row.runner_lease_until > now() and row.status not in TERMINAL
                if (not row or not record or not self.ownership.matches(record)
                        or record.container_id != container.id
                        or any(labels.get(key) != value for key, value in ownership_labels(record).items())):
                    clean = False
                    await self.ownership.refuse_resource(execution_id, container.id)
                    continue  # Missing/forged/foreign records NEVER grant cleanup.
                if live:
                    continue  # Another trusted runner owns the live lease.
                removed = await asyncio.to_thread(self.driver.remove, container)
                clean = clean and removed
            async with self.connections.sessions() as session:
                stale = list((await session.scalars(select(SandboxExecution).join(SandboxOwnership,
                    SandboxOwnership.execution_id == SandboxExecution.id).where(
                    SandboxOwnership.runner_instance_id == self.ownership.scope.runner_instance_id,
                    SandboxOwnership.runner_generation == self.ownership.scope.runner_generation,
                    SandboxOwnership.project_id == self.ownership.scope.project_id,
                    SandboxOwnership.sandbox_namespace == self.ownership.scope.sandbox_namespace,
                    SandboxExecution.launch_claimed_at.is_not(None),
                    (SandboxExecution.status.not_in(TERMINAL) | (SandboxExecution.cleanup_status == "unconfirmed")),
                    (SandboxExecution.runner_lease_until.is_(None) | (SandboxExecution.runner_lease_until <= now()))))).all())
            for row in stale:
                if row.id not in self.active:
                    await self._mark_uncertain(row.id)
            async with self.connections.sessions() as session:
                unresolved = await session.scalar(select(func.count()).select_from(SandboxExecution).where(
                    (SandboxExecution.cleanup_status == "unconfirmed") |
                    ((SandboxExecution.status == "needs_reconciliation") & (SandboxExecution.cleanup_status != "removed"))))
            self.blocked = not clean or bool(unresolved)
        except Exception:
            self.blocked = True

    async def _mark_uncertain(self, execution_id):
        async with self.connections.sessions() as session:
            snapshot = await session.get(SandboxExecution, execution_id)
            ownership = await session.get(SandboxOwnership, execution_id)
            if snapshot is None or not ownership or not self.ownership.matches(ownership):
                self.blocked = True
                return
            task_id = snapshot.task_id
        absent = await self._absence(execution_id)
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, task_id)
            await self.ownership._identity(session)
            row = await session.get(SandboxExecution, execution_id, with_for_update=True)
            ownership = await session.get(SandboxOwnership, execution_id)
            if not ownership or not self.ownership.matches(ownership):
                self.blocked = True
                return
            if not row or (row.status in TERMINAL and row.cleanup_status != "unconfirmed") or (row.runner_lease_until and row.runner_lease_until > now()):
                return
            row.status = "needs_reconciliation"
            row.failure_reason = row.failure_reason or "RUNNER_RESTART_AFTER_LAUNCH_INTENT"
            row.cleanup_status = "removed" if absent else "unconfirmed"
            row.finished_at, row.runner_lease_until = now(), None
            from app.services.sandbox import settle_budget
            if row.cleanup_status == "removed":
                await settle_budget(session, row)  # Conservative full reservation, idempotent.
            event(session, task, "sandbox_reconciliation_required", {"execution_id": str(row.id),
                "cleanup_status": row.cleanup_status, "failure_reason": row.failure_reason})

    async def _absence(self, execution_id):
        try:
            async with self.connections.sessions() as session:
                record = await session.get(SandboxOwnership, execution_id)
                if not record or not self.ownership.matches(record):
                    return False
                container_id = record.container_id
            return await asyncio.to_thread(self.driver.absence, execution_id, container_id)
        except Exception:
            return False

    async def dispatch(self, request):
        if self.closing:
            raise AppError("RUNNER_UNAVAILABLE", "Sandbox runner is stopping", 503)
        # Existing durable results are readable while capacity/health is blocked.
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, request.task_id)
            row = await session.get(SandboxExecution, request.execution_id, with_for_update=True)
            if row is None or row.task_id != task.id:
                raise AppError("EXECUTION_NOT_FOUND", "Sandbox execution not found", 404)
            await require_replayable(session, row)
            if row.launch_claimed_at is not None or row.status in TERMINAL:
                return {"execution_id": str(row.id), "status": row.status}
            await require_open(session)
            check_lease(task, request.owner, request.fence)
            approval = await session.get(TaskApproval, row.approval_reference)
            try:
                validate_execution(row, approval, task, self.settings)
                if row.parent_context:
                    from app.services.agent_tools import authorize_parent
                    await authorize_parent(session, row.tenant_id, row.parent_context, sandbox=True)
            except PolicyViolation as exc:
                raise AppError(str(exc), "Sandbox execution is not authorized", 403) from None
            if self.blocked:
                raise AppError("RUNNER_UNAVAILABLE", "Sandbox runner is unavailable or requires reconciliation", 503)
            # Database-wide lock protects all runner processes, not only this instance.
            await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('agentforge:p3:capacity',0))"))
            unresolved = await session.scalar(select(func.count()).select_from(SandboxExecution).where(
                (SandboxExecution.cleanup_status == "unconfirmed") |
                ((SandboxExecution.status == "needs_reconciliation") & (SandboxExecution.cleanup_status != "removed"))))
            if unresolved:
                self.blocked = True
                raise AppError("RUNNER_UNAVAILABLE", "Sandbox cleanup requires reconciliation", 503)
            active_stmt = select(func.count()).select_from(SandboxExecution).where(
                SandboxExecution.launch_claimed_at.is_not(None), SandboxExecution.cleanup_status.in_(["pending", "unconfirmed"]))
            total = await session.scalar(active_stmt)
            tenant = await session.scalar(active_stmt.where(SandboxExecution.tenant_id == row.tenant_id))
            if total >= self.settings.sandbox_max_concurrency or tenant >= self.settings.sandbox_tenant_concurrency:
                raise AppError("SANDBOX_CAPACITY", "Sandbox concurrency limit reached", 429)
            usage = await session.get(SandboxDailyUsage, (row.tenant_id, row.budget_day), with_for_update=True)
            if not usage or usage.cpu_seconds_reserved + usage.cpu_seconds_used > self.settings.sandbox_daily_cpu_seconds:
                raise AppError("SANDBOX_BUDGET", "Sandbox tenant daily quota reached", 409)
            # Both ownership and launch intent commit in this transaction.
            # Issue BEFORE marking launched: an already-launched unowned row
            # is historical quarantine, never an invitation to adopt it.
            await self.ownership.issue(session, row)
            row.launch_claimed_at, row.runner_owner = now(), self.owner
            row.runner_lease_until = now() + timedelta(seconds=15)
            row.container_name, row.image_id = "agentforge-p3-exec-" + row.id.hex, self.settings.sandbox_image_id
            row.status, row.cleanup_status = "starting", "pending"
            event(session, task, "sandbox_launch_claimed", {"execution_id": str(row.id), "code_hash": row.code_hash,
                "policy_version": POLICY_VERSION, "timeout_seconds": row.timeout_seconds, "resource_limits": row.resource_limits})
            inputs = row.code, row.resource_limits, row.timeout_seconds
        # Intent committed before Docker sees the request. Crash after this point
        # becomes uncertain, never an excuse to run the same code again.
        stop = Event()
        self.controls[request.execution_id] = stop
        operation = asyncio.create_task(self._run(request, inputs, stop))
        self.active[request.execution_id] = operation
        operation.add_done_callback(lambda task: self._forget(request.execution_id, task))
        return {"execution_id": str(request.execution_id), "status": "starting"}

    def _forget(self, execution_id, task):
        self.active.pop(execution_id, None)
        self.controls.pop(execution_id, None)
        if not task.cancelled():
            task.exception()  # Consume safe persistence failures; reconcile owns recovery.

    async def _authorize_boundary(self, request, container_id=None, started=False):
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, request.task_id)
            await self.ownership._identity(session)
            row = await session.get(SandboxExecution, request.execution_id, with_for_update=True)
            assert_runner_lease(row, self.owner, now())
            if not started:
                check_lease(task, request.owner, request.fence)
                validate_execution(row, await session.get(TaskApproval, row.approval_reference), task, self.settings)
                if row.parent_context:
                    from app.services.agent_tools import authorize_parent
                    await authorize_parent(session, row.tenant_id, row.parent_context, sandbox=True)
            if container_id:
                if row.container_id and row.container_id != container_id:
                    raise PolicyViolation('SANDBOX_CONTAINER_ID_MISMATCH')
                row.container_id = container_id
            if started:
                row.status, row.started_at = "running", now()
                event(session, task, "sandbox_started", {"execution_id": str(row.id), "container_id": row.container_id})
            row.runner_lease_until = now() + timedelta(seconds=15)

    async def _monitor(self, request):
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, request.task_id)
            try:
                await self.ownership._identity(session)
            except PolicyViolation:
                return 'RUNNER_OWNERSHIP_LOST'
            row = await session.get(SandboxExecution, request.execution_id, with_for_update=True)
            try:
                assert_runner_lease(row, self.owner, now())
            except PolicyViolation:
                return "RUNNER_LEASE_LOST"
            if row.parent_context:
                from app.services.agent_tools import authorize_parent
                try:
                    await authorize_parent(session, row.tenant_id, row.parent_context, sandbox=True)
                except AppError:
                    return 'AGENT_PARENT_STOPPED'
            if task.deadline <= now():
                return "TASK_TIMEOUT"
            if task.status in {"cancel_requested", "cancelled"}:
                return "TASK_CANCELLED"
            if task.status not in {"running", "queued"}:
                return "TASK_STOPPED"
            # Independent runner lease; the Worker may restart/release its own lease.
            row.runner_lease_until = now() + timedelta(seconds=15)
            return None

    async def _run(self, request, inputs, stop):
        messages, permit = Queue(maxsize=8), Event()
        code, limits, timeout = inputs
        operation = asyncio.create_task(asyncio.to_thread(self.driver.run, request.execution_id, code, limits, timeout, stop, permit, messages))
        stop_reason = None
        last_monitor = 0.0
        try:
            while not operation.done() or not messages.empty():
                try:
                    kind, value = messages.get_nowait()
                except Empty:
                    kind = None
                if kind == "created":
                    await asyncio.wait_for(self._authorize_boundary(request, container_id=value), self.settings.dependency_timeout)
                    permit.set()
                elif kind == "attested":
                    await asyncio.wait_for(self._authorize_boundary(request), self.settings.dependency_timeout)
                    permit.set()
                elif kind == "started":
                    await asyncio.wait_for(self._authorize_boundary(request, started=True), self.settings.dependency_timeout)
                clock = asyncio.get_running_loop().time()
                if clock - last_monitor >= 0.25:
                    stop_reason = await asyncio.wait_for(self._monitor(request), self.settings.dependency_timeout)
                    last_monitor = clock
                    if stop_reason:
                        stop.set()
                await asyncio.sleep(0.05)
        except Exception:
            stop_reason = "STATE_VALIDATION_FAILED"
            stop.set()
        result = await operation
        if stop_reason and result.status != "needs_reconciliation":
            result.status = "timed_out" if stop_reason == "TASK_TIMEOUT" else "cancelled" if stop_reason == "TASK_CANCELLED" else "failed"
            result.failure_reason = stop_reason
        if result.cleanup_status == "unconfirmed":
            self.blocked = True
        await self._finish(request, result)

    async def _finish(self, request, result):
        # Sanitize bounded untrusted output before holding any business-row lock.
        # A future sanitizer regression must not pin task cancellation/checkpoints.
        def summary(raw):
            return redact(raw.decode(errors="replace"), self.settings).encode()[:SUMMARY_LIMIT].decode(errors="ignore")
        stdout_summary, stderr_summary = await asyncio.gather(
            asyncio.to_thread(summary, result.stdout), asyncio.to_thread(summary, result.stderr))
        async with self.connections.sessions() as session, session.begin():
            task = await locked_task(session, request.task_id)
            try:
                await self.ownership._identity(session)
            except PolicyViolation:
                self.blocked = True
                return
            row = await session.get(SandboxExecution, request.execution_id, with_for_update=True)
            if row.runner_owner != self.owner or row.status in TERMINAL:
                self.blocked = self.blocked or row.cleanup_status == "unconfirmed"
                return
            if row.runner_lease_until is None or row.runner_lease_until <= now():
                # A late finisher cannot revive an expired lease or publish success.
                # Cleanup evidence remains useful; the launch intent stays immutable.
                result.status, result.failure_reason = "needs_reconciliation", "RUNNER_LEASE_LOST"
            row.status, row.exit_code, row.failure_reason = result.status, result.exit_code, result.failure_reason
            row.container_id = result.container_id or row.container_id
            row.stdout_summary, row.stderr_summary = stdout_summary, stderr_summary
            row.duration_ms, row.resource_usage, row.cleanup_status = result.duration_ms, result.resource_usage, result.cleanup_status
            row.finished_at, row.runner_lease_until = now(), None
            from app.services.sandbox import settle_budget
            if row.cleanup_status in {"removed", "not_created"}:
                await settle_budget(session, row)  # Samples are observability, never billing.
            event(session, task, "sandbox_completed", {"execution_id": str(row.id), "status": row.status,
                "exit_code": row.exit_code, "cleanup_status": row.cleanup_status, "duration_ms": row.duration_ms,
                "resource_usage": row.resource_usage, "failure_reason": row.failure_reason})
