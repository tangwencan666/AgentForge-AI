"""Actual project-scoped Windows Worker restart, with an explicit Provider Stub."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4
from sqlalchemy import delete, select
from app.core.config import Settings
from app.domain.entities import ModelSlot
from app.domain.tasks import AgentTask, ModelOperation
from app.domain.real import RealDailyUsage
from app.repositories.connections import Connections
from app.schemas.tasks import TaskCreate, ApprovalDecision
from app.services.tasks import TaskService

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'tests/fixtures/provider_stub_worker.py'


def child_pid(process, tenant, stop=False):
    env = os.environ.copy()
    env.update(P5_PROBE_PID=str(process.pid), P5_PROBE_HELPER=str(HELPER), P5_PROBE_TENANT=tenant, P5_PROBE_STOP='1' if stop else '0')
    command = r'''
$ErrorActionPreference='Stop'
$taskProcesses=@(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
    ($_.ProcessId -eq [int]$env:P5_PROBE_PID -or $_.ParentProcessId -eq [int]$env:P5_PROBE_PID) -and
    $_.CommandLine -and $_.CommandLine.Contains($env:P5_PROBE_HELPER) -and $_.CommandLine.Contains($env:P5_PROBE_TENANT)
})
if ($env:P5_PROBE_STOP -eq '1') {
    foreach ($taskProcess in $taskProcesses) { Stop-Process -Id $taskProcess.ProcessId }
    Write-Output $taskProcesses.Count
} else {
    $taskChild=$taskProcesses | Where-Object { $_.ParentProcessId -eq [int]$env:P5_PROBE_PID } | Select-Object -First 1
    if (-not $taskChild) { $taskChild=$taskProcesses | Select-Object -First 1 }
    if (-not $taskChild) { throw 'Project test Worker not found' }
    Write-Output $taskChild.ProcessId
}
'''
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command], cwd=ROOT,
        env=env, capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode: raise RuntimeError('Project test process ownership check failed')
    return int(result.stdout.strip())


def start(tenant):
    env = os.environ.copy()
    env['AGENTFORGE_MODEL_P5_STUB_KEY'] = 'explicit-provider-stub-only-value'
    return subprocess.Popen([sys.executable, str(HELPER), tenant], cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)


async def main():
    settings = Settings().model_copy(update={'tenant_id': str(uuid4())})
    c = Connections(settings)
    service = TaskService(c, settings)
    process = None
    try:
        async with c.sessions() as session, session.begin():
            for role in ('planner','coder','researcher','reviewer'):
                session.add(ModelSlot(tenant_id=UUID(settings.tenant_id), role=role, provider='openai_compatible', base_url='https://api.openai.com/v1',
                    model='stub-' + role, credential_reference='env:AGENTFORGE_MODEL_P5_STUB_KEY', temperature=.2,
                    max_tokens=1024, timeout=2, enabled=True, version=1))
        # Construct the same approved test configuration without installing a production Stub flag.
        from decimal import Decimal
        settings = settings.model_copy(update={'real_calls_enabled': True, 'real_daily_budget_usd': Decimal('1'),
            'model_credential_hosts': {'AGENTFORGE_MODEL_P5_STUB_KEY': ['api.openai.com']},
            'model_prices': {'openai_compatible/stub-' + role: {'input_per_million': '1', 'output_per_million': '2',
                'input_upper_bound': 8192, 'output_upper_bound': 1024, 'version': 'explicit-stub-price-v1'} for role in ('planner','coder','researcher','reviewer')}})
        os.environ['AGENTFORGE_MODEL_P5_STUB_KEY'] = 'explicit-provider-stub-only-value'
        service.settings = settings
        task = await service.create(settings.tenant_id, uuid4(), TaskCreate(goal='P5 actual OS restart with explicit Provider Stub', execution_mode='real', require_approval=True))
        task_id = UUID(task['task_id'])
        process = start(settings.tenant_id)
        for _ in range(160):
            await asyncio.sleep(.15)
            task = await service.get(task_id, settings.tenant_id)
            async with c.sessions() as session: row = await session.get(AgentTask, task_id)
            if task['status'] == 'waiting_approval' and row.owner is None: break
        else: raise RuntimeError('Planner checkpoint did not become durable')
        first_pid = child_pid(process, settings.tenant_id)
        child_pid(process, settings.tenant_id, stop=True)
        await asyncio.to_thread(process.wait, 10)
        approval = next(r for r in await service.approvals(settings.tenant_id) if r['task_id'] == str(task_id))
        await service.decide(UUID(approval['approval_id']), settings.tenant_id, ApprovalDecision(decision='approved', operation_hash=approval['operation_hash']))
        process = start(settings.tenant_id)
        await asyncio.sleep(.4)
        second_pid = child_pid(process, settings.tenant_id)
        assert first_pid != second_pid
        for _ in range(200):
            await asyncio.sleep(.15)
            task = await service.get(task_id, settings.tenant_id)
            if task['status'] in {'succeeded','failed','needs_reconciliation'}: break
        assert task['status'] == 'succeeded', 'Restarted explicit Stub workflow did not succeed'
        planner_calls = sum(r['role'] == 'planner' for r in task['calls'])
        assert planner_calls == 1 and len(task['calls']) == 4
        record = {'status': 'PASSED', 'test_type': 'actual_os_worker_restart_with_explicit_provider_stub',
            'actual_external_api_calls': 0, 'first_pid': first_pid, 'second_pid': second_pid,
            'planner_attempts': planner_calls, 'total_stub_attempts': 4, 'task_state': task['status']}
        (ROOT / 'work/p5-worker-restart.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
        print(json.dumps(record))
    finally:
        if process and process.poll() is None:
            child_pid(process, settings.tenant_id, stop=True)
            await asyncio.to_thread(process.wait, 10)
        async with c.sessions() as session, session.begin():
            for model in (AgentTask, ModelSlot, RealDailyUsage):
                await session.execute(delete(model).where(model.tenant_id == UUID(settings.tenant_id)))
        await c.close()

try: asyncio.run(main())
except Exception as exc:
    print('P5 OS restart probe failed: ' + type(exc).__name__)
    raise SystemExit(1) from None
