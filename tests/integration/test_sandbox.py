"""Opt-in real PG/Redis/independent Docker Runner tests, never host code execution."""
import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import UUID,uuid4
import pytest
from sqlalchemy import select,func
from app.core.config import Settings
from app.core.errors import AppError
from app.repositories.connections import Connections
from app.schemas.sandbox import SandboxCreate
from app.schemas.tasks import ApprovalDecision
from app.services.sandbox import SandboxService,EXECUTION_TERMINAL
from app.services.tasks import TaskService,TERMINAL
from app.domain.sandbox import SandboxExecution
from app.domain.tasks import Outbox,GraphCheckpoint
from app.workers.engine import Worker,STREAM

pytestmark=[pytest.mark.integration,pytest.mark.sandbox]

@pytest.fixture
async def setup():
    if os.environ.get("AGENTFORGE_RUN_SANDBOX")!="1": pytest.skip("Real Docker sandbox opt-in required")
    settings=Settings()
    connections=Connections(settings)
    worker=Worker(connections,settings)
    await worker.initialize()
    service=SandboxService(connections,settings)
    try: yield settings,connections,worker,service
    finally:
        await worker.close()
        await connections.close()

async def drive(setup,execution_id,wanted=EXECUTION_TERMINAL,timeout=20):
    settings,connections,worker,service=setup
    until=asyncio.get_running_loop().time()+timeout
    while asyncio.get_running_loop().time()<until:
        await worker.tick()
        await asyncio.sleep(.06)
        row=await service.get(UUID(execution_id),settings.tenant_id)
        if row["status"] in wanted: return row
    raise AssertionError("Sandbox did not reach expected bounded state")

async def create(setup,code,**changes):
    settings,connections,worker,service=setup
    row=await service.create(settings.tenant_id,uuid4(),SandboxCreate(code=code,**changes))
    waiting=await drive(setup,row["execution_id"],{"waiting_approval"})
    # Interrupt checkpoint must commit and its Worker lease must be released.
    await asyncio.sleep(.12)
    for attempt in range(50):
        try:
            await service.decide(UUID(row["execution_id"]),settings.tenant_id,ApprovalDecision(decision="approved",operation_hash=row["operation_hash"]))
            return row
        except AppError as exc:
            if exc.code!="APPROVAL_CHECKPOINT_PENDING": raise
            await worker.tick(); await asyncio.sleep(.1)
    raise AssertionError("Approval checkpoint not durable")

def assert_no_container(row):
    output=subprocess.check_output(["docker","ps","-aq","--filter","label=agentforge.sandbox.execution="+row["execution_id"]],text=True)
    assert not output.strip(),"Project execution container was not removed"

async def test_python_real_docker_execution_and_checkpoint(setup):
    row=await create(setup,"print('P3 actual Docker execution')")
    result=await drive(setup,row["execution_id"])
    assert result["status"]=="succeeded",result["failure_reason"]
    assert result["exit_code"]==0 and "P3 actual Docker execution" in result["stdout_summary"]
    assert result["is_mock"] is False and result["cleanup_status"]=="removed"
    settings,connections,worker,service=setup
    async with connections.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(GraphCheckpoint).where(GraphCheckpoint.task_id==UUID(row["task_id"])))>0
    assert_no_container(result)

