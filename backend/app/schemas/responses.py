from typing import Any
from pydantic import BaseModel
from app.core.logging import request_id_var


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: list[dict[str, str]] | None = None


class ApiResponse(BaseModel):
    success: bool
    data: Any = None
    error: ErrorInfo | None = None
    request_id: str


def envelope(data: Any = None, *, error: ErrorInfo | None = None) -> dict:
    return ApiResponse(success=error is None, data=data, error=error, request_id=request_id_var.get()).model_dump()
