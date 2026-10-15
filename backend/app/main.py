from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from app.api.v1.routes import router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.sandbox import router as sandbox_router
from app.api.v1.capabilities import router as capabilities_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.repositories.connections import Connections
from app.schemas.responses import ApiResponse, ErrorInfo, envelope
from app.schemas.models import ModelConfig, ModelUpdate


def create_app(settings: Settings | None = None, connections=None) -> FastAPI:
    try:
        settings = settings or get_settings()
    except ValidationError:
        raise RuntimeError("Invalid AgentForge environment configuration; check required variables without logging values") from None
    logger = configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.connections = connections or Connections(settings)
        logger.info("application_started")
        yield
        await app.state.connections.close()
        logger.info("application_stopped")

    app = FastAPI(title="AgentForge AI", version="0.1.0", lifespan=lifespan,
                  responses={code: {"model": ApiResponse} for code in (400, 401, 403, 409, 422, 500, 503)},
                  description="P4 controlled MCP Tool Gateway and declarative Skills Registry; approved Docker sandbox. Model responses remain explicitly Mock.")
    app.state.settings = settings
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return JSONResponse(envelope(error=ErrorInfo(code=exc.code, message=exc.message)), status_code=exc.status,
                            headers={"WWW-Authenticate": "Bearer"} if exc.status == 401 else None)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        safe_fields = set(ModelConfig.model_fields) | set(ModelUpdate.model_fields) | {"role"}
        details = []
        for error in exc.errors():
            location = error["loc"][-1]
            field = location if isinstance(location, str) and location in safe_fields else "field"
            details.append({"field": field, "reason": error["type"]})
        return JSONResponse(envelope(error=ErrorInfo(code="VALIDATION_ERROR", message="Invalid request", details=details)), status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(envelope(error=ErrorInfo(code="HTTP_ERROR", message="Request could not be served")), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.error("request_failed", extra={"error_type": type(exc).__name__})
        # ServerErrorMiddleware runs outside request middleware; use saved state ID.
        return JSONResponse({"success": False, "data": None,
                             "error": {"code": "INTERNAL_ERROR", "message": "Internal service error", "details": None},
                             "request_id": getattr(request.state, "request_id", "-")}, status_code=500,
                            headers={"X-Request-ID": getattr(request.state, "request_id", "-"), "Cache-Control": "no-store"})

    @app.get("/health/live", response_model=ApiResponse, tags=["Health"])
    async def live():
        return envelope({"status": "alive", "phase": "P4"})

    @app.get("/health/ready", response_model=ApiResponse, tags=["Health"])
    async def ready(request: Request):
        dependencies = await request.app.state.connections.readiness()
        is_ready = all(status == "up" for status in dependencies.values())
        return JSONResponse(envelope({"status": "ready" if is_ready else "not_ready", "dependencies": dependencies},
                                     error=None if is_ready else ErrorInfo(code="DEPENDENCIES_NOT_READY", message="Required dependencies are not ready")),
                            status_code=200 if is_ready else 503)

    app.include_router(router)
    app.include_router(tasks_router)
    app.include_router(sandbox_router)
    app.include_router(capabilities_router)
    return app
