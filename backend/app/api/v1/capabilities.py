import secrets
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials
from app.core.errors import AppError
from app.core.security import bearer, require_admin
from app.schemas.responses import ApiResponse, envelope
from app.schemas.tools import CapabilityDecision, PermissionUpdate, SkillAction, SkillCandidate, SkillRef, ToolRequest, public_catalog
from app.services.skills import SkillRegistry
from app.services.tool_gateway import ToolGateway

router = APIRouter(prefix="/api/v1", tags=["P4 capabilities"])


def gateway(request):
    return ToolGateway(request.app.state.connections, request.app.state.settings)


def registry(request):
    return SkillRegistry(request.app.state.connections, request.app.state.settings)


def require_capability_approver(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    expected = request.app.state.settings.capability_approver_token
    if not expected or not credentials or not secrets.compare_digest(credentials.credentials.encode(), expected.get_secret_value().encode()):
        raise AppError("CAPABILITY_APPROVAL_FORBIDDEN", "Independent P4 approval permission required", 403)
    return request.app.state.settings.tenant_id


@router.get("/mcp/tools", response_model=ApiResponse)
async def tools(request: Request, tenant=Depends(require_admin)):
    settings = request.app.state.settings
    return envelope({"tools": public_catalog(), "transport": "controlled_stdio", "policy_version": "p4-gateway-v1",
                     "configured": bool(settings.mcp_server_token and settings.capability_approver_token),
                     "daily_call_limit": settings.mcp_daily_call_limit, "timeout_seconds": settings.mcp_timeout_seconds})


@router.get("/mcp/permissions", response_model=ApiResponse)
async def permissions(request: Request, tenant=Depends(require_admin)):
    return envelope(await gateway(request).permissions(tenant))


@router.put("/mcp/permissions", response_model=ApiResponse)
async def permission(body: PermissionUpdate, request: Request, tenant=Depends(require_admin)):
    return envelope(await gateway(request).permission(tenant, body))


@router.get("/mcp/calls", response_model=ApiResponse)
async def calls(request: Request, tenant=Depends(require_admin)):
    return envelope(await gateway(request).list(tenant))


@router.post("/mcp/calls", response_model=ApiResponse, status_code=202)
async def prepare(body: ToolRequest, request: Request, idempotency_key: UUID = Header(alias="Idempotency-Key"), tenant=Depends(require_admin)):
    return envelope(await gateway(request).create(tenant, idempotency_key, body))


@router.get("/mcp/calls/{call_id}", response_model=ApiResponse)
async def call(call_id: UUID, request: Request, tenant=Depends(require_admin)):
    return envelope(await gateway(request).get(tenant, call_id))


@router.post("/mcp/calls/{call_id}/execute", response_model=ApiResponse)
async def execute(call_id: UUID, request: Request, tenant=Depends(require_admin)):
    return envelope(await gateway(request).execute(tenant, call_id))


@router.post("/mcp/calls/{call_id}/reconcile", response_model=ApiResponse)
async def reconcile(call_id: UUID, request: Request, tenant=Depends(require_admin)):
    return envelope(await gateway(request).reconcile(tenant, call_id))


@router.get("/skills", response_model=ApiResponse)
async def skills(request: Request, tenant=Depends(require_admin)):
    return envelope(await registry(request).list(tenant))


@router.post("/skills/candidates", response_model=ApiResponse, status_code=201)
async def candidate(body: SkillCandidate, request: Request, tenant=Depends(require_admin)):
    return envelope(await registry(request).candidate(tenant, body))


@router.post("/skills/{skill_id}/{version}/actions", response_model=ApiResponse)
async def skill_action(skill_id: str, version: str, body: SkillAction, request: Request, tenant=Depends(require_admin)):
    # Validate path components with the same immutable identity schema as the manifest.
    from pydantic import ValidationError
    try:
        SkillRef(skill_id=skill_id, version=version)
    except ValidationError:
        raise AppError("SKILL_IDENTITY_INVALID", "Invalid Skill version identity", 422) from None
    try:
        return envelope(await registry(request).action(tenant, skill_id, version, body.action))
    except AppError as exc:
        await gateway(request).refused(tenant, skill_id + "@" + version, exc.code)
        raise


@router.get("/capabilities/approvals", response_model=ApiResponse)
async def approvals(request: Request, tenant=Depends(require_admin)):
    return envelope(await gateway(request).approvals(tenant))


@router.get("/capabilities/approvals/{approval_id}/review", response_model=ApiResponse)
async def review(approval_id: UUID, request: Request, tenant=Depends(require_capability_approver)):
    return envelope(await gateway(request).review(tenant, approval_id))


@router.post("/capabilities/approvals/{approval_id}/decision", response_model=ApiResponse)
async def decide(approval_id: UUID, body: CapabilityDecision, request: Request, tenant=Depends(require_capability_approver)):
    return envelope(await gateway(request).decide(tenant, approval_id, body))


@router.get("/capabilities/audit", response_model=ApiResponse)
async def history(request: Request, tenant=Depends(require_admin)):
    return envelope(await gateway(request).history(tenant))