async def test_runtime_network_identity_root_and_credentials(setup):
    code="""import os,json,socket,pathlib,errno
s=socket.socket();network_errno=None
try:s.connect(('1.1.1.1',80));network=True
except OSError as e:network=False;network_errno=e.errno
try:pathlib.Path('/opt/agentforge/rootfs-canary').write_text('x');readonly=False
except OSError as e:readonly=e.errno==errno.EROFS
st=dict(l.split(':',1) for l in pathlib.Path('/proc/self/status').read_text().splitlines() if ':' in l)
print(json.dumps({'uid':os.getuid(),'network':network,'network_errno':network_errno,'readonly':readonly,'seccomp':st['Seccomp'].strip(),'nnp':st['NoNewPrivs'].strip(),'caps':st['CapEff'].strip(),'secret_env':[k for k in os.environ if any(x in k for x in ['TOKEN','PASSWORD','AGENTFORGE','DATABASE','REDIS'])],'docker_socket':pathlib.Path('/var/run/docker.sock').exists()}))"""
    row=await create(setup,code)
    result=await drive(setup,row["execution_id"])
    assert result["status"]=="succeeded",result["failure_reason"]
    probe=json.loads(result["stdout_summary"])
    # The task executes on Linux; Windows host errno.ENETUNREACH is 10051.
    assert probe=={"uid":10001,"network":False,"network_errno":101,"readonly":True,"seccomp":"2","nnp":"1","caps":"0000000000000000","secret_env":[],"docker_socket":False}
    assert_no_container(result)

async def test_host_marker_is_not_readable(setup):
    root=Path(__file__).resolve().parents[2]
    marker=root/"work"/("p3-host-marker-"+uuid4().hex+".txt")
    marker.write_text("non-sensitive isolation fixture",encoding="utf-8")
    candidates=[str(marker),"/run/desktop/mnt/host/d/AIProjects/AgentForge-AI/work/"+marker.name,"/mnt/host/d/AIProjects/AgentForge-AI/work/"+marker.name]
    row=await create(setup,"import pathlib,json\nprint(json.dumps([pathlib.Path(p).exists() for p in "+repr(candidates)+"]))")
    result=await drive(setup,row["execution_id"])
    assert result["status"]=="succeeded",result["failure_reason"]
    assert json.loads(result["stdout_summary"])==[False,False,False]
    assert_no_container(result)

async def test_cpu_quota_actually_throttles(setup):
    code="import time,json\ns=time.monotonic();c=time.process_time()\nwhile time.monotonic()-s<2: pass\nprint(json.dumps({'wall':time.monotonic()-s,'cpu':time.process_time()-c}))"
    row=await create(setup,code,resource_limits={"cpu":.25,"memory_mb":128,"pids":32},timeout_seconds=8)
    result=await drive(setup,row["execution_id"])
    assert result["status"]=="succeeded",result["failure_reason"]
    probe=json.loads(result["stdout_summary"])
    assert probe["cpu"]/probe["wall"]<.55
    assert_no_container(result)

async def test_memory_limit_bounded_allocation(setup):
    row=await create(setup,"import time\nblocks=[]\nfor i in range(16):\n blocks.append(bytearray(8*1024*1024));time.sleep(.02)\nprint('allocation unexpectedly finished')",resource_limits={"cpu":.5,"memory_mb":64,"pids":32},timeout_seconds=8)
    result=await drive(setup,row["execution_id"])
    assert result["status"]=="failed" and result["exit_code"]!=0,result["failure_reason"]
    assert "allocation unexpectedly finished" not in result["stdout_summary"]
    assert_no_container(result)

async def test_pids_limit_bounded_spawn(setup):
    code="""import subprocess,sys,json
children=[];limited=False
try:
 for i in range(12):children.append(subprocess.Popen([sys.executable,'-c','import time;time.sleep(2)']))
except OSError:limited=True
print(json.dumps({'limited':limited,'spawned':len(children)}),flush=True)
for child in children:child.terminate()
for child in children:child.wait()"""
    row=await create(setup,code,resource_limits={"cpu":.5,"memory_mb":128,"pids":8},timeout_seconds=8)
    result=await drive(setup,row["execution_id"])
    assert result["status"]=="succeeded",result["failure_reason"]
    data=json.loads(result["stdout_summary"])
    assert data["limited"] and data["spawned"]<=6
    assert_no_container(result)

async def test_timeout_kills_entire_container(setup):
    row=await create(setup,"import time;time.sleep(30)",timeout_seconds=1)
    result=await drive(setup,row["execution_id"])
    assert result["status"]=="timed_out" and result["cleanup_status"]=="removed"
    assert_no_container(result)

