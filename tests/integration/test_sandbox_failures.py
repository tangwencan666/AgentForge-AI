"""Opt-in real Runner capacity and isolated unavailable-daemon acceptance.

Root stops the demo Worker before these tests. The fixtures create only their own
PG tasks/approvals and heartbeat keys. Cleanup is requested through the trusted
service; this test never removes a container or changes Docker configuration.
"""
import asyncio
from datetime import timedelta
import os
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.domain.sandbox import SandboxExecution
from app.domain.tasks import AgentTask, TaskEvent
from app.repositories.connections import Connections
from app.schemas.sandbox import SandboxCreate
from app.schemas.tasks import ApprovalDecision
from app.services.sandbox import EXECUTION_TERMINAL, SandboxService
from app.services.tasks import now
from app.workers.engine import Worker

pytestmark = [pytest.mark.integration, pytest.mark.sandbox]


class RealHarness:
    def __init__(self, settings, connections):
        self.settings, self.connections = settings, connections
        self.service = SandboxService(connections, settings)
        self.workers = []
        self.executions = []
        self.claims = []

    async def worker(self):
        worker = Worker(self.connections, self.settings)
        await worker.initialize()
        self.workers.append(worker)
        return worker

    async def approved(self, tenant, code="import time;time.sleep(8)"):
        row = await self.service.create(tenant, uuid4(), SandboxCreate(code=code, timeout_seconds=12))
        self.executions.append((UUID(row["execution_id"]), tenant))
        worker = await self.worker()
        claim = await worker.claim(UUID(row["task_id"]))
        assert claim is not None, "Test task could not claim its own approval Worker lease"
        # Real LangGraph interrupt and PostgreSQL checkpoint; no fake approval row.
        await worker.execute(UUID(row["task_id"]), claim[0], claim[1], "0-0")
        async with self.connections.sessions() as session:
            task = await session.get(AgentTask, UUID(row["task_id"]))
            assert task.status == "waiting_approval" and task.owner is None
        await self.service.decide(UUID(row["execution_id"]), tenant,
            ApprovalDecision(decision="approved", operation_hash=row["operation_hash"]))
        return row

    async def claim(self, row):
        worker = await self.worker()
        task_id = UUID(row["task_id"])
        claim = await worker.claim(task_id)
        assert claim is not None, "Test task could not obtain an authorized Worker lease"
        self.claims.append((worker, task_id, claim[1]))
        return worker, {"task_id": row["task_id"], "execution_id": row["execution_id"],
                        "owner": worker.owner, "fence": claim[1]}

    async def refresh_leases(self):
        for worker in self.workers:
            await worker.heartbeat()

    async def wait_running(self, rows, timeout=12):
        until = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < until:
            await self.refresh_leases()
            values = []
            async with self.connections.sessions() as session:
                for row in rows:
                    values.append(await session.get(SandboxExecution, UUID(row["execution_id"])))
                if all(row.status == "running" and row.container_id for row in values):
                    return
                if any(row.status in EXECUTION_TERMINAL for row in values):
                    raise AssertionError("A capacity probe ended before simultaneous execution was observed")
            await asyncio.sleep(.08)
        raise AssertionError("Real Docker capacity probes did not all enter running state")

    async def no_containers(self, rows):
        import docker
        def inspect():
            client = docker.from_env(timeout=5)
            try:
                return [container for row in rows for container in client.containers.list(all=True,
                    filters={"label": "agentforge.sandbox.execution=" + row["execution_id"]})]
            finally:
                client.close()
        assert not await asyncio.to_thread(inspect), "A test execution container remains after trusted cleanup"

    async def cleanup(self):
        for execution_id, tenant in self.executions:
            await self.service.cancel(execution_id, tenant)
        for worker, task_id, fence in self.claims:
            await worker.finish(task_id, fence, stopping=True)
        until = asyncio.get_running_loop().time() + 25
        incomplete = []
        while asyncio.get_running_loop().time() < until:
            incomplete = []
            for execution_id, tenant in self.executions:
                row = await self.service.get(execution_id, tenant)
                if row["status"] not in EXECUTION_TERMINAL or row["cleanup_status"] not in {"removed", "not_created"}:
                    incomplete.append(row["execution_id"])
            if not incomplete:
                break
            await asyncio.sleep(.1)
        assert not incomplete, "Trusted cleanup of this test's execution records was not confirmed"
        await self.no_containers([{"execution_id": str(execution_id)} for execution_id, _ in self.executions])


