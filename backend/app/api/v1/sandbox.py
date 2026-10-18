import secrets
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials
from app.core.security import bearer, require_admin
from app.core.errors import AppError
from app.schemas.responses import ApiResponse, envelope
from app.schemas.sandbox import SandboxCreate
from app.schemas.tasks import ApprovalDecision
from app.services.sandbox import SandboxService

router=APIRouter(prefix="/api/v1/sandbox",tags=["Sandbox"])

def service(request): return SandboxService(request.app.state.connections,request.app.state.settings)

def require_approver(request: Request, credentials: HTTPAuthorizationCredentials | None=Depends(bearer)):
    expected=request.app.state.settings.sandbox_approver_token
    if expected is None or credentials is None or not secrets.compare_digest(credentials.credentials.encode(),expected.get_secret_value().encode()):
        raise AppError("SANDBOX_APPROVAL_FORBIDDEN","Independent sandbox approval permission required",403)
    return request.app.state.settings.tenant_id

@router.get("/policy",response_model=ApiResponse)
async def policy(request: Request,tenant=Depends(require_admin)):
    data=service(request).policy()
    from app.services.sandbox_maintenance import public_state
    data['maintenance'] = await public_state(request.app.state.connections)
    data["runner_status"]={"available":False,"blocked":True,"active_executions":None}
    settings=request.app.state.settings
    if settings.sandbox_runner_token:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=.7,trust_env=False) as client:
                response=await client.get(settings.sandbox_runner_url+"/internal/status",headers={"X-AgentForge-Runner-Token":settings.sandbox_runner_token.get_secret_value()})
                if response.status_code==200:
                    status=response.json()
                    data["runner_status"]={"available":status.get("available") is True,"blocked":status.get("blocked") is not False,
                        "active_executions":status.get("active_executions") if isinstance(status.get("active_executions"),int) else None}
        except (httpx.HTTPError,ValueError): pass
    if not data['maintenance']['admission_open']:
        data['runner_status']['available'], data['runner_status']['blocked'] = False, True
    return envelope(data)

@router.post("/executions",response_model=ApiResponse,status_code=202)
async def create(body: SandboxCreate,request: Request,idempotency_key: UUID=Header(alias="Idempotency-Key"),tenant=Depends(require_admin)):
    return envelope(await service(request).create(tenant,idempotency_key,body))

@router.get("/executions",response_model=ApiResponse)
async def list_executions(request: Request,tenant=Depends(require_admin)):
    return envelope(await service(request).list(tenant))

@router.get("/executions/{execution_id}",response_model=ApiResponse)
async def get(execution_id: UUID,request: Request,tenant=Depends(require_admin)):
    return envelope(await service(request).get(execution_id,tenant))

@router.post("/executions/{execution_id}/decision",response_model=ApiResponse)
async def decide(execution_id: UUID,body: ApprovalDecision,request: Request,tenant=Depends(require_approver)):
    return envelope(await service(request).decide(execution_id,tenant,body))

@router.post("/executions/{execution_id}/cancel",response_model=ApiResponse)
async def cancel(execution_id: UUID,request: Request,tenant=Depends(require_admin)):
    return envelope(await service(request).cancel(execution_id,tenant))

@router.get("/executions/{execution_id}/source",response_model=ApiResponse)
async def source(execution_id: UUID,request: Request,tenant=Depends(require_approver)):
    from sqlalchemy import select
    from app.domain.sandbox import SandboxExecution
    async with request.app.state.connections.sessions() as session:
        row=(await session.scalars(select(SandboxExecution).where(SandboxExecution.id==execution_id,SandboxExecution.tenant_id==UUID(tenant)))).one_or_none()
        if not row: raise AppError("EXECUTION_NOT_FOUND","Execution not found",404)
        return envelope({"language":row.language,"code":row.code,"code_hash":row.code_hash,"operation_hash":row.operation_hash})
