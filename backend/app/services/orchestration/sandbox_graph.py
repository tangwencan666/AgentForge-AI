"""Real LangGraph checkpointed approval followed by a restricted Runner dispatch."""
import asyncio
from uuid import UUID
import httpx
from sqlalchemy import select
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from app.domain.tasks import TaskApproval
from app.domain.sandbox import SandboxExecution
from app.core.errors import AppError
from app.services.tasks import locked_task, check_lease, event
from app.services.sandbox import EXECUTION_TERMINAL, execution_dto
from app.schemas.sandbox import POLICY_VERSION

def build_sandbox_graph(connections,settings,task_id,tenant,owner,fence,saver):
    async def approval(state):
        async with connections.sessions() as session,session.begin():
            task=await locked_task(session,task_id,tenant)
            check_lease(task,owner,fence,allow_waiting=True)
            row=(await session.scalars(select(SandboxExecution).where(SandboxExecution.task_id==task_id))).one()
            record=await session.get(TaskApproval,row.approval_reference)
            if record.policy_version!=POLICY_VERSION or record.operation_hash!=row.operation_hash:
                raise AppError("APPROVAL_MISMATCH","Sandbox approval mismatch",409)
            approved=record.status=="approved" and record.decided_by=="sandbox-reviewer"
            if not approved:
                task.status="waiting_approval"
                row.status="waiting_approval"
                event(session,task,"sandbox_approval_required",{"execution_id":str(row.id),"code_hash":row.code_hash,"operation_hash":row.operation_hash})
            execution_id=str(row.id)
        if not approved:
            interrupt({"type":"sandbox_execution","execution_id":execution_id,"is_mock":False})
            # Resume only wakes graph; authorization is re-read by the Runner.
        return {"execution_id":execution_id}

    async def execute(state):
        execution_id=UUID(state["execution_id"])
        if settings.sandbox_runner_token is None:
            raise AppError("SANDBOX_UNAVAILABLE","Sandbox Runner unavailable",503)
        headers={"X-AgentForge-Runner-Token":settings.sandbox_runner_token.get_secret_value()}
        dispatched=False
        async with httpx.AsyncClient(timeout=5,trust_env=False) as client:
            while True:
                async with connections.sessions() as session:
                    row=await session.get(SandboxExecution,execution_id)
                    if row.status in EXECUTION_TERMINAL:
                        return {"sandbox_result":execution_dto(row)}
                    if row.launch_claimed_at is not None: dispatched=True
                async with connections.sessions() as session,session.begin():
                    task=await locked_task(session,task_id,tenant)
                    check_lease(task,owner,fence)
                if not dispatched:
                    try:
                        response=await client.post(settings.sandbox_runner_url+f"/internal/executions/{execution_id}/dispatch",
                            headers=headers,json={"task_id":str(task_id),"execution_id":str(execution_id),"owner":owner,"fence":fence})
                        if response.status_code in {200,202}: dispatched=True
                        elif response.status_code==429 and response.json().get("error",{}).get("code")=="SANDBOX_CAPACITY": pass
                        else: raise AppError("SANDBOX_UNAVAILABLE","Sandbox Runner refused dispatch",503)
                    except httpx.HTTPError:
                        raise AppError("SANDBOX_UNAVAILABLE","Sandbox Runner unavailable; no host fallback",503) from None
                await asyncio.sleep(.2)
    builder=StateGraph(dict)
    builder.add_node("approval",approval)
    builder.add_node("sandbox",execute)
    builder.add_edge(START,"approval")
    builder.add_edge("approval","sandbox")
    builder.add_edge("sandbox",END)
    return builder.compile(checkpointer=saver)