@pytest.fixture
async def real_runner():
    if os.environ.get("AGENTFORGE_RUN_SANDBOX") != "1":
        pytest.skip("Explicit real Docker sandbox opt-in required")
    settings = Settings()
    connections = Connections(settings)
    harness = RealHarness(settings, connections)
    try:
        yield harness
    finally:
        try:
            await harness.cleanup()
        finally:
            for worker in harness.workers:
                await worker.close()
            await connections.close()


def control_headers(settings):
    return {"X-AgentForge-Runner-Token": settings.sandbox_runner_token.get_secret_value()}


async def dispatch(client, url, headers, request):
    return await client.post(url + "/internal/executions/" + request["execution_id"] + "/dispatch",
        headers=headers, json=request)


async def test_real_runner_tenant_and_global_capacity_with_live_containers(real_runner):
    harness = real_runner
    assert harness.settings.sandbox_max_concurrency == 4
    assert harness.settings.sandbox_tenant_concurrency == 2
    tenant_a, tenant_b, tenant_c = str(uuid4()), str(uuid4()), str(uuid4())
    rows = [await harness.approved(tenant) for tenant in [tenant_a, tenant_a, tenant_b, tenant_a, tenant_b, tenant_c]]
    headers = control_headers(harness.settings)
    async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
        first = [await harness.claim(row) for row in rows[:3]]
        responses = await asyncio.gather(*[
            dispatch(client, harness.settings.sandbox_runner_url, headers, request) for _, request in first])
        assert all(response.status_code == 202 for response in responses)
        await harness.wait_running(rows[:3])
        # Legitimate Worker restart releases its graph lease, not the live Runner
        # lease. This proves the Runner enforces its own tenant container limit.
        await first[0][0].finish(UUID(rows[0]["task_id"]), first[0][1]["fence"], stopping=True)
        third_a_worker, third_a = await harness.claim(rows[3])
        tenant_denied = await dispatch(client, harness.settings.sandbox_runner_url, headers, third_a)
        assert tenant_denied.status_code == 429
        assert tenant_denied.json()["error"]["code"] == "SANDBOX_CAPACITY"
        async with harness.connections.sessions() as session:
            denied = await session.get(SandboxExecution, UUID(rows[3]["execution_id"]))
            assert denied.launch_claimed_at is None and denied.container_id is None
        await harness.service.cancel(UUID(rows[3]["execution_id"]), tenant_a)
        await third_a_worker.finish(UUID(rows[3]["task_id"]), third_a["fence"], stopping=True)

        second_b_worker, second_b = await harness.claim(rows[4])
        accepted = await dispatch(client, harness.settings.sandbox_runner_url, headers, second_b)
        assert accepted.status_code == 202
        active_rows = [*rows[:3], rows[4]]
        await harness.wait_running(active_rows)
        import docker
        def count_live():
            docker_client = docker.from_env(timeout=5)
            try:
                return sum(len(docker_client.containers.list(filters={"label":
                    "agentforge.sandbox.execution=" + row["execution_id"]})) for row in active_rows)
            finally:
                docker_client.close()
        assert await asyncio.to_thread(count_live) == 4
        await first[2][0].finish(UUID(rows[2]["task_id"]), first[2][1]["fence"], stopping=True)
        _, global_request = await harness.claim(rows[5])
        global_denied = await dispatch(client, harness.settings.sandbox_runner_url, headers, global_request)
        assert global_denied.status_code == 429
        assert global_denied.json()["error"]["code"] == "SANDBOX_CAPACITY"
        async with harness.connections.sessions() as session:
            denied = await session.get(SandboxExecution, UUID(rows[5]["execution_id"]))
            assert denied.launch_claimed_at is None and denied.container_id is None


