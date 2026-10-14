"""Real project-only worker process restart during a persisted plan approval."""
import asyncio
from pathlib import Path
import subprocess
from uuid import UUID, uuid4
from app.core.config import Settings
from app.repositories.connections import Connections
from app.services.tasks import TaskService, TERMINAL
from app.schemas.tasks import TaskCreate, ApprovalDecision
from app.domain.tasks import AgentTask

ROOT=Path(__file__).resolve().parents[1]


async def main():
    settings=Settings(); connections=Connections(settings); service=TaskService(connections,settings)
    task=await service.create(settings.tenant_id,uuid4(),TaskCreate(goal='P2 real process restart probe',execution_mode='mock',require_approval=True))
    task_id=UUID(task['task_id'])
    try:
        for _ in range(100):
            await asyncio.sleep(0.1)
            async with connections.sessions() as session:
                record=await session.get(AgentTask,task_id)
                if record.status=='waiting_approval' and record.owner is None: break
        else: raise RuntimeError('Approval checkpoint not ready')
        restart=await asyncio.to_thread(subprocess.run,['powershell','-NoProfile','-File',str(ROOT/'scripts/restart-worker.ps1')],cwd=ROOT,capture_output=True,text=True,timeout=25)
        if restart.returncode: raise RuntimeError('Worker process restart failed')
        approval=next(row for row in await service.approvals(settings.tenant_id) if row['task_id']==str(task_id))
        await service.decide(UUID(approval['approval_id']),settings.tenant_id,ApprovalDecision(decision='approved',operation_hash=approval['operation_hash']))
        for _ in range(150):
            await asyncio.sleep(0.1)
            task=await service.get(task_id,settings.tenant_id)
            if task['status'] in TERMINAL: break
        assert task['status']=='succeeded'
        assert len(task['calls'])==4 and sum(row['role']=='planner' for row in task['calls'])==1
        print('PASS: real worker process restart; approval resumed from PostgreSQL; 4 unique Mock calls')
    finally:
        await service.cancel(task_id,settings.tenant_id)
        await connections.close()


if __name__=='__main__':
    try: asyncio.run(main())
    except Exception as exc:
        print('Recovery probe failed: '+type(exc).__name__)
        raise SystemExit(1) from None
