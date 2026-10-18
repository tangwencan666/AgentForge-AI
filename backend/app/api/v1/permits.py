from uuid import UUID
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict
from app.core.security import bearer, require_admin
from app.schemas.responses import ApiResponse, envelope
from app.services.permit_authority import verify_issuer
from app.services.execution_permits import PermitService

router = APIRouter(prefix='/api/v1/model-permits', tags=['Single-use model authorization'])


class EmptyPermitRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, hide_input_in_errors=True)


def issuer(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    return verify_issuer(credentials.credentials if credentials else None, request.app.state.settings)


@router.post('', response_model=ApiResponse, status_code=201)
async def issue(body: EmptyPermitRequest, request: Request, authority=Depends(issuer)):
    return envelope(await PermitService(request.app.state.connections, request.app.state.settings).issue(authority))


@router.get('/{permit_id}', response_model=ApiResponse)
async def get(permit_id: UUID, request: Request, tenant=Depends(require_admin)):
    return envelope(await PermitService(request.app.state.connections, request.app.state.settings).get(permit_id))


@router.post('/{permit_id}/revoke', response_model=ApiResponse)
async def revoke(permit_id: UUID, body: EmptyPermitRequest, request: Request, authority=Depends(issuer)):
    return envelope(await PermitService(request.app.state.connections, request.app.state.settings).revoke(permit_id, authority))
