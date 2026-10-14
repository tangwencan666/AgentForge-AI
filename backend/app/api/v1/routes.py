from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from app.core.errors import AppError
from app.core.security import require_admin
from app.schemas.models import ModelConfig, ModelRole, ModelUpdate
from app.schemas.responses import ApiResponse, envelope
from app.services.models import list_slots, update_slot, validate_configuration

router = APIRouter(prefix="/api/v1")


@router.get("/system", response_model=ApiResponse)
async def system():
    return envelope({"name": "AgentForge AI", "phase": "P2", "model_calls": "mock_only",
                     "agent_execution": "langgraph_mock_workflow", "sandbox_execution": "not_implemented",
                     "mcp_execution": "not_implemented", "skills_execution": "not_implemented"})


@router.get("/model-slots", response_model=ApiResponse)
async def models(request: Request, tenant_id: str = Depends(require_admin)):
    try:
        async with request.app.state.connections.sessions() as session:
            return envelope(await list_slots(session, tenant_id))
    except SQLAlchemyError:
        raise AppError("DATABASE_UNAVAILABLE", "Project database is unavailable", 503) from None


@router.post("/model-slots/validate", response_model=ApiResponse)
async def validate_model(config: ModelConfig, request: Request, tenant_id: str = Depends(require_admin)):
    validate_configuration(config, request.app.state.settings)
    return envelope({"valid": True, "is_mock": config.provider == "mock", "call_status": "not_implemented"})


@router.put("/model-slots/{role}", response_model=ApiResponse)
async def save_model(role: ModelRole, config: ModelUpdate, request: Request, tenant_id: str = Depends(require_admin)):
    try:
        async with request.app.state.connections.sessions() as session:
            return envelope(await update_slot(session, tenant_id, role, config, request.app.state.settings))
    except SQLAlchemyError:
        raise AppError("DATABASE_UNAVAILABLE", "Project database is unavailable", 503) from None
