import asyncio
import json
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from app.core.errors import AppError
from app.core.security import require_admin
from app.schemas.responses import ApiResponse, envelope
from app.schemas.tasks import TaskCreate, ApprovalDecision
from app.services.tasks import TaskService, TERMINAL

router = APIRouter(prefix="/api/v1", tags=["Tasks"])


def service(request: Request):
    return TaskService(request.app.state.connections, request.app.state.settings)


@router.post("/tasks", response_model=ApiResponse, status_code=202)
async def create_task(body: TaskCreate, request: Request, idempotency_key: UUID = Header(alias="Idempotency-Key"), tenant: str = Depends(require_admin)):
    return envelope(await service(request).create(tenant, idempotency_key, body))


@router.get("/tasks", response_model=ApiResponse)
async def list_tasks(request: Request, tenant: str = Depends(require_admin)):
    return envelope(await service(request).list(tenant))


@router.get("/tasks/{task_id}", response_model=ApiResponse)
async def get_task(task_id: UUID, request: Request, tenant: str = Depends(require_admin)):
    return envelope(await service(request).get(task_id, tenant))


@router.post("/tasks/{task_id}/cancel", response_model=ApiResponse)
async def cancel_task(task_id: UUID, request: Request, tenant: str = Depends(require_admin)):
    return envelope(await service(request).cancel(task_id, tenant))


@router.get("/approvals", response_model=ApiResponse)
async def list_approvals(request: Request, tenant: str = Depends(require_admin)):
    return envelope(await service(request).approvals(tenant))


@router.post("/approvals/{approval_id}/decision", response_model=ApiResponse)
async def decide_approval(approval_id: UUID, body: ApprovalDecision, request: Request, tenant: str = Depends(require_admin)):
    return envelope(await service(request).decide(approval_id, tenant, body))


@router.get("/tasks/{task_id}/events")
async def stream_events(task_id: UUID, request: Request, last_event_id: int = Header(default=0, alias="Last-Event-ID"), tenant: str = Depends(require_admin)):
    if last_event_id < 0:
        raise AppError("INVALID_CURSOR", "Event cursor must be nonnegative", 422)
    task_service = service(request)
    await task_service.get(task_id, tenant)  # Authorize before committing SSE response headers.
    await task_service.events(task_id, tenant, last_event_id)
    async def events():
        cursor = last_event_id
        try:
            while not await request.is_disconnected():
                # Recheck credential and resource scope throughout a long-lived stream.
                from fastapi.security import HTTPAuthorizationCredentials
                auth = request.headers.get("Authorization", "")
                if not auth.startswith("Bearer "):
                    break
                require_admin(request, HTTPAuthorizationCredentials(scheme="Bearer",credentials=auth[7:]))
                rows, status = await task_service.events(task_id, tenant, cursor)
                for row in rows:
                    cursor = row["id"]
                    yield f"id: {cursor}\nevent: {row['kind']}\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
                if status in TERMINAL and len(rows) < 200:
                    yield "event: completed\ndata: {}\n\n"
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.4)
        except asyncio.CancelledError:
            raise
        except Exception:
            yield 'event: error\ndata: {"code":"EVENT_STREAM_INTERRUPTED"}\n\n'
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-store","X-Accel-Buffering":"no"})