async def test_real_isolated_unavailable_runner_refuses_without_launch_or_host_fallback(real_runner):
    harness = real_runner
    # Root creates this dedicated Linux control-plane container with a nonexistent
    # DOCKER_HOST and no socket mount. The shared daemon is never stopped.
    from urllib.parse import urlsplit
    failure_url = f"http://127.0.0.1:{urlsplit(harness.settings.sandbox_runner_url).port + 1}"
    row = await harness.approved(harness.settings.tenant_id,
        "print('unavailable runner must never execute this code')")
    _, request = await harness.claim(row)
    headers = control_headers(harness.settings)
    async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
        status = await client.get(failure_url + "/internal/status", headers=headers)
        assert status.status_code == 200
        assert status.json()["available"] is False and status.json()["blocked"] is True
        response = await dispatch(client, failure_url, headers, request)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "RUNNER_UNAVAILABLE"
    async with harness.connections.sessions() as session:
        persisted = await session.get(SandboxExecution, UUID(row["execution_id"]))
        assert persisted.launch_claimed_at is None and persisted.container_id is None
        assert persisted.stdout_summary == persisted.stderr_summary == ""
    await harness.no_containers([row])


async def test_real_expired_runner_lease_cannot_revive_with_live_worker_lease(real_runner):
    harness = real_runner
    row = await harness.approved(harness.settings.tenant_id, "import time;time.sleep(5)")
    worker, request = await harness.claim(row)
    execution_id, task_id = UUID(row["execution_id"]), UUID(row["task_id"])
    async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
        response = await dispatch(client, harness.settings.sandbox_runner_url,
            control_headers(harness.settings), request)
        assert response.status_code == 202
    await harness.wait_running([row])
    await worker.heartbeat()
    async with harness.connections.sessions() as session, session.begin():
        execution = await session.get(SandboxExecution, execution_id, with_for_update=True)
        task = await session.get(AgentTask, task_id)
        assert execution.status == "running" and execution.container_id
        assert task.owner == worker.owner and task.lease_until > now()
        original_intent, original_container = execution.launch_claimed_at, execution.container_id
        assert original_intent is not None
        # Controlled failure injection changes only this test's Runner lease. The
        # Worker retains valid authority; it must not revive expired Runner authority.
        execution.runner_lease_until = now() - timedelta(seconds=1)
    until = asyncio.get_running_loop().time() + 15
    result = None
    while asyncio.get_running_loop().time() < until:
        await worker.heartbeat()
        result = await harness.service.get(execution_id, harness.settings.tenant_id)
        if result["status"] in EXECUTION_TERMINAL:
            break
        await asyncio.sleep(.08)
    assert result is not None and result["status"] == "needs_reconciliation"
    assert result["cleanup_status"] == "removed"
    # The monitor normally detects this first; the periodic stale-lease reconciler
    # can win the race and uses its explicit existing launch-intent failure reason.
    assert result["failure_reason"] in {"RUNNER_LEASE_LOST", "RUNNER_RESTART_AFTER_LAUNCH_INTENT"}
    assert result["container_id"] == original_container
    async with harness.connections.sessions() as session:
        persisted = await session.get(SandboxExecution, execution_id)
        task = await session.get(AgentTask, task_id)
        assert persisted.launch_claimed_at == original_intent
        assert persisted.container_id == original_container
        assert task.owner == worker.owner and task.lease_until > now()
        launches = (await session.scalars(select(TaskEvent).where(
            TaskEvent.task_id == task_id, TaskEvent.kind == "sandbox_launch_claimed"))).all()
        assert len(launches) == 1, "Expired Runner authority caused another durable launch intent"
    await harness.no_containers([row])
