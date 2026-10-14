"""Actual Windows Worker termination/restart while one real Docker task runs.

Run only after stopping the project demo Worker and starting the trusted Runner.
Only app.workers.main is launched on the host. Task source is sent to the existing
service and is never passed to a host Python/shell command.
"""
import asyncio
import os
from pathlib import Path
import subprocess
from uuid import UUID, uuid4

from app.core.config import Settings
from app.domain.sandbox import SandboxExecution
from app.domain.tasks import AgentTask
from app.repositories.connections import Connections
from app.schemas.sandbox import SandboxCreate
from app.schemas.tasks import ApprovalDecision
from app.services.sandbox import EXECUTION_TERMINAL, SandboxService

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def powershell(command, **values):
    environment = os.environ.copy()
    environment["AGENTFORGE_PROBE_ROOT"] = str(ROOT)
    environment.update({"AGENTFORGE_PROBE_" + key: str(value) for key, value in values.items()})
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT, env=environment, capture_output=True, text=True, timeout=12,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("Project Worker process ownership operation failed")
    return result.stdout.strip()


def check_no_existing_worker():
    count = powershell("""
$ErrorActionPreference='Stop'
$taskRoot=$env:AGENTFORGE_PROBE_ROOT
. (Join-Path $taskRoot 'scripts/process-ownership.ps1')
$taskProcesses=@(Get-CimInstance Win32_Process -Filter "CommandLine like '%app.workers.main%'" | Where-Object { Test-AgentForgeProcess $_ 'worker' $taskRoot })
Write-Output $taskProcesses.Count
""")
    if count != "0":
        raise RuntimeError("Stop the project demo Worker before running the restart probe")


def actual_worker_pid(process):
    value = powershell("""
$ErrorActionPreference='Stop'
$taskRoot=$env:AGENTFORGE_PROBE_ROOT
$taskLauncherId=[int]$env:AGENTFORGE_PROBE_LAUNCHER_PID
. (Join-Path $taskRoot 'scripts/process-ownership.ps1')
$taskProcess=Get-CimInstance Win32_Process -Filter "ParentProcessId=$taskLauncherId" | Where-Object { Test-AgentForgeProcess $_ 'worker' $taskRoot } | Select-Object -First 1
if (-not $taskProcess) { $taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$taskLauncherId" | Where-Object { Test-AgentForgeProcess $_ 'worker' $taskRoot } | Select-Object -First 1 }
if ($taskProcess) { Write-Output $taskProcess.ProcessId }
""", LAUNCHER_PID=process.pid)
    return int(value) if value else None


