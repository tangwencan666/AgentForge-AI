"""Internal service. Do not publish this API or pass its credential to an Agent."""
from contextlib import asynccontextmanager
import asyncio
import hmac
from uuid import UUID
from fastapi import FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.repositories.connections import Connections
from app.sandbox.engine import SandboxRunner
from app.schemas.sandbox import RunnerDispatch


def create_app(settings=None, connections=None, runner=None):
    settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app):
        app.state.connections = connections or Connections(settings)
        app.state.runner = runner or SandboxRunner(app.state.connections, settings)
        await app.state.runner.start()
        yield
        await app.state.runner.close()
        if connections is None:
            await app.state.connections.close()

    app = FastAPI(title="AgentForge trusted Sandbox Runner", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.exception_handler(AppError)
    async def error(request, exc):
        return JSONResponse({"code": exc.code, "error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({"error": {"code": "INVALID_REQUEST", "message": "Invalid runner request"}}, status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        code = "RUNNER_FORBIDDEN" if exc.status_code == 403 else "HTTP_ERROR"
        return JSONResponse({"error": {"code": code, "message": "Runner request denied"}}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        return JSONResponse({"error": {"code": "RUNNER_UNAVAILABLE", "message": "Runner unavailable"}}, status_code=503)

    @app.get("/health/live")
    async def live():
        return {"status": "live"}

    def authorized(token):
        credential = settings.sandbox_runner_token
        expected = credential.get_secret_value() if credential else ""
        if not expected or not token or not hmac.compare_digest(token.encode(), expected.encode()):
            raise HTTPException(status_code=403, detail="Runner authorization required")

    @app.get("/internal/status")
    async def status(token: str | None = Header(default=None, alias="X-AgentForge-Runner-Token")):
        authorized(token)
        runner = app.state.runner
        try:
            healthy = bool(await asyncio.to_thread(runner.driver.health))
        except Exception:
            healthy = False
        from app.services.sandbox_maintenance import public_state
        maintenance = await public_state(app.state.connections)
        return {"available": healthy and not runner.blocked and not runner.closing and maintenance['admission_open'],
                "blocked": runner.blocked or not healthy or not maintenance['admission_open'],
                "active_executions": len(runner.active), 'maintenance': maintenance}

    @app.post("/internal/executions/{execution_id}/dispatch", status_code=202)
    async def dispatch(execution_id: UUID, request: RunnerDispatch,
                       token: str | None = Header(default=None, alias="X-AgentForge-Runner-Token")):
        authorized(token)
        if execution_id != request.execution_id:
            raise AppError("EXECUTION_MISMATCH", "Execution ID mismatch", 409)
        return await app.state.runner.dispatch(request)

    return app