async def test_cancel_kills_and_confirms_cleanup(setup):
    settings,connections,worker,service=setup
    row=await create(setup,"import time;print('running',flush=True);time.sleep(20)")
    await drive(setup,row["execution_id"],{"running"})
    await service.cancel(UUID(row["execution_id"]),settings.tenant_id)
    result=await drive(setup,row["execution_id"])
    assert result["status"]=="cancelled" and result["cleanup_status"]=="removed"
    assert_no_container(result)

async def test_output_limit_truncates_and_removes(setup):
    row=await create(setup,"import sys\nsys.stdout.write('x'*(2*1024*1024));sys.stdout.flush()")
    result=await drive(setup,row["execution_id"])
    assert result["status"]=="output_limit" and result["resource_usage"]["output_truncated"]
    assert len(result["stdout_summary"].encode())<=4096
    assert_no_container(result)

async def test_no_state_leak_between_disposable_tasks(setup):
    first=await create(setup,"from pathlib import Path\nPath('/workspace/marker').write_text('task A');print('stored')")
    a=await drive(setup,first["execution_id"])
    second=await create(setup,"from pathlib import Path\nprint(Path('/workspace/marker').exists())")
    b=await drive(setup,second["execution_id"])
    assert a["status"]==b["status"]=="succeeded"
    assert b["stdout_summary"].strip()=="False" and a["container_id"]!=b["container_id"]
    assert_no_container(a);assert_no_container(b)

async def test_rejection_never_launches(setup):
    settings,connections,worker,service=setup
    row=await service.create(settings.tenant_id,uuid4(),SandboxCreate(code="print('must not run')"))
    await drive(setup,row["execution_id"],{"waiting_approval"});await asyncio.sleep(.3)
    await service.decide(UUID(row["execution_id"]),settings.tenant_id,ApprovalDecision(decision="rejected",operation_hash=row["operation_hash"]))
    result=await service.get(UUID(row["execution_id"]),settings.tenant_id)
    assert result["status"]=="rejected" and result["container_id"] is None
    assert_no_container(result)

async def test_duplicate_messages_and_worker_restart_reuse_execution(setup):
    settings,connections,worker,service=setup
    row=await create(setup,"import time;print('once',flush=True);time.sleep(2)")
    running=await drive(setup,row["execution_id"],{"running"})
    await connections.redis.xadd(STREAM,{"task_id":row["task_id"],"outbox_id":str(uuid4())})
    await worker.close()
    replacement=Worker(connections,settings)
    setup2=settings,connections,replacement,service
    try:
        result=await drive(setup2,row["execution_id"])
        task=await TaskService(connections,settings).get(UUID(row["task_id"]),settings.tenant_id)
        for _ in range(20):
            if task["status"] in TERMINAL:break
            await replacement.tick();await asyncio.sleep(.1)
            task=await TaskService(connections,settings).get(UUID(row["task_id"]),settings.tenant_id)
        assert result["status"]=="succeeded" and result["container_id"]==running["container_id"]
        assert result["stdout_summary"].count("once")==1
        assert task["status"]=="succeeded"
        assert_no_container(result)
    finally:await replacement.close()

async def test_idempotent_create_and_secret_rejection(setup):
    settings,connections,worker,service=setup
    key=uuid4();body=SandboxCreate(code="print(1)")
    a,b=await asyncio.gather(service.create(settings.tenant_id,key,body),service.create(settings.tenant_id,key,body))
    assert a["execution_id"]==b["execution_id"]
    await service.cancel(UUID(a["execution_id"]),settings.tenant_id)
    with pytest.raises(AppError) as error:
        await service.create(settings.tenant_id,uuid4(),SandboxCreate(code="print("+repr(settings.sandbox_runner_token.get_secret_value())+")"))
    assert error.value.code=="SENSITIVE_CODE_REJECTED"