async def start_worker(log):
    environment = os.environ.copy()
    environment["LANGSMITH_TRACING"] = environment["LANGCHAIN_TRACING_V2"] = "false"
    process = subprocess.Popen(f'"{PYTHON}" -m app.workers.main', executable=str(PYTHON),
        cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(30):
        if process.poll() is not None:
            raise RuntimeError("Trusted project Worker did not start")
        pid = await asyncio.to_thread(actual_worker_pid, process)
        if pid is not None:
            return process, pid
        await asyncio.sleep(.1)
    process.terminate()  # Only the Popen handle created above, never a name match.
    await asyncio.to_thread(process.wait, 10)
    raise RuntimeError("Actual project Worker PID could not be verified")


async def stop_worker(process, pid):
    # Recheck both exact PID and project command ownership immediately before kill.
    await asyncio.to_thread(powershell, """
$ErrorActionPreference='Stop'
$taskRoot=$env:AGENTFORGE_PROBE_ROOT
$taskProcessId=[int]$env:AGENTFORGE_PROBE_WORKER_PID
. (Join-Path $taskRoot 'scripts/process-ownership.ps1')
$taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$taskProcessId" -ErrorAction SilentlyContinue
if ($taskProcess) {
    if (-not (Test-AgentForgeProcess $taskProcess 'worker' $taskRoot)) { throw 'Refusing to stop a process whose ownership changed' }
    Stop-Process -Id $taskProcessId -Force
}
""", WORKER_PID=pid)
    await asyncio.to_thread(process.wait, 10)


async def wait_execution(service, execution_id, tenant, statuses, timeout):
    until = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < until:
        row = await service.get(execution_id, tenant)
        if row["status"] in statuses:
            return row
        if row["status"] in EXECUTION_TERMINAL:
            raise RuntimeError("Real execution ended before the expected restart boundary")
        await asyncio.sleep(.05)
    raise RuntimeError("Real execution did not reach the expected bounded state")


async def main():
    if os.name != "nt" or os.environ.get("AGENTFORGE_RUN_SANDBOX") != "1":
        raise RuntimeError("Explicit sandbox opt-in and Windows project Worker environment required")
    await asyncio.to_thread(check_no_existing_worker)
    settings = Settings()
    connections = Connections(settings)
    service = SandboxService(connections, settings)
    process = worker_pid = execution_id = None
    root_work = ROOT / "work"
    root_work.mkdir(exist_ok=True)
    log_path = root_work / ("p3-recovery-worker-" + uuid4().hex + ".log")
    with log_path.open("ab") as log:
        try:
            process, worker_pid = await start_worker(log)
            created = await service.create(settings.tenant_id, uuid4(),
                SandboxCreate(code="import time;print('once',flush=True);time.sleep(3)", timeout_seconds=10))
            execution_id, task_id = UUID(created["execution_id"]), UUID(created["task_id"])
            until = asyncio.get_running_loop().time() + 20
            while asyncio.get_running_loop().time() < until:
                async with connections.sessions() as session:
                    task = await session.get(AgentTask, task_id)
                    if task.status == "waiting_approval" and task.owner is None:
                        break
                await asyncio.sleep(.08)
            else:
                raise RuntimeError("Real approval checkpoint was not persisted")
            await service.decide(execution_id, settings.tenant_id,
                ApprovalDecision(decision="approved", operation_hash=created["operation_hash"]))
            running = await wait_execution(service, execution_id, settings.tenant_id, {"running"}, 20)
            async with connections.sessions() as session:
                initial = await session.get(SandboxExecution, execution_id)
                launch_intent = initial.launch_claimed_at
            assert running["container_id"] and launch_intent is not None
            original_pid = worker_pid
            await stop_worker(process, worker_pid)
            process = worker_pid = None
            process, worker_pid = await start_worker(log)
            assert worker_pid != original_pid, "The real Worker process was not replaced"
            completed = await wait_execution(service, execution_id, settings.tenant_id, EXECUTION_TERMINAL, 25)
            assert completed["status"] == "succeeded"
            assert completed["container_id"] == running["container_id"]
            assert completed["stdout_summary"].splitlines().count("once") == 1
            assert completed["cleanup_status"] == "removed"
            until = asyncio.get_running_loop().time() + 10
            while asyncio.get_running_loop().time() < until:
                async with connections.sessions() as session:
                    task = await session.get(AgentTask, task_id)
                    persisted = await session.get(SandboxExecution, execution_id)
                    assert persisted.launch_claimed_at == launch_intent
                    if task.status == "succeeded":
                        break
                await asyncio.sleep(.1)
            else:
                raise RuntimeError("Replacement Worker did not recover the persisted task result")
            import docker
            def no_container():
                client = docker.from_env(timeout=5)
                try:
                    return not client.containers.list(all=True, filters={"label":
                        "agentforge.sandbox.execution=" + str(execution_id)})
                finally:
                    client.close()
            assert await asyncio.to_thread(no_container), "Restarted task left a project execution container"
            print("PASS: actual OS Worker replaced during real Docker execution; one launch intent, same container, one output, confirmed cleanup")
        finally:
            try:
                if execution_id:
                    await service.cancel(execution_id, settings.tenant_id)
                    until = asyncio.get_running_loop().time() + 20
                    while asyncio.get_running_loop().time() < until:
                        row = await service.get(execution_id, settings.tenant_id)
                        if row["status"] in EXECUTION_TERMINAL and row["cleanup_status"] in {"removed", "not_created"}:
                            break
                        await asyncio.sleep(.1)
                    else:
                        raise RuntimeError("Probe cleanup could not be confirmed")
            finally:
                try:
                    if process is not None:
                        await stop_worker(process, worker_pid)
                finally:
                    await connections.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        # No source, token, credentials, raw exception or subprocess output is printed.
        print("P3 recovery probe failed: " + type(exc).__name__)
        raise SystemExit(1) from None
